"""Esquemas de edificio, piso, tramo, plano y persona."""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.servicios.teselas import leer_teselas

BASE = ConfigDict(from_attributes=True)


class PersonaLeer(BaseModel):
    model_config = BASE

    id: int
    nombre: str
    email: str | None = None
    unidad: str | None = None
    rol: str | None = None


class PersonaCrear(BaseModel):
    nombre: str = Field(max_length=120)
    email: str | None = None
    unidad: str | None = None
    rol: str | None = None


class TeselasLeer(BaseModel):
    """La lámina pre-dibujada en teselas (ver ``app.servicios.teselas``)."""

    url: str = Field(description="Bajo /media, con {z}, {x} e {y}")
    zoom_max: int = Field(description="Nivel del visor del nivel más detallado de la pirámide")
    niveles: int
    tamano: int


class PlanoLeer(BaseModel):
    model_config = BASE

    id: int
    piso_id: int
    tramo_id: int | None = None
    tramo_codigo: str | None = None
    nombre: str
    archivo: str
    formato: str | None = None
    ancho_px: int
    alto_px: int
    version: str | None = None
    vigente: bool
    notas: str | None = None
    #: Nulo mientras no se generen: el visor muestra entonces la lámina original.
    teselas: TeselasLeer | None = None

    @model_validator(mode="after")
    def _con_teselas(self) -> PlanoLeer:
        if self.teselas is None and (info := leer_teselas(self.archivo)) is not None:
            self.teselas = TeselasLeer(**asdict(info))
        return self


class RecintoLeer(BaseModel):
    """Sala de una lámina, con el punto donde se ubican sus elementos."""

    model_config = BASE

    numero: str
    nombre: str | None = None
    plano_id: int
    #: Tramo de la lámina donde está; nulo si la lámina cubre el piso completo.
    tramo_codigo: str | None = None
    pos_x: float
    pos_y: float


class TramoLeer(BaseModel):
    model_config = BASE

    id: int
    codigo: str
    nombre: str | None = None


class PisoLeer(BaseModel):
    model_config = BASE

    id: int
    edificio_id: int
    codigo: str
    nombre: str | None = None
    orden: int
    tramos: list[TramoLeer] = []
    planos_vigentes: list[PlanoLeer] = []


class EdificioLeer(BaseModel):
    model_config = BASE

    id: int
    codigo: str
    nombre: str
    campus: str | None = None
    direccion: str | None = None
    observaciones: str | None = None
    activo: bool


class EdificioDetalle(EdificioLeer):
    pisos: list[PisoLeer] = []


class EdificioCrear(BaseModel):
    codigo: str = Field(max_length=8)
    nombre: str = Field(max_length=200)
    campus: str | None = "Punta Arenas"
    direccion: str | None = None
    observaciones: str | None = None


class PisoCrear(BaseModel):
    codigo: str = Field(max_length=4, description="P00, P01, …, PXX")
    nombre: str | None = None
    orden: int = 0


class TramoCrear(BaseModel):
    codigo: str = Field(max_length=6, description="T1, T2, …")
    nombre: str | None = None


class PlanoCrear(BaseModel):
    nombre: str
    ancho_px: int = Field(gt=0)
    alto_px: int = Field(gt=0)
    version: str | None = None
    notas: str | None = None


class EjemploLamina(BaseModel):
    nombre: str
    destino: str


class RevisionLamina(BaseModel):
    """Lo que dice el nombre de un archivo, antes de subirlo."""

    archivo: str
    #: Nombre con que se guardará; nulo si se rechaza.
    nombre: str | None = None
    piso: str | None = None
    tramo: str | None = None
    destino: str | None = None
    #: Por qué se rechaza; nulo si se acepta.
    error: str | None = None
    #: El nombre que debería tener, si se pudo deducir del original.
    sugerencia: str | None = None


class LaminaPendiente(BaseModel):
    """Un plano subido que espera a confirmarse."""

    nombre: str
    piso: str
    tramo: str | None = None
    destino: str
    ancho_px: int
    alto_px: int
    bytes: int


class PlanoCargado(BaseModel):
    """Un plano vigente del edificio."""

    destino: str
    archivo: str
    ancho_px: int
    alto_px: int


class CargaDePlanos(BaseModel):
    """Si se pueden cargar o quitar planos desde el visor, cómo deben llamarse, los
    que ya están y los que esperan."""

    edificio: str
    #: Solo mientras el edificio no tenga elementos.
    permitida: bool
    #: Por qué no, si no se puede.
    motivo: str | None = None
    nomenclatura: str
    ejemplos: list[EjemploLamina]
    #: El nombre de un edificio con un solo plano.
    unico: str
    #: Los planos vigentes del edificio.
    cargados: list[PlanoCargado] = []
    pendientes: list[LaminaPendiente] = []
    #: La revisión de los nombres pedidos en ``?archivo=``.
    revisados: list[RevisionLamina] = []


class PlanosQuitados(BaseModel):
    planos: int
    tramos: int
    pisos: list[str]


class CargaConfirmada(BaseModel):
    pisos: list[str]
    tramos: list[str]
    planos: list[PlanoLeer]
