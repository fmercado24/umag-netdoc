"""Declarative base, convenciones de nombres y tipos portables."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum

# Nombres determinísticos para índices y constraints: Alembic los necesita
# para poder generar migraciones reversibles.
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


#: JSONB en PostgreSQL, JSON en SQLite. Permite desarrollar sobre SQLite y
#: migrar a PostgreSQL sin tocar los modelos.
TipoJSON = JSON().with_variant(JSONB(), "postgresql")


def columna_enum(enum_cls, *, longitud: int = 40) -> SAEnum:
    """Enum portable: se almacena como VARCHAR + CHECK, no como tipo nativo.

    Evita el ciclo de ``CREATE TYPE`` de PostgreSQL, que complica las
    migraciones cuando se agregan valores nuevos a la taxonomía.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=longitud,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class MixinTiempos:
    """Marcas de tiempo de auditoría, comunes a casi todas las tablas."""

    creado_en: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actualizado_en: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
