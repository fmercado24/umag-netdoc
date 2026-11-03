/**
 * Documentación interactiva de la API (/docs). Se compila con el visor en vez
 * de traerse de un CDN: ese JavaScript corre con la sesión del administrador.
 */

import 'swagger-ui-dist/swagger-ui.css'
// @ts-expect-error el paquete no trae tipos
import SwaggerUI from 'swagger-ui-dist/swagger-ui-es-bundle.js'

SwaggerUI({ url: '/openapi.json', dom_id: '#swagger-ui' })
