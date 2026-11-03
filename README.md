# NetDoc UMAG

Sistema de documentación visual interactiva de infraestructura de red para
instituciones multi-edificio — caso Universidad de Magallanes.

Implementa la metodología definida en **SOP-DSI-RED-001** y los entregables de
la propuesta de memoria *"Diseño e implementación de una metodología y sistema
de documentación visual interactiva de infraestructura de red para
instituciones multi-edificio: caso UMAG"*.

## Guías para la DSI

| Guía | Para qué |
|---|---|
| [Incorporar un edificio](docs/guia-nuevo-edificio.md) | Paso a paso desde el levantamiento en terreno hasta ver el edificio en el visor: planillas, láminas, importación, ubicación de racks y puntos de datos, completar fichas y sumar tramos después |
| [Manual de monitoreo](docs/manual-monitoreo.md) | Instalar y operar Prometheus, Alertmanager y Grafana, y conectar Zabbix, para que el estado de los equipos se actualice solo |
| [Plantillas del levantamiento](data/_plantilla/) | Planillas de ejemplo para copiar en `data/<código>/` |
| [Integraciones y escalabilidad](docs/integraciones.md) | Referencia técnica: métricas, APIs de inventario, conectores, PostgreSQL |
| [Instalar en un servidor](docs/instalacion-servidor.md) | Dejar NetDoc en un servidor Ubuntu con `instalar-servidor.sh`, con SQLite o PostgreSQL: requisitos, HTTPS, respaldos, actualización y problemas frecuentes |
| [Seguridad](docs/seguridad.md) | Contraseña, bloqueos, HTTPS y tokens: cómo operarlos, qué controles hay y qué no cubren |

## Arquitectura

Construcción desde cero (no extensión de NetBox):

| Capa | Tecnología | Por qué |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite | Tipado compartido con los esquemas del backend |
| Visor de planos | Leaflet con `CRS.Simple` | El plano se monta como capa base y las coordenadas son píxeles del plano, sin proyección geográfica |
| Backend | FastAPI + SQLAlchemy 2.0 + Pydantic v2 | Validación declarativa de fichas y OpenAPI generado automáticamente |
| Base de datos | SQLite (desarrollo) → PostgreSQL | Modelo portable: `JSONB` en PostgreSQL, `JSON` en SQLite |
| Migraciones | Alembic | El mismo esquema versionado en SQLite y PostgreSQL; `render_as_batch` para los `ALTER TABLE` de SQLite |
| Acceso | Argon2id, sesiones en la base, CSP, HTTPS | Un único administrador y nada accesible sin él; ver [docs/seguridad.md](docs/seguridad.md) |
| Integraciones | Prometheus, Alertmanager, Grafana, Zabbix | Métricas, descubrimiento de objetivos, webhooks de estado y conector de hosts; ver [docs/integraciones.md](docs/integraciones.md) |
| Lectura de láminas | RapidOCR (opcional, `requirements-ocr.txt`) | Lee los números de sala y los rótulos de racks de las láminas de CAD, cuyo texto viene convertido en trazos. Solo lo necesita quien prepara las láminas |

```
umag-netdoc/
├── iniciar.sh           Prepara y levanta todo: paquetes del sistema, visor, base, edificios nuevos y API
├── instalar-servidor.sh Instala o actualiza NetDoc en un servidor Ubuntu, con SQLite o PostgreSQL
├── backend/
│   ├── app/
│   │   ├── models/      Modelo de datos (SQLAlchemy)
│   │   ├── schemas/     Contratos de entrada y salida (Pydantic)
│   │   ├── servicios/   Acceso, nomenclatura, validación, historial, recintos, monitoreo, métricas
│   │   ├── integraciones/ Conectores con otros sistemas (Zabbix)
│   │   ├── api/v1/      Routers HTTP
│   │   └── scripts/     Migraciones, catálogo, importación de edificios, láminas, recintos, fotos, sincronización
│   ├── alembic/         Migraciones versionadas
│   └── tests/           360 pruebas (pytest)
├── frontend/src/
│   ├── api/             Cliente HTTP tipado
│   ├── components/      Barra, panel lateral, visor de plano, ficha
│   └── types/           Espejo de los esquemas del backend
├── data/cadi/           Planillas y láminas originales del levantamiento del CADI
├── data/_plantilla/     Plantillas para el levantamiento de otros edificios
├── deploy/              Prometheus, Alertmanager, Grafana, Zabbix y el comando netdoc del servidor
└── docs/                Guías de la DSI, modelo de datos, nomenclatura, hallazgos e integraciones
```

