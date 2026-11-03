"""Acceso al sistema: sesiones del administrador e intentos de ingreso.

Viven en la base, no en memoria, para que valgan igual con varios procesos y
para que reiniciar la API no borre un bloqueo. Los momentos se guardan como
segundos desde 1970 (UTC): aquí solo se comparan y suman plazos, y así no
dependen de cómo trata las zonas horarias cada motor.
"""

from __future__ import annotations

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SesionAcceso(Base):
    """Una sesión iniciada. Cerrarla es borrar su fila: deja de valer de inmediato."""

    __tablename__ = "sesion_acceso"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: SHA-256 del token de la cookie: quien lea la base no puede usar la sesión.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    #: Desde dónde se inició, para auditar.
    cliente: Mapped[str] = mapped_column(String(45), nullable=False)
    creada_en: Mapped[float] = mapped_column(Float, nullable=False)
    ultimo_uso: Mapped[float] = mapped_column(Float, nullable=False)
    vence_en: Mapped[float] = mapped_column(Float, nullable=False)


class IntentoIngreso(Base):
    """Un intento de ingreso fallido, o en curso mientras se verifica la clave."""

    __tablename__ = "intento_ingreso"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente: Mapped[str] = mapped_column(String(45), index=True, nullable=False)
    ocurrido_en: Mapped[float] = mapped_column(Float, index=True, nullable=False)
