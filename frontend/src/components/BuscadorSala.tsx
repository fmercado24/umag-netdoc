/**
 * Buscar la sala de un equipo entre las leídas de las láminas del piso, por su
 * número o por su nombre: cada edificio de la UMAG rotula sus salas a su manera
 * («1083» o «SECRETARÍA RECEPCIÓN» en el CADI, «09» o «Idiomas» en la Biblioteca).
 *
 * Lo que se guarda es el código de la sala elegida. Si se escribe y no se elige,
 * el servidor busca igual (backend/app/servicios/recintos.py, `buscar_sala`): un
 * nombre de varias salas pide elegir una.
 */

import { useId, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'

import type { Recinto } from '../types'

/** Lo que no distingue una sala de otra, como en el servidor. */
const VACIAS = new Set(['DE', 'DEL', 'LA', 'LAS', 'EL', 'LOS', 'Y', 'A', 'EN'])
const MAXIMO = 40

function palabras(texto: string | null | undefined): string[] {
  const base = (texto ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase()
  return (base.match(/[A-Z]+|\d+/g) ?? []).filter((p) => !VACIAS.has(p))
}

/**
 * Casi iguales, como en el servidor: el OCR lee «ADMNISTRATIVA» o «OFIQINA».
 * Distancia de edición de a lo más un 20 % de la palabra más larga.
 */
function casiIguales(una: string, otra: string): boolean {
  if (Math.min(una.length, otra.length) < 4) return false
  let anterior = Array.from({ length: otra.length + 1 }, (_, j) => j)
  for (let i = 1; i <= una.length; i++) {
    const fila = [i]
    for (let j = 1; j <= otra.length; j++) {
      fila[j] = Math.min(anterior[j] + 1, fila[j - 1] + 1, anterior[j - 1] + (una[i - 1] === otra[j - 1] ? 0 : 1))
    }
    anterior = fila
  }
  return anterior[otra.length] <= 0.2 * Math.max(una.length, otra.length)
}

/** «09» y «9» son la misma sala. */
const sinCeros = (codigo: string) => codigo.toUpperCase().replace(/\s+/g, '').replace(/^0+(?=\d)/, '')

function orden(codigo: string): (string | number)[] {
  return codigo.split(/(\d+)/).map((t) => (/^\d+$/.test(t) ? Number(t) : t))
}

function compararCodigos(a: string, b: string): number {
  const x = orden(a)
  const y = orden(b)
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if (x[i] === y[i]) continue
    if (x[i] === undefined) return -1
    if (y[i] === undefined) return 1
    if (typeof x[i] === 'number' && typeof y[i] === 'number') return (x[i] as number) - (y[i] as number)
    return String(x[i]).localeCompare(String(y[i]))
  }
  return 0
}

/** Una por código: la misma sala puede verse en las láminas de dos tramos. */
function salasDelPiso(recintos: Recinto[]): Recinto[] {
  const porCodigo = new Map<string, Recinto>()
  for (const r of recintos) if (!r.es_rack && !porCodigo.has(r.numero)) porCodigo.set(r.numero, r)
  return [...porCodigo.values()].sort((a, b) => compararCodigos(a.numero, b.numero))
}

/**
 * Las salas que calzan con lo escrito, las más probables primero: el código
 * («9» es la 09), luego los que empiezan así y luego por el nombre, con cada
 * palabra escrita al comienzo de una palabra de la sala («of adm»).
 */
function filtrarSalas(salas: Recinto[], texto: string): Recinto[] {
  const escritas = palabras(texto)
  if (!texto.trim()) return salas
  const clave = sinCeros(texto.trim())
  const puntaje = (r: Recinto): number | null => {
    const codigo = sinCeros(r.numero)
    if (codigo === clave) return 0
    if (codigo.startsWith(clave)) return 1
    const suyas = [...palabras(r.nombre), ...palabras(r.numero)]
    const calza = (p: string) =>
      suyas.some((s) =>
        /^\d+$/.test(p) && /^\d+$/.test(s)
          ? sinCeros(s).startsWith(sinCeros(p))
          : s.startsWith(p) || casiIguales(p, s),
      )
    if (!escritas.length || !escritas.every(calza)) return null
    const nombre = palabras(r.nombre)
    return nombre.length === escritas.length ? 2 : 3
  }
  return salas
    .map((r) => [puntaje(r), r] as const)
    .filter((par): par is readonly [number, Recinto] => par[0] !== null)
    .sort((a, b) => a[0] - b[0] || compararCodigos(a[1].numero, b[1].numero))
    .map(([, r]) => r)
}

/** Qué sala es lo escrito, si es una sola: por su código o por su nombre completo. */
function salaEscrita(salas: Recinto[], texto: string): Recinto | null {
  if (!texto.trim()) return null
  const clave = sinCeros(texto.trim())
  const porCodigo = salas.find((r) => sinCeros(r.numero) === clave)
  if (porCodigo) return porCodigo
  const escritas = palabras(texto)
  const mismas = salas.filter((r) => {
    const suyas = palabras(r.nombre)
    return (
      suyas.length === escritas.length &&
      escritas.every((p, i) => p === suyas[i] || casiIguales(p, suyas[i]))
    )
  })
  return mismas.length === 1 ? mismas[0] : null
}

function describirSala(r: Recinto): string {
  return [r.numero, r.nombre].filter(Boolean).join(' · ') + (r.tramo_codigo ? ` (tramo ${r.tramo_codigo})` : '')
}

interface Props {
  recintos: Recinto[]
  valor: string
  onCambiar: (valor: string) => void
  /** Al elegir una sala de la lista, por ejemplo para completar la ubicación. */
  onElegir?: (sala: Recinto) => void
  /** El servidor rechazó lo escrito: el campo se marca. */
  conError?: boolean
}

export function BuscadorSala({ recintos, valor, onCambiar, onElegir, conError }: Props) {
  const idLista = useId()
  const [abierta, setAbierta] = useState(false)
  const [marcada, setMarcada] = useState(0)
  const salas = useMemo(() => salasDelPiso(recintos), [recintos])
  const opciones = useMemo(() => filtrarSalas(salas, valor), [salas, valor])
  const visibles = opciones.slice(0, MAXIMO)
  const elegida = salaEscrita(salas, valor)
  const conNombre = valor.trim() !== '' && /\p{L}/u.test(valor) && !elegida
  const mostrar = abierta && salas.length > 0 && visibles.length > 0

  const elegir = (sala: Recinto) => {
    onCambiar(sala.numero)
    onElegir?.(sala)
    setAbierta(false)
  }

  const alTeclear = (evento: KeyboardEvent<HTMLInputElement>) => {
    if (evento.key === 'ArrowDown') {
      evento.preventDefault()
      setAbierta(true)
      setMarcada((m) => Math.min(m + 1, visibles.length - 1))
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault()
      setMarcada((m) => Math.max(m - 1, 0))
    } else if (evento.key === 'Enter' && mostrar && visibles[marcada]) {
      // Elige la sala en vez de enviar el formulario.
      evento.preventDefault()
      elegir(visibles[marcada])
    } else if (evento.key === 'Escape' && abierta) {
      evento.preventDefault()
      setAbierta(false)
    }
  }

  return (
    <div className="buscador-sala">
      <div className="buscador-sala__control">
        <input
          type="text"
          role="combobox"
          aria-expanded={mostrar}
          aria-controls={idLista}
          aria-autocomplete="list"
          aria-invalid={conError || undefined}
          autoComplete="off"
          value={valor}
          placeholder={salas.length ? 'Nombre o número de la sala' : 'Código de la sala, como en el plano'}
          onChange={(e) => {
            onCambiar(e.target.value)
            setMarcada(0)
            setAbierta(true)
          }}
          onFocus={() => setAbierta(true)}
          onBlur={() => setAbierta(false)}
          onKeyDown={alTeclear}
        />
        {mostrar && (
          <ul className="buscador-sala__lista" id={idLista} role="listbox">
            {visibles.map((sala, i) => (
              <li
                key={sala.numero}
                role="option"
                aria-selected={i === marcada}
                className={i === marcada ? 'buscador-sala__opcion--marcada' : undefined}
                // Antes de que el campo pierda el foco y cierre la lista.
                onMouseDown={(e) => {
                  e.preventDefault()
                  elegir(sala)
                }}
                onMouseEnter={() => setMarcada(i)}
              >
                <strong>{sala.numero}</strong>
                <span>{sala.nombre ?? 'sin nombre en el plano'}</span>
                {sala.tramo_codigo && <small>tramo {sala.tramo_codigo}</small>}
              </li>
            ))}
            {opciones.length > MAXIMO && (
              <li className="buscador-sala__mas" aria-disabled="true">
                … y {opciones.length - MAXIMO} más: escriba más del nombre o el número
              </li>
            )}
          </ul>
        )}
      </div>
      {elegida && <span className="buscador-sala__elegida">En el plano: {describirSala(elegida)}</span>}
      {/* Si el servidor ya respondió, su mensaje va bajo el campo. */}
      {!elegida && !conError && conNombre && salas.length > 0 && opciones.length > 1 && (
        <span className="buscador-sala__aviso">
          {opciones.length} salas calzan con «{valor.trim()}»: elija una de la lista.
        </span>
      )}
      {!elegida && !conError && valor.trim() !== '' && salas.length > 0 && opciones.length === 0 && (
        <span className="buscador-sala__aviso">
          Ninguna sala del plano se llama así. Si es un código que el plano no muestra, se guarda
          igual y el equipo se ubica con un clic.
        </span>
      )}
    </div>
  )
}
