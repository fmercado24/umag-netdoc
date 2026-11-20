/**
 * Importar el levantamiento de un edificio subiendo sus planillas CSV.
 *
 * Cada archivo debe llamarse según la nomenclatura: su nombre dice qué trae y, en
 * las de equipamiento, a qué piso y tramo va. Al elegirlos se ensaya la importación
 * completa sin guardar nada, y el informe dice qué se crearía, qué se corrigió y qué
 * quedaría sin ubicar. Lo mal nombrado se rechaza diciendo cómo debería llamarse.
 * Recién al confirmar se importa (ver backend/app/servicios/carga_planillas.py).
 */

import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'

import { api } from '../api/cliente'
import { erroresDelServidor, leerUsuario } from './camposFormulario'
import type { CargaDePlanillas as Estado, InformeCargaPlanillas } from '../types'

interface Props {
  edificio: string
  onCerrar: () => void
  onImportada: (informe: InformeCargaPlanillas) => void
}

/** Cuántas advertencias se muestran antes de pedir «ver todas». */
const ADVERTENCIAS_VISIBLES = 12

export const plural = (n: number, uno: string, varios: string) => `${n} ${n === 1 ? uno : varios}`

/**
 * «4 equipos, 120 puntos de datos y 3 VLANs», vacío si no hay nada nuevo, y si es
 * una sola cosa («1 VLAN»), para concordar el verbo.
 */
export function conteo(informe: InformeCargaPlanillas): { texto: string; uno: boolean } {
  const i = informe.importado
  if (!i) return { texto: '', uno: false }
  const partes = [
    i.pisos > 0 && plural(i.pisos, 'piso', 'pisos'),
    i.tramos > 0 && plural(i.tramos, 'tramo', 'tramos'),
    i.equipos > 0 && plural(i.equipos, 'equipo', 'equipos'),
    i.puntos > 0 && plural(i.puntos, 'punto de datos', 'puntos de datos'),
    i.enlaces > 0 && plural(i.enlaces, 'enlace', 'enlaces'),
    i.vlans > 0 && plural(i.vlans, 'VLAN', 'VLANs'),
  ].filter(Boolean) as string[]
  const total = i.pisos + i.tramos + i.equipos + i.puntos + i.enlaces + i.vlans
  const ultima = partes.pop()
  const texto = partes.length > 0 ? `${partes.join(', ')} y ${ultima}` : (ultima ?? '')
  return { texto, uno: total === 1 }
}

