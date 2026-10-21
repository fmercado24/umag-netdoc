"""Recintos de las láminas y ubicación automática de los elementos.

Cada sala de los planos lleva su número bajo el nombre (``SALA 1`` / ``0021``),
y el número dice el piso: los del subterráneo empiezan con 00 (``0017``), los
del primer piso con 1 (``1083``), los del segundo con 2, y así. Las planillas
del levantamiento anotan ese mismo número en la ubicación de cada elemento
(«Oficina 1083»), de modo que basta con encontrarlo en la lámina para saber
dónde dibujar el elemento.

* ``numero_de_recinto`` saca el número de sala de un texto de ubicación.
* ``sincronizar_recintos`` copia ``<edificio>-recintos.csv`` a la tabla
  ``recinto``. Ese archivo lo escribe ``app.scripts.extraer_recintos``
  leyendo las láminas, y cada fila lleva la huella de la versión de la lámina
  de la que se leyó: una versión nueva necesita volver a leerse.
* ``ubicar_en_recinto`` y ``ubicar_pendientes`` dejan cada elemento en su
  recinto. Los puntos de datos de una sala quedan todos en el mismo punto, y
  el visor los agrupa en un marcador que se despliega; los demás equipos van
  uno al lado del otro, para no taparse.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import (
    Edificio,
    Elemento,
    OrigenCambio,
    Piso,
    Plano,
    Recinto,
    TipoElemento,
)
from app.servicios.historial import registrar_cambios
from app.servicios.planos import NombreLaminaInvalido, interpretar_nombre_lamina

# --------------------------------------------------------------------------
# Números de recinto
# --------------------------------------------------------------------------
#: Cuatro cifras y, en las subdivisiones de una sala, un decimal: "1083.2".
RE_NUMERO = re.compile(r"(?<!\d)(\d{4})(?:[.,](\d{1,2})(?!\d))?(?!\d)")
RE_NUMERO_EXACTO = re.compile(r"\d{4}(?:\.\d{1,2})?")


def prefijo_de_piso(codigo_piso: str) -> str | None:
    """Con qué empiezan los números de recinto del piso: ``P00`` → ``00``,
    ``P03`` → ``3``. None si el piso no sigue la convención (``PXX``, ``P10``)."""
    coincidencia = re.fullmatch(r"P(\d{2})", codigo_piso.strip().upper())
    if coincidencia is None or int(coincidencia.group(1)) > 9:
        return None
    numero = int(coincidencia.group(1))
    return "00" if numero == 0 else str(numero)


def numeros_en(texto: str | None) -> list[str]:
    """Los números de cuatro cifras de un texto: «oficina 1083.2» → ['1083.2']."""
    return [numero + (f".{decimal}" if decimal else "") for numero, decimal in RE_NUMERO.findall(texto or "")]


def corresponde_al_piso(numero: str, codigo_piso: str) -> bool:
    prefijo = prefijo_de_piso(codigo_piso)
    return prefijo is not None and numero.startswith(prefijo)


def numero_de_recinto(texto: str | None, codigo_piso: str) -> str | None:
    """El número de recinto que trae un texto de ubicación, o None.

    Solo cuenta un número del piso: en «Oficina 1039/2018» del primer piso es
    1039, y «Box Fisiopatología 2022» del tercero no tiene ninguno (2022 es del
    segundo piso: es un error de la planilla). Si hay varios, el último, que es
    donde las planillas anotan el número de sala.
    """
    del_piso = [n for n in numeros_en(texto) if corresponde_al_piso(n, codigo_piso)]
    return del_piso[-1] if del_piso else None


def normalizar_numero(valor: str) -> str | None:
    """El número tal como se guarda («1083,2» → «1083.2»), o None si no es uno."""
    texto = valor.strip().replace(",", ".")
    return texto if RE_NUMERO_EXACTO.fullmatch(texto) else None


def numero_base(numero: str) -> str:
    """'1083.2' → '1083': la sala que contiene a una subdivisión sin rótulo propio."""
    return numero.split(".", 1)[0]


#: Los racks también están rotulados en las láminas («RACK 08», «Rack 11»), y
#: así se guardan entre los recintos: «R08». Ubican el rack aunque su sala no
#: tenga número en el plano, como las salas eléctricas del CADI.
RE_CLAVE_RACK = re.compile(r"R\d{2,3}")


def clave_rack(numero: int) -> str:
    return f"R{numero:02d}"


def es_rotulo_de_rack(numero: str) -> bool:
    return RE_CLAVE_RACK.fullmatch(numero) is not None


# --------------------------------------------------------------------------
# <edificio>-recintos.csv
# --------------------------------------------------------------------------
COLUMNAS = ("lamina", "numero", "nombre", "x", "y", "huella")


@dataclass(frozen=True)
class FilaRecinto:
    """Un recinto leído de una lámina.

    ``x`` e ``y`` están en las unidades del plano y marcan el punto donde se
    dibujan sus elementos: bajo el número, para no tapar el rótulo.
    """

    lamina: str  # "cadi-p01-t2.svg"
    numero: str
    nombre: str | None
    x: float
    y: float
    #: Versión de la lámina de la que se leyó (``huella_lamina``).
    huella: str


def huella_lamina(contenido: bytes) -> str:
    """Identifica una versión de la lámina, tal como el sistema la guarda."""
    return hashlib.sha256(contenido).hexdigest()[:16]


def archivo_recintos(dir_datos: Path, codigo_edificio: str) -> Path:
    return dir_datos / f"{codigo_edificio.lower()}-recintos.csv"


def leer_recintos(ruta: Path) -> tuple[list[FilaRecinto], list[str]]:
    """Las filas del archivo y los avisos de las que no se pudieron leer."""
    if not ruta.is_file():
        return [], []
    filas: list[FilaRecinto] = []
    avisos: list[str] = []
    texto = ruta.read_text(encoding="utf-8-sig")
    for numero_fila, fila in enumerate(csv.DictReader(io.StringIO(texto, newline="")), start=2):
        try:
            clave = (fila.get("numero") or "").strip().upper()
            numero = normalizar_numero(clave) or (clave if es_rotulo_de_rack(clave) else None)
            if numero is None:
                raise ValueError(f"número de recinto ilegible «{fila.get('numero') or ''}»")
            filas.append(
                FilaRecinto(
                    lamina=(fila.get("lamina") or "").strip(),
                    numero=numero,
                    nombre=(fila.get("nombre") or "").strip() or None,
                    x=float(fila["x"]),
                    y=float(fila["y"]),
                    huella=(fila.get("huella") or "").strip(),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            avisos.append(f"{ruta.name} fila {numero_fila}: {exc}")
    return filas, avisos


def escribir_recintos(ruta: Path, filas: list[FilaRecinto]) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(COLUMNAS)
        for fila in sorted(filas, key=lambda f: (f.lamina, f.numero)):
            escritor.writerow(
                [fila.lamina, fila.numero, fila.nombre or "", f"{fila.x:.1f}", f"{fila.y:.1f}", fila.huella]
            )


# --------------------------------------------------------------------------
# Tabla recinto
# --------------------------------------------------------------------------
@dataclass
class InformeRecintos:
    #: Nombre del plano → cuántos recintos tiene.
    cargados: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


def _huella_guardada(plano: Plano) -> str | None:
    ruta = configuracion.dir_media / plano.archivo
    return huella_lamina(ruta.read_bytes()) if ruta.is_file() else None


def _reemplazar_recintos(plano: Plano, filas: list[FilaRecinto], informe: InformeRecintos) -> None:
    """Deja los recintos del plano iguales a las filas, tocando solo lo que cambió."""
    deseados: dict[str, FilaRecinto] = {}
    for fila in filas:
        if fila.numero in deseados:
            informe.avisos.append(
                f"el recinto {fila.numero} aparece dos veces en «{fila.lamina}»; se usó el primero"
            )
            continue
        deseados[fila.numero] = fila
    actuales = {recinto.numero: recinto for recinto in plano.recintos}
    for numero, recinto in actuales.items():
        if numero not in deseados:
            plano.recintos.remove(recinto)
    for numero, fila in deseados.items():
        recinto = actuales.get(numero)
        if recinto is None:
            plano.recintos.append(Recinto(numero=numero, nombre=fila.nombre, pos_x=fila.x, pos_y=fila.y))
        else:
            recinto.nombre, recinto.pos_x, recinto.pos_y = fila.nombre, fila.x, fila.y


def sincronizar_recintos(sesion: Session, edificio: Edificio, dir_datos: Path) -> InformeRecintos:
    """Copia ``<edificio>-recintos.csv`` a los planos vigentes del edificio.

    Las filas de una lámina se cargan solo si se leyeron de la versión vigente
    (la huella coincide): con otra versión, los números podrían estar en otro
    lugar del dibujo. Ese caso se avisa y el plano conserva lo que tenía.
    """
    informe = InformeRecintos()
    ruta = archivo_recintos(dir_datos, edificio.codigo)
    filas, informe.avisos = leer_recintos(ruta)

    por_lamina: dict[tuple[str, str | None], list[FilaRecinto]] = defaultdict(list)
    for fila in filas:
        try:
            lamina = interpretar_nombre_lamina(fila.lamina, edificio=edificio.codigo)
        except NombreLaminaInvalido as exc:
            informe.avisos.append(f"{ruta.name}: {exc}")
            continue
        por_lamina[lamina.piso, lamina.tramo].append(fila)

    # Con una consulta, y no con piso.planos: así se ve también un plano
    # recién guardado en esta misma sesión.
    vigentes = sesion.scalars(
        select(Plano)
        .join(Piso, Plano.piso_id == Piso.id)
        .where(Piso.edificio_id == edificio.id, Plano.vigente.is_(True))
        .order_by(Plano.nombre)
    ).all()
    for plano in vigentes:
        propias = por_lamina.pop((plano.piso.codigo, plano.tramo_codigo), [])
        if propias and {f.huella for f in propias} != {_huella_guardada(plano)}:
            informe.avisos.append(
                f"{ruta.name} se leyó de otra versión de «{propias[0].lamina}»: sus recintos no se "
                f"cargaron. Vuelva a leerlos con python -m app.scripts.extraer_recintos {edificio.codigo}"
            )
        elif propias:
            _reemplazar_recintos(plano, propias, informe)
        if plano.recintos:
            informe.cargados[plano.nombre] = len(plano.recintos)

    for propias in por_lamina.values():
        informe.avisos.append(
            f"{ruta.name}: la lámina «{propias[0].lamina}» aún no está cargada; "
            "sus recintos se cargarán con ella"
        )
    sesion.flush()
    return informe


def recintos_del_piso(piso: Piso) -> list[Recinto]:
    """Los recintos de las láminas vigentes del piso."""
    return [r for plano in piso.planos if plano.vigente for r in plano.recintos]


# --------------------------------------------------------------------------
# Ubicación automática
# --------------------------------------------------------------------------
#: Distancia entre los marcadores de un mismo recinto, como fracción del ancho
#: del plano. En las láminas del CADI son unas 8 unidades: los marcadores
#: quedan uno junto al otro al acercarse a ver el recinto.
SEPARACION = 1 / 350


def _desplazamientos() -> list[tuple[int, int]]:
    """Lugares para los equipos de un recinto, en pasos de ``SEPARACION``.

    El centro es de los puntos de datos (un marcador por grupo). Los equipos
    van alrededor, primero a los lados y después más abajo, lejos del rótulo.
    """
    lugares = [(dx, dy) for dy in range(4) for dx in range(-3, 4) if (dx, dy) != (0, 0)]
    return sorted(lugares, key=lambda d: (d[0] ** 2 + d[1] ** 2, d[1], abs(d[0]), -d[0]))


DESPLAZAMIENTOS = _desplazamientos()


def _buscar_en_laminas(elemento: Elemento, claves: list[str]) -> Recinto | None:
    """El primero de ``claves`` que aparece en las láminas vigentes del piso,
    mirando primero la lámina donde se dibuja el elemento."""
    piso = elemento.piso
    vigentes = [p for p in piso.planos if p.vigente]
    preferido = piso.plano_para(elemento.tramo_de_lamina)
    orden = sorted(vigentes, key=lambda p: (p is not preferido, p.tramo_codigo or ""))
    for clave in claves:
        for plano in orden:
            for recinto in plano.recintos:
                if recinto.numero == clave:
                    return recinto
    return None


def buscar_recinto(elemento: Elemento) -> Recinto | None:
    """Dónde va el elemento según las láminas de su piso, o None.

    Un rack rotulado en la lámina («RACK 08») va sobre su rótulo; el resto, en
    el recinto de su número. Se busca primero en la lámina donde se dibuja y
    después en las demás del piso: en el CADI, los racks del primer piso que
    el rótulo pone en el tramo 3 están dibujados en la lámina de otro tramo.
    Una subdivisión sin rótulo propio (1083.2) cae en su sala (1083).
    """
    claves: list[str] = []
    if elemento.tipo.codigo == "R" and elemento.correlativo is not None:
        claves.append(clave_rack(elemento.correlativo))
    if elemento.numero_recinto:
        claves += [elemento.numero_recinto, numero_base(elemento.numero_recinto)]
    return _buscar_en_laminas(elemento, list(dict.fromkeys(claves))) if claves else None


def _posicion_libre(
    sesion: Session, elemento: Elemento, plano: Plano, x: float, y: float
) -> tuple[float, float]:
    """El primer lugar libre alrededor de (x, y): los equipos de un mismo
    recinto quedan uno al lado del otro, sin taparse."""
    # La sesión no se vacía sola antes de consultar: sin esto no se verían
    # los lugares que se acaban de asignar en esta misma pasada.
    sesion.flush()
    paso = plano.ancho_px * SEPARACION
    ocupadas = {
        (round(ox, 1), round(oy, 1))
        for ox, oy in sesion.execute(
            select(Elemento.pos_x, Elemento.pos_y).where(
                Elemento.plano_id == plano.id,
                Elemento.activo.is_(True),
                Elemento.id != elemento.id,
                Elemento.pos_x.is_not(None),
                Elemento.pos_y.is_not(None),
            )
        )
    }
    for dx, dy in DESPLAZAMIENTOS:
        lx, ly = round(x + dx * paso, 1), round(y + dy * paso, 1)
        if (lx, ly) not in ocupadas and 0 <= lx <= plano.ancho_px and 0 <= ly <= plano.alto_px:
            return lx, ly
    return round(x + paso, 1), y


def _lugar_del_grupo(sesion: Session, elemento: Elemento, plano: Plano) -> tuple[float, float] | None:
    """Donde ya están los otros puntos de datos de la sala en esa lámina.

    Un punto de datos nuevo se suma a ellos aunque el recinto se haya vuelto
    a leer y su punto se haya corrido unas décimas: si no, quedaría en un
    marcador aparte. Si alguno se movió a mano, vale el lugar de la mayoría.
    """
    base = numero_base(elemento.numero_recinto or "")
    if not base:
        return None
    sesion.flush()
    lugares = Counter(
        (round(x, 1), round(y, 1))
        for x, y in sesion.execute(
            select(Elemento.pos_x, Elemento.pos_y)
            .join(TipoElemento, Elemento.tipo_elemento_id == TipoElemento.id)
            .where(
                Elemento.plano_id == plano.id,
                Elemento.activo.is_(True),
                Elemento.id != elemento.id,
                TipoElemento.codigo == "PD",
                or_(Elemento.numero_recinto == base, Elemento.numero_recinto.like(f"{base}.%")),
                Elemento.pos_x.is_not(None),
                Elemento.pos_y.is_not(None),
            )
        )
    )
    return lugares.most_common(1)[0][0] if lugares else None


def describir(recinto: Recinto) -> str:
    return f"{recinto.numero} ({recinto.nombre})" if recinto.nombre else recinto.numero


def _registrar_ubicacion(
    sesion: Session,
    elemento: Elemento,
    plano: Plano,
    x: float,
    y: float,
    *,
    origen: OrigenCambio,
    usuario: str | None,
    comentario: str,
) -> None:
    cambios: dict = {"plano_id": plano.id, "pos_x": x, "pos_y": y}
    # La lámina donde quedó pasa a ser la suya (y la de lo que tiene montado).
    if plano.tramo_id is not None:
        cambios["tramo_lamina_id"] = None if plano.tramo_id == elemento.tramo_id else plano.tramo_id
    registrar_cambios(
        sesion, elemento, cambios, origen=origen, usuario=usuario, comentario=comentario
    )


def ubicar_en_recinto(
    sesion: Session,
    elemento: Elemento,
    *,
    origen: OrigenCambio,
    usuario: str | None = None,
) -> Recinto | None:
    """Deja el elemento donde va según la lámina y devuelve el recinto usado.

    Devuelve None, sin cambiar nada, si el elemento va montado (se ve en su
    rack) o si no hay dónde ponerlo: sin número de recinto, o con uno que no
    está en las láminas de su piso. Los puntos de datos de un recinto quedan
    todos en el mismo punto (el visor los agrupa) y un rack, sobre su rótulo;
    los demás equipos, uno junto al otro.
    """
    if elemento.montado:
        return None
    recinto = buscar_recinto(elemento)
    if recinto is None:
        return None
    plano = recinto.plano
    if elemento.tipo.codigo == "PD":
        x, y = _lugar_del_grupo(sesion, elemento, plano) or (recinto.pos_x, recinto.pos_y)
    elif es_rotulo_de_rack(recinto.numero):
        x, y = recinto.pos_x, recinto.pos_y
    else:
        x, y = _posicion_libre(sesion, elemento, plano, recinto.pos_x, recinto.pos_y)
    donde = (
        f"sobre su rótulo {recinto.nombre or recinto.numero}"
        if es_rotulo_de_rack(recinto.numero)
        else f"en el recinto {describir(recinto)}"
    )
    _registrar_ubicacion(
        sesion,
        elemento,
        plano,
        x,
        y,
        origen=origen,
        usuario=usuario,
        comentario=f"Ubicado {donde} de «{plano.nombre}»",
    )
    return recinto


def _lugar(elemento: Elemento) -> tuple | None:
    """Piso, tramo y ubicación de la planilla («Sala Eléctrica»), sin
    mayúsculas ni tildes: lo que comparten dos elementos de la misma sala."""
    texto = elemento.ubicacion_descriptiva
    if not texto or not palabras_clave(texto):
        return None
    return (
        elemento.piso_id,
        elemento.tramo_id,
        frozenset(palabras_clave(texto)),
        tuple(numeros_en(texto)),
    )


def ubicar_junto_a(
    sesion: Session,
    elemento: Elemento,
    companero: Elemento,
    *,
    origen: OrigenCambio,
    usuario: str | None = None,
) -> None:
    """Lo deja al lado de otro elemento de la misma sala que ya está en el plano.

    Es para las salas sin número en la lámina: las salas eléctricas del CADI
    no lo tienen, pero sus racks sí están rotulados, y el AP o la UPS que la
    planilla pone en la misma sala quedan junto al rack.
    """
    plano = companero.plano
    if elemento.tipo.codigo == "PD" and companero.tipo.codigo == "PD":
        x, y = companero.pos_x, companero.pos_y
    else:
        x, y = _posicion_libre(sesion, elemento, plano, companero.pos_x, companero.pos_y)
    _registrar_ubicacion(
        sesion,
        elemento,
        plano,
        x,
        y,
        origen=origen,
        usuario=usuario,
        comentario=(
            f"Ubicado junto a {companero.codigo}: la planilla los pone en la misma sala "
            f"(«{elemento.ubicacion_descriptiva}»)"
        ),
    )


# --- Sugerencias por nombre --------------------------------------------------
#: Palabras que no distinguen un recinto de otro.
PALABRAS_VACIAS = frozenset({"DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "A", "EN", "ROSETA"})


def palabras_clave(texto: str | None) -> set[str]:
    base = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().upper()
    return {p for p in re.findall(r"[A-Z]+", base) if p not in PALABRAS_VACIAS}


def _misma_palabra(una: str, otra: str) -> bool:
    """Iguales, o casi: el OCR lee «REUNIOINES» o «OFIQINA»."""
    if una == otra:
        return True
    return min(len(una), len(otra)) >= 4 and SequenceMatcher(None, una, otra).ratio() >= 0.8


def similitud(un_nombre: str | None, otro_nombre: str | None) -> float:
    """Qué tanto se parecen dos nombres de recinto, de 0 a 1, por sus palabras.

    «Administración Oficina Médica 3006» y la lectura «ADMNISTRACIQN OFIQINA
    MEICA» dan 1; «Sala de Reuniones» y «REUNIOINES», 0,5.
    """
    unas, otras = palabras_clave(un_nombre), palabras_clave(otro_nombre)
    if not unas or not otras:
        return 0.0
    comunes = sum(1 for p in unas if any(_misma_palabra(p, q) for q in otras))
    return comunes / (len(unas) + len(otras) - comunes)


def sugerir_recinto(elemento: Elemento, recintos: list[Recinto]) -> Recinto | None:
    """El recinto del piso cuyo nombre se parece a la ubicación del elemento.

    Sirve para el informe («Recepción 1063» no está en la lámina, pero sí
    SECRETARÍA RECEPCIÓN 1082). Nunca se aplica solo: si la planilla dice
    otra cosa, lo decide quien conoce el edificio.
    """
    puntajes = [
        (similitud(elemento.ubicacion_descriptiva, recinto.nombre), recinto)
        for recinto in recintos
        if not es_rotulo_de_rack(recinto.numero)
    ]
    mejor = max((p for p, _ in puntajes), default=0)
    if mejor < 0.5:
        return None
    candidatos = {r.numero: r for p, r in puntajes if p == mejor}
    if len(candidatos) == 1:
        return next(iter(candidatos.values()))
    # Empate entre láminas (la sala eléctrica de cada tramo): la del elemento.
    preferido = elemento.piso.plano_para(elemento.tramo_de_lamina)
    propios = [r for r in candidatos.values() if r.plano_id == getattr(preferido, "id", None)]
    return propios[0] if len(propios) == 1 else None


@dataclass
class Pendiente:
    """Un elemento que no se pudo ubicar solo."""

    codigo: str
    piso: str
    ubicacion: str | None
    numero: str | None
    sugerencia: str | None = None


@dataclass
class InformeUbicacion:
    ubicados: int = 0
    #: Ubicados junto a otro elemento de la misma sala (sala sin número).
    junto_a: int = 0
    #: Sin número de recinto: hay que completarlo (en el visor, Editar).
    sin_numero: list[Pendiente] = field(default_factory=list)
    #: Con un número que no aparece en las láminas de su piso.
    no_encontrados: list[Pendiente] = field(default_factory=list)
    #: Pisos cuyas láminas aún no tienen recintos: sus elementos esperan.
    pisos_sin_recintos: list[str] = field(default_factory=list)


def ubicar_pendientes(
    sesion: Session,
    edificio: Edificio,
    *,
    origen: OrigenCambio = OrigenCambio.SISTEMA,
    usuario: str | None = "ubicacion-automatica",
) -> InformeUbicacion:
    """Ubica en su recinto cada elemento del edificio que aún no está en el plano.

    Lo que ya tiene posición no se toca, la haya puesto el sistema o una
    persona. Lo montado se ve donde está su rack.
    """
    informe = InformeUbicacion()
    recintos_por_piso: dict[int, list[Recinto]] = {}
    elementos = sesion.scalars(
        select(Elemento)
        .where(Elemento.edificio_id == edificio.id, Elemento.activo.is_(True))
        .order_by(Elemento.codigo)
    ).unique().all()

    restantes: list[Elemento] = []
    for elemento in elementos:
        if elemento.montado or elemento.tiene_coordenadas:
            continue
        if elemento.piso_id not in recintos_por_piso:
            recintos_por_piso[elemento.piso_id] = recintos_del_piso(elemento.piso)
            if not recintos_por_piso[elemento.piso_id]:
                informe.pisos_sin_recintos.append(elemento.piso.codigo)
        if not recintos_por_piso[elemento.piso_id]:
            continue
        if ubicar_en_recinto(sesion, elemento, origen=origen, usuario=usuario):
            informe.ubicados += 1
        else:
            restantes.append(elemento)

    # Lo que no se ubicó por su recinto va junto a otro elemento de la misma
    # sala que sí quedó en el plano (de preferencia, su rack).
    ubicados_por_lugar: dict[tuple, Elemento] = {}
    for elemento in elementos:
        lugar = _lugar(elemento)
        if lugar is None or elemento.montado or not elemento.tiene_coordenadas:
            continue
        actual = ubicados_por_lugar.get(lugar)
        if actual is None or (elemento.tipo.codigo == "R" and actual.tipo.codigo != "R"):
            ubicados_por_lugar[lugar] = elemento

    for elemento in restantes:
        lugar = _lugar(elemento)
        companero = ubicados_por_lugar.get(lugar) if lugar else None
        if companero is not None and companero.plano is not None:
            ubicar_junto_a(sesion, elemento, companero, origen=origen, usuario=usuario)
            informe.junto_a += 1
            continue
        recintos = recintos_por_piso[elemento.piso_id]
        sugerido = sugerir_recinto(elemento, recintos)
        pendiente = Pendiente(
            codigo=elemento.codigo,
            piso=elemento.piso.codigo,
            ubicacion=elemento.ubicacion_descriptiva,
            numero=elemento.numero_recinto,
            sugerencia=describir(sugerido) if sugerido else None,
        )
        (informe.no_encontrados if elemento.numero_recinto else informe.sin_numero).append(pendiente)
    sesion.flush()
    return informe


def sincronizar_y_ubicar(
    sesion: Session, edificio: Edificio, dir_datos: Path
) -> tuple[InformeRecintos, InformeUbicacion]:
    """Lo que se hace al cargar láminas o elementos: recintos al día y luego
    cada elemento sin posición a su recinto."""
    recintos = sincronizar_recintos(sesion, edificio, dir_datos)
    return recintos, ubicar_pendientes(sesion, edificio)


def lineas_informe(
    recintos: InformeRecintos, ubicacion: InformeUbicacion, *, limite: int = 15
) -> list[str]:
    """El informe para la terminal, con los pendientes agrupados por recinto."""
    lineas: list[str] = []
    if recintos.cargados:
        total = sum(recintos.cargados.values())
        lineas.append(f"Recintos en las láminas: {total} en {len(recintos.cargados)} lámina(s)")
    lineas.extend(f"  ! {aviso}" for aviso in recintos.avisos)
    if ubicacion.ubicados:
        lineas.append(f"Ubicados en su recinto: {ubicacion.ubicados}")
    if ubicacion.junto_a:
        lineas.append(
            f"Ubicados junto a otro elemento de su sala, que no tiene número en la lámina: "
            f"{ubicacion.junto_a}"
        )
    if ubicacion.pisos_sin_recintos:
        lineas.append(
            "Pisos cuyas láminas no tienen recintos (sus elementos esperan): "
            + ", ".join(ubicacion.pisos_sin_recintos)
        )

    def agrupados(pendientes: list[Pendiente]) -> list[str]:
        grupos: dict[tuple[str, str], list[Pendiente]] = defaultdict(list)
        for p in pendientes:
            grupos[p.piso, p.ubicacion or "sin ubicación"].append(p)
        salida = []
        for (piso, ubicacion_texto), miembros in list(grupos.items())[:limite]:
            codigos = ", ".join(m.codigo for m in miembros[:3]) + (
                f" y {len(miembros) - 3} más" if len(miembros) > 3 else ""
            )
            sugerencia = miembros[0].sugerencia
            salida.append(
                f"    - {piso} «{ubicacion_texto}»: {codigos}"
                + (f" → en la lámina: {sugerencia}" if sugerencia else "")
            )
        if len(grupos) > limite:
            salida.append(f"    … y {len(grupos) - limite} recintos más")
        return salida

    if ubicacion.no_encontrados:
        lineas.append(
            f"Con un recinto que no aparece en las láminas de su piso ({len(ubicacion.no_encontrados)}):"
            " corrija el N° de recinto en el visor (Editar) o ubíquelos a mano"
        )
        lineas.extend(agrupados(ubicacion.no_encontrados))
    if ubicacion.sin_numero:
        lineas.append(
            f"Sin número de recinto ({len(ubicacion.sin_numero)}): complételo en el visor "
            "(Editar → N° de recinto) y se ubicarán solos"
        )
        lineas.extend(agrupados(ubicacion.sin_numero))
    return lineas
