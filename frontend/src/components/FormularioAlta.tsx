/**
 * Alta de un elemento: un switch recién comprado, un punto de datos nuevo…
 *
 * Como en la edición, la ficha se arma con el catálogo del tipo: un tipo nuevo
 * se puede agregar sin tocar este componente. El código lo asigna la API (SOP
 * sección 8); aquí se muestra antes de guardar. Un tipo sin correlativo se
 * identifica por el rack y el puerto de donde sale su cableado.
 */

import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'

import { api } from '../api/cliente'
import {
  ATRIBUTOS_AUTOMATICOS,
  Campo,
  ControlAtributo,
  convertirAtributo,
  erroresDelServidor,
  leerUsuario,
  recordarUsuario,
  SOLO_CONECTADOS,
} from './camposFormulario'
import type {
  CodigoPropuesto,
  DefinicionAtributo,
  Elemento,
  ElementoDetalle,
  Enumeraciones,
  OpcionEnum,
  Piso,
  Recinto,
  TipoElemento,
} from '../types'

const VACIO = {
  rack_origen: '',
  puerto: '',
  padre_codigo: '',
  unidad_rack: '',
  etiqueta: '',
  estado_operativo: 'activo',
  estado_condicion: '',
  criticidad: '',
  ubicacion_descriptiva: '',
  numero_recinto: '',
  marca: '',
  modelo: '',
  numero_serie: '',
  direccion_ip: '',
  direccion_mac: '',
  fecha_instalacion: '',
  observaciones: '',
}
type CampoBase = keyof typeof VACIO

/** Lo que distingue a cada unidad: al agregar otro igual se borra, el resto se conserva. */
const PROPIOS_DE_CADA_UNO: CampoBase[] = [
  'etiqueta',
  'numero_serie',
  'direccion_ip',
  'direccion_mac',
  'unidad_rack',
]

/** «D17» → «D18», «T09» → «T10»: para documentar varios puertos seguidos. */
function puertoSiguiente(puerto: string): string {
  const partes = /^(.*?)(\d+)$/.exec(puerto.trim())
  if (!partes) return ''
  const numero = String(Number(partes[2]) + 1).padStart(partes[2].length, '0')
  return partes[1] + numero
}

interface Props {
  edificio: string
  pisos: Piso[]
  pisoInicial: string
  tramoInicial: string
  tipos: TipoElemento[]
  enumeraciones: Enumeraciones | null
  onCerrar: () => void
  /** «Agregar»: el formulario se cierra para mostrar el elemento creado. */
  onCreado: (creado: ElementoDetalle) => void
  /** «Agregar y seguir»: el formulario queda abierto. */
  onCreadoYSigue: (creado: ElementoDetalle) => void
}

