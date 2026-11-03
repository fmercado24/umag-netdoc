/** Lo que comparten los formularios de alta y de edición de un elemento. */

import type { ReactNode } from 'react'

import { ErrorApi } from '../api/cliente'
import type { DefinicionAtributo } from '../types'

/** Un rack no va dentro de otro y un punto de datos no tiene contenedor. */
export const SIN_RACK = new Set(['R', 'PD'])

/** Un AP o una UPS se conecta al rack, pero tiene marcador propio y no ocupa unidades. */
export const SOLO_CONECTADOS = new Set(['AP', 'UPS'])

/** Se completa solo con el rack y el puerto: la API la arma como el rótulo físico. */
export const ATRIBUTOS_AUTOMATICOS = new Set(['puerto_origen'])

/** Quién registra: se recuerda en este navegador para no escribirlo cada vez. */
const CLAVE_USUARIO = 'netdoc.usuario'

export function leerUsuario(): string {
  try {
    return localStorage.getItem(CLAVE_USUARIO) ?? ''
  } catch {
    return ''
  }
}

export function recordarUsuario(usuario: string) {
  try {
    localStorage.setItem(CLAVE_USUARIO, usuario)
  } catch {
    /* sin almacenamiento local: se pedirá de nuevo */
  }
}

/** Convierte lo escrito al tipo que exige la ficha; lanza el mensaje de error. */
export function convertirAtributo(texto: string, definicion: DefinicionAtributo): unknown {
  const limpio = texto.trim()
  if (limpio === '') return null
  switch (definicion.tipo_dato) {
    case 'numero': {
      const numero = Number(limpio.replace(',', '.'))
      if (Number.isNaN(numero)) throw new Error('debe ser un número')
      return numero
    }
    case 'booleano':
      return limpio === 'true'
    case 'lista':
      return limpio
        .split(',')
        .map((parte) => parte.trim())
        .filter(Boolean)
    default:
      return limpio
  }
}

/** Ubica los errores de FastAPI (422 de Pydantic o de la ficha) en su campo. */
export function erroresDelServidor(error: unknown): {
  porCampo: Record<string, string>
  general: string | null
} {
  const porCampo: Record<string, string> = {}
  if (!(error instanceof ErrorApi)) {
    return { porCampo, general: error instanceof Error ? error.message : 'Error desconocido' }
  }
  const detalle = error.detalle
  if (Array.isArray(detalle)) {
    const sueltos: string[] = []
    for (const item of detalle) {
      if (typeof item === 'string') {
        // Ficha del tipo: "'clave' debe ser numérico".
        const clave = /^'([^']+)'/.exec(item)?.[1]
        if (clave) porCampo[`atributos.${clave}`] = item.replace(/^'[^']+'\s*/, '')
        else sueltos.push(item)
      } else if (item && typeof item === 'object' && 'loc' in item && 'msg' in item) {
        const loc = (item as { loc: unknown[] }).loc
        const mensaje = String((item as { msg: unknown }).msg).replace(/^Value error, /, '')
        porCampo[String(loc[loc.length - 1])] = mensaje
      }
    }
    return { porCampo, general: sueltos.length ? sueltos.join('; ') : null }
  }
  return { porCampo, general: error.message }
}

export function Campo({
  etiqueta,
  error,
  ayuda,
  children,
}: {
  etiqueta: string
  error?: string
  ayuda?: string
  children: ReactNode
}) {
  return (
    <label className={`formulario__campo ${error ? 'formulario__campo--error' : ''}`}>
      <span>{etiqueta}</span>
      {children}
      {error ? (
        <small className="formulario__error">{error}</small>
      ) : (
        ayuda && <small className="formulario__ayuda">{ayuda}</small>
      )}
    </label>
  )
}

/** El control de un atributo de la ficha, según lo que declara el catálogo. */
export function ControlAtributo({
  definicion,
  valor,
  onCambio,
}: {
  definicion: DefinicionAtributo
  valor: string
  onCambio: (valor: string) => void
}) {
  switch (definicion.tipo_dato) {
    case 'enum':
      return (
        <select value={valor} onChange={(e) => onCambio(e.target.value)}>
          <option value="">—</option>
          {(definicion.opciones ?? []).map((o) => (
            <option key={String(o)} value={String(o)}>
              {String(o)}
            </option>
          ))}
        </select>
      )
    case 'booleano':
      return (
        <select value={valor} onChange={(e) => onCambio(e.target.value)}>
          <option value="">—</option>
          <option value="true">Sí</option>
          <option value="false">No</option>
        </select>
      )
    case 'numero':
      return (
        <input
          type="text"
          inputMode="decimal"
          value={valor}
          onChange={(e) => onCambio(e.target.value)}
        />
      )
    case 'fecha':
      return <input type="date" value={valor} onChange={(e) => onCambio(e.target.value)} />
    default:
      return (
        <input
          type="text"
          value={valor}
          placeholder={
            definicion.tipo_dato === 'lista'
              ? 'Separados por coma'
              : definicion.tipo_dato === 'mac'
                ? 'AA:BB:CC:DD:EE:FF'
                : definicion.tipo_dato === 'referencia'
                  ? 'Código del elemento'
                  : undefined
          }
          onChange={(e) => onCambio(e.target.value)}
        />
      )
  }
}
