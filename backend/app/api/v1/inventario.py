"""Interoperabilidad con otros inventarios (NetBox, GLPI u otros).

* ``GET /inventario`` — exportación completa o incremental, en JSON o CSV,
  con el esquema estable ``netdoc.inventario/v1``.
* ``GET /cambios`` — el historial como registro de cambios con cursor, para
  sincronizar por partes sin volver a leer todo el inventario.
* ``GET /externos/{sistema}/{id_externo}`` — el elemento que otro sistema
  conoce por ese id (se administran en ``/elementos/{id}/externos``).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import SesionBD
from app.core.config import configuracion
from app.models import (
    Edificio,
    Elemento,
    HistorialElemento,
    IdentificadorExterno,
    TipoElemento,
)
from app.schemas.elemento import ElementoLeer
from app.servicios.inventario import ESQUEMA, a_csv, a_registro

router = APIRouter(prefix="/integraciones", tags=["integraciones: inventario"])

#: Nombre corto del sistema externo: netbox, glpi, zabbix…
PATRON_SISTEMA = r"^[a-z0-9][a-z0-9_-]{1,39}$"


def _para_comparar(momento: dt.datetime) -> dt.datetime:
    """SQLite guarda las marcas como texto UTC sin zona; PostgreSQL, con zona."""
    if configuracion.es_sqlite and momento.tzinfo is not None:
        return momento.astimezone(dt.UTC).replace(tzinfo=None)
    return momento


@router.get("/inventario")
def exportar_inventario(
    sesion: SesionBD,
    edificio: str | None = None,
    tipo: list[str] | None = Query(default=None, description="Códigos de tipo, p. ej. SW"),
    modificado_desde: dt.datetime | None = Query(
        default=None, description="Solo lo actualizado desde este momento (sincronización incremental)"
    ),
    incluir_bajas: bool = Query(default=False, description="Incluye los dados de baja"),
    formato: Literal["json", "csv"] = "json",
    limite: int = Query(default=1000, ge=1, le=5000),
    desplazamiento: int = Query(default=0, ge=0),
):
    """Inventario con el esquema ``netdoc.inventario/v1``.

    Pensado para cargarlo en otro sistema: incluye la ubicación completa (con
    el rack y la posición heredada por lo montado), los datos de red y de
    equipo, la ficha del tipo y los ids que el elemento tiene en otros
    sistemas. El CSV lleva el total en la cabecera ``X-Total-Count``.
    """
    consulta = (
        select(Elemento)
        .join(Edificio, Elemento.edificio_id == Edificio.id)
        .join(TipoElemento, Elemento.tipo_elemento_id == TipoElemento.id)
    )
    if not incluir_bajas:
        consulta = consulta.where(Elemento.activo.is_(True))
    if edificio:
        consulta = consulta.where(Edificio.codigo == edificio.upper())
    if tipo:
        consulta = consulta.where(TipoElemento.codigo.in_([t.upper() for t in tipo]))
    if modificado_desde:
        consulta = consulta.where(Elemento.actualizado_en >= _para_comparar(modificado_desde))

    total = sesion.scalar(select(func.count()).select_from(consulta.subquery())) or 0
    elementos = sesion.scalars(
        consulta.order_by(Elemento.codigo).limit(limite).offset(desplazamiento)
    ).unique()
    registros = [a_registro(e) for e in elementos]

    if formato == "csv":
        return Response(
            a_csv(registros),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="netdoc-inventario.csv"',
                "X-Total-Count": str(total),
            },
        )
    return {
        "esquema": ESQUEMA,
        "generado_en": dt.datetime.now(dt.UTC).isoformat(),
        "total": total,
        "limite": limite,
        "desplazamiento": desplazamiento,
        "elementos": registros,
    }


@router.get("/cambios")
def registro_de_cambios(
    sesion: SesionBD,
    desde: int = Query(default=0, ge=0, description="Último id ya procesado (0 = desde el inicio)"),
    limite: int = Query(default=500, ge=1, le=5000),
):
    """Cambios posteriores a ``desde``, en orden.

    El consumidor guarda ``ultimo_id`` y lo envía como ``desde`` en la próxima
    consulta; mientras ``hay_mas`` sea verdadero, sigue pidiendo. Es el mismo
    historial que muestra la ficha, así que registra altas, ediciones,
    posiciones, eventos de monitoreo y bajas (``activo`` → false).
    """
    filas = sesion.execute(
        select(HistorialElemento, Elemento.codigo)
        .join(Elemento, HistorialElemento.elemento_id == Elemento.id)
        .where(HistorialElemento.id > desde)
        .order_by(HistorialElemento.id)
        .limit(limite + 1)
    ).all()
    hay_mas = len(filas) > limite
    filas = filas[:limite]
    return {
        "cambios": [
            {
                "id": h.id,
                "codigo": codigo,
                "campo": h.campo,
                "valor_anterior": h.valor_anterior,
                "valor_nuevo": h.valor_nuevo,
                "origen": h.origen.value,
                "usuario": h.usuario,
                "comentario": h.comentario,
                "registrado_en": h.registrado_en.isoformat(),
            }
            for h, codigo in filas
        ],
        "ultimo_id": filas[-1][0].id if filas else desde,
        "hay_mas": hay_mas,
    }


@router.get("/externos/{sistema}/{id_externo}", response_model=ElementoLeer)
def elemento_por_id_externo(
    sesion: SesionBD,
    sistema: str = Path(pattern=PATRON_SISTEMA),
    id_externo: str = Path(max_length=120),
):
    """El elemento que otro sistema identifica con ``id_externo``."""
    elemento = sesion.scalar(
        select(Elemento)
        .join(IdentificadorExterno, IdentificadorExterno.elemento_id == Elemento.id)
        .where(IdentificadorExterno.sistema == sistema, IdentificadorExterno.id_externo == id_externo)
    )
    if elemento is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Ningún elemento tiene el id '{id_externo}' en {sistema}"
        )
    return elemento
