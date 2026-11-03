import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { Acceso } from './Acceso'
import './index.css'

const contenedor = document.getElementById('root')
if (!contenedor) throw new Error('No se encontró el elemento #root')

createRoot(contenedor).render(
  <StrictMode>
    <Acceso />
  </StrictMode>,
)
