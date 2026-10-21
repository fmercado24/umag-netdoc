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

## Arquitectura

Construcción desde cero (no extensión de NetBox):

| Capa | Tecnología | Por qué |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite | Tipado compartido con los esquemas del backend |
| Visor de planos | Leaflet con `CRS.Simple` | El plano se monta como capa base y las coordenadas son píxeles del plano, sin proyección geográfica |
| Backend | FastAPI + SQLAlchemy 2.0 + Pydantic v2 | Validación declarativa de fichas y OpenAPI generado automáticamente |
| Base de datos | SQLite (desarrollo) → PostgreSQL | Modelo portable: `JSONB` en PostgreSQL, `JSON` en SQLite |
| Migraciones | Alembic | El mismo esquema versionado en SQLite y PostgreSQL; `render_as_batch` para los `ALTER TABLE` de SQLite |
| Integraciones | Prometheus, Alertmanager, Grafana, Zabbix | Métricas, descubrimiento de objetivos, webhooks de estado y conector de hosts; ver [docs/integraciones.md](docs/integraciones.md) |
| Lectura de láminas | RapidOCR (opcional, `requirements-ocr.txt`) | Lee los números de sala y los rótulos de racks de las láminas de CAD, cuyo texto viene convertido en trazos. Solo lo necesita quien prepara las láminas |

```
umag-netdoc/
├── iniciar.sh           Prepara y levanta todo: API, base, edificios nuevos y visor
├── backend/
│   ├── app/
│   │   ├── models/      Modelo de datos (SQLAlchemy)
│   │   ├── schemas/     Contratos de entrada y salida (Pydantic)
│   │   ├── servicios/   Nomenclatura, validación, historial, recintos, monitoreo, métricas
│   │   ├── integraciones/ Conectores con otros sistemas (Zabbix)
│   │   ├── api/v1/      Routers HTTP
│   │   └── scripts/     Migraciones, catálogo, importación de edificios, láminas, recintos, fotos, sincronización
│   ├── alembic/         Migraciones versionadas
│   └── tests/           174 pruebas (pytest)
├── frontend/src/
│   ├── api/             Cliente HTTP tipado
│   ├── components/      Barra, panel lateral, visor de plano, ficha
│   └── types/           Espejo de los esquemas del backend
├── data/cadi/           Planillas y láminas originales del levantamiento del CADI
├── data/_plantilla/     Plantillas para el levantamiento de otros edificios
├── deploy/              Prometheus, Alertmanager, Grafana y Zabbix
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

### Arranque rápido

```bash
./iniciar.sh                  # prepara lo que falte y levanta API + visor
./iniciar.sh --sin-navegador  # igual, sin abrir el navegador
```

La primera vez crea el entorno de Python, instala las dependencias de ambos
lados, crea la base con el catálogo, importa cada edificio que tenga carpeta en
`data/` (hoy el CADI) y carga sus láminas y fotografías. Las siguientes veces
aplica las migraciones pendientes, solo reinstala si cambiaron
`requirements*.txt` o `package-lock.json`, importa los edificios **nuevos**,
carga las fotos nuevas y revisa todas las láminas: una nueva o modificada en
`data/<código>/planos` entra como versión nueva (ver
[Cargar el plano de un piso](#cargar-el-plano-de-un-piso)). Nunca reimporta
elementos ni reemplaza sus datos. También genera las teselas que falten:
cada plano pre-dibujado en imágenes chicas, para que el visor se mueva con
fluidez sobre láminas de CAD pesadas (de 5 a 20 s por lámina, una sola vez;
ver [modelo de datos](docs/modelo-datos.md#teselas)). Con `NETDOC_API_HOST=0.0.0.0` la API escucha en la red (necesario
para el [monitoreo](docs/manual-monitoreo.md)). Deja el visor en
<http://localhost:5173> y la API en <http://localhost:8000>; **Ctrl+C** detiene
ambos, y si uno de los dos se cae el script cierra el otro.

Los pasos por separado, por si se necesita alguno suelto:

### Backend

Requiere Python 3.11 o superior.

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt

# Esquema (migraciones de Alembic) + catálogo (19 edificios, 14 tipos)
.venv/bin/python -m app.scripts.migrar
.venv/bin/python -m app.scripts.cargar_catalogo

# Importar un edificio desde data/<código>/ (el CADI: 389 elementos, 313 enlaces, 4 VLANs)
.venv/bin/python -m app.scripts.importar_edificio CADI
.venv/bin/python -m app.scripts.importar_edificio CADI --solo-advertencias  # ensayo, no modifica
.venv/bin/python -m app.scripts.importar_edificio CADI --agregar           # suma tramos nuevos
.venv/bin/python -m app.scripts.importar_edificio CADI --recargar          # reemplaza todo: se
                                                         # pierden posiciones e historial
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

API en <http://localhost:8000>, documentación interactiva en
<http://localhost:8000/docs>.

> En Ubuntu, si `python3 -m venv` crea el entorno sin `pip`, instala
> `python3-venv` (`sudo apt install python3-venv`) o arranca pip dentro del
> entorno con `curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python`.

### Frontend

Requiere Node.js 20 o superior. En este equipo Node está instalado con nvm y
no queda en el `PATH` de shells no interactivos, así que hay que cargarlo:

```bash
source ~/.nvm/nvm.sh
cd frontend
cp .env.example .env     # VITE_API_URL=http://localhost:8000
npm install
npm run dev
```

Visor en <http://localhost:5173>. `npm run build` genera el bundle de
producción y `npm run typecheck` valida los tipos sin compilar.

### Pruebas

```bash
cd backend && .venv/bin/python -m pytest -q
```

## Cargar el plano de un piso

El visor necesita un plano para poder posicionar elementos. Las dimensiones se
indican explícitamente porque **fijan el sistema de coordenadas**: las
posiciones de los elementos se guardan en esas unidades y sobreviven a que el
archivo se reemplace por una versión reescalada.

```bash
curl -X POST http://localhost:8000/api/v1/edificios/CADI/pisos/P01/plano \
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

