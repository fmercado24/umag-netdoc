"""Catálogo: tipos de elemento, fichas de atributos y enumeraciones."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SesionBD, obtener_tipo
from app.models import (
    COLORES_ESTADO,
    ETIQUETAS,
    CategoriaElemento,
    Criticidad,
    DefinicionAtributo,
    EstadoCondicion,
    EstadoOperativo,
    TipoElemento,
)
from app.schemas.catalogo import (
    DefinicionAtributoLeer,
    TipoElementoCrear,
    TipoElementoDetalle,
    TipoElementoLeer,
)

router = APIRouter(prefix="/catalogo", tags=["catálogo"])


@router.get("/tipos", response_model=list[TipoElementoLeer])
def listar_tipos(
    sesion: SesionBD, categoria: CategoriaElemento | None = None, solo_activos: bool = True
):
    consulta = select(TipoElemento).order_by(TipoElemento.orden, TipoElemento.codigo)
    if categoria is not None:
        consulta = consulta.where(TipoElemento.categoria == categoria)
    if solo_activos:
        consulta = consulta.where(TipoElemento.activo.is_(True))
    return sesion.scalars(consulta).all()


@router.get("/tipos/{codigo}", response_model=TipoElementoDetalle)
def obtener_tipo_detalle(codigo: str, sesion: SesionBD):
    return obtener_tipo(sesion, codigo)


@router.get("/tipos/{codigo}/ficha", response_model=list[DefinicionAtributoLeer])
def obtener_ficha(codigo: str, sesion: SesionBD):
    """Definición de atributos del tipo — lo que el formulario debe pedir."""
    return obtener_tipo(sesion, codigo).atributos


@router.post("/tipos", response_model=TipoElementoDetalle, status_code=status.HTTP_201_CREATED)
def crear_tipo(datos: TipoElementoCrear, sesion: SesionBD):
    """Da de alta un tipo nuevo con su ficha, sin migrar el esquema."""
    existente = sesion.scalar(select(TipoElemento).where(TipoElemento.codigo == datos.codigo))
    if existente is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Ya existe el tipo '{datos.codigo}'"
        )

    tipo = TipoElemento(**datos.model_dump(exclude={"atributos"}))
    for definicion in datos.atributos:
        tipo.atributos.append(DefinicionAtributo(**definicion.model_dump()))

    sesion.add(tipo)
    sesion.flush()
    return tipo


@router.get("/enumeraciones")
def listar_enumeraciones() -> dict:
    """Valores admitidos y sus etiquetas, para poblar los selectores."""

    def opciones(enum_cls, grupo: str | None = None) -> list[dict]:
        etiquetas = ETIQUETAS.get(grupo or "", {})
        return [
            {
                "valor": miembro.value,
                "etiqueta": etiquetas.get(miembro, miembro.value.replace("_", " ").capitalize()),
            }
            for miembro in enum_cls
        ]

    return {
        "estado_operativo": [
            {**opcion, "color": COLORES_ESTADO[EstadoOperativo(opcion["valor"])]}
            for opcion in opciones(EstadoOperativo, "estado_operativo")
        ],
        "estado_condicion": opciones(EstadoCondicion, "estado_condicion"),
        "categoria": opciones(CategoriaElemento, "categoria"),
        "criticidad": opciones(Criticidad),
    }
