"""Catálogo de tipos de elemento y definición de sus fichas de atributos.

Este par de tablas es lo que hace extensible el modelo: para incorporar un
tipo nuevo (por ejemplo, PDU o cámara IP) basta con insertar una fila en
``tipo_elemento`` y las filas de ``definicion_atributo`` de su ficha; no hay
que migrar el esquema ni tocar el código del backend ni del visor.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TipoJSON, columna_enum
from app.models.enums import CategoriaElemento, TipoDato


class TipoElemento(Base):
    """Un tipo de la taxonomía (SOP secciones 7.2 y 8.4)."""

    __tablename__ = "tipo_elemento"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    categoria: Mapped[CategoriaElemento] = mapped_column(
        columna_enum(CategoriaElemento), nullable=False
    )
    descripcion: Mapped[str | None] = mapped_column(Text)
    icono: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(9))
    #: Si es contenedor, otros elementos pueden declararlo como padre (racks).
    es_contenedor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Correlativo de dos dígitos en el código (SW01) o sin correlativo (PD).
    usa_correlativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    atributos: Mapped[list["DefinicionAtributo"]] = relationship(
        back_populates="tipo",
        cascade="all, delete-orphan",
        order_by="DefinicionAtributo.orden",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TipoElemento {self.codigo}>"


class DefinicionAtributo(Base):
    """Un campo de la ficha de un tipo (SOP sección 9.2).

    Los valores concretos se guardan en ``Elemento.atributos`` (JSON), y esta
    tabla actúa como esquema: valida la carga, decide qué es obligatorio para
    el reporte de completitud y le dice al frontend qué formulario dibujar.
    """

    __tablename__ = "definicion_atributo"
    __table_args__ = (
        UniqueConstraint("tipo_elemento_id", "clave", name="uq_definicion_atributo_tipo_clave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_elemento_id: Mapped[int] = mapped_column(
        ForeignKey("tipo_elemento.id", ondelete="CASCADE"), index=True, nullable=False
    )
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(160), nullable=False)
    tipo_dato: Mapped[TipoDato] = mapped_column(columna_enum(TipoDato), nullable=False)
    obligatorio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Valores admitidos cuando ``tipo_dato`` es ENUM.
    opciones: Mapped[list | None] = mapped_column(TipoJSON)
    unidad: Mapped[str | None] = mapped_column(String(20))
    ayuda: Mapped[str | None] = mapped_column(Text)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tipo: Mapped[TipoElemento] = relationship(back_populates="atributos")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DefinicionAtributo {self.clave}>"
