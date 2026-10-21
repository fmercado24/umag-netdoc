/**
 * Ficha del elemento seleccionado.
 *
 * Los atributos específicos se rotulan con las definiciones que entrega
 * `/catalogo/tipos/<código>/ficha`: el panel no conoce de antemano los campos
 * de ningún tipo, así que un tipo nuevo cargado en el catálogo se muestra
 * correctamente sin tocar este componente.
 */

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { urlMedia } from '../api/cliente'
import type {
  DefinicionAtributo,
  ElementoDetalle,
  Enumeraciones,
  ElementoHijo,
  HistorialEntrada,
  Tramo,
} from '../types'
import { FormularioElemento } from './FormularioElemento'
import { VistaRack } from './VistaRack'

interface Props {
  detalle: ElementoDetalle
  ficha: DefinicionAtributo[]
  historial: HistorialEntrada[] | null
  /** Por qué no se puede ubicar en la lámina a la vista; nulo si se puede. */
  bloqueoPosicion: string | null
  /** Para elegir la lámina donde se dibuja, que puede no ser la de su tramo. */
  tramosDelPiso: Tramo[]
  onCambiarLamina: (codigoTramo: string) => void
  /** Opciones de estado, condición y criticidad para el formulario de edición. */
  enumeraciones: Enumeraciones | null
  onGuardado: (actualizado: ElementoDetalle) => void
  onCerrar: () => void
  onPosicionar: () => void
  /** Lo lleva al recinto de su número (ver backend/app/servicios/recintos.py). */
  onUbicarEnRecinto: () => void
  onPedirHistorial: () => void
  onSeleccionarCodigo: (codigo: string) => void
}

function Dato({ etiqueta, valor }: { etiqueta: string; valor: ReactNode }) {
  return (
    <div className="dato">
      <dt>{etiqueta}</dt>
      <dd>{valor ?? <span className="vacio">sin dato</span>}</dd>
    </div>
  )
}

function numeroOVacio(valor: unknown): number | null {
  return typeof valor === 'number' && valor > 0 ? valor : null
}

