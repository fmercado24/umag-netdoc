/**
 * Edición de los datos de un elemento.
 *
 * Envía solo lo que cambió, así el historial registra exactamente lo que se
 * modificó. Los atributos de la ficha se arman con las definiciones del
 * catálogo del tipo, igual que la vista de lectura: un tipo nuevo se edita sin
 * tocar este componente. Los errores de validación del backend se muestran
 * junto al campo que los provocó.
 *
 * El código dice dónde está el elemento y, en un punto de datos, de qué puerto
 * sale. Si lo editado lo cambia, la API lo actualiza; aquí se muestra antes de
 * guardar cuál le tocará.
 */

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '../api/cliente'
import {
  ATRIBUTOS_AUTOMATICOS,
  Campo,
  ControlAtributo,
  convertirAtributo,
  erroresDelServidor,
  leerUsuario,
  recordarUsuario,
  SIN_RACK,
  SOLO_CONECTADOS,
} from './camposFormulario'
import type {
  DefinicionAtributo,
  Elemento,
  ElementoDetalle,
  Enumeraciones,
  OpcionEnum,
  Recinto,
} from '../types'

type CampoBase =
  | 'etiqueta'
  | 'estado_operativo'
  | 'estado_condicion'
  | 'criticidad'
  | 'ubicacion_descriptiva'
  | 'numero_recinto'
  | 'padre_codigo'
  | 'unidad_rack'
  | 'marca'
  | 'modelo'
  | 'numero_serie'
  | 'direccion_mac'
  | 'direccion_ip'
  | 'fecha_instalacion'
  | 'fecha_ultimo_levantamiento'
  | 'observaciones'

const CAMPOS_BASE: CampoBase[] = [
  'etiqueta',
  'estado_operativo',
  'estado_condicion',
  'criticidad',
  'ubicacion_descriptiva',
  'numero_recinto',
  'padre_codigo',
  'unidad_rack',
  'marca',
  'modelo',
  'numero_serie',
  'direccion_mac',
  'direccion_ip',
  'fecha_instalacion',
  'fecha_ultimo_levantamiento',
  'observaciones',
]

const aTexto = (valor: unknown) => (valor === null || valor === undefined ? '' : String(valor))

function atributoATexto(valor: unknown, definicion: DefinicionAtributo): string {
  if (valor === null || valor === undefined) return ''
  if (definicion.tipo_dato === 'lista' && Array.isArray(valor)) return valor.join(', ')
  return String(valor)
}

interface Props {
  detalle: ElementoDetalle
  ficha: DefinicionAtributo[]
  enumeraciones: Enumeraciones | null
  onCancelar: () => void
  onGuardado: (actualizado: ElementoDetalle) => void
}