export function FormularioAlta({
  edificio,
  pisos,
  pisoInicial,
  tramoInicial,
  tipos,
  enumeraciones,
  onCerrar,
  onCreado,
  onCreadoYSigue,
}: Props) {
  const [codigoTipo, setCodigoTipo] = useState('')
  const [codigoPiso, setCodigoPiso] = useState(pisoInicial)
  const [codigoTramo, setCodigoTramo] = useState(tramoInicial)
  const [base, setBase] = useState<Record<CampoBase, string>>(VACIO)
  const [ficha, setFicha] = useState<DefinicionAtributo[]>([])
  const [atributos, setAtributos] = useState<Record<string, string>>({})
  const [usuario, setUsuario] = useState(leerUsuario)
  const [racks, setRacks] = useState<Elemento[]>([])
  const [recintos, setRecintos] = useState<Recinto[]>([])
  const [propuesto, setPropuesto] = useState<CodigoPropuesto | null>(null)
  const [errores, setErrores] = useState<Record<string, string>>({})
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState<string | null>(null)

  const tipo = tipos.find((t) => t.codigo === codigoTipo)
  const piso = pisos.find((p) => p.codigo === codigoPiso)
  const tramos = piso?.tramos ?? []
  const sinCorrelativo = tipo !== undefined && !tipo.usa_correlativo
  const admiteRack = tipo !== undefined && tipo.usa_correlativo && !tipo.es_contenedor
  const soloConectado = SOLO_CONECTADOS.has(codigoTipo)
  const fichaVisible = ficha.filter((d) => !ATRIBUTOS_AUTOMATICOS.has(d.clave))

  const cambiar = (campo: CampoBase, valor: string) => setBase((b) => ({ ...b, [campo]: valor }))

  const cambiarPiso = (codigo: string) => {
    setCodigoPiso(codigo)
    setCodigoTramo(pisos.find((p) => p.codigo === codigo)?.tramos[0]?.codigo ?? '')
    cambiar('numero_recinto', '')
    cambiar('padre_codigo', '')
  }

  // La ficha depende del tipo: otro tipo, otros atributos.
  useEffect(() => {
    setFicha([])
    setAtributos({})
    if (!codigoTipo) return
    let vigente = true
    api
      .ficha(codigoTipo)
      .then((lista) => vigente && setFicha(lista))
      .catch((e) => vigente && setErrorGeneral(erroresDelServidor(e).general))
    return () => {
      vigente = false
    }
  }, [codigoTipo])

  // Un punto de datos puede salir de un rack de otro piso.
  useEffect(() => {
    let vigente = true
    api
      .racks(edificio)
      .then((lista) => vigente && setRacks(lista))
      .catch(() => vigente && setRacks([]))
    return () => {
      vigente = false
    }
  }, [edificio])

  useEffect(() => {
    let vigente = true
    api
      .recintos(edificio, codigoPiso)
      .then((lista) => vigente && setRecintos(lista))
      .catch(() => vigente && setRecintos([]))
    return () => {
      vigente = false
    }
  }, [edificio, codigoPiso])

  // El código que recibirá, con una pausa para no consultar en cada tecla.
  const puertoListo = base.rack_origen !== '' && /^[A-Za-z0-9][A-Za-z0-9-]*$/.test(base.puerto.trim())
  useEffect(() => {
    setPropuesto(null)
    if (!codigoTipo || !codigoPiso) return
    const consulta: Record<string, string> = {
      tipo: codigoTipo,
      edificio,
      piso: codigoPiso,
    }
    if (codigoTramo) consulta.tramo = codigoTramo
    if (sinCorrelativo && puertoListo) {
      consulta.rack_origen = base.rack_origen
      consulta.puerto = base.puerto.trim()
    }
    let vigente = true
    const espera = setTimeout(() => {
      api
        .proximoCodigo(consulta)
        .then((r) => vigente && setPropuesto(r))
        .catch(() => vigente && setPropuesto(null))
    }, 250)
    return () => {
      vigente = false
      clearTimeout(espera)
    }
  }, [edificio, codigoTipo, codigoPiso, codigoTramo, sinCorrelativo, puertoListo, base.rack_origen, base.puerto, ultimo])

  // Los racks del piso elegido van primero.
  const opcionesRack = useMemo(
    () =>
      [...racks]
        .sort(
          (a, b) =>
            Number(b.piso_codigo === codigoPiso) - Number(a.piso_codigo === codigoPiso) ||
            a.codigo.localeCompare(b.codigo),
        )
        .map((r) => ({
          valor: r.codigo,
          etiqueta: r.etiqueta ? `${r.codigo} · ${r.etiqueta}` : r.codigo,
        })),
    [racks, codigoPiso],
  )

  // Montado, está donde esté el rack, y eso dice su código; conectado, basta con el piso.
  const opcionesPadre = racks
    .filter(
      (r) =>
        r.piso_codigo === codigoPiso &&
        (soloConectado || (r.tramo_codigo ?? '') === codigoTramo),
    )
    .map((r) => ({
      valor: r.codigo,
      etiqueta: r.etiqueta ? `${r.codigo} · ${r.etiqueta}` : r.codigo,
    }))

  const hayDatos =
    (Object.keys(VACIO) as CampoBase[]).some((c) => base[c] !== VACIO[c]) ||
    Object.values(atributos).some(Boolean)

  const armar = (): { datos: Record<string, unknown>; errores: Record<string, string> } => {
    const encontrados: Record<string, string> = {}
    const datos: Record<string, unknown> = { tipo: codigoTipo, edificio, piso: codigoPiso }
    if (codigoTramo) datos.tramo = codigoTramo

    for (const campo of Object.keys(VACIO) as CampoBase[]) {
      const texto = base[campo].trim()
      if (texto === '') continue
      if (campo === 'rack_origen' || campo === 'puerto') {
        if (sinCorrelativo) datos[campo] = texto
      } else if (campo === 'padre_codigo') {
        if (admiteRack) datos[campo] = texto
      } else if (campo === 'unidad_rack') {
        if (!admiteRack || soloConectado || base.padre_codigo === '') continue
        const unidad = Number(texto)
        if (!Number.isInteger(unidad) || unidad < 1) {
          encontrados[campo] = 'debe ser un número entero desde 1'
        } else {
          datos[campo] = unidad
        }
      } else {
        datos[campo] = texto
      }
    }

    const ficha_: Record<string, unknown> = {}
    for (const definicion of fichaVisible) {
      const texto = atributos[definicion.clave] ?? ''
      if (texto === '') continue
      try {
        ficha_[definicion.clave] = convertirAtributo(texto, definicion)
      } catch (e) {
        encontrados[`atributos.${definicion.clave}`] = (e as Error).message
      }
    }
    if (Object.keys(ficha_).length > 0) datos.atributos = ficha_
    return { datos, errores: encontrados }
  }

  const guardar = async (seguir: boolean) => {
    const { datos, errores: locales } = armar()
    setErrores(locales)
    setErrorGeneral(null)
    setUltimo(null)
    if (Object.keys(locales).length > 0) return
    if (usuario.trim()) recordarUsuario(usuario.trim())

    setGuardando(true)
    try {
      const creado = await api.crearElemento(datos, usuario.trim() || undefined)
      if (!seguir) {
        onCreado(creado)
        return
      }
      onCreadoYSigue(creado)
      setUltimo(creado.codigo)
      setBase((b) => {
        const siguiente = { ...b, puerto: puertoSiguiente(b.puerto) }
        for (const campo of PROPIOS_DE_CADA_UNO) siguiente[campo] = ''
        return siguiente
      })
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

  const cerrar = () => {
    if (hayDatos && !window.confirm('Hay datos sin guardar. ¿Descartarlos?')) return
    onCerrar()
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
    extra: { tipo?: string; placeholder?: string; ayuda?: string } = {},
  ) =>
    campo(
      id,
      etiqueta,
      <input
        type={extra.tipo ?? 'text'}
        value={base[id]}
        placeholder={extra.placeholder}
        onChange={(e) => cambiar(id, e.target.value)}
      />,
      extra.ayuda,
    )

  const selector = (id: CampoBase, etiqueta: string, opciones: OpcionEnum[], vacio?: string) =>
    campo(
      id,
      etiqueta,
      <select value={base[id]} onChange={(e) => cambiar(id, e.target.value)}>
        {vacio !== undefined && <option value="">{vacio}</option>}
        {opciones.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.etiqueta}
          </option>
        ))}
      </select>,
    )

  const puedeGuardar = !guardando && tipo !== undefined && propuesto?.disponible !== false

  const enviar = (evento: FormEvent) => {
    evento.preventDefault()
    if (puedeGuardar) void guardar(false)
  }

  return (
    <section className="panel-detalle">
      <header className="detalle__cabecera">
        <div>
          <span className="detalle__tipo">Edificio {edificio}</span>
          <h2 className="detalle__titulo">Agregar elemento</h2>
        </div>
        <div className="detalle__botones">
          <button className="boton-cerrar" onClick={cerrar} aria-label="Cerrar sin agregar">
            ×
          </button>
        </div>
      </header>

      <form className="formulario" onSubmit={enviar}>
        {ultimo && (
          <p className="formulario__listo" role="status">
            Agregado: <strong>{ultimo}</strong>
          </p>
        )}
        {errorGeneral && <p className="formulario__aviso">{errorGeneral}</p>}

        <h3 className="subtitulo">Qué es y dónde está</h3>
        {campo(
          'tipo',
          'Tipo de elemento',
          <select
            value={codigoTipo}
            onChange={(e) => {
              setCodigoTipo(e.target.value)
              cambiar('padre_codigo', '')
            }}
            autoFocus
          >
            <option value="">— Elige el tipo —</option>
            {tipos.map((t) => (
              <option key={t.codigo} value={t.codigo}>
                {t.nombre} ({t.codigo})
              </option>
            ))}
          </select>,
        )}
        <div className="formulario__fila">
          {campo(
            'piso',
            'Piso',
            <select value={codigoPiso} onChange={(e) => cambiarPiso(e.target.value)}>
              {pisos.map((p) => (
                <option key={p.codigo} value={p.codigo}>
                  {p.codigo}
                  {p.nombre ? ` — ${p.nombre}` : ''}
                </option>
              ))}
            </select>,
          )}
          {campo(
            'tramo',
            'Tramo',
            <select
              value={codigoTramo}
              onChange={(e) => {
                setCodigoTramo(e.target.value)
                cambiar('padre_codigo', '')
              }}
              disabled={tramos.length === 0}
            >
              {tramos.length === 0 && <option value="">Este piso no tiene</option>}
              {tramos.map((t) => (
                <option key={t.codigo} value={t.codigo}>
                  {t.codigo}
                  {t.nombre ? ` — ${t.nombre}` : ''}
                </option>
              ))}
            </select>,
          )}
        </div>

        {tipo && (
          <>
            {sinCorrelativo && (
              <>
                <div className="formulario__fila">
                  {campo(
                    'rack_origen',
                    'Rack de origen',
                    <select
                      value={base.rack_origen}
                      onChange={(e) => cambiar('rack_origen', e.target.value)}
                    >
                      <option value="">— Aún no se sabe —</option>
                      {opcionesRack.map((o) => (
                        <option key={o.valor} value={o.valor}>
                          {o.etiqueta}
                        </option>
                      ))}
                    </select>,
                  )}
                  {texto('puerto', 'Puerto', { placeholder: 'Ej.: D17' })}
                </div>
                <p className="formulario__ayuda">
                  El prefijo del puerto indica el servicio: D datos, T telefonía, C CCTV. Sin rack ni
                  puerto queda como «sin rótulo», para completarlo después con el tester.
                </p>
              </>
            )}

            {propuesto && (
              <p
                className={propuesto.disponible ? 'formulario__codigo' : 'formulario__aviso'}
                role="status"
              >
                {propuesto.disponible ? 'Se registrará como ' : 'Ya existe '}
                <strong>{propuesto.codigo}</strong>
                {!propuesto.disponible &&
                  (propuesto.eliminado
                    ? ', eliminado: recupéralo desde «Ver eliminados», los códigos no se reutilizan.'
                    : ': ese puerto ya está documentado.')}
              </p>
            )}

            <h3 className="subtitulo">Ubicación</h3>
            {texto('ubicacion_descriptiva', 'Ubicación (recinto)', {
              placeholder: 'Ej.: Oficina 1083',
            })}
            {campo(
              'numero_recinto',
              'N° de recinto',
              <>
                <input
                  type="text"
                  inputMode="decimal"
                  list="recintos-alta"
                  value={base.numero_recinto}
                  placeholder="Ej.: 1083"
                  onChange={(e) => cambiar('numero_recinto', e.target.value)}
                />
                <datalist id="recintos-alta">
                  {recintos.map((r) => (
                    <option key={`${r.plano_id}-${r.numero}`} value={r.numero}>
                      {r.nombre ?? ''}
                    </option>
                  ))}
                </datalist>
              </>,
              'Con el número de una sala del plano, queda ubicado ahí. Sin él, podrás marcarlo con un clic.',
            )}
            {admiteRack &&
              campo(
                'padre_codigo',
                'Rack',
                <select
                  value={base.padre_codigo}
                  onChange={(e) => cambiar('padre_codigo', e.target.value)}
                >
                  <option value="">— Sin rack —</option>
                  {opcionesPadre.map((o) => (
                    <option key={o.valor} value={o.valor}>
                      {o.etiqueta}
                    </option>
                  ))}
                </select>,
                soloConectado
                  ? 'Un AP o una UPS solo se conecta al rack y tiene su propio marcador.'
                  : 'Montado en un rack, se ve a través de él en el plano.',
              )}
            {admiteRack &&
              base.padre_codigo !== '' &&
              !soloConectado &&
              texto('unidad_rack', 'Unidad de rack (U)', { placeholder: 'Ej.: 12' })}

            <h3 className="subtitulo">Identificación y estado</h3>
            {texto('etiqueta', 'Etiqueta', {
              ayuda: sinCorrelativo ? 'Vacía: el rótulo que resulta del rack y el puerto.' : undefined,
            })}
            {selector('estado_operativo', 'Estado operativo', enumeraciones?.estado_operativo ?? [])}
            <div className="formulario__fila">
              {selector('estado_condicion', 'Condición', enumeraciones?.estado_condicion ?? [], '—')}
              {selector('criticidad', 'Criticidad', enumeraciones?.criticidad ?? [], '—')}
            </div>

            {!sinCorrelativo && (
              <>
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
              </>
            )}
            {texto('fecha_instalacion', 'Fecha de instalación', { tipo: 'date' })}

            {fichaVisible.length > 0 && (
              <>
                <h3 className="subtitulo">Ficha de {tipo.nombre.toLowerCase()}</h3>
                <p className="formulario__ayuda">
                  Lo marcado con * es lo que pide el SOP: puedes agregarlo ahora y completarlo
                  después.
                </p>
                {fichaVisible.map((definicion) =>
                  campo(
                    `atributos.${definicion.clave}`,
                    definicion.etiqueta +
                      (definicion.unidad ? ` (${definicion.unidad})` : '') +
                      (definicion.obligatorio ? ' *' : ''),
                    <ControlAtributo
                      definicion={definicion}
                      valor={atributos[definicion.clave] ?? ''}
                      onCambio={(v) => setAtributos((a) => ({ ...a, [definicion.clave]: v }))}
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
                onChange={(e) => cambiar('observaciones', e.target.value)}
              />,
            )}
            {campo(
              'usuario',
              'Registrado por',
              <input type="text" value={usuario} onChange={(e) => setUsuario(e.target.value)} />,
            )}
          </>
        )}

        <div className="formulario__acciones">
          <button type="button" className="boton boton--secundario" onClick={cerrar} disabled={guardando}>
            Cancelar
          </button>
          <button
            type="button"
            className="boton boton--secundario"
            onClick={() => void guardar(true)}
            disabled={!puedeGuardar}
            title="Guarda este y deja el formulario listo para el siguiente"
          >
            Agregar y seguir
          </button>
          <button type="submit" className="boton" disabled={!puedeGuardar}>
            {guardando ? 'Guardando…' : 'Agregar'}
          </button>
        </div>
      </form>
    </section>
  )
}
