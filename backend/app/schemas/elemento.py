"""Esquemas de elemento: creación, actualización, lectura y reportes."""

from __future__ import annotations

import datetime as dt
import ipaddress

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    Criticidad,
    EstadoCondicion,
    EstadoOperativo,
    OrigenCambio,
)
from app.schemas.organizacion import PlanoLeer, RecintoLeer
from app.servicios.validacion import RE_MAC

BASE = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------
class _RedValidada(BaseModel):
    """Formato de IP y MAC, común al alta y a la edición. Vacío = sin dato."""

    @field_validator("direccion_ip", check_fields=False)
    @classmethod
    def _ip_valida(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        try:
            return str(ipaddress.ip_address(valor.strip()))
        except ValueError:
            raise ValueError("no es una dirección IP válida") from None

    @field_validator("direccion_mac", check_fields=False)
    @classmethod
    def _mac_valida(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        if not RE_MAC.match(valor.strip()):
            raise ValueError("debe tener el formato AA:BB:CC:DD:EE:FF")
        return valor.strip().upper().replace("-", ":")


class ElementoCrear(_RedValidada):
    """Alta de un elemento.

    ``codigo`` es opcional: si no se entrega, el sistema lo genera con la
    convención del SOP sección 8 tomando el siguiente correlativo del trío
    tipo + edificio + piso. Un tipo sin correlativo (punto de datos) lo toma de
    ``rack_origen`` y ``puerto`` o, si aún no se conocen, de un ``SIN-ROTULO-NN``.
    """

    codigo: str | None = Field(default=None, max_length=80)
    tipo: str = Field(description="Código del tipo de elemento, p. ej. SW")
    edificio: str = Field(description="Código del edificio, p. ej. CADI")
    piso: str = Field(description="Código del piso, p. ej. P01")
    tramo: str | None = Field(default=None, description="Código del tramo, p. ej. T2")
    rack_origen: str | None = Field(
        default=None, description="Punto de datos: código del rack de donde sale su cableado"
    )
    puerto: str | None = Field(
        default=None,
        max_length=30,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$",
        description="Punto de datos: puerto en ese rack, p. ej. D17 (datos) o T03 (telefonía)",
    )

    etiqueta: str | None = Field(default=None, max_length=160)
    ubicacion_descriptiva: str | None = Field(default=None, max_length=200)
    numero_recinto: str | None = Field(
        default=None,
        max_length=20,
        description="Número de la sala en el plano (p. ej. 1083); vacío = el de la ubicación",
    )
    padre_codigo: str | None = Field(default=None, description="Código del rack contenedor")
    unidad_rack: int | None = None

    plano_id: int | None = None
    pos_x: float | None = None
    pos_y: float | None = None

    estado_operativo: EstadoOperativo = EstadoOperativo.ACTIVO
    estado_condicion: EstadoCondicion | None = None
    criticidad: Criticidad | None = None

    marca: str | None = Field(default=None, max_length=80)
    modelo: str | None = Field(default=None, max_length=120)
    numero_serie: str | None = Field(default=None, max_length=120)
    direccion_mac: str | None = Field(default=None, max_length=17)
    direccion_ip: str | None = Field(default=None, max_length=45)

    fecha_instalacion: dt.date | None = None
    fecha_ultimo_levantamiento: dt.date | None = None
    responsable_id: int | None = None
    observaciones: str | None = None

    atributos: dict = Field(default_factory=dict, description="Ficha específica del tipo")


class TrasladoPedido(BaseModel):
    """A dónde va, dentro de su edificio. Lo que depende del lugar puede indicarse:
    si se omite, en el mismo piso se conserva y en otro piso se borra, porque ya no
    significaría nada."""

    piso: str
    tramo: str | None = None
    ubicacion_descriptiva: str | None = Field(default=None, max_length=200)
    numero_recinto: str | None = Field(default=None, max_length=20)
    padre_codigo: str | None = None
    unidad_rack: int | None = Field(default=None, ge=1)
    usuario: str | None = Field(default=None, max_length=120)
    comentario: str | None = Field(default=None, max_length=1000)


class CambioDeCodigo(BaseModel):
    codigo_actual: str
    codigo_nuevo: str


class PrevioTraslado(BaseModel):
    """Lo que pasaría al trasladarlo, para mostrarlo antes de confirmar."""

    codigo_actual: str
    codigo_nuevo: str | None = None
    #: Por qué no se puede; nulo si se puede.
    conflicto: str | None = None
    #: Lo montado en él, que viaja con él.
    arrastrados: list[CambioDeCodigo] = Field(default_factory=list)
    #: Lo conectado a él que deja de estarlo.
    desconectados: list[str] = Field(default_factory=list)
    #: Su marcador sigue valiendo: el destino se dibuja en la misma lámina.
    conserva_posicion: bool = False
    #: Está en un rack de otro piso: si no se indica otro, queda sin rack.
    pierde_rack: bool = False


class ElementoActualizar(_RedValidada):
    """Actualización parcial. Todo campo omitido se deja intacto.

    El código dice dónde está y, en un punto de datos, de qué puerto sale. Lo que
    cambie eso actualiza también el código: ``tramo``, ``rack_origen`` y ``puerto``,
    y ``padre_codigo`` si el rack está en otro tramo.
    """

    etiqueta: str | None = None
    tramo: str | None = None
    #: Punto de datos: de qué rack y puerto sale (van juntos), como en el alta.
    rack_origen: str | None = None
    puerto: str | None = Field(default=None, max_length=30, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")
    #: Lámina donde se dibuja (código de tramo); nulo = la de su propio tramo.
    tramo_lamina: str | None = None
    ubicacion_descriptiva: str | None = None
    #: Al cambiarlo, el elemento pasa a ese recinto en el plano.
    numero_recinto: str | None = None
    padre_codigo: str | None = None
    unidad_rack: int | None = None
    plano_id: int | None = None
    pos_x: float | None = None
    pos_y: float | None = None
    estado_operativo: EstadoOperativo | None = None
    estado_condicion: EstadoCondicion | None = None
    criticidad: Criticidad | None = None
    marca: str | None = None
    modelo: str | None = None
    numero_serie: str | None = None
    direccion_mac: str | None = None
    direccion_ip: str | None = None
    fecha_instalacion: dt.date | None = None
    fecha_ultimo_levantamiento: dt.date | None = None
    responsable_id: int | None = None
    observaciones: str | None = None
    atributos: dict | None = None
    activo: bool | None = None

    #: Metadatos de la edición, no del elemento.
    usuario: str | None = None
    comentario: str | None = None


class PosicionActualizar(BaseModel):
    """Georreferenciación por clic sobre el plano (SOP sección 10.3)."""

    plano_id: int
    pos_x: float
    pos_y: float
    usuario: str | None = None


class EstadoMonitoreo(BaseModel):
    """Payload del webhook de monitoreo (SOP sección 11.3)."""

    codigo: str | None = None
    direccion_ip: str | None = None
    estado: str = Field(description='"up" / "down" o un estado operativo del sistema')
    minutos_caido: int | None = None
    comentario: str | None = None


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------
class ElementoMapa(BaseModel):
    """Proyección liviana para dibujar marcadores sobre el plano."""

    model_config = BASE

    id: int
    codigo: str
    etiqueta: str | None = None
    tipo_codigo: str
    tipo_nombre: str
    categoria: str
    estado_operativo: EstadoOperativo
    estado_condicion: EstadoCondicion | None = None
    color_estado: str
    pos_x: float | None = None
    pos_y: float | None = None
    plano_id: int | None = None
    padre_id: int | None = None
    #: Dentro de su contenedor: no lleva marcador propio, se ve a través de él.
    montado: bool = False
    #: Tramo de la lámina donde se dibuja; puede no ser el de su código.
    tramo_lamina_codigo: str | None = None
    # Campos que la búsqueda del visor filtra en el cliente.
    ubicacion_descriptiva: str | None = None
    numero_recinto: str | None = None
    marca: str | None = None
    modelo: str | None = None
    direccion_ip: str | None = None


class ElementoLeer(ElementoMapa):
    """Vista de listado: agrega ubicación e identidad del equipo."""

    edificio_codigo: str
    piso_codigo: str
    tramo_codigo: str | None = None
    numero_serie: str | None = None
    criticidad: Criticidad | None = None
    unidad_rack: int | None = None
    responsable_nombre: str | None = None
    activo: bool


class FotografiaLeer(BaseModel):
    model_config = BASE

    id: int
    archivo: str
    descripcion: str | None = None
    tomada_en: dt.datetime | None = None
    orden: int


class HistorialLeer(BaseModel):
    model_config = BASE

    id: int
    campo: str
    valor_anterior: str | None = None
    valor_nuevo: str | None = None
    origen: OrigenCambio
    usuario: str | None = None
    comentario: str | None = None
    registrado_en: dt.datetime


class CampoFaltante(BaseModel):
    clave: str
    etiqueta: str
    origen: str


class CompletitudLeer(BaseModel):
    total_obligatorios: int
    completos: int
    porcentaje: float
    completo: bool
    faltantes: list[CampoFaltante] = []


class ElementoHijo(BaseModel):
    """Lo que el contenedor necesita para dibujar su contenido."""

    model_config = BASE

    id: int
    codigo: str
    etiqueta: str | None = None
    tipo_codigo: str
    tipo_nombre: str
    color_tipo: str | None = None
    estado_operativo: EstadoOperativo
    color_estado: str
    marca: str | None = None
    modelo: str | None = None
    #: False para un AP o una UPS que solo se conectan al rack.
    montado: bool
    unidad_rack: int | None = None
    #: Alto en U, de la ficha (``unidades_rack``), cuando se conoce.
    alto_u: int | None = None


class IdentificadorExternoLeer(BaseModel):
    """Id del elemento en otro sistema (NetBox, GLPI, Zabbix…)."""

    model_config = BASE

    sistema: str
    id_externo: str
    url: str | None = None
    sincronizado_en: dt.datetime | None = None


class IdentificadorExternoGuardar(BaseModel):
    id_externo: str = Field(min_length=1, max_length=120)
    # La ficha la muestra como enlace: otro esquema (javascript:) sería un script.
    url: str | None = Field(default=None, max_length=300, pattern=r"^https?://")


class VlanElemento(BaseModel):
    numero: int
    nombre: str
    subred: str | None = None
    rol: str


class ElementoDetalle(ElementoLeer):
    """Ficha completa que alimenta el panel de detalle del visor."""

    direccion_mac: str | None = None
    fecha_instalacion: dt.date | None = None
    fecha_ultimo_levantamiento: dt.date | None = None
    observaciones: str | None = None
    atributos: dict = {}
    padre_codigo: str | None = None
    #: Punto de datos: el rack y el puerto de donde sale, según su enlace.
    rack_origen_codigo: str | None = None
    puerto_en_rack: str | None = None
    hijos: list[ElementoHijo] = []
    fotografias: list[FotografiaLeer] = []
    vlans: list[VlanElemento] = []
    externos: list[IdentificadorExternoLeer] = []
    completitud: CompletitudLeer | None = None
    #: El recinto de su número en las láminas del piso; nulo si no tiene
    #: número o el número no aparece en ellas.
    recinto_en_plano: RecintoLeer | None = None
    creado_en: dt.datetime
    actualizado_en: dt.datetime


class PaginaElementos(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[ElementoLeer]


class ElementoEnMapa(ElementoMapa):
    #: Sus coordenadas corresponden al plano que muestra la vista. Una
    #: posición guardada sobre la lámina de otro tramo no se puede dibujar
    #: aquí aunque ``pos_x`` y ``pos_y`` tengan valor.
    ubicado: bool


class RespuestaMapa(BaseModel):
    """Todo lo que el visor necesita para dibujar un piso de una sola vez."""

    edificio: str
    piso: str
    tramo: str | None = None
    plano: PlanoLeer | None = None
    total: int
    sin_posicionar: int
    elementos: list[ElementoEnMapa]
