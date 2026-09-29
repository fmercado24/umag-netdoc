"""Almacenamiento de planos: saneamiento, nombre del archivo y versión vigente.

Lo comparten el endpoint de carga y el script que sube las láminas del CADI,
para que ambos caminos dejen exactamente el mismo resultado.
"""

from __future__ import annotations

import re
import unicodedata
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import Piso, Plano, Tramo

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


def nombre_seguro(nombre: str) -> str:
    """Normaliza un nombre de archivo: sin tildes, espacios ni rutas."""
    base = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") or "archivo"


def sanear_svg(contenido: bytes) -> bytes:
    """Quita los caracteres de control ilegales y exige XML bien formado."""
    limpio = RE_CONTROL_XML.sub(b"", contenido)
    try:
        ElementTree.fromstring(limpio)
    except ElementTree.ParseError as exc:
        raise SvgInvalido(
            f"El SVG no es XML válido y el navegador no podría mostrarlo: {exc}"
        ) from exc
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
    """Guarda el archivo y lo registra como el plano vigente del piso–tramo."""
    nombre_original = nombre_seguro(nombre_archivo or "plano")
    extension = "." + nombre_original.rsplit(".", 1)[-1].lower() if "." in nombre_original else ""
    if extension not in EXTENSIONES_PLANO:
        raise FormatoNoAdmitido(
            f"Formato no admitido: {extension or 'sin extensión'}. "
            f"Se aceptan {', '.join(sorted(EXTENSIONES_PLANO))}"
        )
    if extension == ".svg":
        contenido = sanear_svg(contenido)

    tramo_id = tramo.id if tramo else None
    mismo_alcance = [p for p in piso.planos if p.tramo_id == tramo_id]

    # El número de versión evita que un archivo con el mismo nombre pise al
    # del plano histórico, que sigue referenciado desde la base. Se salta
    # cualquier número ya ocupado en disco: si se borraron versiones
    # antiguas, el conteo de planos repetiría el de la versión vigente.
    alcance = f"{piso.edificio.codigo}-{piso.codigo}" + (f"-{tramo.codigo}" if tramo else "")
    numero = len(mismo_alcance) + 1
    while (configuracion.dir_planos / f"{alcance}-v{numero}-{nombre_original}").exists():
        numero += 1
    destino_relativo = f"{alcance}-v{numero}-{nombre_original}"
    (configuracion.dir_planos / destino_relativo).write_bytes(contenido)

    # Un plano vigente por piso–tramo: el anterior del mismo alcance queda
    # como histórico y las láminas de los otros tramos siguen vigentes.
    for anterior in mismo_alcance:
        anterior.vigente = False

    plano = Plano(
        piso_id=piso.id,
        tramo_id=tramo_id,
        nombre=nombre or nombre_original,
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
