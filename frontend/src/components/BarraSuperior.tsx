/** Selector de edificio, piso y tramo, más la búsqueda libre. */

import logoUmag from '../assets/logo-umag.png'
import type { Edificio, Piso } from '../types'

interface Props {
  edificios: Edificio[]
  edificioSel: string
  pisos: Piso[]
  pisoSel: string
  tramoSel: string
  busqueda: string
  onEdificio: (codigo: string) => void
  onPiso: (codigo: string) => void
  onTramo: (codigo: string) => void
  onBusqueda: (texto: string) => void
}

export function BarraSuperior({
  edificios,
  edificioSel,
  pisos,
  pisoSel,
  tramoSel,
  busqueda,
  onEdificio,
  onPiso,
  onTramo,
  onBusqueda,
}: Props) {
  const edificio = edificios.find((e) => e.codigo === edificioSel)
  const piso = pisos.find((p) => p.codigo === pisoSel)
  const planos = piso?.planos_vigentes ?? []
  const planoDelPiso = planos.some((p) => p.tramo_codigo === null)
  // Un tramo sin lámina propia se ve sobre el plano del piso completo.
  const tramoConPlano = (codigo: string) =>
    planoDelPiso || planos.some((p) => p.tramo_codigo === codigo)

  return (
    <header className="barra-superior">
      <div className="marca">
        <span className="marca__sigla">NetDoc</span>
        <span className="marca__sub">Infraestructura de red · UMAG</span>
      </div>

      <div className="controles">
        <label className="campo campo--edificio">
          <span>Edificio</span>
          <select value={edificioSel} onChange={(e) => onEdificio(e.target.value)}>
            {edificios.map((e) => (
              <option key={e.codigo} value={e.codigo}>
                {e.codigo} — {e.nombre}
              </option>
            ))}
          </select>
        </label>

        <label className="campo">
          <span>Piso</span>
          <select
            value={pisoSel}
            onChange={(e) => onPiso(e.target.value)}
            disabled={pisos.length === 0}
          >
            {pisos.length === 0 && <option value="">Sin pisos registrados</option>}
            {pisos.map((p) => (
              <option key={p.codigo} value={p.codigo}>
                {p.codigo}
                {p.nombre ? ` — ${p.nombre}` : ''}
                {p.planos_vigentes.length > 0 ? '' : ' (sin plano)'}
              </option>
            ))}
          </select>
        </label>

        <label className="campo">
          <span>Tramo</span>
          <select
            value={tramoSel}
            onChange={(e) => onTramo(e.target.value)}
            disabled={!piso || piso.tramos.length === 0}
          >
            <option value="">
              Todo el piso
              {planoDelPiso || planos.length === 0 ? '' : ' (lámina por tramo)'}
            </option>
            {piso?.tramos.map((t) => (
              <option key={t.codigo} value={t.codigo}>
                {t.codigo}
                {t.nombre ? ` — ${t.nombre}` : ''}
                {tramoConPlano(t.codigo) ? '' : ' (sin plano)'}
              </option>
            ))}
          </select>
        </label>

        <label className="campo campo--crece">
          <span>Buscar</span>
          <input
            type="search"
            value={busqueda}
            placeholder="Código, etiqueta, modelo, IP…"
            onChange={(e) => onBusqueda(e.target.value)}
          />
        </label>
      </div>

      <div className="institucion">
        <img className="institucion__logo" src={logoUmag} alt="Universidad de Magallanes" />
        {edificio?.campus && <div className="campus">Campus {edificio.campus}</div>}
      </div>
    </header>
  )
}