## Las planillas del CADI

| Archivo | Contenido |
|---|---|
| `cadi-p<piso>-t<tramo>.csv` (9) | Equipamiento por tramo, del subterráneo (`cadi-p00.csv`) al Piso 4 — **fuente autoritativa**, porque traen la ubicación descriptiva que el SOP §9.1 exige |
| `cadi-puntos-de-datos.csv` | 308 puntos de datos (la planilla también los llama "rosetas"), cada uno con el rótulo que codifica piso, tramo, rack y puerto (`SUB-R11-D05` en el subterráneo), y el recinto donde está |
| `cadi-global.csv` | Consolidado histórico. **No se importa**: se usa solo para contrastar y reportar diferencias |
| `cadi-vlans.csv` | Leyenda de VLANs del edificio y la VLAN por omisión de cada servicio |
| `cadi-laminas.csv` | Lo rotulado P01-T3 que está dibujado en otra lámina (ver hallazgo 8) |
| `cadi-levantamiento.csv` | Fechas de las visitas a terreno (pisos 1 a 4 el 15 y 16 de septiembre de 2026; subterráneo el 15 de octubre): dan la fecha del último levantamiento de cada elemento |
| `planos/*.svg` (9) | Láminas de cableado estructurado de la DSI, exportadas desde CAD (2853,6×2018,4): una por tramo en los pisos 1 a 3, una para el piso 4 y otra para el subterráneo. Se llaman según la nomenclatura obligatoria (`cadi-p01-t1.svg`, `cadi-p04.svg`, `cadi-p00.svg`) y `./iniciar.sh` las carga en `backend/media/planos/` |
| `cadi-recintos.csv` | 274 números de sala y 6 rótulos de racks leídos de las láminas con `extraer_recintos`: con ellos cada elemento se ubica solo en su recinto |

El importador deja un informe de discrepancias en cada ejecución, y la carga
de láminas cruza las planillas con los recintos de cada lámina. Los hallazgos
están analizados en [docs/hallazgos-cadi.md](docs/hallazgos-cadi.md): 2 rótulos
duplicados pendientes, 6 puntos de datos sin rótulo, un switch que declara el
rack de otro piso y 7 números de sala de las planillas que no aparecen en las
láminas (la Recepción 1063, por ejemplo, es la 1082 en el plano).

Otros edificios se cargan con el mismo formato en `data/<código>/`: ver la
[guía para incorporar un edificio](docs/guia-nuevo-edificio.md).

## Puesta en marcha

Esto es para trabajar en un equipo propio. Para dejar NetDoc en un servidor, con su
servicio, HTTPS y respaldos, ver la
[guía de instalación en un servidor](docs/instalacion-servidor.md).

### Arranque rápido

```bash
./iniciar.sh                  # prepara lo que falte y levanta NetDoc
./iniciar.sh --sin-navegador  # igual, sin abrir el navegador
```

