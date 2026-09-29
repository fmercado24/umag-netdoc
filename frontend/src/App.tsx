/** Orquestador del visor: selección de ubicación, filtros, plano y ficha. */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, ErrorApi } from './api/cliente'
import { armarArbol } from './arbol'
import { BarraSuperior } from './components/BarraSuperior'
import { PanelDetalle } from './components/PanelDetalle'
import { PanelLateral } from './components/PanelLateral'
import { VisorPlano } from './components/VisorPlano'
import type {
  DefinicionAtributo,
  Edificio,
  ElementoDetalle,
  ElementoEnMapa,
  ElementoMapa,
  Enumeraciones,
  HistorialEntrada,
  Piso,
  RespuestaMapa,
  TipoElemento,
} from './types'

const EDIFICIO_INICIAL = 'CADI'

/**
 * Vista con la que se abre un piso: el piso completo si tiene plano propio
 * (o ninguno), y si no, el primer tramo con lámina, para no abrir en blanco.
 */
function tramoInicial(piso: Piso | undefined): string {
  return piso?.planos_vigentes[0]?.tramo_codigo ?? ''
}

export default function App() {
  // Catálogo
  const [edificios, setEdificios] = useState<Edificio[]>([])
  const [tipos, setTipos] = useState<TipoElemento[]>([])
  const [enumeraciones, setEnumeraciones] = useState<Enumeraciones | null>(null)

  // Ubicación seleccionada
  const [edificioSel, setEdificioSel] = useState('')
  const [pisos, setPisos] = useState<Piso[]>([])
  const [pisoSel, setPisoSel] = useState('')
  /** Vacío = piso completo. */
  const [tramoSel, setTramoSel] = useState('')
  const [mapa, setMapa] = useState<RespuestaMapa | null>(null)
  const [versionMapa, setVersionMapa] = useState(0)

  // Filtros
  const [busqueda, setBusqueda] = useState('')
  const [tiposActivos, setTiposActivos] = useState<Set<string>>(new Set())
  const [estadosActivos, setEstadosActivos] = useState<Set<string>>(new Set())

  // Selección
  const [detalle, setDetalle] = useState<ElementoDetalle | null>(null)
  const [ficha, setFicha] = useState<DefinicionAtributo[]>([])
  const [historial, setHistorial] = useState<HistorialEntrada[] | null>(null)
  const [posicionando, setPosicionando] = useState<ElementoMapa | null>(null)

  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const reportar = useCallback((e: unknown) => {
    if (e instanceof ErrorApi) setError(`${e.estado}: ${e.message}`)
    else if (e instanceof Error) setError(e.message)
    else setError('Error desconocido')
  }, [])

  // --- Carga inicial del catálogo ---------------------------------------
  useEffect(() => {
    Promise.all([api.edificios(), api.tipos(), api.enumeraciones()])
      .then(([listaEdificios, listaTipos, enums]) => {
        setEdificios(listaEdificios)
        setTipos(listaTipos)
        setEnumeraciones(enums)
        const inicial =
          listaEdificios.find((e) => e.codigo === EDIFICIO_INICIAL)?.codigo ??
          listaEdificios[0]?.codigo ??
          ''
        setEdificioSel(inicial)
      })
      .catch(reportar)
      .finally(() => setCargando(false))
  }, [reportar])

  // --- Pisos del edificio seleccionado -----------------------------------
  // Las respuestas de una selección anterior se descartan: si llegaran tarde
  // pisarían los datos del edificio o piso que el usuario tiene a la vista.
  useEffect(() => {
    if (!edificioSel) return
    let vigente = true
    api
      .pisos(edificioSel)
      .then((lista) => {
        if (!vigente) return
        setPisos(lista)
        setPisoSel(lista[0]?.codigo ?? '')
        setTramoSel(tramoInicial(lista[0]))
      })
      .catch((e) => vigente && reportar(e))
    return () => {
      vigente = false
    }
  }, [edificioSel, reportar])

  // --- Elementos y plano del piso ----------------------------------------
  useEffect(() => {
    if (!edificioSel || !pisoSel) {
      setMapa(null)
      return
    }
    let vigente = true
    api
      .mapa(edificioSel, pisoSel, tramoSel || undefined)
      .then((respuesta) => vigente && setMapa(respuesta))
      .catch((e) => vigente && reportar(e))
    return () => {
      vigente = false
    }
  }, [edificioSel, pisoSel, tramoSel, versionMapa, reportar])

  const recargarMapa = useCallback(() => setVersionMapa((v) => v + 1), [])

  // --- Cambio de ubicación -------------------------------------------------
  // El elemento seleccionado pertenece al piso o tramo anterior: si siguiera
  // activo, "Ubicar en el plano" lo intentaría posicionar sobre otra lámina.
  const limpiarSeleccion = () => {
    setDetalle(null)
    setHistorial(null)
    setPosicionando(null)
  }

  const cambiarEdificio = (codigo: string) => {
    limpiarSeleccion()
    // Sin esto se pediría el mapa del piso anterior en el edificio nuevo.
    setPisos([])
    setPisoSel('')
    setTramoSel('')
    setEdificioSel(codigo)
  }

  const cambiarPiso = (codigo: string) => {
    limpiarSeleccion()
    setPisoSel(codigo)
    setTramoSel(tramoInicial(pisos.find((p) => p.codigo === codigo)))
  }

  const cambiarTramo = (codigo: string) => {
    limpiarSeleccion()
    setTramoSel(codigo)
  }

  const pisoActual = pisos.find((p) => p.codigo === pisoSel)

  // --- Selección ---------------------------------------------------------
  const seleccionar = useCallback(
    (idOCodigo: string | number) => {
      setHistorial(null)
      api
        .elemento(idOCodigo)
        .then((d) => {
          setDetalle(d)
          return api.ficha(d.tipo_codigo)
        })
        .then(setFicha)
        .catch(reportar)
    },
    [reportar],
  )

  const posicionar = useCallback(
    (x: number, y: number) => {
      if (!posicionando || !mapa?.plano) return
      api
        .actualizarPosicion(posicionando.id, { plano_id: mapa.plano.id, pos_x: x, pos_y: y })
        .then((actualizado) => {
          setDetalle(actualizado)
          setHistorial(null) // el cambio de posición agrega entradas al historial
          setPosicionando(null)
          recargarMapa()
        })
        .catch(reportar)
    },
    [posicionando, mapa, recargarMapa, reportar],
  )

  /** Cambia la lámina donde se dibuja el elemento; su posición anterior se borra. */
  const cambiarLamina = useCallback(
    (codigoTramo: string) => {
      if (!detalle) return
      api
        .actualizarElemento(detalle.id, { tramo_lamina: codigoTramo })
        .then((actualizado) => {
          setDetalle(actualizado)
          setHistorial(null)
          recargarMapa()
        })
        .catch(reportar)
    },
    [detalle, recargarMapa, reportar],
  )

  // --- Filtrado en cliente ------------------------------------------------
  const texto = busqueda.trim().toLowerCase()
  const filtroActivo = tiposActivos.size > 0 || estadosActivos.size > 0 || texto !== ''

  const coincide = useCallback(
    (e: ElementoEnMapa) => {
      if (tiposActivos.size > 0 && !tiposActivos.has(e.tipo_codigo)) return false
      if (estadosActivos.size > 0 && !estadosActivos.has(e.estado_operativo)) return false
      if (!texto) return true
      return [
        e.codigo,
        e.etiqueta,
        e.tipo_nombre,
        e.ubicacion_descriptiva,
        e.marca,
        e.modelo,
        e.direccion_ip,
      ]
        .filter(Boolean)
        .some((campo) => (campo as string).toLowerCase().includes(texto))
    },
    [texto, tiposActivos, estadosActivos],
  )

  const arbol = useMemo(
    () => armarArbol(mapa?.elementos ?? [], coincide, filtroActivo),
    [mapa, coincide, filtroActivo],
  )
  const totalCoincidencias = useMemo(
    () => (mapa?.elementos ?? []).filter(coincide).length,
    [mapa, coincide],
  )

  // Un elemento montado se resalta a través del marcador de su contenedor.
  const contenedorSeleccionadoId = detalle
    ? detalle.montado
      ? detalle.padre_id
      : detalle.id
    : null

  const conteoPorTipo = useMemo(() => {
    const conteo = new Map<string, number>()
    for (const elemento of mapa?.elementos ?? []) {
      conteo.set(elemento.tipo_codigo, (conteo.get(elemento.tipo_codigo) ?? 0) + 1)
    }
    return conteo
  }, [mapa])

  // El backend rechaza ubicar un elemento sobre la lámina de otro tramo; la
  // ficha lo explica antes de que el usuario haga clic.
  const bloqueoPosicion = useMemo(() => {
    const plano = mapa?.plano
    if (!plano) return 'Requiere un plano cargado para esta vista.'
    const lamina = detalle?.tramo_lamina_codigo
    if (plano.tramo_codigo && lamina && plano.tramo_codigo !== lamina) {
      return `Se dibuja en la lámina del tramo ${lamina}: elige ese tramo para ubicarlo.`
    }
    return null
  }, [mapa, detalle])

  const alternar = (conjunto: Set<string>, valor: string) => {
    const copia = new Set(conjunto)
    if (copia.has(valor)) copia.delete(valor)
    else copia.add(valor)
    return copia
  }

  if (cargando) {
    return <div className="cargando">Cargando catálogo…</div>
  }

  if (edificios.length === 0) {
    return (
      <div className="cargando">
        <h1>Sin datos</h1>
        <p>
          No hay edificios cargados. Ejecuta en el backend:
          <br />
          <code>python -m app.scripts.cargar_catalogo</code>
        </p>
        {error && <p className="error">{error}</p>}
      </div>
    )
  }

  return (
    <div className="aplicacion">
      <BarraSuperior
        edificios={edificios}
        edificioSel={edificioSel}
        pisos={pisos}
        pisoSel={pisoSel}
        tramoSel={tramoSel}
        busqueda={busqueda}
        onEdificio={cambiarEdificio}
        onPiso={cambiarPiso}
        onTramo={cambiarTramo}
        onBusqueda={setBusqueda}
      />

      {error && (
        <div className="franja-error">
          {error}
          <button className="boton-enlace" onClick={() => setError(null)}>
            cerrar
          </button>
        </div>
      )}

      <main className="cuerpo">
        <PanelLateral
          tipos={tipos}
          enumeraciones={enumeraciones}
          tiposActivos={tiposActivos}
          estadosActivos={estadosActivos}
          titulo={tramoSel ? `Elementos del tramo ${tramoSel}` : 'Elementos del piso'}
          nodos={arbol}
          totalCoincidencias={totalCoincidencias}
          filtroActivo={filtroActivo}
          conteoPorTipo={conteoPorTipo}
          seleccionadoId={detalle?.id ?? null}
          sinPosicionar={mapa?.sin_posicionar ?? 0}
          onAlternarTipo={(codigo) => setTiposActivos((s) => alternar(s, codigo))}
          onAlternarEstado={(valor) => setEstadosActivos((s) => alternar(s, valor))}
          onLimpiar={() => {
            setTiposActivos(new Set())
            setEstadosActivos(new Set())
          }}
          onSeleccionar={(e) => seleccionar(e.id)}
        />

        <VisorPlano
          plano={mapa?.plano ?? null}
          hayLaminasPorTramo={Boolean(pisoActual?.planos_vigentes.some((p) => p.tramo_codigo))}
          nodos={arbol}
          seleccionadoId={detalle?.id ?? null}
          contenedorSeleccionadoId={contenedorSeleccionadoId}
          posicionando={posicionando}
          onSeleccionar={(e) => seleccionar(e.id)}
          onPosicionar={posicionar}
        />

        {detalle && (
          <PanelDetalle
            key={detalle.id}
            detalle={detalle}
            ficha={ficha}
            historial={historial}
            bloqueoPosicion={bloqueoPosicion}
            tramosDelPiso={pisoActual?.tramos ?? []}
            onCambiarLamina={cambiarLamina}
            enumeraciones={enumeraciones}
            onGuardado={(actualizado) => {
              setDetalle(actualizado)
              setHistorial(null) // la edición agrega entradas al historial
              recargarMapa() // etiqueta, estado o rack pueden cambiar el listado
            }}
            onCerrar={() => setDetalle(null)}
            onPosicionar={() => setPosicionando(detalle)}
            onPedirHistorial={() => api.historial(detalle.id).then(setHistorial).catch(reportar)}
            onSeleccionarCodigo={seleccionar}
          />
        )}
      </main>
    </div>
  )
}
