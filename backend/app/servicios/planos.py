"""Almacenamiento de planos: nomenclatura, saneamiento y versión vigente.

Lo comparten el endpoint de carga y el script que sube las láminas de
``data/<código>/planos``, para que ambos caminos exijan lo mismo y dejen
exactamente el mismo resultado.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import Elemento, OrigenCambio, Piso, Plano, Tramo
from app.servicios.archivos import contenido_coincide
from app.servicios.historial import registrar_cambios

EXTENSIONES_PLANO = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".pdf"}

#: Caracteres de control que XML 1.0 no admite. Los SVG exportados desde PDF
#: los arrastran en los ``id`` de los textos, y basta uno para que el
#: navegador descarte el plano completo y el visor muestre una imagen rota.
RE_CONTROL_XML = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class PlanoRechazado(Exception):
    """El archivo no puede usarse como plano."""


class FormatoNoAdmitido(PlanoRechazado):
    pass


class SvgInvalido(PlanoRechazado):
    pass


class NombreLaminaInvalido(PlanoRechazado):
    """El nombre no sigue la nomenclatura o no corresponde al destino."""

    def __init__(self, mensaje: str, sugerencia: str | None = None) -> None:
        super().__init__(mensaje)
        #: Nombre estándar deducido del original, si se pudo deducir.
        self.sugerencia = sugerencia


#: Nomenclatura obligatoria de las láminas, la misma de las planillas:
#: ``<edificio>-p<piso>[-t<tramo>].<extensión>``. El piso lleva dos dígitos,
#: como en los códigos del SOP (``p00`` es el subterráneo), y el tramo va sin
#: ceros a la izquierda; sin tramo, la lámina cubre el piso completo. Da igual
#: escribirlo en mayúsculas o minúsculas.
RE_NOMBRE_LAMINA = re.compile(
    r"^([a-z0-9]+)-p(\d{2})(?:-t([1-9]\d*))?(\.[a-z0-9]+)$", re.IGNORECASE
)
NOMENCLATURA = "<edificio>-p<piso>[-t<tramo>].svg (p. ej. cadi-p01-t1.svg o cadi-p04.svg)"


@dataclass(frozen=True)
class NombreLamina:
    """Lo que dice el nombre de una lámina: a qué edificio, piso y tramo va."""

    edificio: str  # "CADI"
    piso: str  # "P01"
    tramo: str | None  # "T1", o None si cubre el piso completo
    extension: str  # ".svg"

    @property
    def ubicacion(self) -> str:
        return f"{self.edificio} {self.piso}" + (
            f"-{self.tramo}" if self.tramo else " (piso completo)"
        )

    @property
    def titulo(self) -> str:
        """Nombre del plano en el visor: «CADI P01 · Tramo 1»."""
        return f"{self.edificio} {self.piso} · " + (
            f"Tramo {self.tramo[1:]}" if self.tramo else "Piso completo"
        )


def nombre_lamina(
    edificio: str, piso: str, tramo: str | None = None, extension: str = ".svg"
) -> str:
    """El nombre estándar: ``nombre_lamina("CADI", "P01", "T1")`` → ``cadi-p01-t1.svg``."""
    return (f"{edificio}-{piso}" + (f"-{tramo}" if tramo else "") + extension).lower()


def sugerir_nombre_lamina(nombre: str, *, edificio: str | None = None) -> str | None:
    """Nombre estándar deducido de uno que no lo es, o None si no se puede.

    Reconoce los nombres con que suelen llegar las láminas: «cadi 1er piso
    tramo 2.svg», «cadi subterraneo.svg», «CADI_P1_T01.svg». El edificio se
    toma de ``edificio`` (el de la carpeta) o, si no se indica, de la primera
    palabra del nombre.
    """
    base = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    raiz, punto, extension = base.rpartition(".")
    if not punto or not raiz:
        return None
    fichas = [f for f in re.split(r"[\s_.\-]+", raiz) if f]

    piso = tramo = None
    for ficha in fichas:
        if coincidencia := re.fullmatch(r"p(\d{1,2})", ficha):
            piso = int(coincidencia.group(1))
        elif coincidencia := re.fullmatch(r"t(\d{1,2})", ficha):
            tramo = int(coincidencia.group(1))
    if piso is None:
        if "subterraneo" in raiz:
            piso = 0
        elif coincidencia := re.search(r"(\d+)\s*[a-z]*\s+piso|piso\s*(\d+)", raiz):
            piso = int(coincidencia.group(1) or coincidencia.group(2))
    if tramo is None and (coincidencia := re.search(r"tramo\s*(\d+)", raiz)):
        tramo = int(coincidencia.group(1))
    if piso is None or piso > 99:
        return None

    if edificio is None:
        primera = fichas[0]
        if not re.fullmatch(r"[a-z0-9]+", primera) or re.fullmatch(r"[pt]\d{1,2}", primera):
            return None
        edificio = primera
    return nombre_lamina(edificio, f"P{piso:02d}", f"T{tramo}" if tramo else None, "." + extension)


def interpretar_nombre_lamina(nombre: str, *, edificio: str | None = None) -> NombreLamina:
    """Edificio, piso y tramo de una lámina según su nombre.

    Con ``edificio`` (el de la carpeta o el del destino), el nombre además
    debe ser de ese edificio. Lanza ``NombreLaminaInvalido`` con un mensaje
    para la DSI y, cuando se puede, el nombre estándar que corresponde.
    """
    coincidencia = RE_NOMBRE_LAMINA.match(nombre)
    if coincidencia is None:
        sugerencia = sugerir_nombre_lamina(nombre, edificio=edificio)
        raise NombreLaminaInvalido(
            f"«{nombre}» no sigue la nomenclatura {NOMENCLATURA}"
            + (f": renómbrela «{sugerencia}»" if sugerencia else ""),
            sugerencia,
        )
    codigo, piso, tramo, extension = coincidencia.groups()
    lamina = NombreLamina(
        codigo.upper(), f"P{piso}", f"T{tramo}" if tramo else None, extension.lower()
    )
    if edificio is not None and lamina.edificio != edificio.upper():
        raise NombreLaminaInvalido(
            f"«{nombre}» es una lámina del edificio {lamina.edificio}, no de {edificio.upper()}"
        )
    return lamina


def quitar_caracteres_de_control(contenido: bytes) -> bytes:
    """Lo que ``sanear_svg`` guarda, sin validar el XML (mucho más rápido)."""
    return RE_CONTROL_XML.sub(b"", contenido)


def sanear_svg(contenido: bytes) -> bytes:
    """Quita los caracteres de control ilegales y exige un SVG bien formado."""
    limpio = quitar_caracteres_de_control(contenido)
    try:
        raiz = ElementTree.fromstring(limpio)
    except ElementTree.ParseError as exc:
        raise SvgInvalido(
            f"El SVG no es XML válido y el navegador no podría mostrarlo: {exc}"
        ) from exc
    if raiz.tag.rpartition("}")[2] != "svg":
        raise SvgInvalido("El archivo es XML, pero no un SVG")
    return limpio


def guardar_plano(
    sesion: Session,
    piso: Piso,
    tramo: Tramo | None,
    nombre_archivo: str,
    contenido: bytes,
    *,
    ancho_px: int,
    alto_px: int,
    nombre: str | None = None,
    version: str | None = None,
    notas: str | None = None,
) -> Plano:
    """Guarda el archivo y lo registra como el plano vigente del piso–tramo.

    El nombre del archivo debe seguir la nomenclatura y corresponder a
    ``piso`` y ``tramo``: así lo que se guarda siempre dice dónde va.
    Las posiciones marcadas sobre la versión anterior no se tocan aquí: el
    que llama decide cuándo trasladarlas con ``trasladar_posiciones``.
    """
    lamina = interpretar_nombre_lamina(nombre_archivo, edificio=piso.edificio.codigo)
    destino = NombreLamina(
        piso.edificio.codigo, piso.codigo, tramo.codigo if tramo else None, lamina.extension
    )
    if lamina != destino:
        raise NombreLaminaInvalido(
            f"«{nombre_archivo}» es la lámina de {lamina.ubicacion}, no de {destino.ubicacion}"
        )
    extension = lamina.extension
    if extension not in EXTENSIONES_PLANO:
        raise FormatoNoAdmitido(
            f"Formato no admitido: {extension or 'sin extensión'}. "
            f"Se aceptan {', '.join(sorted(EXTENSIONES_PLANO))}"
        )
    if extension == ".svg":
        contenido = sanear_svg(contenido)
    elif not contenido_coincide(extension, contenido):
        raise FormatoNoAdmitido(f"El contenido del archivo no corresponde a un {extension}")

    tramo_id = tramo.id if tramo else None
    mismo_alcance = [p for p in piso.planos if p.tramo_id == tramo_id]

    # El número de versión evita que el archivo pise al del plano histórico,
    # que sigue referenciado desde la base. Sigue al mayor ya usado, en la
    # base o en disco: si se borraron versiones antiguas, contar los planos
    # repetiría el número de una existente.
    alcance = f"{piso.edificio.codigo}-{piso.codigo}" + (f"-{tramo.codigo}" if tramo else "")
    patron_version = re.compile(rf"^{re.escape(alcance)}-v(\d+)\b")
    usados = [p.archivo.removeprefix("planos/") for p in mismo_alcance]
    usados += [r.name for r in configuracion.dir_planos.glob(f"{alcance}-v*")]
    numero = 1 + max(
        (int(m.group(1)) for n in usados if (m := patron_version.match(n))), default=0
    )
    destino_relativo = f"{alcance}-v{numero}{extension}"
    (configuracion.dir_planos / destino_relativo).write_bytes(contenido)

    # Un plano vigente por piso–tramo: el anterior del mismo alcance queda
    # como histórico y las láminas de los otros tramos siguen vigentes.
    for anterior in mismo_alcance:
        anterior.vigente = False

    plano = Plano(
        piso_id=piso.id,
        tramo_id=tramo_id,
        nombre=nombre or lamina.titulo,
        archivo=f"planos/{destino_relativo}",
        formato=extension.lstrip("."),
        ancho_px=ancho_px,
        alto_px=alto_px,
        version=version,
        notas=notas,
        vigente=True,
    )
    sesion.add(plano)
    sesion.flush()
    return plano


def trasladar_posiciones(
    sesion: Session,
    plano: Plano,
    *,
    origen: OrigenCambio,
    usuario: str | None = None,
) -> list[Elemento]:
    """Lleva a ``plano`` las posiciones marcadas sobre sus versiones anteriores.

    Si la lámina conserva su tamaño, las coordenadas siguen valiendo y solo
    cambian de plano. Si el tamaño cambió, el dibujo es otro (otro encuadre u
    otra escala) y no hay forma segura de trasladarlas: el elemento queda sin
    ubicar, para volver a marcarlo, y las coordenadas anteriores quedan en su
    historial. Devuelve los elementos que quedaron sin ubicar.
    """
    mismo_tramo = (
        Plano.tramo_id == plano.tramo_id if plano.tramo_id else Plano.tramo_id.is_(None)
    )
    anteriores = {
        p.id: p
        for p in sesion.scalars(
            select(Plano).where(Plano.piso_id == plano.piso_id, mismo_tramo, Plano.id != plano.id)
        )
    }
    if not anteriores:
        return []

    sin_ubicar: list[Elemento] = []
    elementos = sesion.scalars(
        select(Elemento).where(Elemento.plano_id.in_(anteriores)).order_by(Elemento.codigo)
    )
    for elemento in elementos:
        anterior = anteriores[elemento.plano_id]
        if (anterior.ancho_px, anterior.alto_px) == (plano.ancho_px, plano.alto_px):
            cambios: dict = {"plano_id": plano.id}
        else:
            cambios = {"plano_id": None, "pos_x": None, "pos_y": None}
            sin_ubicar.append(elemento)
        registrar_cambios(
            sesion,
            elemento,
            cambios,
            origen=origen,
            usuario=usuario,
            comentario=f"Nueva versión de la lámina «{plano.nombre}»",
        )
    return sin_ubicar
