"""Correspondencia con sistemas externos (NetBox, GLPI, Zabbix u otros)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, MixinTiempos


class IdentificadorExterno(Base, MixinTiempos):
    """El id que otro sistema le asignó a un elemento.

    Es lo que permite sincronizar en ambos sentidos: un conector que crea el
    elemento en NetBox guarda aquí el id del device, y la próxima pasada lo
    actualiza en vez de duplicarlo. A la inversa, un evento que llega con el
    id de GLPI o Zabbix se traduce al elemento de NetDoc. Un elemento tiene a
    lo más un id por sistema, y un id externo apunta a un solo elemento.
    """

    __tablename__ = "identificador_externo"
    __table_args__ = (
        UniqueConstraint("elemento_id", "sistema", name="uq_identificador_externo_elemento_sistema"),
        UniqueConstraint("sistema", "id_externo", name="uq_identificador_externo_sistema_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    elemento_id: Mapped[int] = mapped_column(
        ForeignKey("elemento.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Nombre corto del sistema en minúsculas: ``netbox``, ``glpi``, ``zabbix``…
    sistema: Mapped[str] = mapped_column(String(40), nullable=False)
    id_externo: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Enlace al registro en el otro sistema, si tiene interfaz web.
    url: Mapped[str | None] = mapped_column(String(300))
    #: Última vez que un conector confirmó que ambos registros coinciden.
    sincronizado_en: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    elemento = relationship("Elemento", back_populates="externos")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IdentificadorExterno {self.sistema}:{self.id_externo}>"


class LatidoMonitoreo(Base):
    """Cuándo se supo por última vez de cada herramienta de monitoreo.

    Los avisos de monitoreo llegan solo cuando algo cambia (modelo *push*): sin
    este registro, una herramienta caída no se distingue de una red sin fallas.
    Cada aviso que llega con el token, o un latido explícito, actualiza la hora;
    si pasan más de ``NETDOC_MONITOREO_LATIDO_MINUTOS`` sin noticias, el visor lo
    advierte (``app.servicios.latidos``).
    """

    __tablename__ = "latido_monitoreo"

    #: "zabbix" (webhook genérico), "alertmanager" u otra herramienta.
    fuente: Mapped[str] = mapped_column(String(40), primary_key=True)
    ultimo_contacto: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
