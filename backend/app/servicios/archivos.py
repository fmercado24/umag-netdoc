"""Comprobación del contenido de los archivos que se cargan."""

from __future__ import annotations

_FIRMAS = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".pdf": b"%PDF-",
}


def contenido_coincide(extension: str, contenido: bytes) -> bool:
    """La extensión decide con qué tipo se sirve el archivo: el contenido debe
    ser de verdad de ese tipo. Los SVG se validan aparte (``sanear_svg``)."""
    if extension == ".webp":
        return contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP"
    return contenido.startswith(_FIRMAS[extension])
