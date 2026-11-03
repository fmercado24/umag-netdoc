/**
 * Filtros por tipo y estado, leyenda y listado jerárquico de la vista.
 *
 * Los contenedores (racks) se despliegan para mostrar lo que
 * tienen montado; ver `armarArbol` para las reglas.
 */

import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'

import { nodoDelSeleccionado } from '../arbol'
import type { Nodo } from '../arbol'
import type { ElementoEnMapa, ElementoMapa, Enumeraciones, TipoElemento } from '../types'

interface Props {
  tipos: TipoElemento[]
  enumeraciones: Enumeraciones | null
  tiposActivos: Set<string>
  estadosActivos: Set<string>
  /** Encabezado del listado: el piso completo o un tramo. */
  titulo: string
  nodos: Nodo[]
  /** Elementos que cumplen el filtro, contando también los montados. */
  totalCoincidencias: number
  /** Con filtro activo los contenedores se muestran desplegados. */
  filtroActivo: boolean
  conteoPorTipo: Map<string, number>
  seleccionadoId: number | null
  sinPosicionar: number
  onAlternarTipo: (codigo: string) => void
  onAlternarEstado: (valor: string) => void
  onLimpiar: () => void
  onSeleccionar: (elemento: ElementoMapa) => void
  /** Un edificio aún sin pisos no tiene dónde ubicar un elemento nuevo. */
  puedeAgregar: boolean
  onAgregar: () => void
  onVerEliminados: () => void
}

