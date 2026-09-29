"""Esquemas del catálogo de tipos y de sus fichas de atributos."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CategoriaElemento, TipoDato

BASE = ConfigDict(from_attributes=True)


class DefinicionAtributoLeer(BaseModel):
    model_config = BASE

    id: int
    clave: str
    etiqueta: str
    tipo_dato: TipoDato
    obligatorio: bool
    opciones: list | None = None
    unidad: str | None = None
    ayuda: str | None = None
    orden: int


class TipoElementoLeer(BaseModel):
    model_config = BASE

    id: int
    codigo: str
    nombre: str
    categoria: CategoriaElemento
    descripcion: str | None = None
    icono: str | None = None
    color: str | None = None
    es_contenedor: bool
    usa_correlativo: bool
    orden: int


class TipoElementoDetalle(TipoElementoLeer):
    atributos: list[DefinicionAtributoLeer] = []


class DefinicionAtributoCrear(BaseModel):
    clave: str = Field(max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    etiqueta: str = Field(max_length=160)
    tipo_dato: TipoDato = TipoDato.TEXTO
    obligatorio: bool = False
    opciones: list | None = None
    unidad: str | None = None
    ayuda: str | None = None
    orden: int = 0


class TipoElementoCrear(BaseModel):
    codigo: str = Field(max_length=8, pattern=r"^[A-Z]{1,8}$")
    nombre: str = Field(max_length=120)
    categoria: CategoriaElemento
    descripcion: str | None = None
    icono: str | None = None
    color: str | None = None
    es_contenedor: bool = False
    usa_correlativo: bool = True
    orden: int = 0
    atributos: list[DefinicionAtributoCrear] = []
