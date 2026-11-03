/**
 * Visor del plano de piso.
 *
 * El plano se monta como capa base de un mapa Leaflet con CRS.Simple, de modo
 * que las coordenadas del sistema son directamente las unidades del plano: no
 * hay proyección geográfica de por medio. Leaflet mide la latitud hacia
 * arriba y los planos numeran el eje Y hacia abajo, así que la conversión se
 * concentra en `aLatLng` / `aCoordenadas`: la esquina superior izquierda del
 * plano es el origen y la lámina ocupa latitudes negativas. Así la grilla de
 * teselas de Leaflet, que parte del origen, calza con la de la pirámide.
 *
 * La lámina se muestra con sus teselas cuando existen: un SVG de CAD tiene
 * cientos de miles de trazos y, como imagen única, el navegador los vuelve a
 * dibujar cada vez que se mueve o acerca el plano.
 */

import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect } from 'react'
import {
  ImageOverlay,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet'

import { urlMedia } from '../api/cliente'
import { colorDelGrupo } from '../arbol'
import type { Nodo, NodoGrupo } from '../arbol'
import type { ElementoMapa, Plano } from '../types'

export function aLatLng(x: number, y: number): L.LatLngTuple {
  return [-y, x]
}

export function aCoordenadas(punto: L.LatLng): { x: number; y: number } {
  return {
    x: Math.round(punto.lng * 100) / 100,
    y: Math.round(-punto.lat * 100) / 100,
  }
}

function limitesDe(plano: Plano): L.LatLngBoundsLiteral {
  return [
    [-plano.alto_px, 0],
    [0, plano.ancho_px],
  ]
}

const ZOOM_MIN = -4
const ZOOM_MAX = 4

/**
 * Con teselas, el acercamiento llega un nivel más allá del más detallado de
 * la pirámide: ahí las teselas se ven al doble, todavía nítidas. Más allá se
 * verían borrosas, y el nivel más detallado ya deja leer los rótulos.
 */
function zoomMaximo(plano: Plano): number {
  return plano.teselas ? Math.min(ZOOM_MAX, plano.teselas.zoom_max + 1) : ZOOM_MAX
}

/** La lámina: sus teselas si ya se generaron o, si no, la imagen original. */
function Lamina({ plano }: { plano: Plano }) {
  const limites = limitesDe(plano)
  const { teselas } = plano
  if (!teselas) return <ImageOverlay url={urlMedia(plano.archivo)} bounds={limites} />
  // El nivel z del visor es el nivel z + zoomOffset de la pirámide; fuera del
  // rango de la pirámide, Leaflet amplía o reduce el nivel más cercano.
  return (
    <TileLayer
      url={urlMedia(teselas.url)}
      tileSize={teselas.tamano}
      zoomOffset={teselas.niveles - 1 - teselas.zoom_max}
      minNativeZoom={teselas.zoom_max - (teselas.niveles - 1)}
      maxNativeZoom={teselas.zoom_max}
      minZoom={ZOOM_MIN}
      maxZoom={zoomMaximo(plano)}
      bounds={limites}
      noWrap
    />
  )
}

/** Los contenedores (racks) se distinguen por la forma y
 * llevan el número de elementos montados que representan. */
function iconoElemento(elemento: ElementoMapa, seleccionado: boolean, montados: number): L.DivIcon {
  const clases = [
    'marcador',
    montados > 0 ? 'marcador--contenedor' : '',
    seleccionado ? 'marcador--activo' : '',
  ]
    .filter(Boolean)
    .join(' ')
  const conteo = montados > 0 ? `<span class="marcador__conteo">${montados}</span>` : ''
  return L.divIcon({
    className: 'marcador-envoltorio',
    html: `<span class="${clases}" style="--color-marcador:${elemento.color_estado}">${elemento.tipo_codigo}${conteo}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  })
}

/** Varios puntos de datos en el mismo lugar: un marcador con cuántos son. */
function iconoGrupo(grupo: NodoGrupo, seleccionado: boolean): L.DivIcon {
  const clases = ['marcador', 'marcador--grupo', seleccionado ? 'marcador--activo' : '']
    .filter(Boolean)
    .join(' ')
  return L.divIcon({
    className: 'marcador-envoltorio',
    html: `<span class="${clases}" style="--color-marcador:${colorDelGrupo(grupo.miembros)}">PD<span class="marcador__conteo">${grupo.miembros.length}</span></span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  })
}

function AjustarVista({ plano }: { plano: Plano }) {
  const mapa = useMap()
  useEffect(() => {
    const limites = limitesDe(plano)
    mapa.setMaxBounds(L.latLngBounds(limites).pad(0.25))
    mapa.fitBounds(limites)
  }, [mapa, plano.id, plano.alto_px, plano.ancho_px])
  return null
}

/**
 * Leaflet solo escucha el `resize` de la ventana. Al abrirse o cerrarse la
 * ficha lateral cambia el ancho del visor y, sin avisarle, el plano queda
 * descentrado y tapado por la ficha.
 */
function SeguirTamano() {
  const mapa = useMap()
  useEffect(() => {
    const observador = new ResizeObserver(() => mapa.invalidateSize())
    observador.observe(mapa.getContainer())
    return () => observador.disconnect()
  }, [mapa])
  return null
}

function CapturadorClic({
  activo,
  onPosicionar,
}: {
  activo: boolean
  onPosicionar: (x: number, y: number) => void
}) {
  useMapEvents({
    click(evento) {
      if (!activo) return
      const { x, y } = aCoordenadas(evento.latlng)
      onPosicionar(x, y)
    },
  })
  return null
}

interface Props {
  plano: Plano | null
  /** El piso tiene láminas por tramo aunque la vista actual no muestre ninguna. */
  hayLaminasPorTramo: boolean
  /** Solo lo que lleva marcador propio; lo montado va dentro de su nodo. */
  nodos: Nodo[]
  /** Elemento seleccionado: resalta el grupo de puntos de datos que lo contiene. */
  seleccionadoId: number | null
  /** El seleccionado o, si está montado, su contenedor: resalta ese marcador. */
  contenedorSeleccionadoId: number | null
  posicionando: ElementoMapa | null
  onSeleccionar: (elemento: ElementoMapa) => void
  onPosicionar: (x: number, y: number) => void
  onCancelarPosicion: () => void
}

export function VisorPlano({
  plano,
  hayLaminasPorTramo,
  nodos,
  seleccionadoId,
  contenedorSeleccionadoId,
  posicionando,
  onSeleccionar,
  onPosicionar,
  onCancelarPosicion,
}: Props) {
  if (!plano && hayLaminasPorTramo) {
    return (
      <div className="visor visor--vacio">
        <div className="mensaje-vacio">
          <h2>Este piso tiene una lámina por tramo</h2>
          <p>
            Elige un tramo en la barra superior para ver su plano y ubicar sus elementos.
          </p>
          <p className="mensaje-vacio__nota">
            Mientras tanto, el listado lateral muestra todos los elementos del piso.
          </p>
        </div>
      </div>
    )
  }

  if (!plano) {
    return (
      <div className="visor visor--vacio">
        <div className="mensaje-vacio">
          <h2>Este piso todavía no tiene plano cargado</h2>
          <p>
            Súbelo con <code>POST /api/v1/edificios/&lt;CÓDIGO&gt;/pisos/&lt;PISO&gt;/plano</code>{' '}
            indicando el archivo y sus dimensiones, más el <code>tramo</code> si la lámina cubre
            solo uno. Esas dimensiones fijan el sistema de coordenadas en que se guardará la
            posición de cada elemento.
          </p>
          <p className="mensaje-vacio__nota">
            Mientras tanto, los elementos del piso siguen consultables en el listado lateral.
          </p>
        </div>
      </div>
    )
  }

  const limites = limitesDe(plano)
  const posicionandoPD = posicionando?.tipo_codigo === 'PD'

  /**
   * Clic sobre un marcador. Mientras se ubica un elemento, el clic lo ubica
   * ahí mismo; si es un punto de datos soltado sobre otro, toma exactamente
   * su posición para que ambos formen un grupo.
   */
  const alClicEnMarcador =
    (x: number, y: number, esPD: boolean, alternativa: () => void) =>
    (evento: L.LeafletMouseEvent) => {
      if (!posicionando) return alternativa()
      if (esPD && posicionandoPD) return onPosicionar(x, y)
      const punto = aCoordenadas(evento.latlng)
      onPosicionar(punto.x, punto.y)
    }

  return (
    <div className={`visor ${posicionando ? 'visor--posicionando' : ''}`}>
      {posicionando && (
        <div className="aviso-posicionar">
          Haz clic sobre el plano para fijar la posición de{' '}
          <strong>{posicionando.codigo}</strong>
          {posicionandoPD && ', o sobre otro punto de datos para agruparlo con él'}
          <button className="aviso-posicionar__cancelar" onClick={onCancelarPosicion}>
            Ahora no
          </button>
        </div>
      )}
      <MapContainer
        key={plano.id}
        crs={L.CRS.Simple}
        bounds={limites}
        minZoom={ZOOM_MIN}
        maxZoom={zoomMaximo(plano)}
        zoomSnap={0.25}
        attributionControl={false}
        className="mapa"
      >
        <AjustarVista plano={plano} />
        <SeguirTamano />
        <CapturadorClic activo={Boolean(posicionando)} onPosicionar={onPosicionar} />
        <Lamina plano={plano} />

        {nodos.map((nodo) => {
          if (nodo.tipo === 'grupo') {
            const recintos = [
              ...new Set(nodo.miembros.map((m) => m.ubicacion_descriptiva).filter(Boolean)),
            ].join(', ')
            return (
              <Marker
                key={nodo.clave}
                position={aLatLng(nodo.pos_x, nodo.pos_y)}
                icon={iconoGrupo(nodo, nodo.miembros.some((m) => m.id === seleccionadoId))}
                eventHandlers={{ click: alClicEnMarcador(nodo.pos_x, nodo.pos_y, true, () => {}) }}
              >
                <Tooltip direction="top" offset={[0, -18]}>
                  {recintos && (
                    <>
                      <strong>{recintos}</strong>
                      <br />
                    </>
                  )}
                  {nodo.miembros.length} puntos de datos · clic para verlos
                </Tooltip>
                {/* Mientras se ubica algo, el clic ubica: no abre la lista. */}
                {!posicionando && (
                  <Popup className="globo-grupo">
                    <strong className="globo-grupo__titulo">
                      {nodo.miembros.length} puntos de datos
                    </strong>
                    {recintos && <small className="globo-grupo__recinto">{recintos}</small>}
                    <ul className="lista-hijos">
                      {nodo.miembros.map((miembro) => (
                        <li key={miembro.id}>
                          <button
                            className={`lista-hijos__item ${miembro.id === seleccionadoId ? 'item--activo' : ''}`}
                            onClick={() => onSeleccionar(miembro)}
                          >
                            <span className="item__punto" style={{ background: miembro.color_estado }} />
                            <span className="item__texto">
                              <strong>{miembro.codigo}</strong>
                              <small>{miembro.etiqueta}</small>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </Popup>
                )}
              </Marker>
            )
          }

          const { elemento, totalHijos } = nodo
          // Una posición sobre la lámina de otro tramo no corresponde a esta
          // imagen, y un montado suelto (su rack está en otra lámina) no tiene
          // coordenadas propias.
          if (!elemento.ubicado || elemento.montado) return null
          const x = elemento.pos_x as number
          const y = elemento.pos_y as number
          return (
            <Marker
              key={nodo.clave}
              position={aLatLng(x, y)}
              icon={iconoElemento(elemento, elemento.id === contenedorSeleccionadoId, totalHijos)}
              eventHandlers={{
                click: alClicEnMarcador(x, y, elemento.tipo_codigo === 'PD', () =>
                  onSeleccionar(elemento),
                ),
              }}
            >
              <Tooltip direction="top" offset={[0, -18]}>
                <strong>{elemento.codigo}</strong>
                <br />
                {elemento.etiqueta ?? elemento.tipo_nombre}
                {elemento.ubicacion_descriptiva && (
                  <>
                    <br />
                    {elemento.ubicacion_descriptiva}
                  </>
                )}
                {totalHijos > 0 && (
                  <>
                    <br />
                    {totalHijos} {totalHijos === 1 ? 'equipo montado' : 'equipos montados'}
                  </>
                )}
              </Tooltip>
            </Marker>
          )
        })}
      </MapContainer>
    </div>
  )
}