function ListaHijos({
  titulo,
  nota,
  hijos,
  onSeleccionarCodigo,
}: {
  titulo: string
  nota?: string
  hijos: ElementoHijo[]
  onSeleccionarCodigo: (codigo: string) => void
}) {
  return (
    <>
      <h3 className="subtitulo">
        {titulo} ({hijos.length})
      </h3>
      {nota && <p className="nota-seccion">{nota}</p>}
      <ul className="lista-hijos">
        {hijos.map((hijo) => (
          <li key={hijo.id}>
            <button className="lista-hijos__item" onClick={() => onSeleccionarCodigo(hijo.codigo)}>
              <span className="item__punto" style={{ background: hijo.color_estado }} />
              <span className="item__texto">
                <strong>{hijo.etiqueta ?? hijo.codigo}</strong>
                <small>
                  {hijo.tipo_nombre} · {hijo.codigo}
                </small>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

function formatearValor(valor: unknown, definicion?: DefinicionAtributo): string {
  if (valor === null || valor === undefined || valor === '') return '—'
  if (typeof valor === 'boolean') return valor ? 'Sí' : 'No'
  if (Array.isArray(valor)) return valor.join(', ')
  const texto = String(valor)
  return definicion?.unidad ? `${texto} ${definicion.unidad}` : texto
}

export function PanelDetalle({
  detalle,
  ficha,
  historial,
  bloqueoPosicion,
  tramosDelPiso,
  onCambiarLamina,
  enumeraciones,
  onGuardado,
  onCerrar,
  onPosicionar,
  onUbicarEnRecinto,
  onPedirHistorial,
  onSeleccionarCodigo,
}: Props) {
  const [verHistorial, setVerHistorial] = useState(false)
  const [editando, setEditando] = useState(false)
  const completitud = detalle.completitud
  const montados = detalle.hijos.filter((h) => h.montado)
  const conectados = detalle.hijos.filter((h) => !h.montado)
  // Dónde lo ubica el sistema: un rack, sobre su rótulo en la lámina
  // («RACK 08», clave R08); el resto, en el recinto de su número.
  const recinto = detalle.recinto_en_plano
  const sobreRotuloDeRack = recinto !== null && /^R\d{2,3}$/.test(recinto.numero)
  const nombreDelRecinto = recinto && !sobreRotuloDeRack ? recinto.nombre : null
  // Tiene número, pero ese número no está rotulado en las láminas del piso.
  const recintoNoEncontrado = detalle.numero_recinto !== null && recinto === null

  const cambiarLamina = (codigo: string) => {
    const aviso = 'Cambiar la lámina borra su posición actual en el plano. ¿Continuar?'
    if (detalle.pos_x !== null && !window.confirm(aviso)) return
    onCambiarLamina(codigo)
  }

  // Se pide también cuando el historial se invalida con el panel abierto
  // (p. ej. tras mover el elemento), no solo al desplegarlo. onPedirHistorial
  // queda fuera de las dependencias porque cambia en cada render del padre.
  useEffect(() => {
    if (verHistorial && historial === null) onPedirHistorial()
  }, [verHistorial, historial])

  const alternarHistorial = () => setVerHistorial((v) => !v)

  return (
    <section className="panel-detalle">
      <header className="detalle__cabecera">
        <div>
          <span className="detalle__tipo">{detalle.tipo_nombre}</span>
          <h2>{detalle.codigo}</h2>
          {detalle.etiqueta && <p className="detalle__etiqueta">{detalle.etiqueta}</p>}
        </div>
        <div className="detalle__botones">
          {!editando && (
            <button className="boton-editar" onClick={() => setEditando(true)}>
              Editar
            </button>
          )}
          <button className="boton-cerrar" onClick={onCerrar} aria-label="Cerrar ficha">
            ×
          </button>
        </div>
      </header>

      {editando ? (
        <FormularioElemento
          detalle={detalle}
          ficha={ficha}
          enumeraciones={enumeraciones}
          onCancelar={() => setEditando(false)}
          onGuardado={(actualizado) => {
            setEditando(false)
            onGuardado(actualizado)
          }}
        />
      ) : (
        <>
          <div className="insignias">
            <span className="insignia" style={{ background: detalle.color_estado }}>
              {detalle.estado_operativo.replace('_', ' ')}
            </span>
            {detalle.estado_condicion && (
              <span className="insignia insignia--suave">{detalle.estado_condicion}</span>
            )}
            {detalle.criticidad && (
              <span className="insignia insignia--suave">criticidad {detalle.criticidad}</span>
            )}
          </div>

          {completitud && (
            <div className="completitud">
              <div className="completitud__barra">
                <div
                  className="completitud__relleno"
                  style={{ width: `${completitud.porcentaje}%` }}
                />
              </div>
              <p>
                Ficha {completitud.porcentaje}% completa ({completitud.completos} de{' '}
                {completitud.total_obligatorios} atributos obligatorios)
              </p>
              {!completitud.completo && (
                <details className="faltantes">
                  <summary>Ver {completitud.faltantes.length} pendientes</summary>
                  <ul>
                    {completitud.faltantes.map((f) => (
                      <li key={f.clave}>{f.etiqueta}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}

          {detalle.montado && detalle.padre_codigo ? (
            <div className="acciones">
              <button
                className="boton boton--secundario"
                onClick={() => onSeleccionarCodigo(detalle.padre_codigo as string)}
              >
                Ver {detalle.padre_codigo}
              </button>
              <small className="nota">
                Está montado ahí: se ubica en el plano a través de su contenedor.
              </small>
            </div>
          ) : (
            <div className="acciones">
              <div className="acciones__botones">
                <button
                  className="boton"
                  onClick={onPosicionar}
                  disabled={bloqueoPosicion !== null}
                >
                  {detalle.pos_x === null ? 'Ubicar en el plano' : 'Mover en el plano'}
                </button>
                {recinto && (
                  <button
                    className="boton boton--secundario"
                    onClick={onUbicarEnRecinto}
                    title="Lo deja donde lo indica la lámina"
                  >
                    {sobreRotuloDeRack
                      ? `Ubicar sobre su rótulo (${recinto.nombre ?? recinto.numero})`
                      : `Ubicar en su recinto (${recinto.numero})`}
                  </button>
                )}
              </div>
              {bloqueoPosicion && <small className="nota">{bloqueoPosicion}</small>}
              {recintoNoEncontrado && (
                <small className="nota">
                  El recinto {detalle.numero_recinto} no aparece en las láminas de este piso:
                  corrige el número (Editar) o ubícalo a mano.
                </small>
              )}
              {!detalle.numero_recinto && !recinto && (
                <small className="nota">
                  Sin número de recinto: complétalo (Editar) y se ubicará solo en su sala.
                </small>
              )}
            </div>
          )}

          {detalle.tipo_codigo === 'R' && (
            <>
              <h3 className="subtitulo">Equipos montados ({montados.length})</h3>
              <VistaRack
                equipos={montados}
                unidadesTotales={numeroOVacio(detalle.atributos.unidades_totales)}
                onSeleccionar={onSeleccionarCodigo}
              />
            </>
          )}

          {detalle.tipo_codigo !== 'R' && montados.length > 0 && (
            <ListaHijos
              titulo="Contenido"
              hijos={montados}
              onSeleccionarCodigo={onSeleccionarCodigo}
            />
          )}

          {conectados.length > 0 && (
            <ListaHijos
              titulo="Conectados a este rack"
              nota="Se ubican en el plano donde realmente están."
              hijos={conectados}
              onSeleccionarCodigo={onSeleccionarCodigo}
            />
          )}

          <h3 className="subtitulo">Ubicación</h3>
          <dl className="datos">
            <Dato etiqueta="Edificio" valor={detalle.edificio_codigo} />
            <Dato etiqueta="Piso" valor={detalle.piso_codigo} />
            <Dato etiqueta="Tramo" valor={detalle.tramo_codigo} />
            <Dato
              etiqueta="Lámina"
              valor={
                detalle.montado ? (
                  `la de ${detalle.padre_codigo}`
                ) : tramosDelPiso.length > 1 ? (
                  <select
                    className="selector-lamina"
                    value={detalle.tramo_lamina_codigo ?? ''}
                    onChange={(e) => cambiarLamina(e.target.value)}
                    aria-label="Lámina donde se dibuja"
                  >
                    {!detalle.tramo_lamina_codigo && <option value="">—</option>}
                    {tramosDelPiso.map((t) => (
                      <option key={t.codigo} value={t.codigo}>
                        Tramo {t.codigo.replace(/^T/, '')}
                        {t.codigo === detalle.tramo_codigo ? ' (el de su código)' : ''}
                      </option>
                    ))}
                  </select>
                ) : (
                  detalle.tramo_lamina_codigo
                )
              }
            />
            <Dato etiqueta="Ubicación" valor={detalle.ubicacion_descriptiva} />
            <Dato
              etiqueta="Recinto"
              valor={
                detalle.numero_recinto &&
                (nombreDelRecinto
                  ? `${detalle.numero_recinto} · ${nombreDelRecinto}`
                  : detalle.numero_recinto)
              }
            />
            <Dato
              etiqueta="Coordenadas"
              valor={
                detalle.montado
                  ? `las de ${detalle.padre_codigo}`
                  : detalle.pos_x !== null && detalle.pos_y !== null
                    ? `${detalle.pos_x}, ${detalle.pos_y}`
                    : null
              }
            />
            {detalle.padre_codigo && (
              <Dato
                etiqueta={detalle.montado ? 'Montado en' : 'Conectado a'}
                valor={
                  <button
                    className="boton-enlace"
                    onClick={() => onSeleccionarCodigo(detalle.padre_codigo as string)}
                  >
                    {detalle.padre_codigo}
                  </button>
                }
              />
            )}
            {detalle.montado && <Dato etiqueta="Unidad de rack" valor={detalle.unidad_rack} />}
          </dl>

          <h3 className="subtitulo">Equipo</h3>
          <dl className="datos">
            <Dato etiqueta="Marca" valor={detalle.marca} />
            <Dato etiqueta="Modelo" valor={detalle.modelo} />
            <Dato etiqueta="N° de serie" valor={detalle.numero_serie} />
            <Dato etiqueta="MAC" valor={detalle.direccion_mac} />
            <Dato etiqueta="IP de gestión" valor={detalle.direccion_ip} />
            <Dato etiqueta="Instalación" valor={detalle.fecha_instalacion} />
            <Dato etiqueta="Último levantamiento" valor={detalle.fecha_ultimo_levantamiento} />
            <Dato etiqueta="Responsable" valor={detalle.responsable_nombre} />
          </dl>

          {ficha.length > 0 && (
            <>
              <h3 className="subtitulo">Ficha de {detalle.tipo_nombre.toLowerCase()}</h3>
              <dl className="datos">
                {ficha.map((definicion) => (
                  <Dato
                    key={definicion.clave}
                    etiqueta={definicion.etiqueta + (definicion.obligatorio ? ' *' : '')}
                    valor={
                      definicion.clave in detalle.atributos
                        ? formatearValor(detalle.atributos[definicion.clave], definicion)
                        : null
                    }
                  />
                ))}
              </dl>
            </>
          )}

          {detalle.vlans.length > 0 && (
            <>
              <h3 className="subtitulo">VLANs</h3>
              <ul className="lista-simple">
                {detalle.vlans.map((vlan) => (
                  <li key={`${vlan.numero}-${vlan.rol}`}>
                    <strong>VLAN {vlan.numero}</strong> {vlan.nombre}
                    {vlan.subred && <span className="vacio"> · {vlan.subred}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}

          {detalle.externos.length > 0 && (
            <>
              <h3 className="subtitulo">En otros sistemas</h3>
              <ul className="lista-simple">
                {detalle.externos.map((externo) => (
                  <li key={externo.sistema}>
                    <strong>{externo.sistema}</strong>{' '}
                    {externo.url ? (
                      <a href={externo.url} target="_blank" rel="noreferrer">
                        {externo.id_externo}
                      </a>
                    ) : (
                      externo.id_externo
                    )}
                    {externo.sincronizado_en && (
                      <span className="vacio">
                        {' '}
                        · sincronizado {new Date(externo.sincronizado_en).toLocaleString('es-CL')}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {detalle.observaciones && (
            <>
              <h3 className="subtitulo">Observaciones</h3>
              <p className="observaciones">{detalle.observaciones}</p>
            </>
          )}

          {detalle.fotografias.length > 0 && (
            <>
              <h3 className="subtitulo">Evidencia fotográfica</h3>
              <div className="galeria">
                {detalle.fotografias.map((foto) => (
                  <a key={foto.id} href={urlMedia(foto.archivo)} target="_blank" rel="noreferrer">
                    <img src={urlMedia(foto.archivo)} alt={foto.descripcion ?? detalle.codigo} />
                  </a>
                ))}
              </div>
            </>
          )}

          <h3 className="subtitulo">
            <button className="boton-enlace" onClick={alternarHistorial}>
              {verHistorial ? 'Ocultar historial' : 'Ver historial de cambios'}
            </button>
          </h3>
          {verHistorial && (
            <ul className="historial">
              {historial === null && <li className="vacio">Cargando…</li>}
              {historial?.length === 0 && <li className="vacio">Sin cambios registrados.</li>}
              {historial?.map((entrada) => (
                <li key={entrada.id}>
                  <span className="historial__fecha">
                    {new Date(entrada.registrado_en).toLocaleString('es-CL')}
                  </span>
                  <span className="historial__campo">{entrada.campo}</span>
                  <span className="historial__origen">{entrada.origen}</span>
                  {entrada.campo !== 'alta' && (
                    <span className="historial__valores">
                      {entrada.valor_anterior ?? '∅'} → {entrada.valor_nuevo ?? '∅'}
                    </span>
                  )}
                  {(entrada.usuario || entrada.comentario) && (
                    <span className="historial__nota">
                      {[entrada.usuario, entrada.comentario].filter(Boolean).join(' · ')}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