export function FormularioElemento({
  detalle,
  ficha,
  enumeraciones,
  onCancelar,
  onGuardado,
}: Props) {
  const inicialBase = useMemo(
    () =>
      Object.fromEntries(
        CAMPOS_BASE.map((campo) => [campo, aTexto(detalle[campo as keyof ElementoDetalle])]),
      ) as Record<CampoBase, string>,
    [detalle],
  )
  const inicialAtributos = useMemo(
    () =>
      Object.fromEntries(
        ficha.map((d) => [d.clave, atributoATexto(detalle.atributos[d.clave], d)]),
      ) as Record<string, string>,
    [detalle, ficha],
  )

  const [base, setBase] = useState(inicialBase)
  const [atributos, setAtributos] = useState(inicialAtributos)
  const [comentario, setComentario] = useState('')
  const [usuario, setUsuario] = useState(leerUsuario)
  const [errores, setErrores] = useState<Record<string, string>>({})
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [racks, setRacks] = useState<Elemento[]>([])
  const [recintos, setRecintos] = useState<Recinto[]>([])
  const inicialRackOrigen = detalle.rack_origen_codigo ?? ''
  const inicialPuerto = detalle.puerto_en_rack ?? ''
  const [rackOrigen, setRackOrigen] = useState(inicialRackOrigen)
  const [puerto, setPuerto] = useState(inicialPuerto)
  /** Lo que el cambio hace con su código: el que le tocará, o por qué no se puede. */
  const [consecuencia, setConsecuencia] = useState<{
    codigo: string | null
    aviso: string | null
  } | null>(null)

  const admiteRack = !SIN_RACK.has(detalle.tipo_codigo)
  const conectadoAlRack = SOLO_CONECTADOS.has(detalle.tipo_codigo)
  const esPunto = detalle.tipo_codigo === 'PD'
  const edificio = detalle.edificio_codigo
  const piso = detalle.piso_codigo
  const tramoActual = detalle.tramo_codigo ?? ''

  // Un punto de datos puede salir de un rack de otro piso.
  useEffect(() => {
    if (!admiteRack && !esPunto) return
    let vigente = true
    api
      .racks(edificio, esPunto ? undefined : piso)
      .then((lista) => vigente && setRacks(lista))
      .catch(() => vigente && setRacks([]))
    return () => {
      vigente = false
    }
  }, [admiteRack, esPunto, edificio, piso])

  // Los recintos de las láminas del piso, para elegir el número sin errores.
  useEffect(() => {
    let vigente = true
    api
      .recintos(detalle.edificio_codigo, detalle.piso_codigo)
      .then((lista) => vigente && setRecintos(lista))
      .catch(() => vigente && setRecintos([]))
    return () => {
      vigente = false
    }
  }, [detalle.edificio_codigo, detalle.piso_codigo])

  const cambiarBase = (campo: CampoBase, valor: string) =>
    setBase((b) => ({ ...b, [campo]: valor }))
  const cambiarAtributo = (clave: string, valor: string) =>
    setAtributos((a) => ({ ...a, [clave]: valor }))

  const fichaVisible = esPunto ? ficha.filter((d) => !ATRIBUTOS_AUTOMATICOS.has(d.clave)) : ficha
  const puertoEscrito = puerto.trim().toUpperCase()
  const cambiaPuerto =
    esPunto && (rackOrigen !== inicialRackOrigen || puertoEscrito !== inicialPuerto)

  const hayCambios =
    CAMPOS_BASE.some((c) => base[c] !== inicialBase[c]) ||
    ficha.some((d) => atributos[d.clave] !== inicialAtributos[d.clave]) ||
    cambiaPuerto

  // Montado en un rack de otro tramo, pasa a ese tramo: su código lo dice.
  const rackNuevo = racks.find((r) => r.codigo === base.padre_codigo)
  const tramoDelRackNuevo =
    admiteRack &&
    !conectadoAlRack &&
    rackNuevo &&
    base.padre_codigo !== inicialBase.padre_codigo &&
    (rackNuevo.tramo_codigo ?? '') !== tramoActual
      ? (rackNuevo.tramo_codigo ?? '')
      : null

  // El código que recibirá, con una pausa para no consultar en cada tecla.
  useEffect(() => {
    setConsecuencia(null)
    const puertoListo = /^[A-Z0-9][A-Z0-9-]*$/.test(puertoEscrito)
    const porPuerto = cambiaPuerto && rackOrigen !== '' && puertoListo
    if (!porPuerto && tramoDelRackNuevo === null) return
    let vigente = true
    const espera = setTimeout(() => {
      const pedido = porPuerto
        ? api
            .proximoCodigo({
              tipo: detalle.tipo_codigo,
              edificio,
              piso,
              ...(tramoActual ? { tramo: tramoActual } : {}),
              rack_origen: rackOrigen,
              puerto: puertoEscrito,
              para: String(detalle.id),
            })
            .then((r) =>
              r.disponible
                ? { codigo: r.codigo, aviso: null }
                : {
                    codigo: null,
                    aviso: r.eliminado
                      ? `Ya existe ${r.codigo}, eliminado: recupéralo desde «Ver eliminados», los códigos no se reutilizan.`
                      : `Ya existe ${r.codigo}: ese puerto ya está documentado.`,
                  },
            )
        : api
            .previoTraslado(detalle.id, piso, tramoDelRackNuevo || undefined)
            .then((r) => ({ codigo: r.codigo_nuevo, aviso: r.conflicto }))
      pedido
        .then((r) => vigente && setConsecuencia(r))
        .catch(() => vigente && setConsecuencia(null))
    }, 250)
    return () => {
      vigente = false
      clearTimeout(espera)
    }
  }, [
    detalle.id,
    detalle.tipo_codigo,
    edificio,
    piso,
    tramoActual,
    cambiaPuerto,
    rackOrigen,
    puertoEscrito,
    tramoDelRackNuevo,
  ])

  const cambiaraCodigo = consecuencia?.codigo != null && consecuencia.codigo !== detalle.codigo

  /** Arma el PATCH con lo que cambió; devuelve los errores si algo no se puede enviar. */
  const armarCambios = (): {
    cambios: Record<string, unknown>
    errores: Record<string, string>
  } => {
    const cambios: Record<string, unknown> = {}
    const encontrados: Record<string, string> = {}

    for (const campo of CAMPOS_BASE) {
      if (base[campo] === inicialBase[campo]) continue
      const texto = base[campo].trim()
      if (campo === 'unidad_rack' && texto !== '') {
        const unidad = Number(texto)
        if (!Number.isInteger(unidad) || unidad < 1) {
          encontrados[campo] = 'debe ser un número entero desde 1'
          continue
        }
        cambios[campo] = unidad
      } else {
        cambios[campo] = texto === '' ? null : texto
      }
    }

    const nuevosAtributos: Record<string, unknown> = {}
    for (const definicion of ficha) {
      const texto = atributos[definicion.clave]
      if (texto === inicialAtributos[definicion.clave]) continue
      try {
        // null borra la clave de la ficha: el backend fusiona el resto.
        nuevosAtributos[definicion.clave] = convertirAtributo(texto, definicion)
      } catch (e) {
        encontrados[`atributos.${definicion.clave}`] = (e as Error).message
      }
    }
    if (Object.keys(nuevosAtributos).length > 0) cambios.atributos = nuevosAtributos

    if (cambiaPuerto) {
      cambios.rack_origen = rackOrigen || null
      cambios.puerto = puertoEscrito || null
    }

    return { cambios, errores: encontrados }
  }

  const guardar = async () => {
    const { cambios, errores: locales } = armarCambios()
    setErrores(locales)
    setErrorGeneral(null)
    if (Object.keys(locales).length > 0) return
    if (Object.keys(cambios).length === 0) {
      onCancelar()
      return
    }
    if (usuario.trim()) recordarUsuario(usuario.trim())

    setGuardando(true)
    try {
      const actualizado = await api.actualizarElemento(detalle.id, {
        ...cambios,
        ...(comentario.trim() ? { comentario: comentario.trim() } : {}),
        ...(usuario.trim() ? { usuario: usuario.trim() } : {}),
      })
      onGuardado(actualizado)
    } catch (e) {
      const { porCampo, general } = erroresDelServidor(e)
      setErrores(porCampo)
      setErrorGeneral(
        general ?? (Object.keys(porCampo).length ? 'Revisa los campos marcados.' : null),
      )
    } finally {
      setGuardando(false)
    }
  }

  const cancelar = () => {
    if (hayCambios && !window.confirm('Hay cambios sin guardar. ¿Descartarlos?')) return
    onCancelar()
  }

  // --- Piezas del formulario ----------------------------------------------
  const campo = (id: string, etiqueta: string, control: ReactNode, ayuda?: string) => (
    <Campo key={id} etiqueta={etiqueta} error={errores[id]} ayuda={ayuda}>
      {control}
    </Campo>
  )

  const texto = (
    id: CampoBase,
    etiqueta: string,
    extra: { tipo?: string; placeholder?: string } = {},
  ) =>
    campo(
      id,
      etiqueta,
      <input
        type={extra.tipo ?? 'text'}
        value={base[id]}
        placeholder={extra.placeholder}
        onChange={(e) => cambiarBase(id, e.target.value)}
      />,
    )

  const selector = (id: CampoBase, etiqueta: string, opciones: OpcionEnum[], vacio?: string) =>
    campo(
      id,
      etiqueta,
      <select value={base[id]} onChange={(e) => cambiarBase(id, e.target.value)}>
        {vacio !== undefined && <option value="">{vacio}</option>}
        {opciones.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.etiqueta}
          </option>
        ))}
      </select>,
    )

  // Un equipo que pasa a montarse en un rack pierde su posición propia.
  const avisoRack =
    base.padre_codigo !== inicialBase.padre_codigo &&
    base.padre_codigo !== '' &&
    !conectadoAlRack &&
    detalle.pos_x !== null
      ? 'Al montarlo en el rack se borra su posición propia: se verá donde esté el rack.'
      : conectadoAlRack
        ? 'Un AP o una UPS solo se conecta al rack y conserva su propio marcador.'
        : undefined

  // El rack actual puede no estar en la lista (otro tipo de contenedor).
  const opcionesRack = [
    ...racks.map((r) => ({
      valor: r.codigo,
      etiqueta: r.etiqueta ? `${r.codigo} · ${r.etiqueta}` : r.codigo,
    })),
    ...(inicialBase.padre_codigo && !racks.some((r) => r.codigo === inicialBase.padre_codigo)
      ? [{ valor: inicialBase.padre_codigo, etiqueta: inicialBase.padre_codigo }]
      : []),
  ]

  // Los racks de su piso van primero. El actual puede estar fuera de la lista (eliminado).
  const opcionesRackOrigen = [
    ...[...racks].sort(
      (a, b) =>
        Number(b.piso_codigo === piso) - Number(a.piso_codigo === piso) ||
        a.codigo.localeCompare(b.codigo),
    ),
    ...(inicialRackOrigen && !racks.some((r) => r.codigo === inicialRackOrigen)
      ? [{ codigo: inicialRackOrigen, etiqueta: null }]
      : []),
  ]

  const avisoDeCodigo = consecuencia?.aviso ? (
    <p className="formulario__aviso" role="status">
      {consecuencia.aviso}
    </p>
  ) : (
    cambiaraCodigo && (
      <div className="traslado" role="status">
        <p className="formulario__codigo">
          Su código pasará a ser <strong>{consecuencia?.codigo}</strong>
        </p>
        <p className="formulario__ayuda">
          {tramoDelRackNuevo !== null &&
            `Ese rack está en el tramo ${tramoDelRackNuevo}: el equipo pasa a ese tramo. `}
          Si lleva el código anterior en su rótulo físico, hay que cambiarlo. {detalle.codigo} queda
          reservado y sigue llevando a este elemento.
        </p>
      </div>
    )
  )

  return (
    <form
      className="formulario"
      onSubmit={(e) => {
        e.preventDefault()
        if (!consecuencia?.aviso) void guardar()
      }}
    >
      {errorGeneral && <p className="formulario__aviso">{errorGeneral}</p>}

      <h3 className="subtitulo">Identificación y estado</h3>
      {texto('etiqueta', 'Etiqueta')}
      {selector('estado_operativo', 'Estado operativo', enumeraciones?.estado_operativo ?? [])}
      <div className="formulario__fila">
        {selector('estado_condicion', 'Condición', enumeraciones?.estado_condicion ?? [], '—')}
        {selector('criticidad', 'Criticidad', enumeraciones?.criticidad ?? [], '—')}
      </div>

      {esPunto && (
        <>
          <h3 className="subtitulo">De dónde sale</h3>
          <div className="formulario__fila">
            {campo(
              'rack_origen',
              'Rack de origen',
              <select value={rackOrigen} onChange={(e) => setRackOrigen(e.target.value)}>
                {!inicialRackOrigen && <option value="">— Aún no se sabe —</option>}
                {opcionesRackOrigen.map((r) => (
                  <option key={r.codigo} value={r.codigo}>
                    {r.etiqueta ? `${r.codigo} · ${r.etiqueta}` : r.codigo}
                  </option>
                ))}
              </select>,
            )}
            {campo(
              'puerto',
              'Puerto',
              <input
                type="text"
                value={puerto}
                placeholder="Ej.: D17"
                onChange={(e) => setPuerto(e.target.value)}
              />,
            )}
          </div>
          <p className="formulario__ayuda">
            El prefijo del puerto indica el servicio: D datos, T telefonía, C CCTV. Su código y su
            rótulo salen de aquí.
          </p>
          {avisoDeCodigo}
        </>
      )}

      <h3 className="subtitulo">Ubicación</h3>
      {texto('ubicacion_descriptiva', 'Ubicación (recinto)')}
      {campo(
        'numero_recinto',
        'N° de recinto',
        <>
          <input
            type="text"
            inputMode="decimal"
            list={`recintos-${detalle.id}`}
            value={base.numero_recinto}
            placeholder="Ej.: 1083"
            onChange={(e) => cambiarBase('numero_recinto', e.target.value)}
          />
          <datalist id={`recintos-${detalle.id}`}>
            {recintos.map((r) => (
              <option key={`${r.plano_id}-${r.numero}`} value={r.numero}>
                {r.nombre ?? ''}
              </option>
            ))}
          </datalist>
        </>,
        detalle.montado
          ? 'Montado en su rack: se ve donde esté el rack.'
          : 'El número de la sala en el plano. Al guardar, el elemento se ubica en ese recinto.',
      )}
      {admiteRack &&
        campo(
          'padre_codigo',
          'Rack',
          <select
            value={base.padre_codigo}
            onChange={(e) => cambiarBase('padre_codigo', e.target.value)}
          >
            <option value="">— Sin rack —</option>
            {opcionesRack.map((o) => (
              <option key={o.valor} value={o.valor}>
                {o.etiqueta}
              </option>
            ))}
          </select>,
          avisoRack,
        )}
      {!esPunto && avisoDeCodigo}
      {admiteRack &&
        base.padre_codigo !== '' &&
        !conectadoAlRack &&
        texto('unidad_rack', 'Unidad de rack (U)', { placeholder: 'Ej.: 12' })}

      <h3 className="subtitulo">Equipo</h3>
      <div className="formulario__fila">
        {texto('marca', 'Marca')}
        {texto('modelo', 'Modelo')}
      </div>
      {texto('numero_serie', 'N° de serie')}
      <div className="formulario__fila">
        {texto('direccion_ip', 'IP de gestión', { placeholder: '10.0.0.1' })}
        {texto('direccion_mac', 'MAC', { placeholder: 'AA:BB:CC:DD:EE:FF' })}
      </div>
      <div className="formulario__fila">
        {texto('fecha_instalacion', 'Instalación', { tipo: 'date' })}
        {texto('fecha_ultimo_levantamiento', 'Último levantamiento', { tipo: 'date' })}
      </div>

      {fichaVisible.length > 0 && (
        <>
          <h3 className="subtitulo">Ficha de {detalle.tipo_nombre.toLowerCase()}</h3>
          {fichaVisible.map((definicion) =>
            campo(
              `atributos.${definicion.clave}`,
              definicion.etiqueta +
                (definicion.unidad ? ` (${definicion.unidad})` : '') +
                (definicion.obligatorio ? ' *' : ''),
              <ControlAtributo
                definicion={definicion}
                valor={atributos[definicion.clave] ?? ''}
                onCambio={(v) => cambiarAtributo(definicion.clave, v)}
              />,
              definicion.ayuda ?? undefined,
            ),
          )}
        </>
      )}

      <h3 className="subtitulo">Observaciones</h3>
      {campo(
        'observaciones',
        'Observaciones',
        <textarea
          rows={3}
          value={base.observaciones}
          onChange={(e) => cambiarBase('observaciones', e.target.value)}
        />,
      )}

      <h3 className="subtitulo">Registro del cambio</h3>
      <div className="formulario__fila">
        {campo(
          'usuario',
          'Registrado por',
          <input type="text" value={usuario} onChange={(e) => setUsuario(e.target.value)} />,
        )}
        {campo(
          'comentario',
          'Comentario',
          <input
            type="text"
            value={comentario}
            placeholder="Ej.: verificado en terreno"
            onChange={(e) => setComentario(e.target.value)}
          />,
        )}
      </div>

      <div className="formulario__acciones">
        <button
          type="button"
          className="boton boton--secundario"
          onClick={cancelar}
          disabled={guardando}
        >
          Cancelar
        </button>
        <button
          type="submit"
          className="boton"
          disabled={guardando || !hayCambios || Boolean(consecuencia?.aviso)}
        >
          {guardando ? 'Guardando…' : 'Guardar cambios'}
        </button>
      </div>
    </form>
  )
}
