"""Elementos lógicos (VLAN/subred) y enlaces entre elementos físicos."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, MixinTiempos, columna_enum
from app.models.enums import MedioEnlace, RolVlan


class Vlan(Base, MixinTiempos):
    """VLAN y su subred asociada (SOP sección 7.1, categoría lógica)."""

    __tablename__ = "vlan"
    # El número se repite entre edificios: la VLAN 3 del CADI y la de otro
    # edificio pueden ser redes distintas. Una VLAN sin edificio es de campus.
    __table_args__ = (UniqueConstraint("edificio_id", "numero", name="uq_vlan_edificio_numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    subred: Mapped[str | None] = mapped_column(String(50))
    gateway: Mapped[str | None] = mapped_column(String(45))
    descripcion: Mapped[str | None] = mapped_column(Text)
    edificio_id: Mapped[int | None] = mapped_column(ForeignKey("edificio.id", ondelete="SET NULL"))

    edificio = relationship("Edificio")
    elementos: Mapped[list["ElementoVlan"]] = relationship(
        back_populates="vlan", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Vlan {self.numero} {self.nombre}>"


class ElementoVlan(Base):
    """Vínculo entre un elemento físico y la VLAN que materializa."""

    __tablename__ = "elemento_vlan"
    __table_args__ = (
        UniqueConstraint("elemento_id", "vlan_id", "rol", name="uq_elemento_vlan"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    elemento_id: Mapped[int] = mapped_column(
        ForeignKey("elemento.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vlan_id: Mapped[int] = mapped_column(
        ForeignKey("vlan.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rol: Mapped[RolVlan] = mapped_column(
        columna_enum(RolVlan), default=RolVlan.SERVICIO, nullable=False
    )

    elemento = relationship("Elemento", back_populates="vlans")
    vlan: Mapped[Vlan] = relationship(back_populates="elementos")


class Enlace(Base, MixinTiempos):
    """Conexión física entre dos elementos.

    Cubre tanto el uplink de un switch (SOP 9.2.1) como el mapeo
    puerto de patch panel → punto de datos (SOP 9.2.3).
    """

    __tablename__ = "enlace"

    id: Mapped[int] = mapped_column(primary_key=True)
    origen_id: Mapped[int] = mapped_column(
        ForeignKey("elemento.id", ondelete="CASCADE"), index=True, nullable=False
    )
    puerto_origen: Mapped[str | None] = mapped_column(String(40))
    destino_id: Mapped[int | None] = mapped_column(
        ForeignKey("elemento.id", ondelete="SET NULL"), index=True
    )
    puerto_destino: Mapped[str | None] = mapped_column(String(40))
    #: Destino aún no documentado como elemento (texto de la etiqueta física).
    destino_descripcion: Mapped[str | None] = mapped_column(String(200))
    medio: Mapped[MedioEnlace] = mapped_column(
        columna_enum(MedioEnlace), default=MedioEnlace.COBRE, nullable=False
    )
    categoria: Mapped[str | None] = mapped_column(String(40))
    etiqueta: Mapped[str | None] = mapped_column(String(160))
    observaciones: Mapped[str | None] = mapped_column(Text)

    origen = relationship("Elemento", foreign_keys=[origen_id])
    destino = relationship("Elemento", foreign_keys=[destino_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Enlace {self.origen_id}:{self.puerto_origen} -> {self.destino_id}>"
