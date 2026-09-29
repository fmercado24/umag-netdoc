"""Modelos ORM. Importar todo aquí garantiza que SQLAlchemy resuelva las
relaciones declaradas por nombre y que Alembic vea el metadata completo."""

from app.models.catalogo import DefinicionAtributo, TipoElemento
from app.models.elemento import (
    Elemento,
    Fotografia,
    HistorialElemento,
    Levantamiento,
)
from app.models.enums import (
    COLORES_ESTADO,
    ETIQUETAS,
    CategoriaElemento,
    Criticidad,
    EstadoCondicion,
    EstadoLevantamiento,
    EstadoOperativo,
    MedioEnlace,
    OrigenCambio,
    RolVlan,
    TipoDato,
)
from app.models.integracion import IdentificadorExterno
from app.models.logico import ElementoVlan, Enlace, Vlan
from app.models.organizacion import Edificio, Persona, Piso, Plano, Tramo

__all__ = [
    "COLORES_ESTADO",
    "ETIQUETAS",
    "CategoriaElemento",
    "Criticidad",
    "DefinicionAtributo",
    "Edificio",
    "Elemento",
    "ElementoVlan",
    "Enlace",
    "EstadoCondicion",
    "EstadoLevantamiento",
    "EstadoOperativo",
    "Fotografia",
    "HistorialElemento",
    "IdentificadorExterno",
    "Levantamiento",
    "MedioEnlace",
    "OrigenCambio",
    "Persona",
    "Piso",
    "Plano",
    "RolVlan",
    "TipoDato",
    "TipoElemento",
    "Tramo",
    "Vlan",
]
