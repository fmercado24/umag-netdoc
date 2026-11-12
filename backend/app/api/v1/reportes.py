"""Reportes de gestión y control de calidad del dato."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import SesionBD, edificio_de_consulta, obtener_edificio
from app.models import ETIQUETAS, Elemento, EstadoOperativo, Piso, TipoElemento
from app.schemas.reportes import (
    Conteo,
    ElementoIncompleto,
    ReporteIncompletos,
    ResumenEdificio,
)
from app.servicios.validacion import evaluar_completitud

router = APIRouter(prefix="/reportes", tags=["reportes"])


def _etiqueta(grupo: str, valor) -> str:
    mapa = ETIQUETAS.get(grupo, {})
    return mapa.get(valor, str(getattr(valor, "value", valor)).replace("_", " ").capitalize())


@router.get("/resumen", response_model=ResumenEdificio)
def resumen_edificio(sesion: SesionBD, edificio: str):
    """Tablero por edificio: inventario, estados y cobertura del plano."""
    ed = obtener_edificio(sesion, edificio)
    base = [Elemento.edificio_id == ed.id, Elemento.activo.is_(True)]

    total = sesion.scalar(select(func.count(Elemento.id)).where(*base)) or 0
    con_coordenadas = (
        sesion.scalar(
            select(func.count(Elemento.id)).where(
                *base, Elemento.pos_x.is_not(None), Elemento.pos_y.is_not(None)
            )
        )
        or 0
    )

    por_tipo = [
        Conteo(clave=codigo, etiqueta=nombre, total=cantidad)
        for codigo, nombre, cantidad in sesion.execute(
            select(TipoElemento.codigo, TipoElemento.nombre, func.count(Elemento.id))
            .join(Elemento, Elemento.tipo_elemento_id == TipoElemento.id)
            .where(*base)
            .group_by(TipoElemento.codigo, TipoElemento.nombre, TipoElemento.orden)
            .order_by(TipoElemento.orden, TipoElemento.codigo)
        ).all()
    ]

    por_estado = [
        Conteo(clave=str(valor.value), etiqueta=_etiqueta("estado_operativo", valor), total=cantidad)
        for valor, cantidad in sesion.execute(
            select(Elemento.estado_operativo, func.count(Elemento.id))
            .where(*base)
            .group_by(Elemento.estado_operativo)
        ).all()
    ]

    por_condicion = [
        Conteo(
            clave=str(valor.value) if valor else "sin_dato",
            etiqueta=_etiqueta("estado_condicion", valor) if valor else "Sin dato",
            total=cantidad,
        )
        for valor, cantidad in sesion.execute(
            select(Elemento.estado_condicion, func.count(Elemento.id))
            .where(*base)
            .group_by(Elemento.estado_condicion)
        ).all()
    ]

    por_piso = [
        Conteo(clave=codigo, etiqueta=nombre or codigo, total=cantidad)
        for codigo, nombre, cantidad in sesion.execute(
            select(Piso.codigo, Piso.nombre, func.count(Elemento.id))
            .join(Elemento, Elemento.piso_id == Piso.id)
            .where(*base)
            .group_by(Piso.codigo, Piso.nombre, Piso.orden)
            .order_by(Piso.orden)
        ).all()
    ]

    return ResumenEdificio(
        edificio=ed.codigo,
        nombre=ed.nombre,
        total_elementos=total,
        con_coordenadas=con_coordenadas,
        sin_coordenadas=total - con_coordenadas,
        por_tipo=por_tipo,
        por_estado=por_estado,
        por_condicion=por_condicion,
        por_piso=por_piso,
    )


@router.get("/elementos-incompletos", response_model=ReporteIncompletos)
def elementos_incompletos(
    sesion: SesionBD,
    edificio: str,
    tipo: list[str] | None = Query(default=None),
    limite: int = Query(default=500, ge=1, le=2000),
):
    """Reporte exigido por el SOP sección 10.5, punto 22.

    Lista los elementos que no cumplen el mínimo obligatorio de la sección 9
    y detalla exactamente qué atributo falta en cada uno.
    """
    ed = obtener_edificio(sesion, edificio)

    consulta = (
        select(Elemento)
        .where(Elemento.edificio_id == ed.id, Elemento.activo.is_(True))
        .order_by(Elemento.codigo)
    )
    if tipo:
        consulta = consulta.join(TipoElemento).where(
            TipoElemento.codigo.in_([t.upper() for t in tipo])
        )

    elementos = sesion.scalars(consulta).unique().all()

    items: list[ElementoIncompleto] = []
    suma_porcentajes = 0.0
    for elemento in elementos:
        completitud = evaluar_completitud(elemento)
        suma_porcentajes += completitud.porcentaje
        if completitud.completo:
            continue
        items.append(
            ElementoIncompleto(
                id=elemento.id,
                codigo=elemento.codigo,
                tipo_codigo=elemento.tipo.codigo,
                piso_codigo=elemento.piso.codigo,
                etiqueta=elemento.etiqueta,
                porcentaje=completitud.porcentaje,
                faltantes=completitud.faltantes,
            )
        )

    items.sort(key=lambda i: i.porcentaje)
    promedio = round(suma_porcentajes / len(elementos), 1) if elementos else 100.0

    return ReporteIncompletos(
        edificio=ed.codigo,
        total_elementos=len(elementos),
        total_incompletos=len(items),
        porcentaje_promedio=promedio,
        items=items[:limite],
    )


@router.get("/fuera-de-servicio")
def fuera_de_servicio(sesion: SesionBD, edificio: str | None = None):
    """Atajo operativo: qué está caído o en falla ahora mismo."""
    filtros = [
        Elemento.activo.is_(True),
        Elemento.estado_operativo.in_([EstadoOperativo.INACTIVO, EstadoOperativo.EN_FALLA]),
    ]
    edificio = edificio_de_consulta(sesion, edificio)
    if edificio:
        filtros.append(Elemento.edificio_id == obtener_edificio(sesion, edificio).id)

    elementos = sesion.scalars(select(Elemento).where(*filtros).order_by(Elemento.codigo)).unique().all()
    return [
        {
            "codigo": e.codigo,
            "tipo": e.tipo.codigo,
            "etiqueta": e.etiqueta,
            "edificio": e.edificio.codigo,
            "piso": e.piso.codigo,
            "ubicacion": e.ubicacion_descriptiva,
            "estado_operativo": e.estado_operativo.value,
            "estado_condicion": e.estado_condicion.value if e.estado_condicion else None,
        }
        for e in elementos
    ]
