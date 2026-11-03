# Seguridad de NetDoc

Para quien administre NetDoc en la DSI: cómo operar la contraseña, los bloqueos,
HTTPS y los tokens, qué controles hay y qué **no** cubren. NetDoc guarda la
topología de la red, sus IP de gestión y los planos de los edificios: es
información que ayudaría a atacarla, y por eso no se muestra a nadie sin ingresar.

## Operación

### Contraseña del administrador

Hay un único usuario, `admin-netdoc`. Su contraseña no está en el repositorio, ni
siquiera como hash: el hash vive en `.env`, en la raíz del proyecto, que git ignora
y que queda legible solo para el usuario que corre NetDoc. `iniciar.sh` la pide la
primera vez. Sin ella, nadie puede ingresar. **Al instalar NetDoc en otro equipo
hay que volver a definirla:** el `.env` no viaja con el repositorio.

Para cambiarla, lo que además cierra todas las sesiones y levanta los bloqueos:

```bash
cd backend
.venv/bin/python -m app.scripts.definir_clave
# y reiniciar NetDoc (Ctrl+C y ./iniciar.sh) para que la tome
```

Pide al menos 8 caracteres y avisa si son menos de 15, que es lo recomendado. Con
un solo factor de autenticación, el largo es lo que más protege.

### Si se bloquea el ingreso

El tercer intento fallido desde un equipo lo bloquea por 15 minutos, y durante el
bloqueo tampoco sirve la contraseña correcta. Reiniciar NetDoc no lo levanta: los
intentos se cuentan en la base. Desde el servidor se levanta de inmediato:

```bash
cd backend && .venv/bin/python -m app.scripts.definir_clave --desbloquear
```

Si se reciben 30 intentos fallidos en 15 minutos entre todos los equipos, el ingreso
se bloquea para todos: es lo que frena un ataque repartido entre muchas direcciones.
El registro de la API (`backend/netdoc.log`, legible solo para su dueño) anota cada
intento fallido y cada ingreso, con la IP de origen y sin lo que se escribió:

```
WARNING app.servicios.autenticacion: Ingreso fallido (2 de 3): 10.0.0.5
```

Los límites se ajustan con `NETDOC_INGRESO_INTENTOS`,
`NETDOC_INGRESO_INTENTOS_GLOBALES` y `NETDOC_INGRESO_BLOQUEO_MINUTOS`.

### Acceso desde otros equipos (HTTPS)

Con `./iniciar.sh`, NetDoc atiende por HTTP en `127.0.0.1`: el tráfico no sale del
equipo. Con `NETDOC_API_HOST=0.0.0.0 ./iniciar.sh` atiende en la red **solo por
HTTPS**, en `https://<servidor>:8000`. La API además rechaza por sí misma lo que
llegue de otro equipo sin HTTPS, aunque se la levante a mano.

Si no hay certificado, `iniciar.sh` genera uno autofirmado en
`backend/certs/netdoc.crt`, válido por 397 días para `localhost`,
`host.docker.internal` y el nombre y las IP del equipo. El navegador pedirá
aceptarlo la primera vez. Para producción, use un certificado de la institución:
deje el certificado y su clave en `backend/certs/netdoc.crt` y
`backend/certs/netdoc.key`, y reinicie. Un certificado que venció detiene el
arranque; para generar otro autofirmado, borre esos dos archivos.

En un servidor, `instalar-servidor.sh` deja esto resuelto, con nginx delante y NetDoc como un
servicio sin privilegios: ver la [guía de instalación](instalacion-servidor.md).

### Detrás de un proxy propio

Si un proxy (nginx, Caddy) termina el HTTPS, NetDoc necesita creerle lo que informa
sobre el cliente: la IP, con la que cuenta los intentos, y que llegó por HTTPS, de lo
que depende la cookie segura. Se le indica cuál es su proxy:

```bash
NETDOC_PROXY_CONFIABLE=127.0.0.1 ./iniciar.sh
```

El proxy debe enviar `X-Forwarded-For` y `X-Forwarded-Proto`. **Sin esa variable, NetDoc
ignora esas cabeceras**, porque cualquiera podría falsearlas para esquivar el límite de
intentos; con ella, si el proxy no las envía, todos los clientes contarían como uno solo.