```bash
docker compose up -d db adminer
cd backend
.venv/bin/python -m pip install -r requirements-postgres.txt
export NETDOC_DATABASE_URL="postgresql+psycopg://netdoc:netdoc@localhost:5432/umag_netdoc"
.venv/bin/python -m app.scripts.migrar
```

Las migraciones de `alembic/versions` crean el mismo esquema en ambos motores:
`TipoJSON` usa `JSONB` en PostgreSQL y `JSON` en SQLite, y los enums se guardan
como `VARCHAR` (sin tipos nativos), validados por la aplicación. Traspasar los
datos desde SQLite es un paso aparte (ver
[docs/integraciones.md](docs/integraciones.md#escalabilidad)).

Para cambiar el modelo: editar `app/models`, generar la migración con
`.venv/bin/alembic revision --autogenerate -m "<qué cambia>"`, revisarla y
correr `migrar`. La prueba `test_migraciones` falla si falta la migración.

## Endpoints principales

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/v1/catalogo/tipos` | Taxonomía de tipos (SOP §7.2) |
| `GET` | `/api/v1/catalogo/tipos/{codigo}/ficha` | Atributos de la ficha del tipo (SOP §9.2) |
| `POST` | `/api/v1/catalogo/tipos` | Da de alta un tipo nuevo **sin migrar el esquema** |
| `GET` | `/api/v1/edificios` | Catálogo de edificios (SOP §8.2) |
| `POST` | `/api/v1/edificios/{cod}/pisos/{piso}/plano` | Carga el plano vigente del piso o, con `tramo`, de uno de sus tramos |
| `GET` | `/api/v1/edificios/{cod}/pisos/{piso}/recintos` | Recintos de las láminas del piso (número, nombre y dónde se ubican sus elementos) |
| `GET` | `/api/v1/elementos/mapa?edificio=&piso=&tramo=` | Plano + elementos del piso o del tramo, en una llamada |
| `GET` | `/api/v1/elementos` | Listado con filtros por tipo, estado, rack y búsqueda libre |
| `POST` | `/api/v1/elementos` | Alta; genera el código según SOP §8 si no se entrega |
| `PATCH` | `/api/v1/elementos/{id}` | Actualización parcial con registro en bitácora. Cambiar `numero_recinto` lo lleva a ese recinto |
| `POST` | `/api/v1/elementos/{id}/ubicar-en-recinto` | Lo deja en su recinto (o un rack, sobre su rótulo) según la lámina |
| `PATCH` | `/api/v1/elementos/{id}/posicion` | Georreferenciación sobre el plano (SOP §10.3) |
| `DELETE` | `/api/v1/elementos/{id}` | Baja lógica; el código queda inactivo y no se reasigna (SOP §8.5) |
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

- Backend completo y verificado: 174 pruebas en verde.
- 389 elementos del CADI importados desde las planillas por tramo y de puntos
  de datos, del subterráneo al Piso 4: 81 equipos, 308 puntos de datos,
  313 enlaces y 4 VLANs. Ningún rack inferido.
- 317 de los 337 elementos con marcador propio quedaron ubicados solos en su
  recinto (los 52 montados se ven en su rack). Completitud promedio 54,6 %.
- Las 9 láminas cargadas, con sus recintos leídos.
- Frontend compila y corre: `tsc -b` sin errores, build de producción en
  ~103 kB gzip. `npm audit` informa una vulnerabilidad alta en
  `source-map-js`, una dependencia de desarrollo de Vite (`npm audit fix`).
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
