/** Orquestador del visor: selección de ubicación, filtros, plano y ficha. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, ErrorApi, ESTADO_CAMBIO_AJENO } from './api/cliente'
import { armarArbol } from './arbol'
import { BarraSuperior } from './components/BarraSuperior'
import { CargaDePlanos } from './components/CargaDePlanos'
import { FormularioAlta } from './components/FormularioAlta'
import { PanelDetalle } from './components/PanelDetalle'
import { PanelEliminados } from './components/PanelEliminados'
import { PanelLateral } from './components/PanelLateral'
import { leerUsuario } from './components/camposFormulario'
import { VisorPlano } from './components/VisorPlano'
import type {
  CargaConfirmada,
  PlanosQuitados,
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

/** Cada cuánto se pregunta si otra persona cambió algo en el edificio. */
const PAUSA_NOVEDADES_MS = 15_000
/**
 * Sin usar el visor por este tiempo, se deja de preguntar: una pestaña olvidada
 * no carga al servidor, y la sesión vence por inactividad como siempre.
 */
const INACTIVIDAD_MS = 5 * 60_000

/**
 * Vista con la que se abre un piso: el piso completo si tiene plano propio
 * (o ninguno), y si no, el primer tramo con lámina, para no abrir en blanco.
 */
function tramoInicial(piso: Piso | undefined): string {
  return piso?.planos_vigentes[0]?.tramo_codigo ?? ''
}

interface Props {
  usuario: string
  onSalir: () => void
}

