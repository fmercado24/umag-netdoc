/** Pide confirmación y motivo antes de eliminar un elemento (baja lógica, SOP sección 8.5). */

import { useState } from 'react'
import type { FormEvent } from 'react'

import { api } from '../api/cliente'
import { Campo, erroresDelServidor, leerUsuario, recordarUsuario } from './camposFormulario'
import type { ElementoDetalle } from '../types'

interface Props {
  detalle: ElementoDetalle
  onCancelar: () => void
  onEliminado: (eliminado: ElementoDetalle) => void
}

export function ConfirmarEliminacion({ detalle, onCancelar, onEliminado }: Props) {
  const [motivo, setMotivo] = useState('')
  const [usuario, setUsuario] = useState(leerUsuario)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const conectados = detalle.hijos.filter((h) => !h.montado)

  const enviar = async (evento: FormEvent) => {
    evento.preventDefault()
    if (guardando) return
    setError(null)
    if (usuario.trim()) recordarUsuario(usuario.trim())
    setGuardando(true)
    try {
      onEliminado(
        await api.eliminar(detalle.id, motivo.trim() || undefined, usuario.trim() || undefined),
      )
    } catch (e) {
      setError(erroresDelServidor(e).general)
      setGuardando(false)
    }
  }

  return (
    <form className="formulario" onSubmit={enviar}>
      <h3 className="subtitulo">Eliminar {detalle.codigo}</h3>
      <p className="formulario__ayuda">
        Sale del plano y de los listados. Su historial se conserva, su código no se vuelve a usar y
        se puede restaurar desde «Ver eliminados».
      </p>
      {conectados.length > 0 && (
        <div className="traslado">
          <p className="traslado__titulo">
            Siguen en su lugar, pero dejan de estar conectados ({conectados.length}):
          </p>
          <ul className="traslado__lista">
            {conectados.map((h) => (
              <li key={h.id}>{h.codigo}</li>
            ))}
          </ul>
        </div>
      )}
      {error && <p className="formulario__aviso">{error}</p>}
      <Campo etiqueta="Motivo" ayuda="Queda en su historial.">
        <input
          type="text"
          value={motivo}
          placeholder="Ej.: Equipo retirado por falla"
          onChange={(e) => setMotivo(e.target.value)}
          autoFocus
        />
      </Campo>
      <Campo etiqueta="Registrado por">
        <input type="text" value={usuario} onChange={(e) => setUsuario(e.target.value)} />
      </Campo>
      <div className="formulario__acciones">
        <button
          type="button"
          className="boton boton--secundario"
          onClick={onCancelar}
          disabled={guardando}
        >
          Cancelar
        </button>
        <button type="submit" className="boton boton--peligro-fuerte" disabled={guardando}>
          {guardando ? 'Eliminando…' : 'Eliminar'}
        </button>
      </div>
    </form>
  )
}