### Sistemas externos

Prometheus, Alertmanager, Zabbix, NetBox y GLPI no pueden iniciar sesión: usan
`NETDOC_MONITOREO_TOKEN`, en `Authorization: Bearer` o `X-NetDoc-Token`. Solo abre los
webhooks de monitoreo y las lecturas de `/metrics` y `/api/v1/integraciones/`; el resto
de la API, los planos y las fotos siguen exigiendo la sesión. Se genera con
`openssl rand -hex 24`, va en `.env` y no se escribe en los archivos de `deploy/`, que
están versionados: Docker lo entrega a los contenedores desde `.env`. Para cambiarlo,
modifíquelo en `.env` y en Zabbix, y reinicie NetDoc y los contenedores.

Prometheus, Alertmanager, Grafana y Adminer se publican solo en `127.0.0.1`, porque
los dos primeros no piden credenciales y muestran las IP del inventario. Desde otro
equipo se accede con un túnel SSH
([manual de monitoreo](manual-monitoreo.md#opción-a-prometheus--alertmanager--grafana-con-docker)).

### Mantener las dependencias al día

Las versiones están fijadas con sus sumas en `backend/requirements.lock` y
`frontend/package-lock.json`, así que **no se actualizan solas**: conviene revisarlas
de forma periódica.

```bash
cd backend
.venv/bin/python -m pip install pip-audit uv
.venv/bin/pip-audit -r requirements.lock --require-hashes --disable-pip   # lo vulnerable
.venv/bin/uv pip compile requirements.txt --universal --generate-hashes \
  --python-version 3.11 --no-header --upgrade -o requirements.lock        # actualiza

cd ../frontend
npm audit       # lo vulnerable
npm audit fix   # actualiza
```

Después, correr las pruebas y `./iniciar.sh`, que instala lo que cambió.

## Controles

No es una certificación ni reemplaza una auditoría: es lo que está implementado,
siguiendo las recomendaciones vigentes de OWASP (ASVS, Top 10 y las guías de
autenticación, contraseñas y sesiones) y de NIST SP 800-63B. Las pruebas están en
`backend/tests/test_autenticacion.py`, `test_proteccion.py` y `test_definir_clave.py`.

| Riesgo | Control | Dónde |
|---|---|---|
| Uso sin autenticarse | Todo se rechaza salvo lo exceptuado explícitamente: una ruta nueva nace protegida. Sin sesión solo responden la pantalla de ingreso con sus recursos, `/salud` y los webhooks | `servicios/proteccion.py` |
| Secreto en el repositorio | El hash vive en `.env`; el código no trae valor por omisión, y sin él nadie ingresa. Las claves de Docker tampoco tienen valor por omisión | `core/config.py`, `scripts/definir_clave.py`, `docker-compose.yml` |
| Robo de la base o de `.env` | Contraseña con Argon2id (64 MiB). Las sesiones se guardan como SHA-256 de un token aleatorio de 256 bits | `servicios/autenticacion.py` |
| Fuerza bruta | 3 intentos por equipo y 30 entre todos, en una ventana de 15 minutos. Se cuentan en la base y antes de verificar la clave, de modo que ni un reinicio ni peticiones simultáneas dan más intentos. Una red IPv6 /64 cuenta como un solo equipo | `servicios/autenticacion.py` |
| Agotar memoria con el ingreso | Verificar la clave es lo caro, y el límite de intentos lo acota. Un cuerpo mayor a 1 MiB se rechaza antes de leerlo | `servicios/proteccion.py` |
| Sesión robada o abandonada | Cookie `HttpOnly`, `SameSite=Strict` y, por HTTPS, `Secure` con prefijo `__Host-`. Vence a los 30 minutos sin actividad y a las 12 horas. **Salir** y cambiar la contraseña la invalidan en el servidor | `servicios/autenticacion.py`, `api/v1/autenticacion.py` |
| Escuchar el tráfico | Hacia la red, solo HTTPS (TLS 1.2 o superior, con secreto perfecto hacia adelante) y HSTS. La API rechaza lo que llegue de otro equipo sin HTTPS | `iniciar.sh`, `servicios/proteccion.py` |
| Falsificación de peticiones (CSRF) | La cookie no viaja desde otro sitio; las escrituras además comprueban `Sec-Fetch-Site` u `Origin`. No hay CORS: el navegador habla con un solo origen | `servicios/proteccion.py` |
| Inyección de scripts (XSS) | CSP sin scripts en línea, sin `eval` y sin orígenes externos. Las URL de ids externos solo admiten `http(s)`. `X-Content-Type-Options: nosniff` en todo | `servicios/proteccion.py`, `schemas/elemento.py` |
| SVG con script subido como plano | Abierto directamente se sirve con CSP `sandbox`, sin ejecutar nada; como imagen, el navegador no ejecuta scripts | `servicios/proteccion.py` |
| Incrustar NetDoc en otro sitio | `frame-ancestors 'none'`, `X-Frame-Options`, `Cross-Origin-Resource-Policy` | `servicios/proteccion.py` |
| Archivos maliciosos o enormes | Se comprueba que el contenido corresponda a su extensión, y que un SVG sea un SVG. Máximo 100 MB, antes de leerlo. Los nombres en disco los genera NetDoc | `servicios/archivos.py`, `servicios/planos.py` |
| Fuga de información | `/salud` no expone errores internos, los errores de validación no devuelven lo recibido (podría ser la contraseña), sin cabecera `Server`. Lo que exige sesión no se sirve desde una caché sin volver a comprobarla | `main.py`, `servicios/proteccion.py`, `iniciar.sh` |
| Código de terceros alterado | Versiones y sumas fijadas en ambos lados, verificadas al instalar. Swagger UI se compila con el visor en vez de cargarse de un CDN. La API sirve el visor compilado, no el servidor de desarrollo de Vite | `backend/requirements.lock`, `iniciar.sh`, `frontend/src/docs.ts` |
| Exposición por servicios auxiliares | Prometheus, Alertmanager, Grafana, Adminer y PostgreSQL se publican solo en `127.0.0.1` | `docker-compose.yml` |
| Privilegios de más | `iniciar.sh` usa `sudo` solo para instalar paquetes y se niega a correr como root; la API corre con el usuario normal. Lo que crea queda legible solo para ese usuario | `iniciar.sh` |
| Ataques que pasan inadvertidos | Cada ingreso, intento fallido y bloqueo queda en el registro, con la IP de origen | `servicios/autenticacion.py` |

## Lo que no cubre

Son decisiones abiertas, en orden de lo que más reduciría el riesgo:

1. **Una contraseña es un solo factor, y la cuenta es compartida.** No hay segundo factor
   (TOTP o WebAuthn), que es lo que hoy se espera de una cuenta de administrador. Y como
   todos usan la misma cuenta, el registro dice desde qué equipo se hizo algo, pero no
   quién. Integrar el directorio de la UMAG (LDAP u OIDC) resolvería ambas cosas.
2. **El largo de la contraseña.** El límite de intentos protege de quien prueba por la
   pantalla de ingreso, no de quien obtenga `.env`, que podría probar sin límite contra el
   hash. Una contraseña corta o con un patrón predecible se puede adivinar así, a pesar de
   Argon2id. Por eso se recomiendan 15 caracteres o más.
3. **La base y los archivos no están cifrados en disco.** Inventario, planos y fotos
   quedan protegidos por los permisos del sistema, no por cifrado: un respaldo o un disco
   robado los expone. Conviene cifrar el disco y los respaldos.
4. **El certificado autofirmado solo cifra.** El navegador no puede saber si habla con el
   servidor verdadero, y acostumbrarse a aceptar su advertencia es justo lo que aprovecharía
   un atacante en la red. En producción, use un certificado de la institución.
5. **Es un bloqueo por equipo.** Quien comparta IP con el atacante (detrás de un NAT, o de
   un proxy mal indicado) también queda bloqueado. Y quien acumule 30 fallos desde varias
   direcciones puede dejar el ingreso bloqueado para todos mientras insista, aunque las
   sesiones abiertas siguen funcionando.
6. **Los planos ya abiertos.** Lo que el navegador ya mostró puede quedar en la memoria o el
   disco del equipo. Conviene no usar NetDoc en equipos compartidos.
