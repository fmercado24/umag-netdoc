"""Esquemas de VLAN y enlaces."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MedioEnlace, RolVlan

BASE = ConfigDict(from_attributes=True)


class VlanLeer(BaseModel):
    model_config = BASE

    id: int
    numero: int
    nombre: str
    subred: str | None = None
    gateway: str | None = None
    descripcion: str | None = None
    edificio_id: int | None = None


class VlanCrear(BaseModel):
    numero: int = Field(ge=1, le=4094)
    nombre: str = Field(max_length=80)
    subred: str | None = None
    gateway: str | None = None
    descripcion: str | None = None
    edificio: str | None = Field(default=None, description="Código del edificio")


class VlanAsignar(BaseModel):
    vlan_id: int
    rol: RolVlan = RolVlan.SERVICIO


class EnlaceLeer(BaseModel):
    model_config = BASE

    id: int
    origen_id: int
    puerto_origen: str | None = None
    destino_id: int | None = None
    puerto_destino: str | None = None
    destino_descripcion: str | None = None
    medio: MedioEnlace
    categoria: str | None = None
    etiqueta: str | None = None
    observaciones: str | None = None


class EnlaceCrear(BaseModel):
    origen_codigo: str
    puerto_origen: str | None = None
    destino_codigo: str | None = None
    puerto_destino: str | None = None
    destino_descripcion: str | None = None
    medio: MedioEnlace = MedioEnlace.COBRE
    categoria: str | None = None
    etiqueta: str | None = None
    observaciones: str | None = None
