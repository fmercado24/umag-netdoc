/**
 * Carga de los planos de un edificio vacío (sin planos ni elementos).
 *
 * Cada archivo debe llamarse según la nomenclatura: su nombre dice a qué piso y
 * tramo va. Se revisa antes de subirlo y, si no la sigue, se rechaza y se dice
 * cómo debería llamarse. Los aceptados quedan en espera; al confirmar se crean de
 * una vez los pisos y tramos que nombran (ver backend/app/servicios/carga_planos.py).
 */

import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'

import { api } from '../api/cliente'
import { erroresDelServidor } from './camposFormulario'
import type { CargaConfirmada, CargaDePlanos as Estado } from '../types'

interface Props {
  edificio: string
  onCerrar: () => void
  onConfirmada: (resultado: CargaConfirmada) => void
}

/** Lo que pasó con cada archivo de la última selección. */
interface Fila {
  archivo: string
  estado: 'subiendo' | 'aceptado' | 'rechazado'
  /** El destino si se aceptó; por qué no, si se rechazó. */
  texto: string
  sugerencia?: string | null
}

const tamano = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`

export function CargaDePlanos({ edificio, onCerrar, onConfirmada }: Props) {
  const [estado, setEstado] = useState<Estado | null>(null)
  const [filas, setFilas] = useState<Fila[]>([])
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const recargar = () =>
    api
      .cargaDePlanos(edificio)
      .then(setEstado)
      .catch((e) => setError(erroresDelServidor(e).general))

  useEffect(() => {
    void recargar()
    // recargar solo depende del edificio
  }, [edificio])

  const actualizarFila = (archivo: string, cambio: Partial<Fila>) =>
    setFilas((todas) => todas.map((f) => (f.archivo === archivo ? { ...f, ...cambio } : f)))

  const elegir = async (evento: ChangeEvent<HTMLInputElement>) => {
    const archivos = Array.from(evento.target.files ?? [])
    evento.target.value = '' // para poder volver a elegir el mismo archivo
    if (archivos.length === 0) return
    setError(null)
    setOcupado(true)
    setFilas(archivos.map((a) => ({ archivo: a.name, estado: 'subiendo', texto: 'Revisando…' })))
    try {
      // Primero solo los nombres: lo mal nombrado se rechaza sin subirlo.
      const { revisados } = await api.cargaDePlanos(
        edificio,
        archivos.map((a) => a.name),
      )
      for (const [i, archivo] of archivos.entries()) {
        const revision = revisados[i]
        if (revision.error) {
          actualizarFila(archivo.name, {
            estado: 'rechazado',
            texto: revision.error,
            sugerencia: revision.sugerencia,
          })
          continue
        }
        actualizarFila(archivo.name, { texto: `Subiendo… (${tamano(archivo.size)})` })
        try {
          const pendiente = await api.subirPlanoPendiente(edificio, archivo)
          actualizarFila(archivo.name, { estado: 'aceptado', texto: pendiente.destino })
        } catch (e) {
          actualizarFila(archivo.name, {
            estado: 'rechazado',
            texto: erroresDelServidor(e).general ?? 'No se pudo subir',
          })
        }
      }
    } catch (e) {
      setError(erroresDelServidor(e).general)
    } finally {
      setOcupado(false)
      void recargar()
    }
  }

  const quitar = (nombre: string) => {
    setError(null)
    api
      .quitarPlanoPendiente(edificio, nombre)
      .then(recargar)
      .catch((e) => setError(erroresDelServidor(e).general))
  }

  const pendientes = estado?.pendientes ?? []
  const pisosNuevos = [...new Set(pendientes.map((p) => p.piso))]
  const tramosNuevos = pendientes.filter((p) => p.tramo).map((p) => `${p.piso}-${p.tramo}`)

  const confirmar = () => {
    setError(null)
    setOcupado(true)
    api
      .confirmarCargaDePlanos(edificio)
      .then(onConfirmada)
      .catch((e) => {
        setError(erroresDelServidor(e).general)
        void recargar()
      })
      .finally(() => setOcupado(false))
  }

  return (
    <section className="panel-detalle">
      <header className="detalle__cabecera">
        <div>
          <span className="detalle__tipo">Edificio {edificio}</span>
          <h2 className="detalle__titulo">Cargar planos</h2>
        </div>
        <div className="detalle__botones">
          <button className="boton-cerrar" onClick={onCerrar} aria-label="Cerrar sin cargar">
            ×
          </button>
        </div>
      </header>

      {error && <p className="formulario__aviso">{error}</p>}
      {estado && !estado.permitida && (
        <p className="formulario__aviso" role="alert">
          {estado.motivo}
        </p>
      )}

      {estado && (
        <div className="formulario">
          <h3 className="subtitulo">Cómo deben llamarse</h3>
          <p className="formulario__ayuda">
            El nombre de cada archivo dice a qué piso y tramo va: <code>{estado.nomenclatura}</code>.
            El piso lleva dos dígitos y el tramo, ninguno de más. Solo se aceptan SVG.
          </p>
          <table className="nomenclatura">
            <tbody>
              {estado.ejemplos.map((e) => (
                <tr key={e.nombre}>
                  <td>
                    <code>{e.nombre}</code>
                  </td>
                  <td>{e.destino}</td>
                </tr>
              ))}
              <tr className="nomenclatura__unico">
                <td>
                  <code>{estado.unico}</code>
                </td>
                <td>Si el edificio tiene un único plano</td>
              </tr>
            </tbody>
          </table>

          {estado.permitida && (
            <>
              <h3 className="subtitulo">Planos</h3>
              <label className="boton boton--secundario selector-archivos">
                {ocupado ? 'Subiendo…' : 'Elegir archivos SVG…'}
                <input
                  type="file"
                  accept=".svg,image/svg+xml"
                  multiple
                  disabled={ocupado}
                  onChange={(e) => void elegir(e)}
                />
              </label>

              {filas.some((f) => f.estado !== 'aceptado') && (
                <ul className="carga__filas" aria-live="polite">
                  {filas
                    .filter((f) => f.estado !== 'aceptado')
                    .map((f) => (
                      <li key={f.archivo} className={`carga__fila carga__fila--${f.estado}`}>
                        <strong>{f.archivo}</strong>
                        <span>{f.texto}</span>
                        {f.sugerencia && (
                          <span>
                            Debe llamarse <code>{f.sugerencia}</code>
                          </span>
                        )}
                      </li>
                    ))}
                </ul>
              )}

              {pendientes.length === 0 ? (
                <p className="vacio">Todavía no hay planos en espera.</p>
              ) : (
                <ul className="carga__pendientes">
                  {pendientes.map((p) => (
                    <li key={p.nombre}>
                      <span className="carga__marca" aria-hidden="true">
                        ✓
                      </span>
                      <span className="carga__texto">
                        <strong>{p.destino}</strong>
                        <small>
                          {p.nombre} · {p.ancho_px} × {p.alto_px} · {tamano(p.bytes)}
                        </small>
                      </span>
                      <button
                        type="button"
                        className="boton-enlace"
                        onClick={() => quitar(p.nombre)}
                        disabled={ocupado}
                      >
                        Quitar
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {pendientes.length > 0 && (
                <p className="formulario__ayuda">
                  Se crearán los pisos {pisosNuevos.join(', ')}
                  {tramosNuevos.length > 0 && ` y los tramos ${tramosNuevos.join(', ')}`}, si aún no
                  existen. Después, los planos de este edificio se agregan o reemplazan desde la
                  terminal (guía de edificio nuevo, sección 4).
                </p>
              )}
            </>
          )}

          <div className="formulario__acciones">
            <button
              type="button"
              className="boton boton--secundario"
              onClick={onCerrar}
              disabled={ocupado}
            >
              {estado.permitida ? 'Cancelar' : 'Cerrar'}
            </button>
            {estado.permitida && (
              <button
                type="button"
                className="boton"
                onClick={confirmar}
                disabled={ocupado || pendientes.length === 0}
              >
                {pendientes.length === 1 ? 'Cargar 1 plano' : `Cargar ${pendientes.length} planos`}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
