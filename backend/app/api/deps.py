"""Dependencias compartidas por los routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import obtener_sesion
from app.models import Edificio, Elemento, Piso, TipoElemento, Tramo

SesionBD = Annotated[Session, Depends(obtener_sesion)]


def obtener_edificio(sesion: Session, codigo: str) -> Edificio:
    edificio = sesion.scalar(select(Edificio).where(Edificio.codigo == codigo.upper()))
    if edificio is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No existe el edificio '{codigo.upper()}'"
        )
    return edificio


def obtener_piso(sesion: Session, edificio: Edificio, codigo: str) -> Piso:
    piso = sesion.scalar(
        select(Piso).where(Piso.edificio_id == edificio.id, Piso.codigo == codigo.upper())
    )
    if piso is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"El edificio '{edificio.codigo}' no tiene el piso '{codigo.upper()}'",
        )
    return piso


def obtener_tramo(sesion: Session, piso: Piso, codigo: str | None) -> Tramo | None:
    if not codigo:
        return None
    tramo = sesion.scalar(
        select(Tramo).where(Tramo.piso_id == piso.id, Tramo.codigo == codigo.upper())
    )
    if tramo is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"El piso '{piso.codigo}' no tiene el tramo '{codigo.upper()}'",
        )
    return tramo


def obtener_tipo(sesion: Session, codigo: str) -> TipoElemento:
    tipo = sesion.scalar(select(TipoElemento).where(TipoElemento.codigo == codigo.upper()))
    if tipo is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No existe el tipo de elemento '{codigo.upper()}'"
        )
    return tipo


def obtener_elemento(sesion: Session, id_o_codigo: int | str) -> Elemento:
    """Acepta el id numérico o el código del SOP indistintamente."""
    consulta = select(Elemento)
    if isinstance(id_o_codigo, int) or str(id_o_codigo).isdigit():
        consulta = consulta.where(Elemento.id == int(id_o_codigo))
    else:
        consulta = consulta.where(Elemento.codigo == str(id_o_codigo).upper())

    elemento = sesion.scalar(consulta)
    if elemento is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el elemento '{id_o_codigo}'")
    return elemento
