/** Tipos espejo de los esquemas del backend (app/schemas). */

export interface SesionActiva {
  usuario: string
}

export type EstadoOperativo =
  | 'activo'
  | 'inactivo'
  | 'en_falla'
  | 'en_mantenimiento'
  | 'retirado'

export type EstadoCondicion = 'excelente' | 'regular' | 'malo' | 'obsoleto'

export type Categoria = 'activo' | 'pasivo' | 'soporte' | 'logico'

export interface Edificio {
  id: number
  codigo: string
  nombre: string
  campus: string | null
  direccion: string | null
  activo: boolean
}

export interface Tramo {
  id: number
  codigo: string
  nombre: string | null
}

/** La lámina pre-dibujada en una pirámide de teselas (ver backend/app/servicios/teselas.py). */
export interface Teselas {
  /** Bajo /media, con {z}, {x} e {y}. */
  url: string
  /** Nivel del visor que corresponde al nivel más detallado de la pirámide. */
  zoom_max: number
  niveles: number
  tamano: number
}

export interface Plano {
  id: number
  piso_id: number
  /** Nulo cuando la lámina cubre el piso completo. */
  tramo_id: number | null
  tramo_codigo: string | null
  nombre: string
  archivo: string
  formato: string | null
  ancho_px: number
  alto_px: number
  version: string | null
  vigente: boolean
  notas: string | null
  /** Nulo mientras no se generen: se muestra la lámina original, más lenta. */
  teselas: Teselas | null
}

/** Sala dibujada en una lámina, con el punto donde se ubican sus elementos. */
export interface Recinto {
  /** Como lo rotula el plano: "1083", "0017". */
  numero: string
  nombre: string | null
  plano_id: number
  /** Tramo de la lámina donde está; nulo si la lámina cubre el piso completo. */
  tramo_codigo: string | null
  pos_x: number
  pos_y: number
}

export interface Piso {
  id: number
  edificio_id: number
  codigo: string
  nombre: string | null
  orden: number
  tramos: Tramo[]
  /** El del piso completo primero y después los de cada tramo. */
  planos_vigentes: Plano[]
}

export interface DefinicionAtributo {
  id: number
  clave: string
  etiqueta: string
  tipo_dato: string
  obligatorio: boolean
  opciones: unknown[] | null
  unidad: string | null
  ayuda: string | null
  orden: number
}

export interface TipoElemento {
  id: number
  codigo: string
  nombre: string
  categoria: Categoria
  descripcion: string | null
  icono: string | null
  color: string | null
  es_contenedor: boolean
  usa_correlativo: boolean
  orden: number
}

export interface ElementoMapa {
  id: number
  codigo: string
  etiqueta: string | null
  tipo_codigo: string
  tipo_nombre: string
  categoria: Categoria
  estado_operativo: EstadoOperativo
  estado_condicion: EstadoCondicion | null
  color_estado: string
  pos_x: number | null
  pos_y: number | null
  plano_id: number | null
  padre_id: number | null
  /** Dentro de su contenedor: no lleva marcador propio, se ve a través de él. */
  montado: boolean
  /** Tramo de la lámina donde se dibuja; puede no ser el de su código. */
  tramo_lamina_codigo: string | null
  ubicacion_descriptiva: string | null
  /** Número de la sala donde está; con él se ubica solo en el plano. */
  numero_recinto: string | null
  marca: string | null
  modelo: string | null
  direccion_ip: string | null
}

export interface Elemento extends ElementoMapa {
  /** Sube en cada cambio: se envía al modificarlo, para no pisar el cambio de otra persona. */
  version: number
  edificio_codigo: string
  piso_codigo: string
  tramo_codigo: string | null
  numero_serie: string | null
  criticidad: string | null
  unidad_rack: number | null
  responsable_nombre: string | null
  activo: boolean
}

/** El código que recibiría un alta, y si sigue libre. */
export interface CodigoPropuesto {
  codigo: string
  disponible: boolean
  /** Es de un elemento eliminado: se recupera restaurándolo, no se reasigna. */
  eliminado: boolean
}

/** Lo que pasaría al trasladarlo. Ver backend/app/servicios/traslados.py. */
export interface PrevioTraslado {
  codigo_actual: string
  codigo_nuevo: string | null
  /** Por qué no se puede; nulo si se puede. */
  conflicto: string | null
  arrastrados: { codigo_actual: string; codigo_nuevo: string }[]
  desconectados: string[]
  conserva_posicion: boolean
  pierde_rack: boolean
}