export default function App({ usuario, onSalir }: Props) {
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
  const [agregando, setAgregando] = useState(false)
  /** El edificio está vacío y se le pueden cargar planos desde el visor. */
  const [cargaPermitida, setCargaPermitida] = useState(false)
  const [cargandoPlanos, setCargandoPlanos] = useState(false)
  const [versionPisos, setVersionPisos] = useState(0)
  const [aviso, setAviso] = useState<string | null>(null)
  const [viendoEliminados, setViendoEliminados] = useState(false)
  /** Lo último que se eliminó, para poder deshacerlo. */
  const [eliminado, setEliminado] = useState<ElementoDetalle | null>(null)

  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  // --- Lo que hacen las demás personas ---------------------------------------
  /** La versión más nueva del elemento abierto, cuando otra persona lo modificó. */
  const [versionNueva, setVersionNueva] = useState<ElementoDetalle | null>(null)
  const detalleActual = useRef(detalle)
  detalleActual.current = detalle

  /** Va a buscar el elemento abierto: si cambió, la ficha lo muestra o lo avisa. */
  const revisarFicha = useCallback(() => {
    const abierto = detalleActual.current
    if (!abierto) return
    api
      .elemento(abierto.id)
      .then((reciente) => {
        const sigue = detalleActual.current
        if (sigue?.id === reciente.id && sigue.version !== reciente.version) {
          setVersionNueva(reciente)
        }
      })
      .catch(() => {
        /* se volverá a intentar con la próxima novedad */
      })
  }, [])

  const reportar = useCallback(
    (e: unknown) => {
      if (e instanceof ErrorApi) {
        // El mensaje ya lo explica: otra persona lo modificó antes.
        const cambioAjeno = e.estado === ESTADO_CAMBIO_AJENO
        if (cambioAjeno) revisarFicha()
        setError(e.estado && !cambioAjeno ? `${e.estado}: ${e.message}` : e.message)
      } else if (e instanceof Error) setError(e.message)
      else setError('Error desconocido')
    },
    [revisarFicha],
  )

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
        // Sin elementos, sus planos se cargan o se quitan desde el visor.
        setCargaPermitida(false)
        api
          .cargaDePlanos(edificioSel)
          .then((estado) => vigente && setCargaPermitida(estado.permitida))
          .catch(() => vigente && setCargaPermitida(false))
      })
      .catch((e) => vigente && reportar(e))
    return () => {
      vigente = false
    }
  }, [edificioSel, versionPisos, reportar])

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

  // --- Novedades -----------------------------------------------------------
  // Cada plano llega con la marca del edificio en ese momento. Mientras se usa el
  // visor, se pregunta cada tanto por la marca actual, que es barato: si es otra,
  // alguien cambió algo, y recién entonces se piden de nuevo el plano y la ficha.
  const marcaVista = useRef<string | null>(null)
  marcaVista.current = mapa?.marca ?? null
  useEffect(() => {
    if (!edificioSel) return
    let vigente = true
    let ultimoUso = Date.now()

    const revisar = () => {
      if (document.hidden || Date.now() - ultimoUso > INACTIVIDAD_MS) return
      api
        .novedades(edificioSel)
        .then(({ marca }) => {
          if (!vigente || marcaVista.current === null || marca === marcaVista.current) return
          recargarMapa()
          revisarFicha()
        })
        .catch(() => {
          /* sin conexión: lo dirá la próxima acción; una sesión vencida ya pide ingresar */
        })
    }
    const alUsar = () => {
      const dormido = Date.now() - ultimoUso > INACTIVIDAD_MS
      ultimoUso = Date.now()
      if (dormido) revisar()
    }
    const alVolver = () => {
      if (!document.hidden) revisar()
    }

    const reloj = window.setInterval(revisar, PAUSA_NOVEDADES_MS)
    window.addEventListener('pointerdown', alUsar)
    window.addEventListener('keydown', alUsar)
    document.addEventListener('visibilitychange', alVolver)
    return () => {
      vigente = false
      window.clearInterval(reloj)
      window.removeEventListener('pointerdown', alUsar)
      window.removeEventListener('keydown', alUsar)
      document.removeEventListener('visibilitychange', alVolver)
    }
  }, [edificioSel, recargarMapa, revisarFicha])

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
    setAgregando(false)
    setViendoEliminados(false)
    setCargandoPlanos(false)
    setEliminado(null)
    setAviso(null)
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
  const sinPlanos = pisos.every((p) => p.planos_vigentes.length === 0)

  // --- Alta ---------------------------------------------------------------
  const abrirAlta = () => {
    limpiarSeleccion()
    setViendoEliminados(false)
    setCargandoPlanos(false)
    setAgregando(true)
  }

  // --- Planos de un edificio vacío -------------------------------------------
  const abrirCargaDePlanos = () => {
    limpiarSeleccion()
    setAgregando(false)
    setViendoEliminados(false)
    setCargandoPlanos(true)
  }

  const alQuitarPlanos = (resultado: PlanosQuitados) => {
    setCargandoPlanos(false)
    limpiarSeleccion()
    setAviso(
      `Se quitaron ${resultado.planos} plano(s) de ${edificioSel}, con sus pisos y tramos. ` +
        'El edificio volvió a quedar vacío.',
    )
    setVersionPisos((v) => v + 1)
  }

  const alCargarPlanos = (resultado: CargaConfirmada) => {
    setCargandoPlanos(false)
    const partes = [`${resultado.planos.length} plano(s)`]
    if (resultado.pisos.length) partes.push(`${resultado.pisos.length} piso(s)`)
    if (resultado.tramos.length) partes.push(`${resultado.tramos.length} tramo(s)`)
    setAviso(
      `Cargados en ${edificioSel}: ${partes.join(', ')}. Mientras se preparan para moverse con ` +
        'fluidez, el visor muestra las láminas originales.',
    )
    setVersionPisos((v) => v + 1)
  }

  /**
   * Lleva a lo recién creado, trasladado o restaurado; si no quedó en el plano,
   * deja listo marcarlo con un clic.
   */
  const mostrarCreado = (creado: ElementoDetalle) => {
    setAgregando(false)
    setViendoEliminados(false)
    setHistorial(null)
    setDetalle(creado)
    api.ficha(creado.tipo_codigo).then(setFicha).catch(reportar)

    const piso = pisos.find((p) => p.codigo === creado.piso_codigo)
    const tramo = creado.tramo_lamina_codigo ?? creado.tramo_codigo ?? tramoInicial(piso)
    setPisoSel(creado.piso_codigo)
    setTramoSel(tramo)
    recargarMapa()

    const hayLamina = (piso?.planos_vigentes.length ?? 0) > 0
    setPosicionando(hayLamina && !creado.montado && creado.pos_x === null ? creado : null)
  }

  // --- Baja -----------------------------------------------------------------
  const alEliminar = (baja: ElementoDetalle) => {
    limpiarSeleccion()
    setEliminado(baja)
    recargarMapa()
  }

  const restaurar = (elemento: ElementoDetalle) => {
    api
      .restaurar(elemento.id, leerUsuario() || undefined, elemento.version)
      .then((restaurado) => {
        setEliminado(null)
        mostrarCreado(restaurado)
      })
      .catch(reportar)
  }

  // --- Selección ---------------------------------------------------------
  const seleccionar = useCallback(
    (idOCodigo: string | number) => {
      setViendoEliminados(false)
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
        .actualizarPosicion(
          posicionando.id,
          { plano_id: mapa.plano.id, pos_x: x, pos_y: y },
          detalle?.id === posicionando.id ? detalle.version : undefined,
        )
        .then((actualizado) => {
          setDetalle(actualizado)
          setHistorial(null) // el cambio de posición agrega entradas al historial
          setPosicionando(null)
          recargarMapa()
        })
        .catch(reportar)
    },
    [posicionando, mapa, detalle, recargarMapa, reportar],
  )

  /** Lo deja en el recinto de su número; puede quedar en la lámina de otro tramo. */
  const ubicarEnRecinto = useCallback(() => {
    if (!detalle) return
    api
      .ubicarEnRecinto(detalle.id, detalle.version)
      .then((actualizado) => {
        setDetalle(actualizado)
        setHistorial(null)
        setPosicionando(null)
        recargarMapa()
      })
      .catch(reportar)
  }, [detalle, recargarMapa, reportar])

  /** Cambia la lámina donde se dibuja el elemento; su posición anterior se borra. */
  const cambiarLamina = useCallback(
    (codigoTramo: string) => {
      if (!detalle) return
      api
        .actualizarElemento(detalle.id, { tramo_lamina: codigoTramo }, detalle.version)
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
        e.numero_recinto,
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
    // Con un error, no se sabe si hay edificios: la lista solo no se pudo cargar.
    return (
      <div className="cargando">
        <h1>{error ? 'No se pudo cargar NetDoc' : 'Sin datos'}</h1>
        {error ? (
          <p className="error">{error}</p>
        ) : (
          <p>
            No hay edificios cargados. Ejecuta en el backend:
            <br />
            <code>python -m app.scripts.cargar_catalogo</code>
          </p>
        )}
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
        usuario={usuario}
        onSalir={onSalir}
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

      {eliminado && (
        <div className="franja-exito" role="status">
          <span>
            Eliminado: <strong>{eliminado.codigo}</strong>
          </span>
          <span className="franja-exito__botones">
            <button className="boton-enlace" onClick={() => restaurar(eliminado)}>
              Deshacer
            </button>
            <button className="boton-enlace" onClick={() => setEliminado(null)}>
              cerrar
            </button>
          </span>
        </div>
      )}

      {aviso && (
        <div className="franja-exito" role="status">
          <span>{aviso}</span>
          <span className="franja-exito__botones">
            <button className="boton-enlace" onClick={() => setAviso(null)}>
              cerrar
            </button>
          </span>
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
          puedeAgregar={pisos.length > 0}
          onAgregar={abrirAlta}
          onPlanos={cargaPermitida && !sinPlanos ? abrirCargaDePlanos : undefined}
          onVerEliminados={() => {
            setAgregando(false)
            setViendoEliminados(true)
          }}
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
          onCancelarPosicion={() => setPosicionando(null)}
          edificio={edificioSel}
          edificioVacio={cargaPermitida && sinPlanos}
          onCargarPlanos={cargaPermitida && !cargandoPlanos ? abrirCargaDePlanos : undefined}
        />

        {cargandoPlanos && (
          <CargaDePlanos
            edificio={edificioSel}
            onCerrar={() => setCargandoPlanos(false)}
            onConfirmada={alCargarPlanos}
            onQuitados={alQuitarPlanos}
          />
        )}

        {agregando && !cargandoPlanos && (
          <FormularioAlta
            edificio={edificioSel}
            pisos={pisos}
            pisoInicial={pisoSel}
            tramoInicial={tramoSel || (pisoActual?.tramos[0]?.codigo ?? '')}
            tipos={tipos}
            enumeraciones={enumeraciones}
            onCerrar={() => setAgregando(false)}
            onCreado={mostrarCreado}
            onCreadoYSigue={recargarMapa}
          />
        )}

        {viendoEliminados && !agregando && !cargandoPlanos && (
          <PanelEliminados
            edificio={edificioSel}
            onCerrar={() => setViendoEliminados(false)}
            onSeleccionar={seleccionar}
            onRestaurado={(restaurado) => {
              setEliminado(null)
              mostrarCreado(restaurado)
            }}
          />
        )}

        {detalle && !agregando && !viendoEliminados && !cargandoPlanos && (
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
              // Montado en un rack de otro tramo, pasó a ese tramo: la vista lo acompaña.
              if (actualizado.tramo_codigo !== detalle.tramo_codigo) {
                mostrarCreado(actualizado)
                return
              }
              setDetalle(actualizado)
              setHistorial(null) // la edición agrega entradas al historial
              recargarMapa() // etiqueta, estado o rack pueden cambiar el listado
            }}
            onCerrar={() => setDetalle(null)}
            onPosicionar={() => setPosicionando(detalle)}
            onUbicarEnRecinto={ubicarEnRecinto}
            onPedirHistorial={() => api.historial(detalle.id).then(setHistorial).catch(reportar)}
            onSeleccionarCodigo={seleccionar}
            pisos={pisos}
            onTrasladado={mostrarCreado}
            onEliminado={alEliminar}
            onRestaurar={() => restaurar(detalle)}
            hayVersionNueva={
              versionNueva?.id === detalle.id && versionNueva.version !== detalle.version
            }
            onVerVersionNueva={() => {
              if (versionNueva?.id !== detalle.id) return
              setDetalle(versionNueva)
              setVersionNueva(null)
              setHistorial(null) // el cambio ajeno agregó entradas
            }}
            onCambioAjeno={revisarFicha}
          />
        )}
      </main>
    </div>
  )
}
