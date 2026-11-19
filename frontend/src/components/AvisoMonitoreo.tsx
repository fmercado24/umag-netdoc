/**
 * Las herramientas de monitoreo que dejaron de informar (requisito RNF5): sus
 * avisos llegan solo cuando algo cambia, así que su silencio no prueba que la
 * red esté bien. Ver backend/app/servicios/latidos.py.
 */

import type { MonitoreoSinLatido } from '../types'

function hace(minutos: number): string {
  if (minutos < 120) return `${minutos} minutos`
  const horas = Math.floor(minutos / 60)
  if (horas < 48) return `${horas} horas`
  return `${Math.floor(horas / 24)} días`
}

interface Props {
  fuentes: MonitoreoSinLatido[]
}

export function AvisoMonitoreo({ fuentes }: Props) {
  if (!fuentes.length) return null
  const lista = fuentes.map((f) => `${f.nombre} no informa desde hace ${hace(f.minutos)}`).join('; ')
  return (
    <div className="franja-alerta" role="status">
      <span>
        <strong>{lista}.</strong> El estado operativo de los elementos puede no estar al día.
      </span>
    </div>
  )
}