export function CargaDePlanillas({ edificio, onCerrar, onImportada }: Props) {
  const [estado, setEstado] = useState<Estado | null>(null)
  const [archivos, setArchivos] = useState<File[]>([])
  const [informe, setInforme] = useState<InformeCargaPlanillas | null>(null)
  const [todas, setTodas] = useState(false)
  const [ocupado, setOcupado] = useState<'revisando' | 'importando' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .cargaDePlanillas(edificio)
      .then(setEstado)
      .catch((e) => setError(erroresDelServidor(e).general))
  }, [edificio])

  /** Ensaya con la selección: nada se guarda. */
  const revisar = (seleccion: File[]) => {
    setArchivos(seleccion)
    setInforme(null)
    setTodas(false)
    setError(null)
    if (seleccion.length === 0) return
    setOcupado('revisando')
    api
      .subirPlanillas(edificio, seleccion, true)
      .then(setInforme)
      .catch((e) => setError(erroresDelServidor(e).general))
      .finally(() => setOcupado(null))
  }

  /** Lo elegido se suma a lo anterior; un archivo con el mismo nombre lo reemplaza. */
  const elegir = (evento: ChangeEvent<HTMLInputElement>) => {
    const nuevos = Array.from(evento.target.files ?? [])
    evento.target.value = '' // para poder volver a elegir el mismo archivo
    if (nuevos.length === 0) return
    const nombres = new Set(nuevos.map((a) => a.name))
    revisar([...archivos.filter((a) => !nombres.has(a.name)), ...nuevos])
  }

  const quitar = (nombre: string) => revisar(archivos.filter((a) => a.name !== nombre))

  const aceptados = new Set(informe?.aceptados.map((a) => a.archivo) ?? [])
  const porImportar = archivos.filter((a) => aceptados.has(a.name))

  const importar = () => {
    setError(null)
    setOcupado('importando')
    api
      .subirPlanillas(edificio, porImportar, false, leerUsuario() || undefined)
      .then(onImportada)
      .catch((e) => setError(erroresDelServidor(e).general))
      .finally(() => setOcupado(null))
  }

  const advertencias = informe?.advertencias ?? []
  const creado = informe ? conteo(informe) : { texto: '', uno: false }
  const motivo = informe?.motivo ?? (estado && !estado.permitida ? estado.motivo : null)

  return (
    <section className="panel-detalle">
      <header className="detalle__cabecera">
        <div>
          <span className="detalle__tipo">Edificio {edificio}</span>
          <h2 className="detalle__titulo">Importar planillas</h2>
        </div>
        <div className="detalle__botones">
          <button className="boton-cerrar" onClick={onCerrar} aria-label="Cerrar sin importar">
            ×
          </button>
        </div>
      </header>

      {error && (
        <p className="formulario__aviso" role="alert">
          {error}
        </p>
      )}
      {motivo && (
        <p className="formulario__aviso" role="alert">
          {motivo}
        </p>
      )}

      {estado && (
        <div className="formulario">
          <p className="formulario__ayuda">
            {estado.modo === 'nuevo'
              ? 'El edificio no tiene elementos: se importa todo lo que traigan las planillas.'
              : 'El edificio ya tiene elementos: se suma solo lo nuevo. Un tramo ya importado se ' +
                'omite, y no se toca lo ubicado ni lo corregido en el visor.'}{' '}
            Cada elemento queda en su sala según la columna <em>Sala del plano</em>; lo que no se
            pueda ubicar queda sin coordenadas, para ubicarlo en el plano.
          </p>

          {/* Plegada cuando ya hay archivos elegidos: así el informe queda a la vista. */}
          <details className="plegable" open={archivos.length === 0}>
            <summary className="subtitulo">Cómo deben llamarse</summary>
            <p className="formulario__ayuda">
              Exporte cada hoja de la plantilla como «CSV UTF-8». El nombre dice qué trae:{' '}
              <code>{estado.nomenclatura}</code> para el equipamiento, con el piso en dos dígitos, y
              un nombre fijo para las demás.
            </p>
            <table className="nomenclatura">
              <tbody>
                {estado.ejemplos.map((e) => (
                  <tr key={e.nombre}>
                    <td>
                      <code>{e.nombre}</code>
                    </td>
                    <td>{e.contenido}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          {estado.guardadas.length > 0 && (
            <>
              <h3 className="subtitulo">Ya guardadas ({estado.guardadas.length})</h3>
              <p className="formulario__ayuda">
                Se usan junto con las que elija; una con el mismo nombre las reemplaza.
              </p>
              <ul className="carga__pendientes">
                {estado.guardadas.map((g) => (
                  <li key={g.nombre}>
                    <span className="carga__texto">
                      <strong>{g.nombre}</strong>
                      <small>{g.contenido}</small>
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <h3 className="subtitulo">Planillas</h3>
          <label className="boton boton--secundario selector-archivos">
            {ocupado === 'revisando'
              ? 'Revisando…'
              : archivos.length > 0
                ? 'Agregar más archivos CSV…'
                : 'Elegir archivos CSV…'}
            <input
              type="file"
              accept=".csv,text/csv"
              multiple
              disabled={ocupado !== null}
              onChange={elegir}
            />
          </label>

          {informe && (
            <ul className="carga__filas" aria-live="polite">
              {informe.rechazados.map((r) => (
                <li key={r.archivo} className="carga__fila carga__fila--rechazado">
                  <strong>{r.archivo}</strong>
                  <span>{r.error}</span>
                  {r.sugerencia && (
                    <span>
                      Debe llamarse <code>{r.sugerencia}</code>
                    </span>
                  )}
                  <button
                    type="button"
                    className="boton-enlace"
                    onClick={() => quitar(r.archivo)}
                    disabled={ocupado !== null}
                  >
                    Quitar
                  </button>
                </li>
              ))}
            </ul>
          )}
          {informe && informe.aceptados.length > 0 && (
            <ul className="carga__pendientes">
              {informe.aceptados.map((a) => (
                <li key={a.archivo}>
                  <span className="carga__marca" aria-hidden="true">
                    ✓
                  </span>
                  <span className="carga__texto">
                    <strong>{a.nombre}</strong>
                    <small>{a.contenido}</small>
                  </span>
                  <button
                    type="button"
                    className="boton-enlace"
                    onClick={() => quitar(a.archivo)}
                    disabled={ocupado !== null}
                  >
                    Quitar
                  </button>
                </li>
              ))}
            </ul>
          )}

          {informe?.importado && (
            <div className="informe-planillas" aria-live="polite">
              <h3 className="subtitulo">Revisión: así quedaría</h3>
              <p>
                {creado.texto ? (
                  <>
                    {creado.uno ? 'Se crearía' : 'Se crearían'} <strong>{creado.texto}</strong>.
                  </>
                ) : (
                  'No se crearía nada nuevo.'
                )}
                {informe.ubicados > 0 &&
                  ` ${plural(informe.ubicados, 'elemento quedaría', 'elementos quedarían')} en su sala.`}
                {informe.sin_ubicar > 0 &&
                  ` ${plural(
                    informe.sin_ubicar,
                    'elemento quedaría sin ubicar, para ubicarlo',
                    'elementos quedarían sin ubicar, para ubicarlos',
                  )} en el plano.`}{' '}
                Nada se ha guardado todavía.
              </p>
              {informe.guardadas.length > 0 && (
                <p className="formulario__ayuda">
                  Con las ya guardadas: {informe.guardadas.join(', ')}.
                </p>
              )}
              {informe.omitidas.length > 0 && (
                <p className="formulario__ayuda">Se omiten: {informe.omitidas.join(', ')}.</p>
              )}
              {informe.puntos_existentes > 0 && (
                <p className="formulario__ayuda">
                  {plural(informe.puntos_existentes, 'punto de datos ya existía', 'puntos de datos ya existían')}{' '}
                  y no se repiten.
                </p>
              )}
              {informe.racks_completados.length > 0 && (
                <p className="formulario__ayuda">
                  Racks completados con su planilla: {informe.racks_completados.join(', ')}.
                </p>
              )}
              {informe.racks_inferidos.length > 0 && (
                <p className="formulario__ayuda">
                  Racks nombrados en los rótulos pero sin fila propia, que se crearían para
                  verificarlos en terreno: {informe.racks_inferidos.join(', ')}.
                </p>
              )}
              {informe.levantamiento && (
                <p className="formulario__ayuda">Levantamiento: {informe.levantamiento}.</p>
              )}
              {informe.ubicacion.length > 0 && (
                <>
                  <h4 className="informe-planillas__titulo">Ubicación en los planos</h4>
                  <ul className="informe-planillas__lista">
                    {informe.ubicacion.map((linea, i) => (
                      <li key={i}>{linea.trim().replace(/^- /, '')}</li>
                    ))}
                  </ul>
                </>
              )}
              {advertencias.length > 0 && (
                <>
                  <h4 className="informe-planillas__titulo">
                    Para revisar en las planillas ({advertencias.length})
                  </h4>
                  <ul className="informe-planillas__lista">
                    {(todas ? advertencias : advertencias.slice(0, ADVERTENCIAS_VISIBLES)).map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                  {advertencias.length > ADVERTENCIAS_VISIBLES && (
                    <button type="button" className="boton-enlace" onClick={() => setTodas(!todas)}>
                      {todas ? 'Ver menos' : `Ver las ${advertencias.length}`}
                    </button>
                  )}
                </>
              )}
            </div>
          )}

          <div className="formulario__acciones">
            <button
              type="button"
              className="boton boton--secundario"
              onClick={onCerrar}
              disabled={ocupado === 'importando'}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="boton"
              onClick={importar}
              disabled={ocupado !== null || !informe?.importado || Boolean(motivo) || porImportar.length === 0}
              title={motivo ?? undefined}
            >
              {ocupado === 'importando'
                ? 'Importando…'
                : informe && informe.rechazados.length > 0
                  ? porImportar.length === 1
                    ? 'Importar la aceptada'
                    : `Importar las ${porImportar.length} aceptadas`
                  : `Importar ${plural(porImportar.length, 'planilla', 'planillas')}`}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