La primera vez instala con `sudo` los paquetes del sistema que falten (en Ubuntu,
con apt: `python3-venv`, Node.js, curl y openssl; en 24.04, cuyo Node es muy
antiguo, el oficial de nodejs.org en `/usr/local`). Es lo único que requiere
permisos de administrador: NetDoc corre con tu usuario, así que el script **no**
se ejecuta con `sudo`. Después crea el entorno de Python, instala las dependencias
de ambos lados con sus versiones y sumas fijadas, compila el visor, crea la base
con el catálogo, pide la contraseña del administrador, importa cada edificio que
tenga carpeta en `data/` (hoy el CADI) y carga sus láminas y fotografías. Las
siguientes veces aplica las migraciones pendientes, solo reinstala o recompila si
algo cambió, importa los edificios **nuevos**, carga las fotos nuevas y revisa
todas las láminas: una nueva o modificada en `data/<código>/planos` entra como
versión nueva (ver [Cargar el plano de un piso](#cargar-el-plano-de-un-piso)).
Nunca reimporta elementos ni reemplaza sus datos. También genera las teselas que
falten: cada plano pre-dibujado en imágenes chicas, para que el visor se mueva con
fluidez sobre láminas de CAD pesadas (de 5 a 20 s por lámina, una sola vez; ver
[modelo de datos](docs/modelo-datos.md#teselas)).

Deja NetDoc en <http://localhost:8000>, solo para este equipo: la API sirve también
el visor, de modo que el navegador habla con un solo origen. **Deja abierta esa
terminal:** al cerrarla o con **Ctrl+C**, NetDoc se detiene, y el visor abierto avisa
que no hay conexión hasta que vuelvas a ejecutar `./iniciar.sh`, sin tener que volver
a ingresar. Lo que la API informa queda además en `backend/netdoc.log` (el de la
ejecución anterior, en `netdoc.anterior.log`).
Con `NETDOC_API_HOST=0.0.0.0` atiende en la red (lo necesita el
[monitoreo](docs/manual-monitoreo.md)) y entonces **solo por HTTPS**, con un
certificado propio o, si no hay, uno autofirmado que genera en `backend/certs/`.

### Acceso

El sistema tiene un único usuario, el administrador `admin-netdoc`, y no se puede
usar sin ingresar con él: la API rechaza toda petición sin sesión, incluidos los
planos, las fotografías y la documentación interactiva. Detalle en
[docs/seguridad.md](docs/seguridad.md).

- **Contraseña.** No está en el repositorio, ni siquiera su hash: vive en `.env`,
  que no se versiona. `iniciar.sh` la pide la primera vez. Para cambiarla, lo que
  además cierra todas las sesiones:

  ```bash
  cd backend && .venv/bin/python -m app.scripts.definir_clave   # y reiniciar NetDoc
  ```
- **Intentos.** El tercer intento fallido bloquea el ingreso desde ese equipo por
  15 minutos; reiniciar no lo levanta. Desde el servidor, `definir_clave
  --desbloquear` lo levanta de inmediato.
- **Sesión.** Vence a los 30 minutos sin actividad y a las 12 horas en cualquier
  caso. **Salir**, en la barra superior, la invalida en el servidor.
- **Otros sistemas.** Los que no pueden iniciar sesión usan
  `NETDOC_MONITOREO_TOKEN`: los webhooks de monitoreo y las lecturas de `/metrics` y
  `/api/v1/integraciones/` (ver [integraciones](docs/integraciones.md)).

Los pasos por separado, por si se necesita alguno suelto:

### Backend

Requiere Python 3.11 o superior.

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock

# Esquema (migraciones de Alembic) + catálogo (19 edificios, 14 tipos)
.venv/bin/python -m app.scripts.migrar
.venv/bin/python -m app.scripts.cargar_catalogo

# Contraseña del administrador: su hash queda en .env, fuera del repositorio
.venv/bin/python -m app.scripts.definir_clave

# Importar un edificio desde data/<código>/ (el CADI: 389 elementos, 313 enlaces, 4 VLANs)
.venv/bin/python -m app.scripts.importar_edificio CADI
.venv/bin/python -m app.scripts.importar_edificio CADI --solo-advertencias  # ensayo, no modifica
.venv/bin/python -m app.scripts.importar_edificio CADI --agregar           # suma tramos nuevos
.venv/bin/python -m app.scripts.importar_edificio CADI --recargar          # reemplaza todo: se pierden
                                                         # posiciones, historial y lo agregado en el visor
.venv/bin/python -m app.scripts.importar_edificio --pendientes             # todos los edificios nuevos

# Láminas: revisar/orientar, leer sus recintos (OCR) y cargar las que no
# tienen plano vigente. Al cargarlas, cada elemento queda en su recinto
.venv/bin/python -m app.scripts.preparar_laminas CADI [--aplicar]
.venv/bin/python -m pip install -r requirements-ocr.txt      # una vez, solo para leer láminas
.venv/bin/python -m app.scripts.extraer_recintos CADI [cadi-p01-t2.svg]
.venv/bin/python -m app.scripts.cargar_planos [CADI]

# Fotografías de data/<código>/fotos (nombradas con el código del elemento)
.venv/bin/python -m app.scripts.cargar_fotografias [CADI]

# Diagrama de la base para dbdiagram.io (tras cambiar el esquema)
.venv/bin/python -m app.scripts.exportar_dbml -o ../docs/modelo-datos.dbml

.venv/bin/python -m uvicorn app.main:app --reload
```

API y visor compilado en <http://localhost:8000>; documentación interactiva, tras
ingresar, en <http://localhost:8000/docs>.

> En Ubuntu, si `python3 -m venv` crea el entorno sin `pip`, instala
> `python3-venv` (`sudo apt install python3-venv`) o arranca pip dentro del
> entorno con `curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python`.

### Frontend

Requiere Node.js 20.19, 22.12 o superior. `iniciar.sh` compila el visor y la API lo
sirve. Para trabajar en él con recarga automática, con la API corriendo:

```bash
cd frontend
npm ci
npm run dev
```

Visor de desarrollo en <http://localhost:5173>: Vite le reenvía a la API lo que no
es del visor, y el navegador sigue viendo un solo origen. `npm run build` genera el
bundle de producción y `npm run typecheck` valida los tipos sin compilar.

### Pruebas

```bash
cd backend
.venv/bin/python -m pip install -r requirements-dev.txt   # una vez
.venv/bin/python -m pytest -q
```

## Cargar el plano de un piso

El visor necesita un plano para poder posicionar elementos. Las dimensiones se
indican explícitamente porque **fijan el sistema de coordenadas**: las
posiciones de los elementos se guardan en esas unidades y sobreviven a que el
archivo se reemplace por una versión reescalada.

```bash
# Se ingresa una vez y se reutiliza la cookie de sesión. La contraseña se lee de la
# terminal y va por la entrada estándar: así no queda en el historial.
read -rs CLAVE
printf '{"usuario": "admin-netdoc", "clave": "%s"}' "$CLAVE" | curl -c sesion.txt \
  -H "Content-Type: application/json" -d @- http://localhost:8000/api/v1/auth/ingresar

curl -b sesion.txt -X POST http://localhost:8000/api/v1/edificios/CADI/pisos/P01/plano \
  -F "archivo=@cadi-p01.svg" \
  -F "ancho_px=2000" -F "alto_px=1400" \
  -F "nombre=CADI Piso 1"
```

El nombre del archivo debe seguir la nomenclatura de las láminas,
`<edificio>-p<piso>[-t<tramo>].<ext>` (ver la
[guía, sección 4](docs/guia-nuevo-edificio.md#4-láminas-planos)), y
corresponder al destino. Si no, la API responde 422 indicando el nombre que
corresponde. Si la lámina cubre un solo tramo, se agrega `-F "tramo=T2"` y el
archivo se llama `cadi-p01-t2.svg`. Cada tramo tiene
su propio plano vigente y el visor ofrece elegirlo en la barra superior; un
tramo sin lámina propia se ve sobre el plano del piso completo.

Lo habitual es no usar la API, sino dejar las láminas en
`data/<código>/planos/`: `./iniciar.sh` (o `app.scripts.cargar_planos`) deduce
edificio, piso y tramo del nombre, compara cada archivo con las versiones
registradas y carga los nuevos y los modificados. Los archivos con un nombre
fuera de la nomenclatura se informan y no se cargan. Al cambiar una lámina, la anterior queda como versión histórica y
los elementos ubicados sobre ella pasan a la nueva **si el tamaño es el mismo**.
Si cambió, el dibujo es otro (otro encuadre u otra escala) y no hay forma
segura de trasladar las posiciones: esos elementos quedan sin ubicar, el
comando los lista y las coordenadas anteriores quedan en su historial. La
carga por la API sigue la misma regla.

La vista de un tramo muestra lo dibujado en su lámina, que no siempre coincide
con el tramo del código: en el Piso 1, lo rotulado T3 salvo el auditorio está
en la lámina del tramo 1 (ver [hallazgo 8](docs/hallazgos-cadi.md)). La lámina
de un elemento se cambia desde su ficha. Los puntos de datos ubicados en el
mismo lugar se agrupan en un solo marcador; para agregar uno a un grupo, al
ubicarlo se hace clic sobre el marcador existente.

Los SVG exportados desde PDF suelen traer caracteres de control que XML no
admite, y el navegador los descarta enteros. El backend los elimina al cargar
el plano y rechaza con 422 el SVG que aun así no sea XML válido. Cada carga
se guarda con su número de versión, así que el plano histórico no se pisa.

Luego, en el visor: selecciona un elemento → **Ubicar en el plano** → clic
sobre la posición. El sistema guarda `(x, y)` y deja la entrada correspondiente
en el historial.

## Ubicación automática por recinto

Casi nada hay que ubicarlo a mano. Cada sala de los planos lleva su número bajo
el nombre, y el número dice el piso (`0017` en el subterráneo, `1083` en el
primer piso, `2041` en el segundo…). Las planillas anotan ese mismo número en
la ubicación de cada elemento, así que el sistema lo dibuja en su sala:

1. `extraer_recintos` lee con OCR los números de sala y los rótulos de racks
   («RACK 08») de cada lámina y los deja en `data/<código>/<código>-recintos.csv`,
   amarrados a la versión de la lámina que se leyó.
2. Al importar y al cargar láminas (`./iniciar.sh` lo hace en cada arranque),
   cada elemento sin posición va a su recinto: los puntos de datos de una sala
   en un solo marcador que se despliega, cada rack sobre su rótulo y los demás
   equipos uno junto al otro. Un AP o una UPS en una sala sin número en la
   lámina (las salas eléctricas del CADI) queda junto al rack de su sala.
3. Lo que no se pudo ubicar se lista, con una sugerencia cuando el nombre se
   parece a otro recinto de la lámina. En el visor, *Editar → N° de recinto*
   lo ubica al guardar, y *Ubicar en su recinto* devuelve a su sala lo que se
   movió a mano.

Lo que ya tiene posición nunca se mueve solo. Detalle en
[docs/modelo-datos.md](docs/modelo-datos.md#ubicación-por-recinto) y paso a
paso en la [guía, sección 4.1](docs/guia-nuevo-edificio.md#41-recintos-los-números-de-sala-de-cada-lámina).

## Agregar un elemento

Para lo que se instala después del levantamiento (un switch nuevo, puntos de datos,
un access point), **+ Agregar elemento**, en el panel izquierdo. Se elige el tipo, el
piso y el tramo, y el formulario pide lo que corresponde a ese tipo; la ficha sale del
catálogo, así que un tipo nuevo se agrega sin tocar el código. Antes de guardar muestra
el código que recibirá, según la convención del SOP:

- **Con correlativo** (switch, rack, AP…): el siguiente de ese tipo en el piso,
  `CADI-SW09-P01-T1`. Un número dado de baja no se reutiliza.
- **Punto de datos:** se identifica por su rack y puerto, `CADI-PD-P01-T1-R01-D90`. De
  ahí salen también el rótulo (`P01-T1-R1-D90`), el servicio (`D` datos, `T` telefonía,
  `C` CCTV) y el enlace rack → punto de datos, igual que al importar una planilla. Si el
  puerto ya está documentado, avisa antes de guardar. Si aún no se sabe de dónde viene,
  queda como `CADI-PD-P01-T1-SIN-ROTULO-01`.

Con el número de una sala del plano queda ubicado ahí; montado en un rack, se ve a través
de él; si no, la vista va a su piso y un clic en el plano lo deja en su lugar. **Agregar y
seguir** guarda y deja el formulario listo para el siguiente, con el puerto que sigue:
sirve para documentar varios puntos de datos seguidos. Los atributos obligatorios de la
ficha se pueden completar después: mientras tanto, el elemento aparece como incompleto en
el [reporte del SOP](docs/guia-nuevo-edificio.md#9-completar-las-fichas).

## Cambiar un elemento de piso o tramo

En la ficha, **Cambiar piso o tramo**, dentro de su edificio. Antes de confirmar muestra
el código que recibirá y qué más cambia. El código dice dónde está el elemento, así que
cambia con él:

- **En el mismo piso** cambia solo el tramo: `CADI-SW03-P01-T1` → `CADI-SW03-P01-T2`.
- **En otro piso** conserva su número si está libre; si no, toma el siguiente.
- **Un punto de datos** conserva su rack y puerto: `CADI-PD-P01-T1-R04-D17` →
  `CADI-PD-P02-T1-R04-D17`. Si ese código ya existe en el destino, no se puede trasladar.

El código anterior queda reservado y sigue llevando al elemento, para que no se rompa lo
que aún lo use (una alerta de Zabbix, un enlace guardado). **El rótulo físico no cambia
solo**: si lleva el código, hay que cambiarlo.

- **Un rack** se lleva lo que tiene montado, que también cambia de código. Si cambia de
  piso, lo que solo estaba conectado (un AP, una UPS) se queda donde está y se desconecta.
- **Un equipo montado** sale de su rack, salvo que se elija otro en el destino.
- **En otro piso** se borran la sala y el número de recinto, salvo que se indiquen otros.
- **Su marcador** se conserva solo si el destino se dibuja en la misma lámina; si no, la
  vista va al destino y un clic lo deja en su lugar.

Todo queda en su historial, con quién lo registró y el comentario.

### Lo que al editar cambia el código

Cada edición se guarda al instante en la base. Si cambia algo que forma parte del código,
el código cambia en la misma operación, con las mismas reglas que un traslado, y **Editar**
muestra antes de guardar cuál le tocará:

- **Rack y puerto de un punto de datos:** al completar uno `SIN-ROTULO` o cambiar su puerto,
  `CADI-PD-P01-T3-SIN-ROTULO-01` → `CADI-PD-P01-T3-R04-D17`. También se actualizan el rótulo,
  el servicio y el enlace con el rack; una etiqueta escrita a mano se respeta.
- **Montar un equipo en un rack de otro tramo:** pasa al tramo del rack. Un AP o una UPS no
  cambia: solo se conecta.
- **El tramo, por la API** (`PATCH`): es un traslado.

Cambiar solo la sala o la lámina no cambia el código: una sala puede dibujarse en la lámina
de otro tramo, como el rack `CADI-R10-P01-T3`, que está en la lámina del tramo 2.

## Eliminar y restaurar un elemento

En la ficha, **Eliminar elemento**. Es una baja lógica, como exige el SOP §8.5: sale del
plano y de los listados, pero conserva su historial y su código, que no se vuelve a usar.
Se puede deshacer al momento o, más adelante, restaurar desde **Ver eliminados**, en el
panel izquierdo; vuelve con su código y el estado que tenía.

Un rack con equipos montados no se puede eliminar hasta vaciarlo, porque dejarían de
verse: esos equipos se ubican a través de él. Lo que solo está conectado sigue en su lugar
y se desconecta; al restaurar el rack vuelve a conectarse, si sigue suelto y en ese piso. Si
un equipo vuelve cuando su rack ya no está o cambió de lugar, queda sin rack y por ubicar.

Lo agregado queda en la base, no en las planillas de `data/`. `iniciar.sh` nunca lo toca,
pero `importar_edificio --recargar` reemplaza todo el edificio, y lo borraría.

## Editar los datos de un elemento

En la ficha del visor, **Editar** abre un formulario con la etiqueta, el estado,
la condición, la criticidad, la ubicación, el rack (y la unidad dentro de él),
los datos del equipo, la ficha propia del tipo y las observaciones. Los campos
de la ficha salen del catálogo, así que un tipo nuevo se edita sin tocar el
código. Se envía solo lo que cambió, con quién lo registró y un comentario
opcional, que quedan en el historial junto a cada cambio. Los errores (una IP o
MAC mal escrita, un número inválido en la ficha, un rack de otro piso) se
muestran junto al campo. Montar un equipo en un rack borra su posición propia:
desde ahí se ve donde esté el rack.

## Migrar a PostgreSQL

En un servidor, `instalar-servidor.sh` lo instala y prepara, y `--cambiar-base` pasa los
datos ([guía](docs/instalacion-servidor.md#3-elegir-la-base-de-datos)). En un equipo propio:

```bash
# Con NETDOC_POSTGRES_CLAVE=<clave> en .env: sin ella, PostgreSQL no arranca
docker compose --profile postgres up -d db adminer
cd backend
.venv/bin/python -m pip install --require-hashes -r requirements-postgres.lock
export NETDOC_DATABASE_URL="postgresql+psycopg://netdoc:<clave>@localhost:5432/umag_netdoc"
.venv/bin/python -m app.scripts.migrar
.venv/bin/python -m app.scripts.copiar_base --origen sqlite:///umag_netdoc.db --destino "$NETDOC_DATABASE_URL"
```

Las migraciones de `alembic/versions` crean el mismo esquema en ambos motores:
`TipoJSON` usa `JSONB` en PostgreSQL y `JSON` en SQLite, y los enums se guardan
como `VARCHAR` (sin tipos nativos), validados por la aplicación.

Para cambiar el modelo: editar `app/models`, generar la migración con
`.venv/bin/alembic revision --autogenerate -m "<qué cambia>"`, revisarla y
correr `migrar`. La prueba `test_migraciones` falla si falta la migración.

## Endpoints principales

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/v1/auth/ingresar` | Inicia la sesión del administrador; el resto de la API la exige (ver [Acceso](#acceso)) |
| `GET` | `/api/v1/auth/sesion` | El usuario de la sesión activa; 401 si no hay |
| `POST` | `/api/v1/auth/salir` | Cierra la sesión |
| `GET` | `/api/v1/catalogo/tipos` | Taxonomía de tipos (SOP §7.2) |
| `GET` | `/api/v1/catalogo/tipos/{codigo}/ficha` | Atributos de la ficha del tipo (SOP §9.2) |
| `POST` | `/api/v1/catalogo/tipos` | Da de alta un tipo nuevo **sin migrar el esquema** |
| `GET` | `/api/v1/edificios` | Catálogo de edificios (SOP §8.2) |
| `POST` | `/api/v1/edificios/{cod}/pisos/{piso}/plano` | Carga el plano vigente del piso o, con `tramo`, de uno de sus tramos |
| `GET` | `/api/v1/edificios/{cod}/pisos/{piso}/recintos` | Recintos de las láminas del piso (número, nombre y dónde se ubican sus elementos) |
| `GET` | `/api/v1/elementos/mapa?edificio=&piso=&tramo=` | Plano + elementos del piso o del tramo, en una llamada |
| `GET` | `/api/v1/elementos` | Listado con filtros por tipo, estado, rack y búsqueda libre |
| `POST` | `/api/v1/elementos` | Alta; genera el código según SOP §8 si no se entrega. Un punto de datos lo toma de `rack_origen` y `puerto` |
| `GET` | `/api/v1/elementos/proximo-codigo?tipo=&edificio=&piso=` | El código que recibiría un alta, sin crear nada, y si está disponible |
| `PATCH` | `/api/v1/elementos/{id}` | Actualización parcial con registro en bitácora. Cambiar `numero_recinto` lo lleva a ese recinto. Si cambia `tramo`, `rack_origen` y `puerto`, o `padre_codigo` a un rack de otro tramo, también actualiza el código |
| `POST` | `/api/v1/elementos/{id}/ubicar-en-recinto` | Lo deja en su recinto (o un rack, sobre su rótulo) según la lámina |
| `PATCH` | `/api/v1/elementos/{id}/posicion` | Georreferenciación sobre el plano (SOP §10.3) |
| `GET` | `/api/v1/elementos/{id}/traslado?piso=&tramo=` | Qué pasaría al trasladarlo: código nuevo, lo que viaja con él y lo que se desconecta. No cambia nada |
| `POST` | `/api/v1/elementos/{id}/trasladar` | Lo lleva a otro piso o tramo de su edificio; su código cambia y el anterior queda reservado |
| `DELETE` | `/api/v1/elementos/{id}?motivo=&usuario=` | Baja lógica; el código queda inactivo y no se reasigna (SOP §8.5). `409` si tiene equipos montados |
| `POST` | `/api/v1/elementos/{id}/restaurar` | Deshace una baja. La lista de eliminados es `GET /api/v1/elementos?edificio=&solo_eliminados=true` |
| `GET` | `/api/v1/reportes/resumen?edificio=` | Tablero por edificio |
| `GET` | `/api/v1/reportes/elementos-incompletos?edificio=` | Reporte exigido por SOP §10.5 punto 22 |
| `POST` | `/api/v1/integraciones/monitoreo/estado` | Webhook de Zabbix (SOP §11.3) |
| `POST` | `/api/v1/integraciones/alertmanager` | Webhook de Alertmanager (Prometheus) |
| `GET` | `/api/v1/integraciones/prometheus/objetivos` | Descubrimiento de objetivos para Prometheus desde el inventario |
| `GET` | `/metrics` | Métricas de inventario, estado y servicio en formato Prometheus |
| `GET` | `/api/v1/integraciones/inventario` | Inventario `netdoc.inventario/v1` en JSON o CSV, completo o incremental |
| `GET` | `/api/v1/integraciones/cambios?desde=` | Registro de cambios con cursor, para sincronizar |
| `PUT` | `/api/v1/elementos/{id}/externos/{sistema}` | Id del elemento en NetBox, GLPI, Zabbix u otro sistema |

Detalle de las integraciones en [docs/integraciones.md](docs/integraciones.md).

## Decisiones de diseño relevantes para la memoria

**Modelo híbrido de atributos.** Los atributos comunes del SOP §9.1 son
columnas (se filtran, ordenan e indexan); la ficha específica de cada tipo
(SOP §9.2) vive en una columna JSON cuyo *esquema* está en la tabla
`definicion_atributo`. Incorporar un tipo nuevo — una cámara IP, una PDU — es
insertar filas, no migrar el esquema ni tocar el backend ni el visor. Es lo que
pide el objetivo específico 2 de la propuesta.

**Validación en dos niveles.** Un atributo mal tipado o ajeno a la ficha se
rechaza con 422. Un atributo obligatorio *ausente* no bloquea: el levantamiento
en terreno es incremental y el reporte de elementos incompletos es justamente
el mecanismo para perseguir esos pendientes.

**El código nunca se reutiliza.** La baja es lógica y el correlativo se calcula
sobre todos los elementos del trío tipo + edificio + piso, incluidos los dados
de baja (SOP §8.5).

**El monitoreo no pisa el mantenimiento planificado.** Un elemento marcado
"en mantenimiento" ignora los eventos de Zabbix, y una caída solo escala a
"en falla" tras `NETDOC_MONITOREO_MINUTOS_FALLA` minutos.

**Importación fiel, no optimista.** El importador del CADI deja vacío lo que la
planilla no trae (serie, MAC, IP, fechas, coordenadas) y **reporta lo que no
cuadra en vez de silenciarlo**. La completitud promedio resultante — 46,9% —
es la línea base real contra la cual medir el avance del levantamiento.

**Ubicación por recinto, no por clic.** El número de sala que trae cada
planilla basta para dibujar el elemento: el sistema lee los números de las
láminas una vez y ubica todo lo que coincide. La lectura queda en un CSV que
se revisa como una planilla y vale solo para la versión de la lámina que se
leyó; lo que no coincide se informa en vez de adivinarse.

**El rack como contenedor.** El rack lleva el marcador y, al seleccionarlo,
despliega su vista frontal con los equipos montados. Un equipo montado no se
ubica por separado: toma la posición de su rack. Los AP y las UPS que la planilla
asocia a un rack se **conectan** a él pero no están montados: llevan marcador
propio.

## Estado actual

- Backend completo y verificado: 360 pruebas en verde, en SQLite y en PostgreSQL 18.
- Instalación en servidor probada en Ubuntu Server 24.04 y 26.04
  ([qué se probó](docs/instalacion-servidor.md#qué-se-probó)).
- 389 elementos del CADI importados desde las planillas por tramo y de puntos
  de datos, del subterráneo al Piso 4: 81 equipos, 308 puntos de datos,
  313 enlaces y 4 VLANs. Ningún rack inferido.
- 317 de los 337 elementos con marcador propio quedaron ubicados solos en su
  recinto (los 52 montados se ven en su rack). Completitud promedio 54,6 %.
- Las 9 láminas cargadas, con sus recintos leídos.
- Frontend compila y corre: `tsc -b` sin errores, build de producción en
  ~103 kB gzip. `npm audit` y `pip-audit` no informan vulnerabilidades conocidas.
- 12 hallazgos documentados en
  [docs/hallazgos-cadi.md](docs/hallazgos-cadi.md).

### Pendientes

1. **20 elementos sin ubicar** (hallazgos 11 y 12): ubicar a mano el rack 8
   (sus AP y UPS lo siguen) y resolver los números de sala que no coinciden
   con las láminas.

## Referencias

- `SOP-DSI-RED-001` — Levantamiento y documentación de elementos de
  infraestructura de red por edificio.
- ANSI/TIA-568 (cableado estructurado) y ANSI/TIA-606-C (administración de
  infraestructura de telecomunicaciones).

**Nota: Se utilizó Vibe Coding para facilitar el trabajo de este proyecto**