export function PanelLateral({
  tipos,
  enumeraciones,
  tiposActivos,
  estadosActivos,
  titulo,
  nodos,
  totalCoincidencias,
  filtroActivo,
  conteoPorTipo,
  seleccionadoId,
  sinPosicionar,
  onAlternarTipo,
  onAlternarEstado,
  onLimpiar,
  onSeleccionar,
  puedeAgregar,
  onAgregar,
  onVerEliminados,
}: Props) {
  const hayFiltros = tiposActivos.size > 0 || estadosActivos.size > 0
  const [abiertos, setAbiertos] = useState<Set<string>>(new Set())

  // El rack o grupo del elemento seleccionado se despliega para mostrarlo.
  const claveSeleccionada = nodoDelSeleccionado(nodos, seleccionadoId)?.clave ?? null
  useEffect(() => {
    if (claveSeleccionada === null) return
    setAbiertos((actual) =>
      actual.has(claveSeleccionada) ? actual : new Set(actual).add(claveSeleccionada),
    )
  }, [claveSeleccionada])

  const alternarAbierto = (clave: string) =>
    setAbiertos((actual) => {
      const copia = new Set(actual)
      if (copia.has(clave)) copia.delete(clave)
      else copia.add(clave)
      return copia
    })

  const flecha = (clave: string, desplegado: boolean, cantidad: number, descripcion: string) => (
    <button
      className={`item__abrir ${desplegado ? 'item__abrir--abierto' : ''}`}
      onClick={() => alternarAbierto(clave)}
      disabled={filtroActivo}
      aria-expanded={desplegado}
      aria-label={`${desplegado ? 'Ocultar' : 'Ver'} ${descripcion}`}
      title={descripcion}
    >
      <span className="item__flecha">▸</span>
      <span className="item__conteo">{cantidad}</span>
    </button>
  )

  const fila = (elemento: ElementoEnMapa, clases: string[] = []) => (
    <button
      className={['item', elemento.id === seleccionadoId ? 'item--activo' : '', ...clases]
        .filter(Boolean)
        .join(' ')}
      onClick={() => onSeleccionar(elemento)}
    >
      <span className="item__punto" style={{ background: elemento.color_estado }} />
      <span className="item__texto">
        <strong>{elemento.codigo}</strong>
        {/* "sin ubicar" va en esta línea para dejarle todo el ancho al código,
            que en los puntos de datos es largo. El recinto los distingue. */}
        <span className="item__linea">
          {!elemento.montado && !elemento.ubicado && (
            <span className="item__marca">sin ubicar</span>
          )}
          <small>
            {[elemento.etiqueta ?? elemento.tipo_nombre, elemento.ubicacion_descriptiva]
              .filter(Boolean)
              .join(' · ')}
          </small>
        </span>
      </span>
    </button>
  )

  return (
    <aside className="panel-lateral">
      <section className="bloque">
        <div className="bloque__titulo">
          <h2>Filtros</h2>
          {hayFiltros && (
            <button className="boton-enlace" onClick={onLimpiar}>
              Limpiar
            </button>
          )}
        </div>

        <h3 className="subtitulo">Tipo de elemento</h3>
        <div className="fichas">
          {tipos
            .filter((t) => (conteoPorTipo.get(t.codigo) ?? 0) > 0)
            .map((tipo) => {
              const activo = tiposActivos.has(tipo.codigo)
              return (
                <button
                  key={tipo.codigo}
                  className={`ficha ${activo ? 'ficha--activa' : ''}`}
                  style={{ '--color-ficha': tipo.color ?? '#64748B' } as CSSProperties}
                  onClick={() => onAlternarTipo(tipo.codigo)}
                  title={tipo.nombre}
                >
                  <span className="ficha__codigo">{tipo.codigo}</span>
                  <span className="ficha__conteo">{conteoPorTipo.get(tipo.codigo) ?? 0}</span>
                </button>
              )
            })}
        </div>

        <h3 className="subtitulo">Estado operativo</h3>
        <div className="fichas">
          {enumeraciones?.estado_operativo.map((opcion) => {
            const activo = estadosActivos.has(opcion.valor)
            return (
              <button
                key={opcion.valor}
                className={`ficha ficha--ancha ${activo ? 'ficha--activa' : ''}`}
                style={{ '--color-ficha': opcion.color ?? '#64748B' } as CSSProperties}
                onClick={() => onAlternarEstado(opcion.valor)}
              >
                <span className="punto" />
                {opcion.etiqueta}
              </button>
            )
          })}
        </div>
      </section>

      <section className="bloque bloque--crece">
        <div className="bloque__titulo">
          <h2>{titulo}</h2>
          <span className="contador">{totalCoincidencias}</span>
        </div>

        <button
          className="boton boton--agregar"
          onClick={onAgregar}
          disabled={!puedeAgregar}
          title={puedeAgregar ? undefined : 'Este edificio aún no tiene pisos registrados'}
        >
          + Agregar elemento
        </button>
        <button className="boton-enlace boton--eliminados" onClick={onVerEliminados}>
          Ver eliminados
        </button>

        {sinPosicionar > 0 && (
          <p className="aviso">
            {sinPosicionar} {sinPosicionar === 1 ? 'elemento' : 'elementos'} sin coordenadas sobre
            el plano.
          </p>
        )}

        <ul className="lista">
          {nodos.map((nodo) => {
            if (nodo.tipo === 'grupo') {
              const desplegado = filtroActivo || abiertos.has(nodo.clave)
              const recintos = [
                ...new Set(nodo.miembros.map((m) => m.ubicacion_descriptiva).filter(Boolean)),
              ].join(', ')
              const activo = nodo.miembros.some((m) => m.id === seleccionadoId)
              return (
                <li key={nodo.clave}>
                  <div className="item-contenedor">
                    {flecha(nodo.clave, desplegado, nodo.miembros.length, 'los puntos de datos del grupo')}
                    <button
                      className={`item item--grupo ${activo ? 'item--activo' : ''}`}
                      onClick={() => alternarAbierto(nodo.clave)}
                    >
                      <span className="item__punto item__punto--grupo" />
                      {/* Los ubicados por su recinto forman el grupo de la sala. */}
                      <span className="item__texto">
                        <strong>{recintos || 'Mismo lugar del plano'}</strong>
                        <small>{nodo.miembros.length} puntos de datos</small>
                      </span>
                    </button>
                  </div>
                  {desplegado && (
                    <ul className="lista__hijos">
                      {nodo.visibles.map((miembro) => (
                        <li key={miembro.id}>{fila(miembro, ['item--hijo'])}</li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            }

            const { elemento, coincide, hijos, totalHijos } = nodo
            const desplegado = hijos.length > 0 && (filtroActivo || abiertos.has(nodo.clave))
            return (
              <li key={nodo.clave}>
                <div className="item-contenedor">
                  {totalHijos > 0 ? (
                    flecha(nodo.clave, desplegado, totalHijos, `el contenido de ${elemento.codigo}`)
                  ) : (
                    <span className="item__abrir item__abrir--vacio" />
                  )}
                  {fila(elemento, coincide ? [] : ['item--contexto'])}
                </div>
                {desplegado && (
                  <ul className="lista__hijos">
                    {hijos.map((hijo) => (
                      <li key={hijo.id}>{fila(hijo, ['item--hijo'])}</li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
          {nodos.length === 0 && <li className="lista__vacia">Nada coincide con el filtro.</li>}
        </ul>
      </section>
    </aside>
  )
}
