/**
 * Traslado a otro piso o tramo del mismo edificio.
 *
 * El código dice dónde está el elemento, así que cambia con él: la API muestra
 * antes de confirmar cuál le tocará y qué más se mueve o se desconecta (ver
 * backend/app/servicios/traslados.py).
 */

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { api, ErrorApi, ESTADO_CAMBIO_AJENO } from '../api/cliente'
import {
  Campo,
  erroresDelServidor,
  leerUsuario,
  recordarUsuario,
  SIN_RACK,
  SOLO_CONECTADOS,
} from './camposFormulario'
import type { Elemento, ElementoDetalle, Piso, PrevioTraslado, Recinto } from '../types'

interface Props {
  detalle: ElementoDetalle
  pisos: Piso[]
  onCancelar: () => void
  onTrasladado: (trasladado: ElementoDetalle) => void
  /** Otra persona lo modificó mientras se preparaba el traslado: no se hizo. */
  onCambioAjeno: () => void
}

export function FormularioTraslado({
  detalle,
  pisos,
  onCancelar,
  onTrasladado,
  onCambioAjeno,
}: Props) {
  const [codigoPiso, setCodigoPiso] = useState(detalle.piso_codigo)
  const [codigoTramo, setCodigoTramo] = useState(detalle.tramo_codigo ?? '')
  const [ubicacion, setUbicacion] = useState(detalle.ubicacion_descriptiva ?? '')
  const [recinto, setRecinto] = useState(detalle.numero_recinto ?? '')
  const [rack, setRack] = useState(detalle.padre_codigo ?? '')
  const [unidad, setUnidad] = useState(detalle.unidad_rack?.toString() ?? '')
  const [usuario, setUsuario] = useState(leerUsuario)
  const [comentario, setComentario] = useState('')

  const [previo, setPrevio] = useState<PrevioTraslado | null>(null)
  const [racks, setRacks] = useState<Elemento[]>([])
  const [recintos, setRecintos] = useState<Recinto[]>([])
  const [errores, setErrores] = useState<Record<string, string>>({})
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  const edificio = detalle.edificio_codigo
  const piso = pisos.find((p) => p.codigo === codigoPiso)
  const tramos = piso?.tramos ?? []
  const mismoPiso = codigoPiso === detalle.piso_codigo
  const hayCambio = !mismoPiso || codigoTramo !== (detalle.tramo_codigo ?? '')
  const admiteRack = !SIN_RACK.has(detalle.tipo_codigo)
  const soloConectado = SOLO_CONECTADOS.has(detalle.tipo_codigo)

  /** Su rack sigue valiendo si no sale de ahí, o si solo está conectado y sigue en el piso. */
  const elegirDestino = (piso_: string, tramo: string) => {
    const mismo = piso_ === detalle.piso_codigo
    const quedaEnSuTramo = mismo && tramo === (detalle.tramo_codigo ?? '')
    const sigueEnElRack = quedaEnSuTramo || (mismo && soloConectado)
    setCodigoPiso(piso_)
    setCodigoTramo(tramo)
    setRack(sigueEnElRack ? (detalle.padre_codigo ?? '') : '')
    setUnidad(sigueEnElRack ? (detalle.unidad_rack?.toString() ?? '') : '')
  }

  const cambiarPiso = (codigo: string) => {
    elegirDestino(codigo, pisos.find((p) => p.codigo === codigo)?.tramos[0]?.codigo ?? '')
    // La sala y su número son de un piso: al volver al suyo, reaparecen.
    const suyo = codigo === detalle.piso_codigo
    setUbicacion(suyo ? (detalle.ubicacion_descriptiva ?? '') : '')
    setRecinto(suyo ? (detalle.numero_recinto ?? '') : '')
    if (suyo) setCodigoTramo(detalle.tramo_codigo ?? '')
  }

  useEffect(() => {
    setPrevio(null)
    setErrores({})
    setErrorGeneral(null)
    if (!hayCambio) return
    let vigente = true
    api
      .previoTraslado(detalle.id, codigoPiso, codigoTramo || undefined)
      .then((r) => vigente && setPrevio(r))
      .catch((e) => vigente && setErrorGeneral(erroresDelServidor(e).general))
    return () => {
      vigente = false
    }
  }, [detalle.id, codigoPiso, codigoTramo, hayCambio])

  useEffect(() => {
    let vigente = true
    api
      .recintos(edificio, codigoPiso)
      .then((lista) => vigente && setRecintos(lista))
      .catch(() => vigente && setRecintos([]))
    if (admiteRack) {
      api
        .racks(edificio, codigoPiso)
        .then((lista) => vigente && setRacks(lista))
        .catch(() => vigente && setRacks([]))
    }
    return () => {
      vigente = false
    }
  }, [edificio, codigoPiso, admiteRack])

  // Montado en un rack, está donde esté el rack; conectado, basta con el piso.
  const racksPosibles = racks.filter(
    (r) => soloConectado || (r.tramo_codigo ?? '') === codigoTramo,
  )

  const armar = (): { datos: Record<string, unknown>; errores: Record<string, string> } => {
    const encontrados: Record<string, string> = {}
    const datos: Record<string, unknown> = { piso: codigoPiso }
    if (codigoTramo) datos.tramo = codigoTramo
    if (usuario.trim()) datos.usuario = usuario.trim()
    if (comentario.trim()) datos.comentario = comentario.trim()

    // En su piso, lo que no se tocó se deja como está; en otro, vale lo escrito.
    const lugar = ubicacion.trim()
    if (!mismoPiso || lugar !== (detalle.ubicacion_descriptiva ?? '')) {
      datos.ubicacion_descriptiva = lugar || null
    }
    const numero = recinto.trim()
    if (!mismoPiso || numero !== (detalle.numero_recinto ?? '')) {
      datos.numero_recinto = numero || null
    }

    if (admiteRack) {
      datos.padre_codigo = rack || null
      if (rack && !soloConectado && unidad.trim()) {
        const valor = Number(unidad.trim())
        if (!Number.isInteger(valor) || valor < 1) {
          encontrados.unidad_rack = 'debe ser un número entero desde 1'
        } else {
          datos.unidad_rack = valor
        }
      }
    }
    return { datos, errores: encontrados }
  }

  const enviar = async (evento: FormEvent) => {
    evento.preventDefault()
    if (!previo?.codigo_nuevo || guardando) return
    const { datos, errores: locales } = armar()
    setErrores(locales)
    setErrorGeneral(null)
    if (Object.keys(locales).length > 0) return
    if (usuario.trim()) recordarUsuario(usuario.trim())

    setGuardando(true)
    try {
      onTrasladado(await api.trasladar(detalle.id, datos, detalle.version))
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === ESTADO_CAMBIO_AJENO) onCambioAjeno()
      const { porCampo, general } = erroresDelServidor(e)
      setErrores(porCampo)
      setErrorGeneral(
        general ?? (Object.keys(porCampo).length ? 'Revisa los campos marcados.' : null),
      )
    } finally {
      setGuardando(false)
    }
  }

  return (
    <form className="formulario" onSubmit={enviar}>
      <h3 className="subtitulo">Cambiar piso o tramo</h3>
      <div className="formulario__fila">
        <Campo etiqueta="Piso" error={errores.piso}>
          <select value={codigoPiso} onChange={(e) => cambiarPiso(e.target.value)} autoFocus>
            {pisos.map((p) => (
              <option key={p.codigo} value={p.codigo}>
                {p.codigo}
                {p.nombre ? ` — ${p.nombre}` : ''}
              </option>
            ))}
          </select>
        </Campo>
        <Campo etiqueta="Tramo" error={errores.tramo}>
          <select
            value={codigoTramo}
            onChange={(e) => elegirDestino(codigoPiso, e.target.value)}
            disabled={tramos.length === 0}
          >
            {tramos.length === 0 && <option value="">Este piso no tiene</option>}
            {tramos.length > 0 && !codigoTramo && <option value="">— Sin tramo —</option>}
            {tramos.map((t) => (
              <option key={t.codigo} value={t.codigo}>
                {t.codigo}
                {t.nombre ? ` — ${t.nombre}` : ''}
              </option>
            ))}
          </select>
        </Campo>
      </div>

      {!hayCambio && <p className="formulario__ayuda">Elige el piso o tramo al que se trasladó.</p>}
      {previo?.conflicto && <p className="formulario__aviso">{previo.conflicto}</p>}
      {previo?.codigo_nuevo && (
        <div className="traslado" role="status">
          <p className="formulario__codigo">
            Su código pasará a ser <strong>{previo.codigo_nuevo}</strong>
          </p>
          <p className="formulario__ayuda">
            Si lleva el código anterior en su rótulo físico, hay que cambiarlo. {detalle.codigo}{' '}
            queda reservado y sigue llevando a este elemento.
          </p>
          {previo.arrastrados.length > 0 && (
            <>
              <p className="traslado__titulo">
                Se trasladan con él, porque están montados ({previo.arrastrados.length}):
              </p>
              <ul className="traslado__lista">
                {previo.arrastrados.map((a) => (
                  <li key={a.codigo_actual}>
                    {a.codigo_actual} → <strong>{a.codigo_nuevo}</strong>
                  </li>
                ))}
              </ul>
            </>
          )}
          {previo.desconectados.length > 0 && (
            <>
              <p className="traslado__titulo">
                Se quedan en este piso y dejan de estar conectados ({previo.desconectados.length}):
              </p>
              <ul className="traslado__lista">
                {previo.desconectados.map((codigo) => (
                  <li key={codigo}>{codigo}</li>
                ))}
              </ul>
            </>
          )}
          {previo.pierde_rack && detalle.padre_codigo && (
            <p className="formulario__ayuda">
              Saldrá de {detalle.padre_codigo}: su rack se queda donde está.
            </p>
          )}
          {detalle.pos_x !== null && (
            <p className="formulario__ayuda">
              {previo.conserva_posicion
                ? 'Se dibuja en la misma lámina: su marcador queda donde está. Muévelo si cambió de sitio.'
                : 'Su marcador se borra: habrá que ubicarlo en la lámina del destino.'}
            </p>
          )}
        </div>
      )}
      {errorGeneral && <p className="formulario__aviso">{errorGeneral}</p>}

      {hayCambio && previo?.codigo_nuevo && (
        <>
          <Campo etiqueta="Ubicación (recinto)" error={errores.ubicacion_descriptiva}>
            <input
              type="text"
              value={ubicacion}
              placeholder="Ej.: Oficina 1083"
              onChange={(e) => setUbicacion(e.target.value)}
            />
          </Campo>
          <Campo
            etiqueta="N° de recinto"
            error={errores.numero_recinto}
            ayuda="Con el número de una sala del plano, queda ubicado ahí. Sin él, podrás marcarlo con un clic."
          >
            <input
              type="text"
              inputMode="decimal"
              list="recintos-traslado"
              value={recinto}
              placeholder="Ej.: 1083"
              onChange={(e) => setRecinto(e.target.value)}
            />
            <datalist id="recintos-traslado">
              {recintos.map((r) => (
                <option key={`${r.plano_id}-${r.numero}`} value={r.numero}>
                  {r.nombre ?? ''}
                </option>
              ))}
            </datalist>
          </Campo>
          {admiteRack && (
            <Campo
              etiqueta="Rack"
              error={errores.padre_codigo}
              ayuda={
                soloConectado
                  ? 'Un AP o una UPS solo se conecta al rack y tiene su propio marcador.'
                  : 'Los racks del destino. Montado en uno, se ve a través de él en el plano.'
              }
            >
              <select value={rack} onChange={(e) => setRack(e.target.value)}>
                <option value="">— Sin rack —</option>
                {racksPosibles.map((r) => (
                  <option key={r.codigo} value={r.codigo}>
                    {r.etiqueta ? `${r.codigo} · ${r.etiqueta}` : r.codigo}
                  </option>
                ))}
              </select>
            </Campo>
          )}
          {admiteRack && rack !== '' && !soloConectado && (
            <Campo etiqueta="Unidad de rack (U)" error={errores.unidad_rack}>
              <input
                type="text"
                inputMode="numeric"
                value={unidad}
                placeholder="Ej.: 12"
                onChange={(e) => setUnidad(e.target.value)}
              />
            </Campo>
          )}
          <Campo etiqueta="Comentario" error={errores.comentario} ayuda="Queda en su historial.">
            <input
              type="text"
              value={comentario}
              placeholder="Ej.: Remodelación del segundo piso"
              onChange={(e) => setComentario(e.target.value)}
            />
          </Campo>
          <Campo etiqueta="Registrado por" error={errores.usuario}>
            <input type="text" value={usuario} onChange={(e) => setUsuario(e.target.value)} />
          </Campo>
        </>
      )}

      <div className="formulario__acciones">
        <button
          type="button"
          className="boton boton--secundario"
          onClick={onCancelar}
          disabled={guardando}
        >
          Cancelar
        </button>
        <button type="submit" className="boton" disabled={!previo?.codigo_nuevo || guardando}>
          {guardando ? 'Trasladando…' : 'Trasladar'}
        </button>
      </div>
    </form>
  )
}
