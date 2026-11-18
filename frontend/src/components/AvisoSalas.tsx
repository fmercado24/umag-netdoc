/**
 * En qué va la lectura de las salas del plano con OCR (ver
 * backend/app/servicios/lectura_recintos.py). Con ellas, el N° de recinto de cada
 * elemento lo ubica en su sala, con la nomenclatura que trae el plano.
 */

import { useState } from 'react'

import type { Plano } from '../types'

interface Props {
  plano: Plano
  /** Pide leerlas de nuevo; sin él no se ofrece. */
  onLeerSalas?: () => Promise<void>
}

export function AvisoSalas({ plano, onLeerSalas }: Props) {
  const [cerrado, setCerrado] = useState<number | null>(null)
  const [pidiendo, setPidiendo] = useState(false)
  const estado = plano.lectura_recintos
  if (estado === null || cerrado === plano.id) return null
  if (estado === 'lista' && plano.cantidad_recintos > 0) return null

  const leer = () => {
    if (!onLeerSalas) return
    setPidiendo(true)
    onLeerSalas().finally(() => setPidiendo(false))
  }

  if (estado === 'pendiente' || estado === 'leyendo') {
    return (
      <div className="aviso-salas" role="status">
        <span className="aviso-salas__giro" aria-hidden="true" />
        <span>
          <strong>Leyendo las salas del plano…</strong> Toma alrededor de un minuto. Después, el N°
          de recinto de cada elemento lo ubica en su sala.
        </span>
      </div>
    )
  }

  const puedeReintentar = estado === 'fallida' || estado === 'sin_ocr'
  const aviso = plano.lectura_aviso ?? 'No se pudieron leer las salas del plano'
  return (
    <div className="aviso-salas aviso-salas--alerta" role="status">
      <span>
        {/[.!?]$/.test(aviso) ? aviso : `${aviso}.`}
        {estado !== 'lista' && ' Mientras tanto, ubica los elementos con un clic.'}
      </span>
      {puedeReintentar && onLeerSalas && (
        <button className="boton boton--secundario" onClick={leer} disabled={pidiendo}>
          {pidiendo ? 'Pidiendo…' : 'Leer las salas'}
        </button>
      )}
      <button
        className="aviso-salas__cerrar"
        onClick={() => setCerrado(plano.id)}
        aria-label="Cerrar aviso"
      >
        ×
      </button>
    </div>
  )
}
