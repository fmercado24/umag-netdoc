/**
 * Edición de los datos de un elemento.
 *
 * Envía solo lo que cambió, así el historial registra exactamente lo que se
 * modificó. Los atributos de la ficha se arman con las definiciones del
 * catálogo del tipo, igual que la vista de lectura: un tipo nuevo se edita sin
 * tocar este componente. Los errores de validación del backend se muestran
 * junto al campo que los provocó.
 */

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api, ErrorApi } from '../api/cliente'
import type {
  DefinicionAtributo,
  Elemento,
  ElementoDetalle,
  Enumeraciones,
  OpcionEnum,
} from '../types'

type CampoBase =
  | 'etiqueta'
  | 'estado_operativo'
  | 'estado_condicion'
  | 'criticidad'
  | 'ubicacion_descriptiva'
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

/** Un rack no va dentro de otro y un punto de datos no tiene contenedor. */
const SIN_RACK = new Set(['R', 'PD'])

/** Quién edita: se recuerda en este navegador para no escribirlo cada vez. */
const CLAVE_USUARIO = 'netdoc.usuario'

function leerUsuario(): string {
  try {
    return localStorage.getItem(CLAVE_USUARIO) ?? ''
  } catch {
    return ''
  }
}

function recordarUsuario(usuario: string) {
  try {
    localStorage.setItem(CLAVE_USUARIO, usuario)
  } catch {
    /* sin almacenamiento local: se pedirá de nuevo */
  }
}

const aTexto = (valor: unknown) => (valor === null || valor === undefined ? '' : String(valor))

function atributoATexto(valor: unknown, definicion: DefinicionAtributo): string {
  if (valor === null || valor === undefined) return ''
  if (definicion.tipo_dato === 'lista' && Array.isArray(valor)) return valor.join(', ')
  return String(valor)
}

/** Convierte lo escrito al tipo que exige la ficha; lanza el mensaje de error. */
function convertirAtributo(texto: string, definicion: DefinicionAtributo): unknown {
  const limpio = texto.trim()
  if (limpio === '') return null
  switch (definicion.tipo_dato) {
    case 'numero': {
      const numero = Number(limpio.replace(',', '.'))
      if (Number.isNaN(numero)) throw new Error('debe ser un número')
      return numero
    }
    case 'booleano':
      return limpio === 'true'
    case 'lista':
      return limpio
        .split(',')
        .map((parte) => parte.trim())
        .filter(Boolean)
    default:
      return limpio
  }
}

/** Ubica los errores de FastAPI (422 de Pydantic o de la ficha) en su campo. */
function erroresDelServidor(error: unknown): {
  porCampo: Record<string, string>
  general: string | null
} {
  const porCampo: Record<string, string> = {}
  if (!(error instanceof ErrorApi)) {
    return { porCampo, general: error instanceof Error ? error.message : 'Error desconocido' }
  }
  const detalle = error.detalle
  if (Array.isArray(detalle)) {
    const sueltos: string[] = []
    for (const item of detalle) {
      if (typeof item === 'string') {
        // Ficha del tipo: "'clave' debe ser numérico".
        const clave = /^'([^']+)'/.exec(item)?.[1]
        if (clave) porCampo[`atributos.${clave}`] = item.replace(/^'[^']+'\s*/, '')
        else sueltos.push(item)
      } else if (item && typeof item === 'object' && 'loc' in item && 'msg' in item) {
        const loc = (item as { loc: unknown[] }).loc
        const mensaje = String((item as { msg: unknown }).msg).replace(/^Value error, /, '')
        porCampo[String(loc[loc.length - 1])] = mensaje
      }
    }
    return { porCampo, general: sueltos.length ? sueltos.join('; ') : null }
  }
  return { porCampo, general: error.message }
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

  const admiteRack = !SIN_RACK.has(detalle.tipo_codigo)
  useEffect(() => {
    if (!admiteRack) return
    let vigente = true
    api
      .racks(detalle.edificio_codigo, detalle.piso_codigo)
      .then((lista) => vigente && setRacks(lista))
      .catch(() => vigente && setRacks([]))
    return () => {
      vigente = false
    }
  }, [admiteRack, detalle.edificio_codigo, detalle.piso_codigo])

  const cambiarBase = (campo: CampoBase, valor: string) =>
    setBase((b) => ({ ...b, [campo]: valor }))
  const cambiarAtributo = (clave: string, valor: string) =>
    setAtributos((a) => ({ ...a, [clave]: valor }))

  const hayCambios =
    CAMPOS_BASE.some((c) => base[c] !== inicialBase[c]) ||
    ficha.some((d) => atributos[d.clave] !== inicialAtributos[d.clave])

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
    <label
      key={id}
      className={`formulario__campo ${errores[id] ? 'formulario__campo--error' : ''}`}
    >
      <span>{etiqueta}</span>
      {control}
      {errores[id] ? (
        <small className="formulario__error">{errores[id]}</small>
      ) : (
        ayuda && <small className="formulario__ayuda">{ayuda}</small>
      )}
    </label>
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

  const controlAtributo = (definicion: DefinicionAtributo) => {
    const valor = atributos[definicion.clave] ?? ''
    const cambiar = (v: string) => cambiarAtributo(definicion.clave, v)
    switch (definicion.tipo_dato) {
      case 'enum':
        return (
          <select value={valor} onChange={(e) => cambiar(e.target.value)}>
            <option value="">—</option>
            {(definicion.opciones ?? []).map((o) => (
              <option key={String(o)} value={String(o)}>
                {String(o)}
              </option>
            ))}
          </select>
        )
      case 'booleano':
        return (
          <select value={valor} onChange={(e) => cambiar(e.target.value)}>
            <option value="">—</option>
            <option value="true">Sí</option>
            <option value="false">No</option>
          </select>
        )
      case 'numero':
        return (
          <input
            type="text"
            inputMode="decimal"
            value={valor}
            onChange={(e) => cambiar(e.target.value)}
          />
        )
      case 'fecha':
        return <input type="date" value={valor} onChange={(e) => cambiar(e.target.value)} />
      default:
        return (
          <input
            type="text"
            value={valor}
            placeholder={
              definicion.tipo_dato === 'lista'
                ? 'Separados por coma'
                : definicion.tipo_dato === 'mac'
                  ? 'AA:BB:CC:DD:EE:FF'
                  : definicion.tipo_dato === 'referencia'
                    ? 'Código del elemento'
                    : undefined
            }
            onChange={(e) => cambiar(e.target.value)}
          />
        )
    }
  }

  // Un equipo que pasa a montarse en un rack pierde su posición propia.
  const conectadoAlRack = detalle.tipo_codigo === 'AP' || detalle.tipo_codigo === 'UPS'
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

  return (
    <form
      className="formulario"
      onSubmit={(e) => {
        e.preventDefault()
        void guardar()
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

      <h3 className="subtitulo">Ubicación</h3>
      {texto('ubicacion_descriptiva', 'Ubicación (recinto)')}
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

      {ficha.length > 0 && (
        <>
          <h3 className="subtitulo">Ficha de {detalle.tipo_nombre.toLowerCase()}</h3>
          {ficha.map((definicion) =>
            campo(
              `atributos.${definicion.clave}`,
              definicion.etiqueta +
                (definicion.unidad ? ` (${definicion.unidad})` : '') +
                (definicion.obligatorio ? ' *' : ''),
              controlAtributo(definicion),
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
        <button type="submit" className="boton" disabled={guardando || !hayCambios}>
          {guardando ? 'Guardando…' : 'Guardar cambios'}
        </button>
      </div>
    </form>
  )
}
