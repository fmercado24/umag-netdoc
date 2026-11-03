"""Modelos ORM. Importar todo aquí garantiza que SQLAlchemy resuelva las
relaciones declaradas por nombre y que Alembic vea el metadata completo."""

from app.models.acceso import IntentoIngreso, SesionAcceso
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
from app.models.organizacion import Edificio, Persona, Piso, Plano, Recinto, Tramo

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
    "IntentoIngreso",
    "Levantamiento",
    "MedioEnlace",
    "OrigenCambio",
    "Persona",
    "Piso",
    "Plano",
    "Recinto",
    "RolVlan",
    "SesionAcceso",
    "TipoDato",
    "TipoElemento",
    "Tramo",
    "Vlan",
]
