"""Lee los números de recinto de las láminas y los deja en ``<código>-recintos.csv``.

    python -m app.scripts.extraer_recintos CADI
    python -m app.scripts.extraer_recintos CADI cadi-p01-t2.svg     # solo esa lámina

Cada sala de los planos lleva su número bajo el nombre (``SALA 1`` / ``0021``)
y los números siguen el piso: los del subterráneo empiezan con 00, los del
primer piso con 1, los del segundo con 2, y así. Las láminas exportadas desde
CAD traen el texto convertido en trazos, así que se leen como imagen: cada una
se dibuja a unos 11 500 px de ancho y pasa por un OCR (RapidOCR) en pedazos
que se solapan. De lo leído quedan:

* los números del piso de la lámina, con el nombre que tienen encima y el
  punto bajo el número donde el sistema dibujará los elementos del recinto;
* los rótulos de los racks («RACK 08» → ``R08``), que ubican el rack aunque su
  sala no tenga número, como las salas eléctricas del CADI.

Un número tapado por una línea del dibujo (la X de un hall, una silla) no se
alcanza a leer en la lámina completa. Para los recintos que nombran las
planillas y no aparecieron, se lee de nuevo justo bajo cada nombre parecido,
en un recorte más grande, y se acepta solo el número que dice la planilla.

El resultado va a ``data/<código>/<código>-recintos.csv``: lámina, número,
nombre, x, y, y la huella de la versión de la lámina que se leyó. Se revisa y
se versiona como cualquier planilla: una fila mal leída se corrige o se borra
a mano. Al cargar las láminas, el sistema ubica cada elemento en el recinto
que dice su ubicación (ver ``app.servicios.recintos``). Si una lámina cambia,
hay que volver a leerla: el sistema no usa recintos de otra versión.

El informe final cruza lo leído con las planillas del levantamiento: los
recintos que las planillas nombran y que no aparecen en las láminas de su piso
son errores de transcripción o salas que el OCR no alcanzó a leer.

El OCR es una dependencia aparte, que solo necesita quien lee las láminas:

    .venv/bin/python -m pip install -r requirements-ocr.txt

Toma cerca de un minuto por lámina.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.scripts.cargar_planos import archivos_de_laminas, dimensiones_svg
from app.scripts.importar_edificio import (
    DIR_DATA,
    EQ_UBICACION,
    PD_ROSETA,
    PD_UBICACION,
    descubrir_planillas,
    nombre_recinto,
    piso_y_tramo,
    texto_csv,
)
from app.servicios.planos import (
    NombreLaminaInvalido,
    interpretar_nombre_lamina,
    quitar_caracteres_de_control,
)
from app.servicios.recintos import (
    RE_NUMERO_EXACTO,
    FilaRecinto,
    archivo_recintos,
    clave_rack,
    corresponde_al_piso,
    escribir_recintos,
    huella_lamina,
    leer_recintos,
    numero_base,
    numero_de_recinto,
    similitud,
)

#: Ancho al que se dibuja la lámina para leerla: en las del CADI, los números
#: de sala quedan de unos 25 px de alto.
ANCHO_LECTURA = 11_500
#: Pedazos que se pasan al OCR. El solape es mayor que cualquier rótulo, así
#: que cada uno queda entero en algún pedazo.
TAMANO_PEDAZO = 1600
SOLAPE = 200

#: Lo que el OCR suele confundir dentro de un número.
CONFUSIONES = str.maketrans({"O": "0", "o": "0", "Q": "0", "I": "1", "l": "1", "|": "1"})
#: Al releer un número tapado por una línea, comparándolo con el esperado.
CONFUSIONES_AMPLIAS = str.maketrans(
    {"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "T": "1",
     "Z": "2", "S": "5", "B": "8", "G": "6"}
)
#: Rótulo de un rack: «RACK 08», «Rack 11», «RACK 1 PRINCIPAL».
RE_ROTULO_RACK = re.compile(r"^\s*RACK\s*[-:#.]*\s*([0-9OoIl|]{1,3})(?![0-9A-Za-z])", re.IGNORECASE)


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
    #: Donde se dibujan sus elementos: bajo el número.
    x: float
    y: float


def como_numero(texto: str) -> str | None:
    """«1083», «1083.2» o «OO17» (0017) como número de recinto; None si no lo es."""
    limpio = texto.strip().replace(" ", "")
    if sum(c.isdigit() for c in limpio) < 2:
        return None
    candidato = limpio.translate(CONFUSIONES).replace(",", ".")
    return candidato if RE_NUMERO_EXACTO.fullmatch(candidato) else None


def _nombre_sobre(caja: tuple[float, float, float, float], textos: list[Lectura], alto: float) -> str | None:
    """Las líneas de texto justo encima del número (hasta tres), de arriba abajo."""
    x0, y0, x1, _ = caja
    centro = (x0 + x1) / 2
    lineas: list[Lectura] = []
    techo = y0
    for _ in range(3):
        encima = [
            t
            for t in textos
            if t not in lineas
            and techo - 1.2 * alto <= t.y1 <= techo + 0.3 * alto
            and t.x0 - 0.5 * alto <= centro <= t.x1 + 0.5 * alto
        ]
        if not encima:
            break
        # La más cercana y, entre lecturas de la misma línea, la más completa.
        linea = max(encima, key=lambda t: (round(t.y1 / (0.5 * alto)), len(t.texto)))
        lineas.insert(0, linea)
        techo = linea.y0
    return " ".join(t.texto.strip() for t in lineas) or None


def _parecido(nombre: str | None, esperados: set[str]) -> float:
    """El mayor parecido entre lo leído y cómo nombran las planillas al recinto."""
    return max((similitud(nombre, esperado) for esperado in esperados), default=0.0)


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
    esperados = esperados or {}
    numeros = [
        (lectura, numero)
        for lectura in lecturas
        if (numero := como_numero(lectura.texto)) and corresponde_al_piso(numero, codigo_piso)
    ]
    if not numeros:
        return [], []
    # Los números de sala tienen todos el mismo tamaño: lo de otro tamaño son
    # cotas, la viñeta u otros rótulos.
    altos = sorted(lectura.alto for lectura, _ in numeros)
    alto = altos[len(altos) // 2]
    numeros = [(l, n) for l, n in numeros if 0.6 * alto <= l.alto <= 1.8 * alto]

    # Un rótulo puede leerse dos veces (pedazos que se solapan) o estar
    # repetido en el CAD justo al lado: es el mismo recinto.
    grupos: dict[str, list[list[Lectura]]] = defaultdict(list)
    for lectura, numero in sorted(numeros, key=lambda p: (p[0].y0, p[0].x0)):
        cx, cy = lectura.centro
        for grupo in grupos[numero]:
            gx, gy = grupo[0].centro
            if abs(gx - cx) < 4 * alto and abs(gy - cy) < 2 * alto:
                grupo.append(lectura)
                break
        else:
            grupos[numero].append([lectura])

    textos = [l for l in lecturas if not como_numero(l.texto) and any(c.isalpha() for c in l.texto)]
    recintos: list[RecintoLeido] = []
    avisos: list[str] = []
    for numero, ocurrencias in sorted(grupos.items()):
        candidatos = []
        for grupo in ocurrencias:
            caja = (
                min(l.x0 for l in grupo),
                min(l.y0 for l in grupo),
                max(l.x1 for l in grupo),
                max(l.y1 for l in grupo),
            )
            alto_rotulo = caja[3] - caja[1]
            candidatos.append(
                RecintoLeido(
                    numero=numero,
                    nombre=_nombre_sobre(caja, textos, alto_rotulo),
                    x=round((caja[0] + caja[2]) / 2, 1),
                    y=round(caja[3] + alto_rotulo, 1),
                )
            )
        elegido = max(
            candidatos,
            key=lambda r: (_parecido(r.nombre, esperados.get(numero, set())), r.nombre is not None),
        )
        if len(candidatos) > 1:
            avisos.append(
                f"el {numero} aparece {len(candidatos)} veces; se usó el de "
                f"({elegido.x:.0f}, {elegido.y:.0f})"
                + (f", bajo «{elegido.nombre}»" if elegido.nombre else "")
            )
        recintos.append(elegido)
    return recintos, avisos


def _caja(lecturas: list[Lectura]) -> tuple[float, float, float, float]:
    return (
        min(l.x0 for l in lecturas),
        min(l.y0 for l in lecturas),
        max(l.x1 for l in lecturas),
        max(l.y1 for l in lecturas),
    )


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
def crear_ocr():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise SystemExit(
            "Falta el OCR para leer las láminas. Instálelo una vez con:\n"
            "  cd backend && .venv/bin/python -m pip install -r requirements-ocr.txt"
        ) from None
    return RapidOCR()


def leer_lamina(ruta: Path, ancho_plano: int, alto_plano: int, ocr) -> list[Lectura]:
    """Todo el texto de la lámina, con sus cajas en las unidades del plano."""
    import numpy as np
    import pyvips

    pyvips.cache_set_max(0)
    natural = pyvips.Image.new_from_file(str(ruta))
    escala = ANCHO_LECTURA / natural.width
    del natural
    imagen = pyvips.Image.new_from_file(str(ruta), scale=escala)
    if imagen.hasalpha():
        imagen = imagen.flatten(background=[255] * (imagen.bands - 1))
    if imagen.bands == 1:
        imagen = imagen.bandjoin([imagen, imagen])
    ancho, alto = imagen.width, imagen.height
    matriz = np.ndarray(
        buffer=imagen.write_to_memory(), dtype=np.uint8, shape=[alto, ancho, imagen.bands]
    )[:, :, :3]
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


class Relector:
    """Lee de nuevo trozos de una lámina, más grandes que en la primera pasada."""

    def __init__(self, ruta: Path, ancho_plano: int, alto_plano: int, ocr) -> None:
        self.ruta, self.ancho_plano, self.alto_plano, self.ocr = ruta, ancho_plano, alto_plano, ocr
        self._imagenes: dict[int, object] = {}

    def _imagen(self, factor: int):
        import pyvips

        if factor not in self._imagenes:
            natural = pyvips.Image.new_from_file(str(self.ruta))
            escala = ANCHO_LECTURA / natural.width * factor
            self._imagenes[factor] = pyvips.Image.new_from_file(str(self.ruta), scale=escala)
        return self._imagenes[factor]

    def leer(self, region: tuple[float, float, float, float], factor: int) -> list[Lectura]:
        import numpy as np

        imagen = self._imagen(factor)
        por_unidad = imagen.width / self.ancho_plano
        izquierda = max(0, int(region[0] * por_unidad))
        arriba = max(0, int(region[1] * por_unidad))
        ancho = min(imagen.width, int(region[2] * por_unidad)) - izquierda
        alto = min(imagen.height, int(region[3] * por_unidad)) - arriba
        if ancho < 8 or alto < 8:
            return []
        recorte = imagen.crop(izquierda, arriba, ancho, alto)
        if recorte.hasalpha():
            recorte = recorte.flatten(background=[255] * (recorte.bands - 1))
        matriz = np.ndarray(
            buffer=recorte.write_to_memory(), dtype=np.uint8, shape=[alto, ancho, recorte.bands]
        )[:, :, :3]
        resultado, _ = self.ocr(np.ascontiguousarray(matriz))
        lecturas = []
        for caja, texto, _confianza in resultado or []:
            xs = [float(p[0]) for p in caja]
            ys = [float(p[1]) for p in caja]
            lecturas.append(
                Lectura(
                    texto,
                    (izquierda + min(xs)) / por_unidad,
                    (arriba + min(ys)) / por_unidad,
                    (izquierda + max(xs)) / por_unidad,
                    (arriba + max(ys)) / por_unidad,
                )
            )
        return lecturas


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
        candidatos = [t for t in textos if _parecido(t.texto, nombres) >= 0.5]
        for nombre in sorted(candidatos, key=lambda t: -_parecido(t.texto, nombres)):
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


# --------------------------------------------------------------------------
# Planillas
# --------------------------------------------------------------------------
def recintos_de_las_planillas(dir_datos: Path, prefijo: str) -> dict[tuple[str, str], set[str]]:
    """(piso, número) → cómo nombran las planillas ese recinto."""
    nombres: dict[tuple[str, str], set[str]] = defaultdict(set)

    def filas(ruta: Path) -> list[list[str]]:
        if not ruta.is_file():
            return []
        texto, separador, _ = texto_csv(ruta)
        return list(csv.reader(io.StringIO(texto, newline=""), delimiter=separador))[1:]

    for archivo, codigo_piso, _ in descubrir_planillas(dir_datos, prefijo):
        for fila in filas(dir_datos / archivo):
            ubicacion = fila[EQ_UBICACION].strip() if len(fila) > EQ_UBICACION else ""
            if numero := numero_de_recinto(ubicacion, codigo_piso):
                nombres[codigo_piso, numero].add(ubicacion)
    for fila in filas(dir_datos / f"{prefijo}-puntos-de-datos.csv"):
        piso_tramo = piso_y_tramo(fila[PD_UBICACION]) if len(fila) > PD_UBICACION else None
        if piso_tramo is None or len(fila) <= PD_ROSETA:
            continue
        recinto = nombre_recinto(fila[PD_ROSETA])
        if numero := numero_de_recinto(recinto, piso_tramo[0]):
            nombres[piso_tramo[0], numero].add(recinto)
    return nombres


def _sugerencia(nombres: set[str], leidos: list[FilaRecinto]) -> str | None:
    """El recinto leído cuyo nombre se parece al de las planillas."""
    mejor = max(leidos, key=lambda f: _parecido(f.nombre, nombres), default=None)
    if mejor is None or _parecido(mejor.nombre, nombres) < 0.5:
        return None
    return f"{mejor.numero} ({mejor.nombre})"


# --------------------------------------------------------------------------
# Programa
# --------------------------------------------------------------------------
def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Lee los números de recinto de las láminas")
    parser.add_argument("edificio", help="Código del edificio, p. ej. CADI")
    parser.add_argument(
        "laminas", nargs="*", help="Solo estas láminas (por omisión, todas las de la carpeta)"
    )
    parser.add_argument(
        "--datos", type=Path, help="Carpeta del edificio (por omisión data/<código>)"
    )
    args = parser.parse_args(argumentos)
    codigo = args.edificio.upper()
    dir_datos = args.datos or DIR_DATA / codigo.lower()
    dir_planos = dir_datos / "planos"

    pedidas = {n.lower() for n in args.laminas}
    laminas = []
    for ruta in archivos_de_laminas(dir_planos):
        if pedidas and ruta.name.lower() not in pedidas:
            continue
        try:
            lamina = interpretar_nombre_lamina(ruta.name, edificio=codigo)
        except NombreLaminaInvalido as exc:
            print(f"  ! {exc}")
            continue
        if lamina.extension == ".svg":
            laminas.append((ruta, lamina))
    if not laminas:
        raise SystemExit(f"No hay láminas SVG que leer en {dir_planos}")

    planillas = recintos_de_las_planillas(dir_datos, codigo.lower())
    ruta_csv = archivo_recintos(dir_datos, codigo)
    anteriores, avisos = leer_recintos(ruta_csv)
    for aviso in avisos:
        print(f"  ! {aviso}")
    leidas = {ruta.name for ruta, _ in laminas}
    filas = [f for f in anteriores if f.lamina not in leidas]

    ocr = crear_ocr()
    # Lo ya encontrado en cada piso: no se vuelve a buscar en sus otras láminas.
    del_piso: dict[str, set[str]] = defaultdict(set)
    for fila in filas:
        del_piso[interpretar_nombre_lamina(fila.lamina, edificio=codigo).piso].add(fila.numero)
    for ruta, lamina in laminas:
        inicio = time.monotonic()
        contenido = quitar_caracteres_de_control(ruta.read_bytes())
        ancho, alto = dimensiones_svg(contenido)
        lecturas = leer_lamina(ruta, ancho, alto, ocr)
        esperados = {
            numero: nombres for (piso, numero), nombres in planillas.items() if piso == lamina.piso
        }
        recintos, avisos = interpretar_lecturas(lecturas, lamina.piso, esperados)
        encontrados = del_piso[lamina.piso] | {r.numero for r in recintos}
        faltantes = {
            numero: nombres
            for numero, nombres in esperados.items()
            if not {numero, numero_base(numero)} & encontrados
        }
        releidos = releer_bajo_los_nombres(Relector(ruta, ancho, alto, ocr), lecturas, faltantes)
        racks, avisos_racks = interpretar_racks(lecturas)
        huella = huella_lamina(contenido)
        for recinto in [*recintos, *releidos, *racks]:
            filas.append(FilaRecinto(ruta.name, recinto.numero, recinto.nombre, recinto.x, recinto.y, huella))
            del_piso[lamina.piso].add(recinto.numero)
        print(
            f"  {ruta.name}: {len(recintos) + len(releidos)} recintos"
            + (f" ({len(releidos)} en la segunda lectura)" if releidos else "")
            + (f", racks {', '.join(r.numero for r in racks)}" if racks else "")
            + f" ({time.monotonic() - inicio:.0f} s)",
            flush=True,
        )
        for aviso in [*avisos, *avisos_racks]:
            print(f"    · {aviso}")

    escribir_recintos(ruta_csv, filas)
    print(f"\nRecintos guardados en {ruta_csv}")

    # Lo que las planillas nombran y no aparece en las láminas de su piso.
    por_piso: dict[str, list[FilaRecinto]] = defaultdict(list)
    for fila in filas:
        por_piso[interpretar_nombre_lamina(fila.lamina, edificio=codigo).piso].append(fila)
    faltan = []
    for (piso, numero), nombres in sorted(planillas.items()):
        leidos = por_piso.get(piso)
        if not leidos:
            continue  # piso sin láminas leídas
        if {numero, numero_base(numero)} & {f.numero for f in leidos}:
            continue
        sugerencia = _sugerencia(nombres, leidos)
        faltan.append(
            f"    - {piso} {numero} «{' / '.join(sorted(nombres))}»"
            + (f" → en la lámina: {sugerencia}" if sugerencia else "")
        )
    if faltan:
        print(
            f"\nRecintos de las planillas que no aparecen en las láminas de su piso ({len(faltan)}).\n"
            "  Puede ser un número mal transcrito en la planilla o un rótulo que el OCR no leyó\n"
            f"  (agréguelo a mano a {ruta_csv.name}):"
        )
        print("\n".join(faltan))


if __name__ == "__main__":
    main()
