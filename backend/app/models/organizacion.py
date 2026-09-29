"""Jerarquía territorial: edificio → piso → tramo, más planos y personas."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, MixinTiempos


class Persona(Base, MixinTiempos):
    """Responsable de un elemento o de un levantamiento (SOP sección 4)."""

    __tablename__ = "persona"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160), unique=True)
    unidad: Mapped[str | None] = mapped_column(String(120))
    rol: Mapped[str | None] = mapped_column(String(120))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Persona {self.nombre}>"


class Edificio(Base, MixinTiempos):
    """Catálogo de edificios (SOP sección 8.2)."""

    __tablename__ = "edificio"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    campus: Mapped[str | None] = mapped_column(String(120), default="Punta Arenas")
    direccion: Mapped[str | None] = mapped_column(String(200))
    observaciones: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    pisos: Mapped[list["Piso"]] = relationship(
        back_populates="edificio",
        cascade="all, delete-orphan",
        order_by="Piso.orden",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Edificio {self.codigo}>"


class Piso(Base):
    """Piso de un edificio. Código P00, P01…, PXX (SOP sección 8.3)."""

    __tablename__ = "piso"
    __table_args__ = (UniqueConstraint("edificio_id", "codigo", name="uq_piso_edificio_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    edificio_id: Mapped[int] = mapped_column(
        ForeignKey("edificio.id", ondelete="CASCADE"), index=True, nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(4), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(120))
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    edificio: Mapped[Edificio] = relationship(back_populates="pisos")
    tramos: Mapped[list["Tramo"]] = relationship(
        back_populates="piso", cascade="all, delete-orphan", order_by="Tramo.codigo"
    )
    planos: Mapped[list["Plano"]] = relationship(
        back_populates="piso", cascade="all, delete-orphan"
    )

    @property
    def planos_vigentes(self) -> list["Plano"]:
        """El del piso completo primero y después los de cada tramo."""
        vigentes = [p for p in self.planos if p.vigente]
        return sorted(vigentes, key=lambda p: (p.tramo is not None, p.tramo_codigo or ""))

    def plano_vigente(self, tramo: "Tramo | None" = None) -> "Plano | None":
        """Plano vigente de un tramo o, sin tramo, el del piso completo."""
        tramo_id = tramo.id if tramo else None
        return next((p for p in self.planos if p.vigente and p.tramo_id == tramo_id), None)

    def plano_para(self, tramo: "Tramo | None" = None) -> "Plano | None":
        """Plano sobre el que se dibuja el tramo.

        Un tramo sin lámina propia se ve sobre el plano del piso completo
        (el cuarto piso del CADI, por ejemplo, viene en una sola lámina).
        """
        return (self.plano_vigente(tramo) if tramo else None) or self.plano_vigente()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Piso {self.codigo}>"


class Tramo(Base):
    """Subdivisión horizontal del piso (T1, T2…), usada en el código CADI."""

    __tablename__ = "tramo"
    __table_args__ = (UniqueConstraint("piso_id", "codigo", name="uq_tramo_piso_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    piso_id: Mapped[int] = mapped_column(
        ForeignKey("piso.id", ondelete="CASCADE"), index=True, nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(6), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(120))

    piso: Mapped[Piso] = relationship(back_populates="tramos")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tramo {self.codigo}>"


class Plano(Base, MixinTiempos):
    """Imagen base del piso sobre la que se posicionan los elementos.

    ``ancho_px`` y ``alto_px`` definen el sistema de coordenadas: las
    posiciones de los elementos se guardan en esas mismas unidades, de modo
    que el visor puede montar el plano como capa base sin reproyectar.

    Un plano cubre el piso completo (``tramo_id`` nulo) o un solo tramo,
    porque la DSI dibuja los pisos grandes del CADI en una lámina por tramo.
    Hay a lo más un plano vigente por cada par piso–tramo.
    """

    __tablename__ = "plano"

    id: Mapped[int] = mapped_column(primary_key=True)
    piso_id: Mapped[int] = mapped_column(
        ForeignKey("piso.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tramo_id: Mapped[int | None] = mapped_column(
        ForeignKey("tramo.id", ondelete="CASCADE"), index=True
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    archivo: Mapped[str] = mapped_column(String(300), nullable=False)
    formato: Mapped[str | None] = mapped_column(String(10))
    ancho_px: Mapped[int] = mapped_column(Integer, nullable=False)
    alto_px: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str | None] = mapped_column(String(40))
    vigente: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notas: Mapped[str | None] = mapped_column(Text)

    piso: Mapped[Piso] = relationship(back_populates="planos")
    tramo: Mapped[Tramo | None] = relationship(lazy="joined")

    @property
    def tramo_codigo(self) -> str | None:
        return self.tramo.codigo if self.tramo else None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Plano {self.nombre}>"