export interface CampoFaltante {
  clave: string
  etiqueta: string
  origen: string
}

export interface Completitud {
  total_obligatorios: number
  completos: number
  porcentaje: number
  completo: boolean
  faltantes: CampoFaltante[]
}

export interface Fotografia {
  id: number
  archivo: string
  descripcion: string | null
  tomada_en: string | null
  orden: number
}

export interface ElementoHijo {
  id: number
  codigo: string
  etiqueta: string | null
  tipo_codigo: string
  tipo_nombre: string
  color_tipo: string | null
  estado_operativo: EstadoOperativo
  color_estado: string
  marca: string | null
  modelo: string | null
  /** False para un AP o una UPS que solo se conectan al rack. */
  montado: boolean
  unidad_rack: number | null
  /** Alto en U, cuando la ficha lo trae. */
  alto_u: number | null
}

export interface VlanElemento {
  numero: number
  nombre: string
  subred: string | null
  rol: string
}

/** Id del elemento en otro sistema (NetBox, GLPI, Zabbix…). */
export interface IdentificadorExterno {
  sistema: string
  id_externo: string
  url: string | null
  sincronizado_en: string | null
}

export interface ElementoDetalle extends Elemento {
  direccion_mac: string | null
  fecha_instalacion: string | null
  fecha_ultimo_levantamiento: string | null
  observaciones: string | null
  atributos: Record<string, unknown>
  padre_codigo: string | null
  /** Punto de datos: el rack y el puerto de donde sale, según su enlace. */
  rack_origen_codigo: string | null
  puerto_en_rack: string | null
  hijos: ElementoHijo[]
  fotografias: Fotografia[]
  vlans: VlanElemento[]
  externos: IdentificadorExterno[]
  completitud: Completitud | null
  /** Su recinto en las láminas del piso; nulo si no tiene número o no aparece en ellas. */
  recinto_en_plano: Recinto | null
  creado_en: string
  actualizado_en: string
}

export interface ElementoEnMapa extends ElementoMapa {
  /** Sus coordenadas corresponden a la lámina que muestra la vista. */
  ubicado: boolean
}

export interface RespuestaMapa {
  edificio: string
  piso: string
  tramo: string | null
  plano: Plano | null
  total: number
  sin_posicionar: number
  elementos: ElementoEnMapa[]
  /** Como estaba el edificio al armar esta respuesta (ver `api.novedades`). */
  marca: string
}

export interface OpcionEnum {
  valor: string
  etiqueta: string
  color?: string
}

export interface Enumeraciones {
  estado_operativo: OpcionEnum[]
  estado_condicion: OpcionEnum[]
  categoria: OpcionEnum[]
  criticidad: OpcionEnum[]
}

export interface HistorialEntrada {
  id: number
  campo: string
  valor_anterior: string | null
  valor_nuevo: string | null
  origen: string
  usuario: string | null
  comentario: string | null
  registrado_en: string
}

/** Un plano subido que espera a confirmarse (ver api.cargaDePlanos). */
export interface LaminaPendiente {
  nombre: string
  piso: string
  tramo: string | null
  /** «Piso 1, tramo 1», «Piso 2 completo», «Subterráneo». */
  destino: string
  ancho_px: number
  alto_px: number
  bytes: number
}

/** Lo que dice el nombre de un archivo, antes de subirlo. */
export interface RevisionLamina {
  archivo: string
  nombre: string | null
  piso: string | null
  tramo: string | null
  destino: string | null
  /** Por qué se rechaza; nulo si se acepta. */
  error: string | null
  /** El nombre que debería tener, si se pudo deducir. */
  sugerencia: string | null
}

export interface CargaDePlanos {
  edificio: string
  /** Solo en un edificio sin planos ni elementos. */
  permitida: boolean
  motivo: string | null
  nomenclatura: string
  ejemplos: { nombre: string; destino: string }[]
  /** Cómo se llama el plano de un edificio que tiene uno solo. */
  unico: string
  pendientes: LaminaPendiente[]
  revisados: RevisionLamina[]
}

export interface CargaConfirmada {
  pisos: string[]
  tramos: string[]
  planos: Plano[]
}
