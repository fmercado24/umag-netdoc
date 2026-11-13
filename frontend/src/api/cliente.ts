/** Cliente HTTP del backend NetDoc. */

import type {
  CargaConfirmada,
  CargaDePlanos,
  CodigoPropuesto,
  DefinicionAtributo,
  Edificio,
  Elemento,
  ElementoDetalle,
  Enumeraciones,
  HistorialEntrada,
  LaminaPendiente,
  Piso,
  PrevioTraslado,
  Recinto,
  RespuestaMapa,
  SesionActiva,
  TipoElemento,
} from '../types'

const BASE = '/api/v1'

export class ErrorApi extends Error {
  constructor(
    public readonly estado: number,
    mensaje: string,
    /** `detail` tal como lo envía FastAPI, para ubicar los errores por campo. */
    public readonly detalle: unknown = null,
  ) {
    super(mensaje)
    this.name = 'ErrorApi'
  }
}

let alVencerSesion: () => void = () => {}

/** Quién vuelve a pedir el ingreso cuando la API rechaza la sesión (venció o se reinició). */
export function avisarSesionVencida(aviso: () => void): void {
  alVencerSesion = aviso
}

const SIN_CONEXION =
  'No hay conexión con NetDoc. Revisa que la terminal de ./iniciar.sh siga abierta y vuelve a intentar.'

/**
 * Sin respuesta del servidor, fetch rechaza con un «Failed to fetch» que no dice
 * nada. Una consulta se puede repetir sin riesgo, lo que salva un corte
 * momentáneo; una escritura no, porque podría haberse aplicado. Estado 0: no hubo
 * respuesta.
 */
async function conectar(url: string, opciones: RequestInit): Promise<Response> {
  const reintentos = (opciones.method ?? 'GET') === 'GET' ? 2 : 0
  for (let intento = 0; ; intento++) {
    try {
      return await fetch(url, opciones)
    } catch {
      if (intento === reintentos) throw new ErrorApi(0, SIN_CONEXION)
      await new Promise((listo) => setTimeout(listo, 500))
    }
  }
}

async function pedir<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  // Con un archivo, el navegador arma el Content-Type (con su separador).
  const tipo: Record<string, string> =
    opciones.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }
  const respuesta = await conectar(`${BASE}${ruta}`, {
    ...opciones,
    headers: { ...tipo, ...(opciones.headers ?? {}) },
  })

  if (!respuesta.ok) {
    if (respuesta.status === 401) alVencerSesion()
    let mensaje = respuesta.statusText
    let detalle: unknown = null
    try {
      const cuerpo = await respuesta.json()
      detalle = cuerpo.detail
      mensaje = typeof detalle === 'string' ? detalle : JSON.stringify(detalle)
    } catch {
      /* la respuesta no era JSON */
    }
    throw new ErrorApi(respuesta.status, mensaje, detalle)
  }

  if (respuesta.status === 204) return undefined as T
  return respuesta.json() as Promise<T>
}

/** La API rechaza el cambio con este estado si otra persona ya modificó el elemento. */
export const ESTADO_CAMBIO_AJENO = 412

/**
 * La versión del elemento que se tenía a la vista. Con ella, la API no deja pisar
 * sin aviso lo que otra persona cambió entretanto.
 */
function vista(version: number | undefined): Record<string, string> {
  return version === undefined ? {} : { 'X-NetDoc-Version': String(version) }
}

/** URL de un archivo servido desde /media (planos y fotografías). */
export function urlMedia(rutaRelativa: string): string {
  return `/media/${rutaRelativa.replace(/^\/+/, '')}`
}

