"""Cómo sabe el visor que otra persona cambió algo en un edificio."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Edificio, Elemento, Piso, Plano


def marca_del_edificio(sesion: Session, edificio: Edificio) -> str:
    """Un valor que cambia cuando cambia algo del edificio.

    Los elementos no se borran y su versión solo sube: la suma cambia con cada
    alta, edición, traslado o baja. Los planos cuentan aparte.
    """
    elementos = sesion.scalar(
        select(func.coalesce(func.sum(Elemento.version), 0)).where(
            Elemento.edificio_id == edificio.id
        )
    )
    planos = sesion.scalar(
        select(func.count(Plano.id)).join(Piso).where(Piso.edificio_id == edificio.id)
    )
    return f"{elementos}.{planos}"
