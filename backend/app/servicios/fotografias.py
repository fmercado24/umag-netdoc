"""Evidencia fotográfica de los elementos (SOP §10.4).

La comparten el endpoint de carga y ``app.scripts.cargar_fotografias``. Cada
foto se guarda como ``<código>_<n>.<ext>``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import Elemento, Fotografia

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp"}


class FormatoFotoNoAdmitido(ValueError):
    pass


def extension_de(nombre_archivo: str) -> str:
    return "." + nombre_archivo.rsplit(".", 1)[-1].lower() if "." in nombre_archivo else ""


def guardar_fotografia(
    sesion: Session,
    elemento: Elemento,
    nombre_archivo: str,
    contenido: bytes,
    *,
    descripcion: str | None = None,
    tomada_en: dt.datetime | None = None,
) -> Fotografia:
    extension = extension_de(nombre_archivo)
    if extension not in EXTENSIONES_FOTO:
        raise FormatoFotoNoAdmitido(
            f"Formato no admitido: {extension or 'sin extensión'}. "
            f"Se aceptan {', '.join(sorted(EXTENSIONES_FOTO))}"
        )

    secuencia = len(elemento.fotografias) + 1
    # Nunca se pisa un archivo existente, aunque falten registros en la base.
    while (configuracion.dir_fotografias / f"{elemento.codigo}_{secuencia}{extension}").exists():
        secuencia += 1
    destino_relativo = f"{elemento.codigo}_{secuencia}{extension}"
    (configuracion.dir_fotografias / destino_relativo).write_bytes(contenido)

    foto = Fotografia(
        elemento_id=elemento.id,
        archivo=f"fotografias/{destino_relativo}",
        descripcion=descripcion,
        tomada_en=tomada_en,
        orden=secuencia,
    )
    sesion.add(foto)
    sesion.flush()
    return foto
