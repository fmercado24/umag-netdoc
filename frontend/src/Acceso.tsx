/** Puerta del visor: sin la sesión del administrador solo se ve el ingreso. */

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { api, avisarSesionVencida, ErrorApi } from './api/cliente'
import App from './App'
import logoUmag from './assets/logo-umag.png'

function PantallaIngreso({ onIngreso }: { onIngreso: (usuario: string) => void }) {
  const [usuario, setUsuario] = useState('')
  const [clave, setClave] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const ingresar = (evento: FormEvent) => {
    evento.preventDefault()
    setError(null)
    setEnviando(true)
    api
      .ingresar(usuario.trim(), clave)
      .then((sesion) => onIngreso(sesion.usuario))
      .catch((e) => {
        setClave('')
        setError(e instanceof ErrorApi ? e.message : 'No se pudo conectar con la API')
        setEnviando(false)
      })
  }

  return (
    <main className="ingreso">
      <form className="ingreso__tarjeta" onSubmit={ingresar}>
        <img className="ingreso__logo" src={logoUmag} alt="Universidad de Magallanes" />
        <div className="marca">
          <span className="marca__sigla">NetDoc</span>
          <span className="marca__sub">Infraestructura de red · UMAG</span>
        </div>

        <label className="campo">
          <span>Usuario</span>
          <input
            value={usuario}
            autoComplete="username"
            autoFocus
            required
            onChange={(e) => setUsuario(e.target.value)}
          />
        </label>

        <label className="campo">
          <span>Contraseña</span>
          <input
            type="password"
            value={clave}
            autoComplete="current-password"
            required
            onChange={(e) => setClave(e.target.value)}
          />
        </label>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button className="boton" type="submit" disabled={enviando}>
          {enviando ? 'Ingresando…' : 'Ingresar'}
        </button>
      </form>
    </main>
  )
}

export function Acceso() {
  const [usuario, setUsuario] = useState<string | null>(null)
  const [verificando, setVerificando] = useState(true)

  useEffect(() => {
    avisarSesionVencida(() => setUsuario(null))
    api
      .sesion()
      .then((sesion) => setUsuario(sesion.usuario))
      .catch(() => setUsuario(null))
      .finally(() => setVerificando(false))
  }, [])

  if (verificando) return <div className="cargando">Verificando la sesión…</div>
  if (!usuario) return <PantallaIngreso onIngreso={setUsuario} />

  const salir = () => {
    api
      .salir()
      .catch(() => undefined)
      .finally(() => setUsuario(null))
  }

  return <App usuario={usuario} onSalir={salir} />
}
