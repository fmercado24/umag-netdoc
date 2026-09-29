/** Cliente HTTP del backend NetDoc. */

import type {
  DefinicionAtributo,
  Edificio,
  Elemento,
  ElementoDetalle,
  Enumeraciones,
  HistorialEntrada,
  Piso,
  RespuestaMapa,
  TipoElemento,
} from '../types'

export const URL_API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const BASE = `${URL_API}/api/v1`

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

async function pedir<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  const respuesta = await fetch(`${BASE}${ruta}`, {
    headers: { 'Content-Type': 'application/json', ...(opciones.headers ?? {}) },
    ...opciones,
  })

  if (!respuesta.ok) {
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

/** URL absoluta de un archivo servido desde /media (planos y fotografías). */
export function urlMedia(rutaRelativa: string): string {
  return `${URL_API}/media/${rutaRelativa.replace(/^\/+/, '')}`
}

export const api = {
  edificios: () => pedir<Edificio[]>('/edificios'),

  pisos: (edificio: string) => pedir<Piso[]>(`/edificios/${edificio}/pisos`),

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

  /** Racks del piso, para elegir dónde está montado un equipo. */
  racks: (edificio: string, piso: string) => {
    const parametros = new URLSearchParams({ edificio, piso, tipo: 'R', limite: '200' })
    return pedir<{ items: Elemento[] }>(`/elementos?${parametros}`).then((r) => r.items)
  },

  elemento: (idOCodigo: string | number) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}`),

  historial: (idOCodigo: string | number) =>
    pedir<HistorialEntrada[]>(`/elementos/${idOCodigo}/historial`),

  actualizarPosicion: (
    idOCodigo: string | number,
    datos: { plano_id: number; pos_x: number; pos_y: number; usuario?: string },
  ) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}/posicion`, {
      method: 'PATCH',
      body: JSON.stringify(datos),
    }),

  actualizarElemento: (idOCodigo: string | number, datos: Record<string, unknown>) =>
    pedir<ElementoDetalle>(`/elementos/${idOCodigo}`, {
      method: 'PATCH',
      body: JSON.stringify(datos),
    }),
}