export const api = {
  sesion: () => pedir<SesionActiva>('/auth/sesion'),

  ingresar: (usuario: string, clave: string) =>
    pedir<SesionActiva>('/auth/ingresar', {
      method: 'POST',
      body: JSON.stringify({ usuario, clave }),
    }),

  salir: () => pedir<void>('/auth/salir', { method: 'POST' }),

  edificios: () => pedir<Edificio[]>('/edificios'),

  pisos: (edificio: string) => pedir<Piso[]>(`/edificios/${edificio}/pisos`),

  /** Recintos de las láminas del piso: los números de sala que se pueden asignar. */
  recintos: (edificio: string, piso: string) =>
    pedir<Recinto[]>(`/edificios/${edificio}/pisos/${piso}/recintos`),

  tipos: () => pedir<TipoElemento[]>('/catalogo/tipos'),

  ficha: (codigoTipo: string) =>
    pedir<DefinicionAtributo[]>(`/catalogo/tipos/${codigoTipo}/ficha`),

  enumeraciones: () => pedir<Enumeraciones>('/catalogo/enumeraciones'),

  /** Sin tramo, la vista es el piso completo. */
  mapa: (edificio: string, piso: string, tramo?: string) => {
    const parametros = new URLSearchParams({ edificio, piso })
    if (tramo) parametros.set('tramo', tramo)
    return pedir<RespuestaMapa>(`/elementos/mapa?${parametros}`)
  },

  /** Racks del piso (sin piso, los del edificio), para elegir dónde está montado un equipo. */
  racks: (edificio: string, piso?: string) => {
    const parametros = new URLSearchParams({ edificio, tipo: 'R', limite: '200' })
    if (piso) parametros.set('piso', piso)
    return pedir<{ items: Elemento[] }>(`/elementos?${parametros}`).then((r) => r.items)
  },

  /** El código que recibiría un alta con estos datos, sin crear nada. */
  proximoCodigo: (consulta: Record<string, string>) =>
    pedir<CodigoPropuesto>(`/elementos/proximo-codigo?${new URLSearchParams(consulta)}`),

  crearElemento: (datos: Record<string, unknown>, usuario?: string) => {
    const parametros = usuario ? `?${new URLSearchParams({ usuario })}` : ''
    return pedir<ElementoDetalle>(`/elementos${parametros}`, {
      method: 'POST',
      body: JSON.stringify(datos),
    })
  },

  elemento: (idOCodigo: string | number) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}`),

  historial: (idOCodigo: string | number) =>
    pedir<HistorialEntrada[]>(`/elementos/${idOCodigo}/historial`),

  actualizarPosicion: (
    idOCodigo: string | number,
    datos: { plano_id: number; pos_x: number; pos_y: number; usuario?: string },
    version?: number,
  ) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}/posicion`, {
      method: 'PATCH',
      body: JSON.stringify(datos),
      headers: vista(version),
    }),

  /** Lo lleva al recinto de su número, en la lámina donde está dibujado. */
  ubicarEnRecinto: (idOCodigo: string | number, version?: number) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}/ubicar-en-recinto`, {
      method: 'POST',
      headers: vista(version),
    }),

  actualizarElemento: (
    idOCodigo: string | number,
    datos: Record<string, unknown>,
    version?: number,
  ) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}`, {
      method: 'PATCH',
      body: JSON.stringify(datos),
      headers: vista(version),
    }),

  /** Qué pasaría al trasladarlo, sin cambiar nada. */
  previoTraslado: (idOCodigo: string | number, piso: string, tramo?: string) => {
    const parametros = new URLSearchParams({ piso })
    if (tramo) parametros.set('tramo', tramo)
    return pedir<PrevioTraslado>(`/elementos/${idOCodigo}/traslado?${parametros}`)
  },

  trasladar: (idOCodigo: string | number, datos: Record<string, unknown>, version?: number) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}/trasladar`, {
      method: 'POST',
      body: JSON.stringify(datos),
      headers: vista(version),
    }),

  /** Baja lógica: se puede deshacer con `restaurar`. */
  eliminar: (idOCodigo: string | number, motivo?: string, usuario?: string, version?: number) => {
    const parametros = new URLSearchParams()
    if (motivo) parametros.set('motivo', motivo)
    if (usuario) parametros.set('usuario', usuario)
    return pedir<ElementoDetalle>(`/elementos/${idOCodigo}?${parametros}`, {
      method: 'DELETE',
      headers: vista(version),
    })
  },

  restaurar: (idOCodigo: string | number, usuario?: string, version?: number) => {
    const parametros = usuario ? `?${new URLSearchParams({ usuario })}` : ''
    return pedir<ElementoDetalle>(`/elementos/${idOCodigo}/restaurar${parametros}`, {
      method: 'POST',
      headers: vista(version),
    })
  },

  /**
   * Si el edificio está vacío y se le pueden cargar planos, cómo deben llamarse y
   * los que ya esperan. Con `archivos`, revisa esos nombres antes de subirlos.
   */
  cargaDePlanos: (edificio: string, archivos: string[] = []) => {
    const parametros = new URLSearchParams()
    for (const archivo of archivos) parametros.append('archivo', archivo)
    return pedir<CargaDePlanos>(`/edificios/${edificio}/carga-de-planos?${parametros}`)
  },

  /** Sube un plano a la espera, revisado. Nada queda vigente hasta confirmar. */
  subirPlanoPendiente: (edificio: string, archivo: File) => {
    const datos = new FormData()
    datos.append('archivo', archivo, archivo.name)
    return pedir<LaminaPendiente>(`/edificios/${edificio}/carga-de-planos`, {
      method: 'POST',
      body: datos,
    })
  },

  quitarPlanoPendiente: (edificio: string, nombre: string) =>
    pedir<void>(`/edificios/${edificio}/carga-de-planos/${encodeURIComponent(nombre)}`, {
      method: 'DELETE',
    }),

  /** Crea los pisos y tramos que nombran los planos en espera y los deja vigentes. */
  confirmarCargaDePlanos: (edificio: string) =>
    pedir<CargaConfirmada>(`/edificios/${edificio}/carga-de-planos/confirmar`, {
      method: 'POST',
    }),

  /** Una marca que cambia cuando alguien cambia algo del edificio; llega también con el plano. */
  novedades: (edificio: string) => pedir<{ marca: string }>(`/edificios/${edificio}/novedades`),

  eliminados: (edificio: string) => {
    const parametros = new URLSearchParams({ edificio, solo_eliminados: 'true', limite: '1000' })
    return pedir<{ items: Elemento[] }>(`/elementos?${parametros}`).then((r) => r.items)
  },
}
