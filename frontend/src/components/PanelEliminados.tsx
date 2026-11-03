/**
 * Lo dado de baja en el edificio. Eliminar es una baja lógica (SOP sección 8.5):
 * el elemento conserva su código e historial, y desde aquí se puede recuperar.
 */

import { useEffect, useState } from 'react'

import { api } from '../api/cliente'
import { erroresDelServidor, leerUsuario } from './camposFormulario'
import type { Elemento, ElementoDetalle } from '../types'

interface Props {
  edificio: string
  onCerrar: () => void
  onSeleccionar: (id: number) => void
  onRestaurado: (restaurado: ElementoDetalle) => void
}

export function PanelEliminados({ edificio, onCerrar, onSeleccionar, onRestaurado }: Props) {
  const [elementos, setElementos] = useState<Elemento[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    setElementos(null)
    api
      .eliminados(edificio)
      .then((lista) => vigente && setElementos(lista))
      .catch((e) => vigente && setError(erroresDelServidor(e).general))
    return () => {
      vigente = false
    }
  }, [edificio])

  const restaurar = (elemento: Elemento) => {
    setError(null)
    api
      .restaurar(elemento.id, leerUsuario() || undefined)
      .then(onRestaurado)
      .catch((e) => setError(erroresDelServidor(e).general))
  }

  return (
    <section className="panel-detalle">
      <header className="detalle__cabecera">
        <div>
          <span className="detalle__tipo">Edificio {edificio}</span>
          <h2 className="detalle__titulo">Elementos eliminados</h2>
        </div>
        <div className="detalle__botones">
          <button className="boton-cerrar" onClick={onCerrar} aria-label="Cerrar eliminados">
            ×
          </button>
        </div>
      </header>

      {error && <p className="formulario__aviso">{error}</p>}
      <p className="nota-seccion">
        No aparecen en el plano ni en los listados. Conservan su historial y su código, que no se
        vuelve a usar.
      </p>
      {elementos === null && !error && <p className="vacio">Cargando…</p>}
      {elementos?.length === 0 && <p className="vacio">No hay elementos eliminados.</p>}
      <ul className="lista-eliminados">
        {elementos?.map((elemento) => (
          <li key={elemento.id}>
            <button className="lista-hijos__item" onClick={() => onSeleccionar(elemento.id)}>
              <span className="item__texto">
                <strong>{elemento.etiqueta ?? elemento.codigo}</strong>
                <small>
                  {elemento.tipo_nombre} · {elemento.codigo}
                </small>
              </span>
            </button>
            <button className="boton boton--secundario" onClick={() => restaurar(elemento)}>
              Restaurar
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
