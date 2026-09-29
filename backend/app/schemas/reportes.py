"""Esquemas de los reportes de gestión y control de calidad del dato."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.elemento import CampoFaltante


class Conteo(BaseModel):
    clave: str
    etiqueta: str
    total: int


class ResumenEdificio(BaseModel):
    """Tablero de un edificio: qué hay, en qué estado y dónde."""

    edificio: str
    nombre: str
    total_elementos: int
    con_coordenadas: int
    sin_coordenadas: int
    por_tipo: list[Conteo]
    por_estado: list[Conteo]
    por_condicion: list[Conteo]
    por_piso: list[Conteo]


class ElementoIncompleto(BaseModel):
    """Fila del reporte 'Elementos incompletos por edificio' (SOP 10.5)."""

    id: int
    codigo: str
    tipo_codigo: str
    piso_codigo: str
    etiqueta: str | None = None
    porcentaje: float
    faltantes: list[CampoFaltante]


class ReporteIncompletos(BaseModel):
    edificio: str
    total_elementos: int
    total_incompletos: int
    porcentaje_promedio: float
    items: list[ElementoIncompleto]
