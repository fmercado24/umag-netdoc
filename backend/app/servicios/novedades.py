"""Cómo sabe el visor que otra persona cambió algo en un edificio."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Edificio, Elemento, Piso, Plano, Recinto


def marca_del_edificio(sesion: Session, edificio: Edificio) -> str:
    """Un valor que cambia cuando cambia algo del edificio.

    Los elementos no se borran y su versión solo sube: la suma cambia con cada
    alta, edición, traslado o baja. Los planos cuentan aparte, y también sus
    salas y en qué va su lectura: así el visor se entera de que terminó de
    leerlas (app.servicios.lectura_recintos).
    """
    elementos = sesion.scalar(
        select(func.coalesce(func.sum(Elemento.version), 0)).where(
            Elemento.edificio_id == edificio.id
        )
    )
    planos, sin_leer = sesion.execute(
        select(
            func.count(Plano.id),
            func.count(Plano.id).filter(Plano.lectura_recintos.in_(("pendiente", "leyendo"))),
        )
        .join(Piso)
        .where(Piso.edificio_id == edificio.id)
    ).one()
    recintos = sesion.scalar(
        select(func.count(Recinto.id))
        .join(Plano, Recinto.plano_id == Plano.id)
        .join(Piso, Plano.piso_id == Piso.id)
        .where(Piso.edificio_id == edificio.id)
    )
    return f"{elementos}.{planos}.{recintos}.{sin_leer}"
