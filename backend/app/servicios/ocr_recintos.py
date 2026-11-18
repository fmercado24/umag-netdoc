"""Lectura con OCR de los rótulos de sala de una lámina.

La universidad no tiene una sola forma de rotular las salas, así que la lámina
se lee sin suponer una:

* En el CADI, el número va bajo el nombre y dice el piso: ``SALA 1`` /
  ``1083`` en el primero, ``0017`` en el subterráneo.
* En la Biblioteca, la categoría va arriba, el número al medio y el nombre
  debajo (``E.`` / ``09`` / ``Oficina administrativa``), y los números
  empiezan de nuevo en cada piso.

Un rótulo de sala es un código corto, con cifras y a veces una letra
(``25A``) o un decimal (``1083.2``), que tiene un nombre justo encima o justo
debajo. La forma que más se repite en la lámina (cuántas cifras, dónde va el
nombre y el tamaño de la letra) dice cómo rotula sus salas ese edificio. Lo
que no tiene esa forma son cotas, la viñeta u otros rótulos. Si los números
siguen la numeración por piso del CADI, se exige además que sean del piso de
la lámina.

Las láminas exportadas desde CAD traen el texto convertido en trazos, así que
se leen como imagen: se dibujan a unos 11 500 px de ancho y pasan por un OCR
(RapidOCR) en pedazos que se solapan. Un número tapado por una línea del
dibujo (la X de un hall o una silla) no se alcanza a leer así. Por eso se
vuelve a leer, más grande, el lugar donde debería estar el número de cada
nombre de sala que quedó sin número.

El OCR es una dependencia aparte (``requirements-ocr.txt``): el resto del
sistema funciona sin él.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.servicios.recintos import (
    clave_rack,
    corresponde_al_piso,
    normalizar_numero,
    similitud,
)

#: Ancho al que se dibuja la lámina para leerla: en las del CADI, los números
#: de sala quedan de unos 25 px de alto.
ANCHO_LECTURA = 11_500
#: Pedazos que se pasan al OCR. El solape es mayor que cualquier rótulo, así
#: que cada uno queda entero en algún pedazo.
TAMANO_PEDAZO = 1600
SOLAPE = 200

#: La segunda lectura pega los trozos en imágenes de este lado, separados por
#: este margen en blanco.
LADO_MOSAICO = 1600
MARGEN_MOSAICO = 40

#: Lo que el OCR suele confundir dentro de un número.
CONFUSIONES = str.maketrans({"O": "0", "o": "0", "Q": "0", "I": "1", "l": "1", "|": "1"})
#: Al releer un número tapado por una línea, comparándolo con el esperado.
CONFUSIONES_AMPLIAS = str.maketrans(
    {"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "T": "1",
     "Z": "2", "S": "5", "B": "8", "G": "6"}
)
#: Rótulo de un rack: «RACK 08», «Rack 11», «RACK 1 PRINCIPAL».
RE_ROTULO_RACK = re.compile(r"^\s*RACK\s*[-:#.]*\s*([0-9OoIl|]{1,3})(?![0-9A-Za-z])", re.IGNORECASE)

#: Código de sala sin letras delante: «09», «25A», «1083.2», «OO17».
RE_CODIGO = re.compile(r"(?P<cifras>[0-9OoQIl|]{1,4})(?P<letra>[A-Za-z])?(?P<decimal>[.,]\d{1,2})?")
#: Con letras delante, como «B-101» o «LAB3». Sin confusiones: aquí una O es
#: una letra.
RE_CODIGO_CON_LETRAS = re.compile(
    r"(?P<prefijo>[A-Za-z]{1,3}[-.]?)(?P<cifras>\d{1,4})(?P<letra>[A-Za-z])?"
)
#: La categoría que la Biblioteca pone sobre el número: «E.», «K.».
RE_CATEGORIA = re.compile(r"[A-Za-z]{1,2}\.?")
#: La superficie que algunos rótulos llevan bajo el nombre: «12,68 m²».
RE_SUPERFICIE = re.compile(r"\d\s*m\s*[²2]|m²", re.IGNORECASE)


@dataclass(frozen=True)
class Lectura:
    """Un texto leído, con su caja en las unidades del plano."""

    texto: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def alto(self) -> float:
        return self.y1 - self.y0

    @property
    def centro(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class RecintoLeido:
    numero: str
    nombre: str | None
    #: Donde se dibujan sus elementos: bajo el rótulo, para no taparlo.
    x: float
    y: float


# --------------------------------------------------------------------------
# Qué es cada texto
# --------------------------------------------------------------------------
def como_numero(texto: str) -> str | None:
    """«1083», «1083.2» o «OO17» (0017) como número de recinto del CADI; None si no lo es."""
    limpio = texto.strip().replace(" ", "")
    if sum(c.isdigit() for c in limpio) < 2:
        return None
    candidato = limpio.translate(CONFUSIONES).replace(",", ".")
    return candidato if normalizar_numero(candidato) == candidato else None


def como_codigo(texto: str) -> str | None:
    """El texto como código de sala, tal como lo escribe el plano, o None.

    «09», «25A», «1083.2», «OO17» (0017) o «B-101». Las letras van en
    mayúscula. Un texto con más de tres letras («SALA 1») es un nombre.
    """
    limpio = texto.strip().replace(" ", "")
    if coincidencia := RE_CODIGO.fullmatch(limpio):
        cifras = coincidencia["cifras"]
        # La mitad o más deben ser cifras de verdad: «Il» no es «11».
        if 2 * sum(c.isdigit() for c in cifras) < len(cifras):
            return None
        return (
            cifras.translate(CONFUSIONES)
            + (coincidencia["letra"] or "").upper()
            + (coincidencia["decimal"] or "").replace(",", ".")
        )
    if coincidencia := RE_CODIGO_CON_LETRAS.fullmatch(texto.strip()):
        return coincidencia[0].upper()
    return None


def forma_del_codigo(codigo: str) -> tuple[bool, int]:
    """Lo que comparten los códigos de un mismo edificio: si llevan letras
    delante y cuántas cifras. «09» y «25A» son de la misma forma."""
    prefijo = re.match(r"[A-Z]*[-.]?", codigo)[0]
    cifras = re.match(r"\d*", codigo[len(prefijo):])[0]
    return bool(prefijo), len(cifras)


def es_categoria(texto: str) -> bool:
    return RE_CATEGORIA.fullmatch(texto.strip()) is not None


def es_nombre(texto: str) -> bool:
    """Si el texto puede ser el nombre de una sala: «Oficina administrativa»,
    «SALA 1», «SS.HH»; no una superficie ni un código."""
    return (
        sum(c.isalpha() for c in texto) >= 3
        and RE_SUPERFICIE.search(texto) is None
        and como_codigo(texto) is None
    )


def _lineas(
    caja: tuple[float, float, float, float],
    textos: list[Lectura],
    alto: float,
    *,
    abajo: bool,
    maximo: int = 3,
) -> list[Lectura]:
    """Las líneas de texto pegadas al rótulo, por encima o por debajo, en
    orden de lectura (de arriba abajo). Cada una debe pasar por el centro del
    rótulo y estar a menos de una línea de la anterior."""
    x0, y0, x1, y1 = caja
    centro = (x0 + x1) / 2
    lineas: list[Lectura] = []
    borde = y1 if abajo else y0
    for _ in range(maximo):
        if abajo:
            cerca = [t for t in textos if borde - 0.3 * alto <= t.y0 <= borde + 1.2 * alto]
        else:
            cerca = [t for t in textos if borde - 1.2 * alto <= t.y1 <= borde + 0.3 * alto]
        cerca = [
            t for t in cerca if t not in lineas and t.x0 - 0.5 * alto <= centro <= t.x1 + 0.5 * alto
        ]
        if not cerca:
            break
        # La más cercana y, entre lecturas de la misma línea, la más completa.
        if abajo:
            linea = max(cerca, key=lambda t: (-round(t.y0 / (0.5 * alto)), len(t.texto)))
            lineas.append(linea)
            borde = linea.y1
        else:
            linea = max(cerca, key=lambda t: (round(t.y1 / (0.5 * alto)), len(t.texto)))
            lineas.insert(0, linea)
            borde = linea.y0
    return lineas


def _linea_completa(linea: Lectura, textos: list[Lectura], alto: float) -> str:
    """La línea con los pedazos que el OCR leyó aparte: «Sala» + «estudio».

    Dos lecturas que se tapan son la misma palabra leída dos veces (pedazos
    que se solapan): queda la más larga.
    """
    misma = sorted(
        (t for t in textos if abs(t.y0 - linea.y0) < 0.5 * alto and abs(t.y1 - linea.y1) < 0.5 * alto),
        key=lambda t: (t.x0, -len(t.texto)),
    )
    partes: list[Lectura] = []
    for t in misma:
        anterior = partes[-1] if partes else None
        if anterior is not None:
            solape = min(anterior.x1, t.x1) - max(anterior.x0, t.x0)
            if solape > 0.5 * min(anterior.x1 - anterior.x0, t.x1 - t.x0):
                mejor = max((anterior, t), key=lambda u: (u is linea, len(u.texto), u.texto[:1].isupper()))
                partes[-1] = mejor
                continue
        partes.append(t)
    # Las palabras pegadas a la elegida, a menos de un espacio grande.
    indice = next((i for i, t in enumerate(partes) if t is linea or t == linea), None)
    if indice is None:
        return linea.texto.strip()
    desde = hasta = indice
    while desde > 0 and partes[desde].x0 - partes[desde - 1].x1 <= 0.8 * alto:
        desde -= 1
    while hasta < len(partes) - 1 and partes[hasta + 1].x0 - partes[hasta].x1 <= 0.8 * alto:
        hasta += 1
    return " ".join(t.texto.strip() for t in partes[desde : hasta + 1])


def limpiar_nombre(texto: str) -> str | None:
    """Sin los signos sueltos que el OCR lee en los bordes: «(Sala estudio» →
    «Sala estudio»."""
    limpio = re.sub(r"\s+", " ", texto).strip(" ()[]{}|-_.,:;'\"")
    return limpio or None


def _nombre_sobre(caja: tuple[float, float, float, float], textos: list[Lectura], alto: float) -> str | None:
    """Las líneas de texto justo encima del número (hasta tres), de arriba abajo."""
    return " ".join(t.texto.strip() for t in _lineas(caja, textos, alto, abajo=False)) or None


def parecido(nombre: str | None, esperados: set[str]) -> float:
    """El mayor parecido entre lo leído y cómo nombran las planillas al recinto."""
    return max((similitud(nombre, esperado) for esperado in esperados), default=0.0)


def _caja(lecturas: list[Lectura]) -> tuple[float, float, float, float]:
    return (
        min(l.x0 for l in lecturas),
        min(l.y0 for l in lecturas),
        max(l.x1 for l in lecturas),
        max(l.y1 for l in lecturas),
    )


# --------------------------------------------------------------------------
# Cómo rotula sus salas la lámina
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Rotulado:
    """Cómo rotula sus salas una lámina, según lo que más se repite en ella."""

    #: Los números dicen el piso, como en el CADI (``1083`` en el primero).
    por_piso: bool
    #: El nombre va bajo el código (Biblioteca) y no encima (CADI).
    nombre_debajo: bool
    #: Ver ``forma_del_codigo``.
    forma: tuple[bool, int]
    #: Alto típico del código, en unidades del plano.
    alto: float

    def admite(self, codigo: str, codigo_piso: str) -> bool:
        if self.por_piso:
            return normalizar_numero(codigo) == codigo and corresponde_al_piso(codigo, codigo_piso)
        return forma_del_codigo(codigo) == self.forma

    def describir(self) -> str:
        if self.por_piso:
            return "números de cuatro cifras que dicen el piso, bajo el nombre de la sala"
        letras, cifras = self.forma
        return (
            f"códigos de {cifras} cifra{'s' if cifras > 1 else ''}"
            + (" con letras delante" if letras else "")
            + (", con el nombre debajo" if self.nombre_debajo else ", bajo el nombre de la sala")
        )


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[len(ordenados) // 2]


def _del_piso(codigo: str, codigo_piso: str) -> bool:
    return normalizar_numero(codigo) == codigo and corresponde_al_piso(codigo, codigo_piso)


def reconocer_rotulado(lecturas: list[Lectura], codigo_piso: str) -> Rotulado | None:
    """Cómo rotula sus salas la lámina, o None si no se ve ningún rótulo.

    Se cuentan códigos distintos y no lecturas: la simbología repite el mismo
    rótulo muchas veces («F.0» en cada cámara), y cada sala tiene el suyo.
    """
    codigos = [(l, c) for l in lecturas if (c := como_codigo(l.texto))]
    nombres = [l for l in lecturas if es_nombre(l.texto)]
    sobre: dict[str, list[Lectura]] = defaultdict(list)
    bajo: dict[str, list[Lectura]] = defaultdict(list)
    for lectura, codigo in codigos:
        caja = (lectura.x0, lectura.y0, lectura.x1, lectura.y1)
        if _lineas(caja, nombres, lectura.alto, abajo=False, maximo=1):
            sobre[codigo].append(lectura)
        if _lineas(caja, nombres, lectura.alto, abajo=True, maximo=1):
            bajo[codigo].append(lectura)

    del_piso = [l for l, c in codigos if _del_piso(c, codigo_piso)]
    rotulos = sorted({*sobre, *bajo})
    if not rotulos:
        if not del_piso:
            return None
        alto = _mediana([l.alto for l in del_piso])
        return Rotulado(por_piso=True, nombre_debajo=False, forma=(False, 4), alto=alto)

    forma = Counter(forma_del_codigo(c) for c in rotulos).most_common(1)[0][0]
    de_la_forma = [c for c in rotulos if forma_del_codigo(c) == forma]
    if forma == (False, 4) and 2 * sum(_del_piso(c, codigo_piso) for c in de_la_forma) >= len(de_la_forma):
        alto = _mediana([l.alto for l in del_piso])
        return Rotulado(por_piso=True, nombre_debajo=False, forma=forma, alto=alto)

    nombre_debajo = sum(c in bajo for c in de_la_forma) > sum(c in sobre for c in de_la_forma)
    lado = bajo if nombre_debajo else sobre
    alto = _mediana([l.alto for c in de_la_forma for l in lado.get(c, [])])
    return Rotulado(por_piso=False, nombre_debajo=nombre_debajo, forma=forma, alto=alto)


# --------------------------------------------------------------------------
# Recintos
# --------------------------------------------------------------------------
@dataclass
class Interpretacion:
    recintos: list[RecintoLeido] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    rotulado: Rotulado | None = None
    #: Las líneas que quedaron como nombre o categoría de un recinto.
    usadas: set[int] = field(default_factory=set)


def interpretar_lecturas(
    lecturas: list[Lectura],
    codigo_piso: str,
    esperados: dict[str, set[str]] | None = None,
) -> tuple[list[RecintoLeido], list[str]]:
    """Los recintos del piso entre lo que leyó el OCR, y los avisos.

    ``esperados`` (número → ubicaciones de las planillas) desempata un número
    que aparece en más de un lugar de la lámina: se elige el de nombre más
    parecido al de las planillas.
    """
    interpretacion = interpretar(lecturas, codigo_piso, esperados)
    return interpretacion.recintos, interpretacion.avisos


def interpretar(
    lecturas: list[Lectura],
    codigo_piso: str,
    esperados: dict[str, set[str]] | None = None,
) -> Interpretacion:
    """Como ``interpretar_lecturas``, con lo que necesita la segunda lectura."""
    esperados = esperados or {}
    rotulado = reconocer_rotulado(lecturas, codigo_piso)
    if rotulado is None:
        return Interpretacion()

    # Con la numeración por piso, como siempre se leyó el CADI: el nombre es
    # cualquier texto con letras sobre el número.
    lee = como_numero if rotulado.por_piso else como_codigo
    textos = [l for l in lecturas if not lee(l.texto) and any(c.isalpha() for c in l.texto)]
    nombres = [t for t in textos if es_nombre(t.texto)]
    categorias = [t for t in textos if es_categoria(t.texto)]
    alto = rotulado.alto
    codigos = []
    for lectura in lecturas:
        codigo = lee(lectura.texto)
        if not codigo or not rotulado.admite(codigo, codigo_piso):
            continue
        # Los códigos de sala tienen todos el mismo tamaño: lo de otro tamaño
        # son cotas, la viñeta u otros rótulos.
        if not 0.6 * alto <= lectura.alto <= 1.8 * alto:
            continue
        if not rotulado.por_piso:
            # Sin la numeración por piso, un código suelto no basta: debe
            # tener su nombre, o su categoría al otro lado.
            caja = (lectura.x0, lectura.y0, lectura.x1, lectura.y1)
            con_nombre = _lineas(caja, nombres, lectura.alto, abajo=rotulado.nombre_debajo, maximo=1)
            con_categoria = _lineas(
                caja, categorias, lectura.alto, abajo=not rotulado.nombre_debajo, maximo=1
            )
            if not con_nombre and not con_categoria:
                continue
        codigos.append((lectura, codigo))

    # Un rótulo puede leerse dos veces (pedazos que se solapan) o estar
    # repetido en el CAD justo al lado: es el mismo recinto.
    grupos: dict[str, list[list[Lectura]]] = defaultdict(list)
    for lectura, codigo in sorted(codigos, key=lambda p: (p[0].y0, p[0].x0)):
        cx, cy = lectura.centro
        for grupo in grupos[codigo]:
            gx, gy = grupo[0].centro
            if abs(gx - cx) < 4 * alto and abs(gy - cy) < 2 * alto:
                grupo.append(lectura)
                break
        else:
            grupos[codigo].append([lectura])

    interpretacion = Interpretacion(rotulado=rotulado)
    for codigo, ocurrencias in sorted(grupos.items()):
        candidatos = []
        for grupo in ocurrencias:
            candidatos.append(
                _recinto_del_rotulo(codigo, _caja(grupo), textos, nombres, categorias, rotulado)
            )
        elegido, usadas = max(
            candidatos,
            key=lambda par: (
                parecido(par[0].nombre, esperados.get(codigo, set())),
                par[0].nombre is not None,
            ),
        )
        if len(candidatos) > 1:
            lado = "sobre" if rotulado.nombre_debajo else "bajo"
            interpretacion.avisos.append(
                f"el {codigo} aparece {len(candidatos)} veces; se usó el de "
                f"({elegido.x:.0f}, {elegido.y:.0f})"
                + (f", {lado} «{elegido.nombre}»" if elegido.nombre else "")
            )
        interpretacion.recintos.append(elegido)
        interpretacion.usadas |= usadas
    return interpretacion


def _recinto_del_rotulo(
    codigo: str,
    caja: tuple[float, float, float, float],
    textos: list[Lectura],
    nombres: list[Lectura],
    categorias: list[Lectura],
    rotulado: Rotulado,
) -> tuple[RecintoLeido, set[int]]:
    """El recinto de un código, con su nombre y el punto bajo el rótulo, y
    las líneas que se usaron."""
    alto = caja[3] - caja[1]
    if rotulado.por_piso:
        lineas = _lineas(caja, textos, alto, abajo=False)
        abajo = caja[3]
    else:
        lineas = _lineas(caja, nombres, alto, abajo=rotulado.nombre_debajo)
        # El punto queda bajo todo el rótulo: con el nombre debajo, bajo él.
        abajo = max([caja[3], *(l.y1 for l in lineas)]) if rotulado.nombre_debajo else caja[3]
    categoria = (
        []
        if rotulado.por_piso
        else _lineas(caja, categorias, alto, abajo=not rotulado.nombre_debajo, maximo=1)
    )
    if rotulado.por_piso:
        nombre = " ".join(t.texto.strip() for t in lineas) or None
    else:
        nombre = limpiar_nombre(" ".join(_linea_completa(t, nombres, alto) for t in lineas))
    recinto = RecintoLeido(
        numero=codigo,
        nombre=nombre,
        x=round((caja[0] + caja[2]) / 2, 1),
        y=round(abajo + alto, 1),
    )
    return recinto, {id(l) for l in [*lineas, *categoria]}


def interpretar_racks(lecturas: list[Lectura]) -> tuple[list[RecintoLeido], list[str]]:
    """Los racks rotulados en la lámina, con el centro de su rótulo."""
    grupos: dict[int, list[list[Lectura]]] = defaultdict(list)
    for lectura in sorted(lecturas, key=lambda l: (l.y0, l.x0)):
        coincidencia = RE_ROTULO_RACK.match(lectura.texto)
        cifras = coincidencia.group(1).translate(CONFUSIONES) if coincidencia else ""
        if not cifras.isdigit():
            continue
        numero = int(cifras)
        cx, cy = lectura.centro
        for grupo in grupos[numero]:
            gx, gy = grupo[0].centro
            if abs(gx - cx) < 3 * lectura.alto and abs(gy - cy) < 2 * lectura.alto:
                grupo.append(lectura)
                break
        else:
            grupos[numero].append([lectura])

    racks: list[RecintoLeido] = []
    avisos: list[str] = []
    for numero, ocurrencias in sorted(grupos.items()):
        x0, y0, x1, y1 = _caja(ocurrencias[0])
        rack = RecintoLeido(
            clave_rack(numero), f"RACK {numero:02d}", round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)
        )
        if len(ocurrencias) > 1:
            avisos.append(
                f"el rack {numero} está rotulado {len(ocurrencias)} veces; "
                f"se usó el de ({rack.x:.0f}, {rack.y:.0f})"
            )
        racks.append(rack)
    return racks, avisos


def es_el_numero_esperado(texto: str, esperado: str) -> bool:
    """Si lo leído bajo el nombre de la sala es el número que dice la planilla.

    Una línea que cruza el número hace leer «161» o «TQ61» donde dice 1061:
    se acepta si las cifras leídas aparecen, en orden, en el esperado.
    """
    if como_numero(texto) == esperado:
        return True
    cifras = re.sub(r"\D", "", texto.translate(CONFUSIONES_AMPLIAS))
    objetivo = esperado.replace(".", "")
    if len(cifras) < 3 or len(cifras) > len(objetivo):
        return False
    restantes = iter(objetivo)
    return all(cifra in restantes for cifra in cifras)


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
class SinOcr(RuntimeError):
    """El OCR no está instalado."""

    def __init__(self) -> None:
        super().__init__(
            "Falta el OCR para leer las láminas. Instálelo una vez con:\n"
            "  cd backend && .venv/bin/python -m pip install -r requirements-ocr.txt"
        )


def crear_ocr():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise SinOcr() from None
    return RapidOCR()


#: Formatos que libvips dibuja a la escala pedida, sin perder nitidez.
VECTORIALES = {".svg", ".pdf"}


def _abrir(ruta: Path, factor: float = 1):
    """La lámina dibujada a ``ANCHO_LECTURA`` × ``factor`` de ancho."""
    import pyvips

    natural = pyvips.Image.new_from_file(str(ruta))
    escala = ANCHO_LECTURA / natural.width * factor
    if ruta.suffix.lower() in VECTORIALES:
        return pyvips.Image.new_from_file(str(ruta), scale=escala)
    # Una foto o un escaneo: a 8 bits por canal y agrandada, porque el OCR lee
    # mejor la letra grande.
    if natural.format != "uchar" or natural.interpretation not in ("srgb", "b-w"):
        natural = natural.colourspace("srgb")
    return natural.resize(escala) if abs(escala - 1) > 0.01 else natural


def _matriz(imagen):
    import numpy as np

    if imagen.hasalpha():
        imagen = imagen.flatten(background=[255] * (imagen.bands - 1))
    if imagen.bands == 1:
        imagen = imagen.bandjoin([imagen, imagen])
    return np.ndarray(
        buffer=imagen.write_to_memory(),
        dtype=np.uint8,
        shape=[imagen.height, imagen.width, imagen.bands],
    )[:, :, :3]


def dibujar_lamina(ruta: Path):
    """La lámina como matriz RGB de ``ANCHO_LECTURA`` de ancho."""
    import pyvips

    pyvips.cache_set_max(0)
    return _matriz(_abrir(ruta))


def leer_lamina(ruta: Path, ancho_plano: int, alto_plano: int, ocr, matriz=None) -> list[Lectura]:
    """Todo el texto de la lámina, con sus cajas en las unidades del plano.

    ``matriz`` es la lámina ya dibujada con ``dibujar_lamina``, si se tiene.
    """
    import numpy as np

    matriz = dibujar_lamina(ruta) if matriz is None else matriz
    alto, ancho = matriz.shape[:2]
    a_plano_x, a_plano_y = ancho_plano / ancho, alto_plano / alto

    lecturas: list[Lectura] = []
    paso = TAMANO_PEDAZO - SOLAPE
    for y0 in range(0, alto, paso):
        for x0 in range(0, ancho, paso):
            pedazo = matriz[y0 : y0 + TAMANO_PEDAZO, x0 : x0 + TAMANO_PEDAZO]
            if pedazo.min() > 245:  # en blanco
                continue
            resultado, _ = ocr(np.ascontiguousarray(pedazo))
            alto_pedazo, ancho_pedazo = pedazo.shape[:2]
            for caja, texto, _confianza in resultado or []:
                xs = [float(p[0]) for p in caja]
                ys = [float(p[1]) for p in caja]
                # Lo que toca un borde interior quedó cortado: entero está en
                # el pedazo vecino.
                if (
                    (x0 > 0 and min(xs) < 3)
                    or (y0 > 0 and min(ys) < 3)
                    or (x0 + ancho_pedazo < ancho and max(xs) > ancho_pedazo - 3)
                    or (y0 + alto_pedazo < alto and max(ys) > alto_pedazo - 3)
                ):
                    continue
                lecturas.append(
                    Lectura(
                        texto=texto,
                        x0=(x0 + min(xs)) * a_plano_x,
                        y0=(y0 + min(ys)) * a_plano_y,
                        x1=(x0 + max(xs)) * a_plano_x,
                        y1=(y0 + max(ys)) * a_plano_y,
                    )
                )
    return lecturas


def _agrandar(matriz, factor: int):
    try:
        import cv2
    except ImportError:  # pragma: no cover - el OCR trae OpenCV
        import numpy as np

        return np.repeat(np.repeat(matriz, factor, axis=0), factor, axis=1)
    return cv2.resize(matriz, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


class Relector:
    """Lee de nuevo trozos de una lámina, solos y agrandados.

    En la primera pasada, un número pegado a una línea del dibujo se pierde
    entre todo lo demás del pedazo; solo, se lee. Los trozos se recortan de la
    lámina ya dibujada (volver a dibujarla para cada uno toma medio segundo),
    y un trozo en blanco no se lee.
    """

    def __init__(self, matriz, ancho_plano: int, ocr) -> None:
        self.matriz, self.ocr = matriz, ocr
        self.por_unidad = matriz.shape[1] / ancho_plano

    def _recortar(self, region: tuple[float, float, float, float], factor: int):
        """El trozo agrandado y su esquina en la lámina dibujada, o None si
        está en blanco o es muy chico."""
        alto_total, ancho_total = self.matriz.shape[:2]
        izquierda = max(0, int(region[0] * self.por_unidad))
        arriba = max(0, int(region[1] * self.por_unidad))
        derecha = min(ancho_total, int(region[2] * self.por_unidad))
        abajo = min(alto_total, int(region[3] * self.por_unidad))
        if derecha - izquierda < 8 or abajo - arriba < 8:
            return None
        recorte = self.matriz[arriba:abajo, izquierda:derecha]
        if recorte.min() > 245:  # en blanco
            return None
        return (_agrandar(recorte, factor) if factor > 1 else recorte), izquierda, arriba

    def _lectura(
        self, texto: str, caja, dx: float, dy: float, factor: int, izquierda: int, arriba: int
    ) -> Lectura:
        """Una caja del OCR, movida ``dx``, ``dy`` en la imagen leída, en las
        unidades del plano."""
        xs = [float(p[0]) - dx for p in caja]
        ys = [float(p[1]) - dy for p in caja]
        escala = self.por_unidad * factor
        return Lectura(
            texto,
            izquierda / self.por_unidad + min(xs) / escala,
            arriba / self.por_unidad + min(ys) / escala,
            izquierda / self.por_unidad + max(xs) / escala,
            arriba / self.por_unidad + max(ys) / escala,
        )

    def leer(self, region: tuple[float, float, float, float], factor: int) -> list[Lectura]:
        import numpy as np

        trozo = self._recortar(region, factor)
        if trozo is None:
            return []
        recorte, izquierda, arriba = trozo
        resultado, _ = self.ocr(np.ascontiguousarray(recorte))
        return [
            self._lectura(texto, caja, 0, 0, factor, izquierda, arriba)
            for caja, texto, _confianza in resultado or []
        ]

    def leer_varios(
        self, regiones: list[tuple[float, float, float, float]], factor: int
    ) -> list[list[Lectura]]:
        """``leer`` de muchos trozos, con una pasada del OCR por cada tanto:
        van pegados en una imagen y separados por blanco. Una pasada toma lo
        mismo con un trozo que con treinta."""
        import numpy as np

        resultados: list[list[Lectura]] = [[] for _ in regiones]
        lote: list[tuple[int, int, int, object, int, int]] = []
        x = y = alto_hilera = 0

        def leer_lote() -> None:
            ancho = max(px + r.shape[1] for _, px, _, r, _, _ in lote) + MARGEN_MOSAICO
            alto = max(py + r.shape[0] for _, _, py, r, _, _ in lote) + MARGEN_MOSAICO
            lienzo = np.full((alto, ancho, 3), 255, dtype=np.uint8)
            for _, px, py, recorte, _, _ in lote:
                lienzo[py : py + recorte.shape[0], px : px + recorte.shape[1]] = recorte
            resultado, _ = self.ocr(lienzo)
            for caja, texto, _confianza in resultado or []:
                xs = [float(p[0]) for p in caja]
                ys = [float(p[1]) for p in caja]
                cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
                for indice, px, py, recorte, izquierda, arriba in lote:
                    alto_r, ancho_r = recorte.shape[:2]
                    if not (px <= cx < px + ancho_r and py <= cy < py + alto_r):
                        continue
                    # Lo que toca el borde del trozo quedó cortado: «08» a
                    # medias se lee «30».
                    entera = min(xs) > px + 2 and max(xs) < px + ancho_r - 2
                    if entera and min(ys) > py + 2 and max(ys) < py + alto_r - 2:
                        resultados[indice].append(
                            self._lectura(texto, caja, px, py, factor, izquierda, arriba)
                        )
                    break

        for indice, region in enumerate(regiones):
            trozo = self._recortar(region, factor)
            if trozo is None:
                continue
            recorte, izquierda, arriba = trozo
            alto_r, ancho_r = recorte.shape[:2]
            if ancho_r + 2 * MARGEN_MOSAICO > LADO_MOSAICO or alto_r + 2 * MARGEN_MOSAICO > LADO_MOSAICO:
                resultados[indice] = self.leer(region, factor)
                continue
            if x + ancho_r + 2 * MARGEN_MOSAICO > LADO_MOSAICO:  # hilera nueva
                x, y, alto_hilera = 0, y + alto_hilera + MARGEN_MOSAICO, 0
            if y + alto_r + 2 * MARGEN_MOSAICO > LADO_MOSAICO and lote:  # imagen nueva
                leer_lote()
                lote, x, y, alto_hilera = [], 0, 0, 0
            lote.append((indice, x + MARGEN_MOSAICO, y + MARGEN_MOSAICO, recorte, izquierda, arriba))
            x += ancho_r + MARGEN_MOSAICO
            alto_hilera = max(alto_hilera, alto_r)
        if lote:
            leer_lote()
        return resultados


def releer_bajo_los_nombres(
    relector: Relector,
    lecturas: list[Lectura],
    faltantes: dict[str, set[str]],
) -> list[RecintoLeido]:
    """Busca los números que faltan bajo los nombres de sala que se les parecen.

    ``faltantes``: número → cómo lo nombran las planillas. Solo se acepta el
    número esperado, leído justo bajo un nombre que coincide con el de la
    planilla: así una lectura dudosa no inventa un recinto.
    """
    textos = [
        l for l in lecturas if not como_numero(l.texto) and sum(c.isalpha() for c in l.texto) >= 3
    ]
    encontrados: list[RecintoLeido] = []
    for numero, nombres in sorted(faltantes.items()):
        candidatos = [t for t in textos if parecido(t.texto, nombres) >= 0.5]
        for nombre in sorted(candidatos, key=lambda t: -parecido(t.texto, nombres)):
            alto = nombre.alto
            region = (nombre.x0 - 2 * alto, nombre.y1, nombre.x1 + 2 * alto, nombre.y1 + 2.4 * alto)
            leido = next(
                (
                    l
                    for factor in (1, 3)
                    for l in relector.leer(region, factor)
                    if es_el_numero_esperado(l.texto, numero)
                ),
                None,
            )
            if leido is not None:
                caja = (leido.x0, leido.y0, leido.x1, leido.y1)
                encontrados.append(
                    RecintoLeido(
                        numero,
                        _nombre_sobre(caja, textos, leido.alto) or nombre.texto.strip(),
                        round((leido.x0 + leido.x1) / 2, 1),
                        round(leido.y1 + leido.alto, 1),
                    )
                )
                break
    return encontrados


def releer_sin_numero(
    relector: Relector,
    lecturas: list[Lectura],
    interpretacion: Interpretacion,
    codigo_piso: str,
    encontrados: set[str],
) -> list[RecintoLeido]:
    """Busca el código de los nombres de sala que quedaron sin uno.

    Se vuelve a leer, más grande, justo donde iría el código según cómo
    rotula la lámina: encima del nombre en la Biblioteca, debajo en el CADI.
    Solo se acepta un código de la forma de la lámina que no esté ya en el
    piso: así una lectura dudosa no repite ni inventa un recinto.
    """
    rotulado = interpretacion.rotulado
    if rotulado is None:
        return []
    alto = rotulado.alto
    nombres = [l for l in lecturas if es_nombre(l.texto)]
    textos = [l for l in lecturas if not como_codigo(l.texto) and any(c.isalpha() for c in l.texto)]
    categorias = [t for t in textos if es_categoria(t.texto)]
    huerfanos = [
        n
        for n in nombres
        if id(n) not in interpretacion.usadas
        # De la letra de los rótulos: los títulos y la viñeta son más grandes.
        and 0.6 * alto <= n.alto <= 1.6 * alto
    ]
    # Primero lo que está más arriba: con el nombre en dos líneas, la de
    # arriba es la que va pegada al código.
    huerfanos.sort(key=lambda n: (n.y0, n.x0))

    def region(nombre: Lectura) -> tuple[float, float, float, float]:
        # Holgada a los lados: un trozo angosto (una palabra del nombre)
        # cortaría el código.
        centro = nombre.centro[0]
        x0, x1 = min(nombre.x0, centro - 3 * alto) - alto, max(nombre.x1, centro + 3 * alto) + alto
        if rotulado.nombre_debajo:
            return (x0, nombre.y0 - 2.6 * alto, x1, nombre.y0 + 0.2 * alto)
        return (x0, nombre.y1 - 0.2 * alto, x1, nombre.y1 + 2.6 * alto)

    def distancia(nombre: Lectura, lectura: Lectura) -> float:
        return abs(nombre.y0 - lectura.y1 if rotulado.nombre_debajo else lectura.y0 - nombre.y1)

    leidas = relector.leer_varios([region(n) for n in huerfanos], factor=3)
    hallados: list[RecintoLeido] = []
    tomadas: set[int] = set()
    for nombre, lecturas_region in zip(huerfanos, leidas):
        if id(nombre) in tomadas:
            continue
        candidatos = [
            (l, codigo)
            for l in lecturas_region
            if (codigo := como_codigo(l.texto))
            and rotulado.admite(codigo, codigo_piso)
            and codigo not in encontrados
            and 0.6 * alto <= l.alto <= 1.8 * alto
            and nombre.x0 - alto <= l.centro[0] <= nombre.x1 + alto
        ]
        if not candidatos:
            continue
        # El más pegado al nombre.
        leida, codigo = min(candidatos, key=lambda par: distancia(nombre, par[0]))
        caja = (leida.x0, leida.y0, leida.x1, leida.y1)
        recinto, usadas = _recinto_del_rotulo(codigo, caja, textos, nombres, categorias, rotulado)
        if recinto.nombre is None:
            recinto = RecintoLeido(recinto.numero, limpiar_nombre(nombre.texto), recinto.x, recinto.y)
        hallados.append(recinto)
        encontrados.add(codigo)
        tomadas |= usadas
    return hallados


# --------------------------------------------------------------------------
# Una lámina, de principio a fin
# --------------------------------------------------------------------------
@dataclass
class LecturaDeLamina:
    recintos: list[RecintoLeido]
    #: Cuántos de ``recintos`` salieron de la segunda lectura.
    releidos: int
    racks: list[RecintoLeido]
    avisos: list[str]
    rotulado: Rotulado | None


def leer_recintos_de_lamina(
    ruta: Path,
    ancho_plano: int,
    alto_plano: int,
    codigo_piso: str,
    ocr,
    *,
    esperados: dict[str, set[str]] | None = None,
    ya_en_el_piso: set[str] | frozenset[str] = frozenset(),
) -> LecturaDeLamina:
    """Los recintos y racks de una lámina.

    ``esperados``: número → cómo nombran las planillas ese recinto, si las
    hay. ``ya_en_el_piso``: lo encontrado en las otras láminas del piso, que
    no se vuelve a buscar.
    """
    from app.servicios.recintos import numero_base

    esperados = esperados or {}
    matriz = dibujar_lamina(ruta)
    lecturas = leer_lamina(ruta, ancho_plano, alto_plano, ocr, matriz)
    interpretacion = interpretar(lecturas, codigo_piso, esperados)
    relector = Relector(matriz, ancho_plano, ocr)
    encontrados = set(ya_en_el_piso) | {r.numero for r in interpretacion.recintos}
    faltantes = {
        numero: nombres
        for numero, nombres in esperados.items()
        if not {numero, numero_base(numero)} & encontrados
    }
    releidos = releer_bajo_los_nombres(relector, lecturas, faltantes)
    encontrados |= {r.numero for r in releidos}
    releidos += releer_sin_numero(relector, lecturas, interpretacion, codigo_piso, encontrados)
    racks, avisos_racks = interpretar_racks(lecturas)
    return LecturaDeLamina(
        recintos=[*interpretacion.recintos, *releidos],
        releidos=len(releidos),
        racks=racks,
        avisos=[*interpretacion.avisos, *avisos_racks],
        rotulado=interpretacion.rotulado,
    )
