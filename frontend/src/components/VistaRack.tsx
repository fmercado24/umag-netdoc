/**
 * Vista frontal del rack con sus equipos montados.
 *
 * La API los entrega en el orden en que se ven: de arriba hacia abajo según
 * la U cuando se conoce y, si no, agrupados por tipo (switches, routers,
 * servidores, patch panels…). Hoy ninguna planilla del CADI trae la U, así
 * que el alto de cada equipo es uniforme salvo que su ficha declare
 * `unidades_rack`.
 */

import type { CSSProperties } from 'react'

import type { ElementoHijo } from '../types'

interface Props {
  equipos: ElementoHijo[]
  unidadesTotales: number | null
  onSeleccionar: (codigo: string) => void
}

export function VistaRack({ equipos, unidadesTotales, onSeleccionar }: Props) {
  return (
    <div className="rack">
      <div className="rack__cabecera">
        <span>Vista frontal</span>
        <span>
          {equipos.length} {equipos.length === 1 ? 'equipo' : 'equipos'}
          {unidadesTotales ? ` · ${unidadesTotales}U` : ''}
        </span>
      </div>

      <div className="rack__cuerpo">
        {equipos.length === 0 && <p className="rack__vacio">Sin equipos montados registrados.</p>}
        {equipos.map((equipo) => (
          <button
            key={equipo.id}
            className="rack__equipo"
            style={
              {
                '--color-tipo': equipo.color_tipo ?? '#64748B',
                '--alto-u': equipo.alto_u ?? 1,
              } as CSSProperties
            }
            onClick={() => onSeleccionar(equipo.codigo)}
            title={`${equipo.tipo_nombre} · ${equipo.codigo}`}
          >
            <span className="rack__tipo">{equipo.tipo_codigo}</span>
            <span className="rack__texto">
              <strong>{equipo.etiqueta ?? equipo.codigo}</strong>
              <small>
                {[equipo.marca, equipo.modelo].filter(Boolean).join(' ') || equipo.tipo_nombre}
              </small>
            </span>
            {equipo.unidad_rack !== null && (
              <span className="rack__u">
                U{equipo.unidad_rack}
                {equipo.alto_u && equipo.alto_u > 1 ? `·${equipo.alto_u}U` : ''}
              </span>
            )}
            <span
              className="rack__estado"
              style={{ background: equipo.color_estado }}
              title={equipo.estado_operativo.replace('_', ' ')}
            />
          </button>
        ))}
      </div>
    </div>
  )
}
