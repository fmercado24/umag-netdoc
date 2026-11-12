"""Dependencias compartidas por los routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import obtener_sesion
from app.models import Edificio, Elemento, Piso, TipoElemento, Tramo
from app.servicios.codigos import elemento_por_codigo


def _sesion_con_acceso(
    request: Request, sesion: Annotated[Session, Depends(obtener_sesion)]
) -> Session:
    """La sesión de base de datos, con quién la usa (lo deja ``proteccion``).

    Así las funciones de este módulo, por las que pasan las rutas para buscar un
    edificio o un elemento, hacen cumplir el alcance del usuario sin que cada
    ruta tenga que acordarse.
    """
    sesion.info["acceso"] = getattr(request.state, "acceso", None)
    return sesion


SesionBD = Annotated[Session, Depends(_sesion_con_acceso)]


def edificio_permitido(sesion: Session) -> str | None:
    """El código del único edificio que puede ver y modificar quien hace la
    petición; None si puede con todos."""
    acceso = sesion.info.get("acceso")
    return acceso.edificio if acceso else None


def _fuera_de_alcance(permitido: str) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN, f"Su usuario solo tiene acceso al edificio {permitido}"
    )


def exigir_todos_los_edificios(sesion: Session) -> None:
    """Para lo que no es de un edificio: crear uno, el catálogo, las VLAN de campus."""
    permitido = edificio_permitido(sesion)
    if permitido:
        raise _fuera_de_alcance(permitido)


def edificio_de_consulta(sesion: Session, pedido: str | None) -> str | None:
    """El edificio por el que filtrar un listado: el pedido o, si el usuario está
    limitado a uno y no pidió ninguno, el suyo."""
    permitido = edificio_permitido(sesion)
    if permitido is None:
        return pedido
    if pedido and pedido.upper() != permitido:
        raise _fuera_de_alcance(permitido)
    return permitido


def obtener_edificio(sesion: Session, codigo: str) -> Edificio:
    # Antes de buscarlo: la respuesta no dice si el edificio existe.
    edificio_de_consulta(sesion, codigo)
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
    if isinstance(id_o_codigo, int) or str(id_o_codigo).isdigit():
        elemento = sesion.scalar(select(Elemento).where(Elemento.id == int(id_o_codigo)))
    else:
        elemento = elemento_por_codigo(sesion, str(id_o_codigo).upper())
    # El de otro edificio se responde igual que el que no existe.
    permitido = edificio_permitido(sesion)
    if elemento is None or (permitido and elemento.edificio.codigo != permitido):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el elemento '{id_o_codigo}'")
    return elemento
