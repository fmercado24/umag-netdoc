"""Elemento documentado, su evidencia fotográfica y su historial de cambios."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, MixinTiempos, TipoJSON, columna_enum
from app.models.catalogo import TipoElemento
from app.models.enums import (
    Criticidad,
    EstadoCondicion,
    EstadoLevantamiento,
    EstadoOperativo,
    OrigenCambio,
)
from app.models.organizacion import Edificio, Persona, Piso, Plano, Tramo

#: Tipos que las planillas asocian a un rack porque se conectan a él, no
#: porque estén montados dentro: el AP va en el cielo de un recinto y la UPS
#: del CADI es de torre. Aunque tengan ``padre``, se ubican en el plano por
#: su cuenta y el rack los muestra como "conectados".
TIPOS_CONECTADOS_AL_CONTENEDOR = frozenset({"AP", "UPS"})


class Elemento(Base, MixinTiempos):
    """Unidad mínima documentada.

    Combina dos capas de atributos:

    * columnas fijas → los atributos comunes del SOP sección 9.1, que
      necesitan filtrarse, ordenarse e indexarse;
    * ``atributos`` (JSON) → la ficha específica del tipo (SOP sección 9.2),
      cuyo esquema vive en ``definicion_atributo``.
    """

    __tablename__ = "elemento"
    __table_args__ = (
        Index("ix_elemento_ubicacion", "edificio_id", "piso_id", "tramo_id"),
        Index("ix_elemento_tipo_estado", "tipo_elemento_id", "estado_operativo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Identificación (SOP sección 8) ---------------------------------
    codigo: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    correlativo: Mapped[int | None] = mapped_column(Integer)
    etiqueta: Mapped[str | None] = mapped_column(String(160))
    tipo_elemento_id: Mapped[int] = mapped_column(
        ForeignKey("tipo_elemento.id"), index=True, nullable=False
    )

    # --- Ubicación --------------------------------------------------------
    edificio_id: Mapped[int] = mapped_column(
        ForeignKey("edificio.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    piso_id: Mapped[int] = mapped_column(
        ForeignKey("piso.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    tramo_id: Mapped[int | None] = mapped_column(ForeignKey("tramo.id", ondelete="SET NULL"))
    #: Tramo de la lámina donde está dibujado, cuando no es el de su código.
    #: En el Piso 1 del CADI la sala eléctrica de los racks se considera
    #: tramo 3, así que sus racks y los puntos de datos que llegan a ellos
    #: llevan T3 en el rótulo, pero están dibujados en la lámina del tramo 1.
    #: Nulo = la lámina de su propio tramo.
    tramo_lamina_id: Mapped[int | None] = mapped_column(
        ForeignKey("tramo.id", ondelete="SET NULL")
    )
    ubicacion_descriptiva: Mapped[str | None] = mapped_column(String(200))
    #: Número de la sala donde está, como lo rotulan los planos ("1083",
    #: "0017"). Con él se ubica solo sobre la lámina: ver ``app.servicios.recintos``.
    numero_recinto: Mapped[str | None] = mapped_column(String(20), index=True)

    #: Elemento contenedor (típicamente el rack). Permite anidar equipos en
    #: una misma coordenada del plano, según SOP sección 10.3 punto 20.
    padre_id: Mapped[int | None] = mapped_column(
        ForeignKey("elemento.id", ondelete="SET NULL"), index=True
    )
    unidad_rack: Mapped[int | None] = mapped_column(Integer)

    # --- Georreferenciación sobre el plano (SOP sección 10.3) -------------
    plano_id: Mapped[int | None] = mapped_column(ForeignKey("plano.id", ondelete="SET NULL"))
    pos_x: Mapped[float | None] = mapped_column(Float)
    pos_y: Mapped[float | None] = mapped_column(Float)

    # --- Estado -----------------------------------------------------------
    estado_operativo: Mapped[EstadoOperativo] = mapped_column(
        columna_enum(EstadoOperativo), default=EstadoOperativo.ACTIVO, nullable=False
    )
    estado_condicion: Mapped[EstadoCondicion | None] = mapped_column(
        columna_enum(EstadoCondicion)
    )
    criticidad: Mapped[Criticidad | None] = mapped_column(columna_enum(Criticidad))

    # --- Identidad física y de red ---------------------------------------
    marca: Mapped[str | None] = mapped_column(String(80))
    modelo: Mapped[str | None] = mapped_column(String(120))
    numero_serie: Mapped[str | None] = mapped_column(String(120))
    direccion_mac: Mapped[str | None] = mapped_column(String(17))
    direccion_ip: Mapped[str | None] = mapped_column(String(45), index=True)

    # --- Trazabilidad -----------------------------------------------------
    fecha_instalacion: Mapped[dt.date | None] = mapped_column(Date)
    fecha_ultimo_levantamiento: Mapped[dt.date | None] = mapped_column(Date)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("persona.id", ondelete="SET NULL"))
    observaciones: Mapped[str | None] = mapped_column(Text)

    #: Ficha específica del tipo. Las claves corresponden a
    #: ``DefinicionAtributo.clave`` del tipo del elemento.
    atributos: Mapped[dict] = mapped_column(TipoJSON, default=dict, nullable=False)

    #: Baja lógica: el código nunca se reutiliza (SOP sección 8.5).
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Relaciones -------------------------------------------------------
    tipo: Mapped[TipoElemento] = relationship(lazy="joined")
    edificio: Mapped[Edificio] = relationship(lazy="joined")
    piso: Mapped[Piso] = relationship(lazy="joined")
    tramo: Mapped[Tramo | None] = relationship(foreign_keys=[tramo_id], lazy="joined")
    tramo_lamina: Mapped[Tramo | None] = relationship(
        foreign_keys=[tramo_lamina_id], lazy="joined"
    )
    plano: Mapped[Plano | None] = relationship()
    responsable: Mapped[Persona | None] = relationship(lazy="joined")

    padre: Mapped["Elemento | None"] = relationship(
        remote_side="Elemento.id", back_populates="hijos"
    )
    hijos: Mapped[list["Elemento"]] = relationship(back_populates="padre")

    fotografias: Mapped[list["Fotografia"]] = relationship(
        back_populates="elemento", cascade="all, delete-orphan", order_by="Fotografia.orden"
    )
    historial: Mapped[list["HistorialElemento"]] = relationship(
        back_populates="elemento",
        cascade="all, delete-orphan",
        order_by="HistorialElemento.registrado_en.desc()",
    )
    vlans: Mapped[list["ElementoVlan"]] = relationship(
        back_populates="elemento", cascade="all, delete-orphan"
    )
    externos: Mapped[list["IdentificadorExterno"]] = relationship(
        back_populates="elemento",
        cascade="all, delete-orphan",
        order_by="IdentificadorExterno.sistema",
    )

    # --- Atajos de lectura -----------------------------------------------
    # Aplanan las relaciones para que los esquemas de salida puedan leerlas
    # directamente con ``from_attributes`` sin recorrer objetos anidados.

    @property
    def tiene_coordenadas(self) -> bool:
        return self.pos_x is not None and self.pos_y is not None

    @property
    def montado(self) -> bool:
        """Está físicamente dentro de su contenedor (un switch en su rack,
        una toma en su punto de datos) y se ubica a través de él."""
        return self.padre is not None and self.tipo.codigo not in TIPOS_CONECTADOS_AL_CONTENEDOR

    @property
    def representante_en_plano(self) -> Elemento:
        """Elemento cuyo marcador lo representa: él mismo o su contenedor.

        Resuelve el punto 20 de la sección 10.3 del SOP: los elementos que
        comparten una coordenada cuelgan del contenedor que lleva el marcador.
        """
        actual = self
        for _ in range(8):  # guarda contra ciclos padre → hijo mal cargados
            if not actual.montado:
                break
            actual = actual.padre
        return actual

    @property
    def tramo_de_lamina(self) -> Tramo | None:
        """Tramo cuya lámina lo muestra; lo montado, la de su contenedor."""
        representante = self.representante_en_plano
        return representante.tramo_lamina or representante.tramo

    @property
    def tramo_lamina_codigo(self) -> str | None:
        tramo = self.tramo_de_lamina
        return tramo.codigo if tramo else None

    @property
    def tipo_codigo(self) -> str:
        return self.tipo.codigo

    @property
    def tipo_nombre(self) -> str:
        return self.tipo.nombre

    @property
    def categoria(self) -> str:
        return self.tipo.categoria.value

    @property
    def edificio_codigo(self) -> str:
        return self.edificio.codigo

    @property
    def piso_codigo(self) -> str:
        return self.piso.codigo

    @property
    def tramo_codigo(self) -> str | None:
        return self.tramo.codigo if self.tramo else None

    @property
    def responsable_nombre(self) -> str | None:
        return self.responsable.nombre if self.responsable else None

    @property
    def padre_codigo(self) -> str | None:
        return self.padre.codigo if self.padre else None

    @property
    def color_estado(self) -> str:
        from app.models.enums import COLORES_ESTADO

        return COLORES_ESTADO.get(self.estado_operativo, "#6B7280")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Elemento {self.codigo}>"


class Fotografia(Base):
    """Registro fotográfico de evidencia (SOP sección 10.4)."""

    __tablename__ = "fotografia"

    id: Mapped[int] = mapped_column(primary_key=True)
    elemento_id: Mapped[int] = mapped_column(
        ForeignKey("elemento.id", ondelete="CASCADE"), index=True, nullable=False
    )
    archivo: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(300))
    tomada_en: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    subida_en: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    elemento: Mapped[Elemento] = relationship(back_populates="fotografias")


class HistorialElemento(Base):
    """Bitácora campo a campo. Retención permanente (SOP sección 12)."""

    __tablename__ = "historial_elemento"

    id: Mapped[int] = mapped_column(primary_key=True)
    elemento_id: Mapped[int] = mapped_column(
        ForeignKey("elemento.id", ondelete="CASCADE"), index=True, nullable=False
    )
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    valor_anterior: Mapped[str | None] = mapped_column(Text)
    valor_nuevo: Mapped[str | None] = mapped_column(Text)
    origen: Mapped[OrigenCambio] = mapped_column(
        columna_enum(OrigenCambio), default=OrigenCambio.MANUAL, nullable=False
    )
    usuario: Mapped[str | None] = mapped_column(String(120))
    comentario: Mapped[str | None] = mapped_column(Text)
    registrado_en: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    elemento: Mapped[Elemento] = relationship(back_populates="historial")


class Levantamiento(Base, MixinTiempos):
    """Bitácora de levantamiento por edificio (SOP sección 10.5 punto 24)."""

    __tablename__ = "levantamiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    edificio_id: Mapped[int] = mapped_column(
        ForeignKey("edificio.id", ondelete="CASCADE"), index=True, nullable=False
    )
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_cierre: Mapped[dt.date | None] = mapped_column(Date)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("persona.id", ondelete="SET NULL"))
    estado: Mapped[EstadoLevantamiento] = mapped_column(
        columna_enum(EstadoLevantamiento), default=EstadoLevantamiento.EN_CURSO, nullable=False
    )
    observaciones: Mapped[str | None] = mapped_column(Text)

    edificio: Mapped[Edificio] = relationship()
    responsable: Mapped[Persona | None] = relationship()
