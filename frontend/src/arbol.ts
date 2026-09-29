/**
 * Jerarquía del listado y de los marcadores del visor.
 *
 * Solo llevan fila propia y marcador los elementos que no están montados:
 * racks, puntos de datos, AP, UPS… Lo montado (un switch o un patch panel en
 * su rack) cuelga de su contenedor y se despliega bajo él. Los puntos de
 * datos ubicados exactamente en el mismo lugar forman un grupo, con un solo
 * marcador y una sola fila. Con un filtro activo se muestran solo las
 * coincidencias, pero siempre bajo su contenedor o su grupo, para que se sepa
 * dónde están.
 */

import type { ElementoEnMapa } from './types'

export interface NodoElemento {
  tipo: 'elemento'
  clave: string
  elemento: ElementoEnMapa
  /** El contenedor cumple el filtro; si no, aparece solo como contexto. */
  coincide: boolean
  /** Montados que se muestran bajo él con el filtro actual. */
  hijos: ElementoEnMapa[]
  /** Todos sus montados, para el contador del listado y del marcador. */
  totalHijos: number
}

/** Puntos de datos con la misma posición en la lámina a la vista. */
export interface NodoGrupo {
  tipo: 'grupo'
  clave: string
  pos_x: number
  pos_y: number
  /** Todos los del lugar, cumplan o no el filtro: el marcador los cuenta. */
  miembros: ElementoEnMapa[]
  /** Los que se muestran en el listado con el filtro actual. */
  visibles: ElementoEnMapa[]
}

export type Nodo = NodoElemento | NodoGrupo

/** Solo se agrupan puntos de datos con marcador propio en esta lámina. */
function agrupable(elemento: ElementoEnMapa): boolean {
  return (
    elemento.tipo_codigo === 'PD' &&
    elemento.ubicado &&
    !elemento.montado &&
    elemento.pos_x !== null &&
    elemento.pos_y !== null
  )
}

const claveDeLugar = (elemento: ElementoEnMapa) => `g${elemento.pos_x},${elemento.pos_y}`

export function armarArbol(
  elementos: ElementoEnMapa[],
  coincide: (elemento: ElementoEnMapa) => boolean,
  filtroActivo: boolean,
): Nodo[] {
  const ids = new Set(elementos.map((e) => e.id))
  const hijosPorPadre = new Map<number, ElementoEnMapa[]>()
  const raices: ElementoEnMapa[] = []

  for (const elemento of elementos) {
    // Si el contenedor no está en la vista (otra lámina), el elemento se
    // muestra suelto antes que desaparecer.
    if (elemento.montado && elemento.padre_id !== null && ids.has(elemento.padre_id)) {
      const hermanos = hijosPorPadre.get(elemento.padre_id) ?? []
      hermanos.push(elemento)
      hijosPorPadre.set(elemento.padre_id, hermanos)
    } else {
      raices.push(elemento)
    }
  }

  const porLugar = new Map<string, ElementoEnMapa[]>()
  for (const raiz of raices.filter(agrupable)) {
    const clave = claveDeLugar(raiz)
    porLugar.set(clave, [...(porLugar.get(clave) ?? []), raiz])
  }

  const nodos: Nodo[] = []
  const gruposEmitidos = new Set<string>()
  for (const raiz of raices) {
    const lugar = agrupable(raiz) ? claveDeLugar(raiz) : null
    const miembros = lugar ? (porLugar.get(lugar) ?? []) : []
    if (lugar && miembros.length > 1) {
      if (gruposEmitidos.has(lugar)) continue
      gruposEmitidos.add(lugar)
      const visibles = miembros.filter(coincide)
      if (visibles.length === 0) continue
      nodos.push({
        tipo: 'grupo',
        clave: lugar,
        pos_x: raiz.pos_x as number,
        pos_y: raiz.pos_y as number,
        miembros,
        visibles,
      })
      continue
    }

    const todos = hijosPorPadre.get(raiz.id) ?? []
    const coincidentes = todos.filter(coincide)
    const propio = coincide(raiz)
    if (!propio && coincidentes.length === 0) continue
    nodos.push({
      tipo: 'elemento',
      clave: `e${raiz.id}`,
      elemento: raiz,
      coincide: propio,
      hijos: filtroActivo ? coincidentes : todos,
      totalHijos: todos.length,
    })
  }

  // Los racks primero: entre decenas de puntos de datos son lo que más cuesta
  // encontrar. El resto conserva el orden por código que entrega la API.
  const esRack = (nodo: Nodo) =>
    nodo.tipo === 'elemento' && nodo.elemento.tipo_codigo === 'R' ? 0 : 1
  return nodos.sort((a, b) => esRack(a) - esRack(b))
}

/** Nodo que contiene al elemento seleccionado, para desplegarlo y resaltarlo. */
export function nodoDelSeleccionado(nodos: Nodo[], id: number | null): Nodo | null {
  if (id === null) return null
  return (
    nodos.find((nodo) =>
      nodo.tipo === 'grupo'
        ? nodo.miembros.some((m) => m.id === id)
        : nodo.elemento.id === id || nodo.hijos.some((h) => h.id === id),
    ) ?? null
  )
}

/** Estado más grave del grupo, para el color de su marcador. */
const GRAVEDAD: Record<string, number> = {
  en_falla: 4,
  en_mantenimiento: 3,
  inactivo: 2,
  activo: 1,
  retirado: 0,
}

export function colorDelGrupo(miembros: ElementoEnMapa[]): string {
  const peor = [...miembros].sort(
    (a, b) => (GRAVEDAD[b.estado_operativo] ?? 0) - (GRAVEDAD[a.estado_operativo] ?? 0),
  )[0]
  return peor?.color_estado ?? '#64748B'
}
