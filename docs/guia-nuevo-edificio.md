# Guía: incorporar un edificio a NetDoc

Procedimiento para que el personal de la DSI documente un edificio nuevo de la
UMAG, desde el levantamiento en terreno hasta verlo en el visor y, si se usa,
en el monitoreo. No hace falta programar; sí usar una terminal. El CADI se
cargó siguiendo estos mismos pasos y sirve de ejemplo en todo el documento.

> **Convenciones.** Los comandos se ejecutan desde la carpeta `umag-netdoc`
> salvo que se indique `cd backend`. En los ejemplos el edificio nuevo es la
> Facultad de Ingeniería, código `ING`; reemplácelo por el que corresponda.
> `<p>` es el código en minúsculas (`ing`). Las direcciones de la API y de
> `http://localhost:8000/docs` piden haber ingresado antes en el visor, en el
> mismo navegador, como administrador.

## Resumen

| # | Paso | Comando o acción | Resultado esperado |
|---|---|---|---|
| 1 | Confirmar el código del edificio | Tabla de la sección 1 | `ING` existe en el catálogo |
| 2 | Crear la carpeta del edificio | `cp -r data/_plantilla data/ing` | `data/ing/` con las plantillas |
| 3 | Llenar las planillas en terreno | Excel o Google Sheets → CSV | `ing-p01-t1.csv`, `ing-puntos-de-datos.csv`… |
| 4 | Preparar las láminas y leer sus recintos | `preparar_laminas ING --aplicar`, `extraer_recintos ING` | Láminas SVG horizontales y `ing-recintos.csv` con los números de sala |
| 5 | Ensayar la importación | `importar_edificio ING --solo-advertencias` | Informe sin discrepancias graves |
| 6 | Importar | `importar_edificio ING` (o `./iniciar.sh`) | "Importación completada" |
| 7 | Cargar planos y fotos | `cargar_planos ING`, `cargar_fotografias ING` (o `./iniciar.sh`) | Planos vigentes por piso o tramo, y cada elemento en su recinto |
| 8 | Ubicar lo pendiente | Visor → *Editar → N° de recinto*, o *Ubicar en el plano* | Todo con su marcador |
| 9 | Completar las fichas | Visor → *Editar* | Completitud cercana al 100 % |
| 10 | Monitoreo (opcional) | [manual-monitoreo.md](manual-monitoreo.md) | El edificio aparece en Grafana / Zabbix |

Los pasos 6 y 7 los hace solo `./iniciar.sh` para cualquier edificio **nuevo**
(sin elementos todavía): basta con dejar su carpeta en `data/` y arrancar.

**Sin terminal**, para empezar un edificio vacío (sin planos ni elementos): elíjalo en el
visor y use **Cargar planos**. Con los nombres de las láminas (sección 4) se crean sus
pisos y tramos, y los elementos se agregan después desde el mismo visor. Mientras no
tenga elementos, **Agregar o quitar planos**, en el panel lateral, permite subir los que
falten o quitarlos todos para empezar de nuevo. Lo que este
camino no hace es leer los números de sala de las láminas (sección 4.1): para eso, deje
también las láminas en `data/<p>/planos/` y corra `extraer_recintos`.

---

## 0. Antes de empezar

- NetDoc debe estar instalado y funcionando (`./iniciar.sh`, ver el
  [README](../README.md#puesta-en-marcha)).
- Si se actualizó el código de NetDoc, arranque una vez con `./iniciar.sh` o
  ejecute `cd backend && .venv/bin/python -m app.scripts.migrar` **antes** de
  importar: aplica los cambios pendientes al esquema de la base.
- Respalde la base antes de una carga grande:
  `cp backend/umag_netdoc.db backend/umag_netdoc.$(date +%F).db`
  (con PostgreSQL: `pg_dump`).

## 1. Código del edificio

Cada edificio tiene un código corto (SOP §8.2) que encabeza el código de todos
sus elementos (`ING-SW01-P01-T2`). Los que ya están en el catálogo:

| Código | Edificio | Código | Edificio |
|---|---|---|---|
| `ING` | Facultad de Ingeniería | `DEC` | Decanato Facultad de Educación y Cs. Sociales |
| `DSI` | Dirección de Servicios Informáticos | `CAS` | Casino Universitario |
| `CADI` | Campus Asistencial Docente e Investigación | `BIB` | Biblioteca y American Corner |
| `HUM` | Facultad de Educación y Cs. Sociales / Cs. Económicas y Jurídicas | `PLA` | Planificación y Desarrollo Institucional |
| `SAL` | Facultad de Ciencias de la Salud / Escuela de Medicina | `FEUM` | Bienestar y Desarrollo Estudiantil / FEUMAG |
| `CS` | Facultad de Ciencias | `VRAF` | Vicerrectoría de Administración y Finanzas |
| `GIM` | Gimnasio Universitario | `REC` | Rectoría |
| `AGR` | Facultad de Cs. Agropecuarias y Agrícolas | `CIGA` | Centro de Investigación GAIA Antártica |
| `PED` | Pabellón de Pedagogías | `CERE` | Centro de Estudio de los Recursos Energéticos |
| | | `PAT` | Instituto de la Patagonia |

**Si el edificio no está en la lista**, agréguelo al catálogo:

1. Edite `backend/app/scripts/cargar_catalogo.py` y sume una línea a
   `EDIFICIOS`, por ejemplo `("LAB", "Edificio Laboratorios Centrales"),`.
   Código: hasta 8 letras mayúsculas, sin espacios, que no se repita.
2. Ejecute `cd backend && .venv/bin/python -m app.scripts.cargar_catalogo`
   (o arranque con `./iniciar.sh`). Debe decir `Edificios creados: 1`.

Así queda también en cualquier instalación nueva. (Alternativa sin editar
archivos: `http://localhost:8000/docs` → `POST /api/v1/edificios`.)

## 2. Carpeta del edificio

```bash
cp -r data/_plantilla data/ing
cd data/ing
for f in codigo-*; do mv "$f" "ing-${f#codigo-}"; done
ls        # ing-laminas.csv  ing-p01-t1.csv  ing-puntos-de-datos.csv  ing-vlans.csv  README.md
```

La carpeta **debe llamarse como el código en minúsculas** (`data/ing`) y cada
archivo empezar con ese prefijo (`ing-…`). Borre las filas de ejemplo de las
plantillas antes de llenarlas. Estructura final:

```
data/ing/
├── ing-p01-t1.csv            equipamiento del piso 1, tramo 1
├── ing-p01-t2.csv            …uno por piso–tramo levantado
├── ing-p02.csv               piso 2, si no está dividido en tramos
├── ing-puntos-de-datos.csv   todos los puntos de datos del edificio (opcional)
├── ing-vlans.csv             leyenda de VLANs (opcional)
├── ing-laminas.csv           excepciones de lámina (opcional, casi nunca hace falta)
├── ing-levantamiento.csv     fechas de las visitas a terreno (opcional)
├── planos/                   ing-p01-t1.svg, ing-p02.svg…
└── fotos/                    ING-SW01-P01-T1.jpg…
```

**Pisos y tramos.** El piso va con dos dígitos: `p00` es el subterráneo, `p01`
el primer piso. El tramo es la subdivisión horizontal que usa la DSI en los
edificios grandes (el CADI tiene hasta tres por piso); si el edificio no se
divide en tramos, omítalo (`ing-p01.csv`).

## 3. Planillas del levantamiento

Se llenan en Excel o Google Sheets y se guardan como CSV:

- **Excel:** *Archivo → Guardar como → CSV UTF-8 (delimitado por comas)*.
- **Google Sheets:** *Archivo → Descargar → Valores separados por comas (.csv)*.

NetDoc acepta también el CSV separado por punto y coma que genera Excel con la
configuración regional de Chile, y el CSV "normal" (Windows-1252); en ese caso
avisa que conviene guardarlo como **CSV UTF-8** para no arriesgar tildes y eñes.

### 3.1 Equipamiento: `ing-p<piso>-t<tramo>.csv`

Una fila por equipo o rack del piso–tramo. Las primeras nueve columnas son las
de las planillas del CADI y van en este orden; las tres últimas son opcionales.

| Columna | Qué va | Ejemplo | Reglas |
|---|---|---|---|
| **Elemento** | Marca y modelo | `Cisco CBS350-24P` | La marca se reconoce sola si es una de: Cisco, Dell, D-Link, Grandstream, HP, Huawei, Linksys, MikroTik, Tripp Lite, Ubiquiti (UniFi/EdgeSwitch)… |
| **Etiqueta** | Rótulo físico del equipo | `SW-DATOS`, `RACK-01` | En patch panels, la cantidad de puertos: `24 Puntos` |
| **Tipo** | Tipo de elemento | `Switches` | Ver la tabla de tipos. Mayúsculas y tildes dan igual |
| **Ubicación** | Recinto donde está | `Sala de Comunicaciones 1101` | Texto libre, con el **número de sala** tal como está en el plano: con él el equipo se ubica solo (sección 4) |
| **Estado Operativo** | Estado del equipo | `Operativo / Activo / En línea (Online)` | Si contiene "fuera de servicio" queda *inactivo*; si no, *activo* |
| **Estado Condición** | Estado físico | `Excelente / Bueno (Óptimo)` | Debe empezar por `Excelente`, `Regular` o `Malo` |
| **Notas** | Observaciones | `Enlace: F.O. a Rack-01 DSI` | Ver "Notas con significado" |
| **Rack** | Rack donde está montado | `Rack-01` | Vacío si no está en un rack. En la fila del propio rack, su número |
| **Foto** | — | | Se ignora: las fotos van en `fotos/` (sección 5) |
| IP *(opcional)* | IP de gestión | `10.40.0.2` | Necesaria para el monitoreo |
| MAC *(opcional)* | MAC | `AA:BB:CC:DD:EE:FF` | Se normaliza a mayúsculas con `:` |
| N° de serie *(opcional)* | Serie | `FOC2345Y0AB` | |

Las columnas opcionales se reconocen por su encabezado (`IP`, `IP de gestión`,
`MAC`, `N° de serie`, `Número de serie`, `Serie`), así que pueden agregarse a
una planilla existente. Una IP o MAC mal escrita se informa y se omite; el
resto del equipo se importa igual.

**Tipos aceptados:**

| Tipo en la planilla | Código |
|---|---|
| `Switch` / `Switches` | SW |
| `Router` / `Routers` | RT |
| `Access Point` / `Access Points` | AP |
| `Patch Panel` / `Patch Panels` | PP |
| `Cabecera F.O.` / `ODF` / `Distribuidor de fibra` | ODF |
| `Rack` / `Racks` | R |
| `UPS` | UPS |
| `PDU` / `PDUs` | PDU |
| `Servidor` / `Servidores` | SV |
| `Central telefónica` / `PBX` | PBX |
| `Media converter` / `Conversor de medios` | MC |
| `ONT` | ONT |

**Racks.** Cada rack lleva su propia fila, con `Racks` en *Tipo* y su número
en la columna *Rack* (`Rack-04`). El número es el que identifica al rack en
todo el edificio: no lo repita en otro piso. Los equipos montados llevan ese
mismo número en *Rack*. Si un equipo o un punto de datos nombra un rack que no
tiene fila, NetDoc lo crea igual como **rack inferido** y lo informa (ver
sección 6).

**Notas con significado:**

- `Enlace: <destino>` registra un enlace físico hacia ese destino (si empieza
  con `F.O.`, de fibra). El texto antes de `Enlace:` queda como observación.
- En patch panels, `Disponibilidad 6 puntos` calcula los puertos ocupados
  (24 − 6 = 18); `Ocupación total` los marca todos ocupados. La categoría
  (Cat6, Cat6A) se toma de la columna *Elemento*.
- Cualquier otro texto queda como observación del equipo.

**Códigos que se generan** (SOP §8): `ING-SW01-P01-T1` — edificio, tipo con
correlativo, piso y tramo. El correlativo avanza por tipo y piso en el orden de
las planillas y **nunca se reutiliza**. El de un rack es su número:
`ING-R04-P01-T2`.

### 3.2 Puntos de datos: `ing-puntos-de-datos.csv`

Un punto de datos por fila; todos los del edificio en un solo archivo.

| Columna | Qué va | Ejemplo |
|---|---|---|
| **Elemento** | Recinto, con o sin "Roseta", y su número de sala | `Roseta Laboratorio 1105` → recinto *Laboratorio 1105* |
| **Etiqueta** | Rótulo físico | `P01-T1-R1-D01` |
| **Tipo** | `Punto de datos` | |
| **Ubicación** | Piso y tramo | `Piso 1 - Tramo 1`, `Piso 1` sin tramos, o `Piso Subterráneo` |
| **Estado Operativo**, **Estado Condición**, **Notas** | Igual que en equipamiento | |

El **rótulo** es `P<piso>-T<tramo>-R<rack>-<puerto>` (sin tramo:
`P01-R1-D01`; en el subterráneo, `SUB-R11-D05`). La primera letra del puerto indica el servicio: `D` datos,
`T` telefonía, `C` CCTV. Con el rótulo NetDoc arma el código
(`ING-PD-P01-T1-R01-D01`) y registra el enlace del rack a ese punto. Un punto
sin rótulo se anota `Sin etiqueta` y queda como `ING-PD-P01-T1-SIN-ROTULO-01`,
pendiente de verificar con tester. Si el piso–tramo del rótulo y el de la
columna *Ubicación* no coinciden, manda el rótulo y se informa.

### 3.3 VLANs: `ing-vlans.csv` (opcional)

```
numero,nombre,gateway,prefijo,servicio
3,DATOS,10.40.0.1,/16,datos
2,TELEFONIA,10.41.0.1,/16,telefonia
1,SCC/CCTV,192.168.10.1,/24,cctv
```

La columna *servicio* (`datos`, `telefonia`, `cctv`) fija la VLAN por omisión
de los puntos de datos de ese servicio. Cada edificio tiene sus propias VLANs:
la VLAN 3 de ING y la del CADI pueden ser redes distintas.

### 3.4 Excepciones de lámina: `ing-laminas.csv` (opcional)

Solo hace falta si hay elementos **dibujados en la lámina de otro tramo** que
el de su rótulo. En el CADI, la sala eléctrica de los racks cuenta como tramo 3
pero aparece en el plano del tramo 1, así que todo lo rotulado P01-T3 se
dibuja en esa lámina, salvo el auditorio
(ver [`data/cadi/cadi-laminas.csv`](../data/cadi/cadi-laminas.csv)):

```
piso,tramo,recinto,lamina,motivo
P01,T3,,T1,La sala eléctrica cuenta como tramo 3 pero está en la lámina del tramo 1
P01,T3,auditorio,T3,El auditorio sí está en la lámina del tramo 3
```

Una fila sin *recinto* vale para todo el tramo; una con recinto es una
excepción que se busca en la ubicación y la etiqueta del elemento. Un caso
aislado no necesita este archivo: se corrige desde la ficha en el visor
(fila *Lámina*).

### 3.5 Fechas del levantamiento: `ing-levantamiento.csv` (opcional)

Las planillas no traen la fecha en que se levantó cada elemento. Se declara
aquí, una fila por visita a terreno, con los pisos que cubrió (vacío = todo
el edificio):

```
fecha_inicio,fecha_cierre,pisos,observaciones
2026-09-15,2026-09-16,P01 P02 P03 P04,"Recorrido del edificio"
```

Cada visita queda en la bitácora de levantamientos del edificio, y los
elementos de esos pisos toman como **fecha del último levantamiento** la de
cierre (la de inicio, si la visita sigue abierta). Una fecha posterior que ya
tenga un elemento, registrada desde el visor, no se reemplaza. Se aplica al
importar y en cada `./iniciar.sh`, también a un edificio ya importado: para
una visita nueva basta con agregar su fila.

## 4. Láminas (planos)

Una lámina por tramo, o una por piso si el piso no se divide. Formato **SVG**
(vectorial: se puede acercar sin perder nitidez).

**Obtener el SVG.** Los planos de arquitectura suelen estar en PDF (desde
AutoCAD: *Trazar/Exportar a PDF*). Para convertir una página a SVG:

```bash
sudo apt install poppler-utils                       # una vez
pdftocairo -svg -f 3 -l 3 planos-ing.pdf data/ing/planos/ing-p01-t1.svg   # página 3
```

También sirve Inkscape (*Abrir el PDF → Guardar como → SVG plano*).

**Nombres (obligatorio).** El sistema sabe a qué edificio, piso y tramo va
cada lámina **solo por su nombre**, así que debe seguir la nomenclatura de las
planillas:

```
<edificio>-p<piso>[-t<tramo>].svg
```

| Lámina | Nombre |
|---|---|
| Piso 1, tramo 1 del ING | `ing-p01-t1.svg` |
| Piso 2 completo (no se divide en tramos) | `ing-p02.svg` |
| Subterráneo | `ing-p00.svg` |
| Piso 10, tramo 3 | `ing-p10-t3.svg` |

- El edificio es su código del catálogo (sección 1) y debe ser el de la
  carpeta: `ing-p01.svg` dentro de `data/cadi/planos/` se rechaza.
- El piso va con **dos dígitos** (`p01`, no `p1`), como en los códigos del SOP.
  El tramo va sin ceros (`t1`, no `t01`).
- Da igual escribirlo en mayúsculas o minúsculas. No lleva espacios, fechas
  ni versiones: una versión nueva reemplaza al archivo con el mismo nombre
  (sección 11).
- Solo se cargan archivos `.svg`. Cualquier otro archivo de la carpeta se
  informa como omitido.

**Desde el visor**, en un edificio vacío, **Cargar planos** pide estos mismos nombres:
rechaza el archivo que no los sigue, dice cómo debería llamarse si se puede deducir, y
muestra los ejemplos del edificio, incluido el de un edificio con un único plano
(`ing-p01.svg`).

Si las láminas llegaron con otros nombres («ing 1er piso tramo 1.svg»,
«ING_P1_T01.svg»), el paso siguiente las renombra solo cuando el nombre
correcto se puede deducir; las demás se informan para renombrarlas a mano.

**Preparar.** Además del nombre, las láminas exportadas desde PDF suelen traer
caracteres que el navegador rechaza y, a veces, el dibujo girado dentro de una
hoja vertical. Revíselas:

```bash
cd backend
.venv/bin/python -m app.scripts.preparar_laminas ING
#   ing 1er piso tramo 1.svg: 4768×6740, texto girado a la derecha (1103 de 1122), 120 caracteres inválidos → limpiar, girar a la izquierda, renombrar a «ing-p01-t1.svg»
#   ing-p02.svg: 6740×4768, texto horizontal (969 de 1052), 0 caracteres inválidos → lista
#   ! «leyenda.svg» no sigue la nomenclatura …: renómbrela a mano
.venv/bin/python -m app.scripts.preparar_laminas ING --aplicar
```

`--aplicar` renombra, limpia y endereza. Los originales de las láminas
limpiadas o giradas quedan en `data/ing/planos/originales/`. Si el
resultado no le convence, copie el original de vuelta. Ábralas en el navegador
(arrastrando el archivo) para confirmar que se ven horizontales y legibles.

Las dimensiones de la lámina fijan el sistema de coordenadas de las posiciones:
**prepare las láminas antes de ubicar elementos**, no después.

### 4.1 Recintos: los números de sala de cada lámina

Cada sala de los planos lleva su número bajo el nombre, y el número dice el
piso: los recintos del subterráneo empiezan con `00` (`0017`), los del primer
piso con `1` (`1083`), los del segundo con `2`, y así. Con ese número, el que
las planillas anotan en la ubicación, **cada elemento queda solo en su sala**:
los puntos de datos de una sala en un solo marcador que se despliega, los
equipos uno junto al otro y cada rack sobre su rótulo de la lámina
(«RACK 08»).

Las láminas de CAD traen el texto convertido en trazos, así que el sistema las
lee con OCR, una vez por versión de cada lámina:

```bash
cd backend
.venv/bin/python -m pip install -r requirements-ocr.txt   # una vez (~400 MB)
.venv/bin/python -m app.scripts.extraer_recintos ING
#   ing-p01-t1.svg: 58 recintos (1 en la segunda lectura), racks R01, R02 (55 s)
#   …
#   Recintos de las planillas que no aparecen en las láminas de su piso (1):
#     - P01 1063 «Recepción 1063» → en la lámina: 1082 (SECRETARÍA RECEPCIÓN)
```

El resultado queda en `data/ing/ing-recintos.csv`, con una fila por recinto:
lámina, número, nombre, `x` e `y` (el punto bajo el número donde se dibujan
sus elementos) y la huella de la lámina leída. Revíselo como una planilla más:

- **Un recinto de las planillas que no aparece** es un número mal transcrito
  (corríjalo en la planilla antes de importar, o después en el visor) o un
  rótulo que el OCR no alcanzó a leer. En ese caso agregue la fila a mano: las
  coordenadas se ven en la ficha de cualquier elemento ubicado cerca.
- **Una fila mal leída** se corrige o se borra.
- Para releer solo una lámina: `extraer_recintos ING ing-p01-t1.svg`.

Si una lámina cambia, vuelva a leerla: el sistema no usa recintos leídos de
otra versión y lo avisa al arrancar. Los recintos se cargan junto con las
láminas (paso 7).

## 5. Fotografías (opcional)

Deje las fotos en `data/ing/fotos/` con el código del elemento como nombre
(SOP §10.4): `ING-SW01-P01-T1.jpg`, y si hay varias, `ING-SW01-P01-T1_2.jpg`.
Formatos: JPG, PNG, WEBP. Como los códigos se conocen después de importar, lo
habitual es sacar las fotos en terreno, importar (paso 6) y renombrarlas
consultando los códigos en el visor.

## 6. Ensayo de importación

```bash
cd backend
.venv/bin/python -m app.scripts.importar_edificio ING --solo-advertencias
```

Hace la importación completa y la **descarta**: no modifica nada. Revise el
informe y corrija las planillas hasta quedar conforme. Mensajes frecuentes:

| Mensaje | Qué significa | Qué hacer |
|---|---|---|
| `No se encontró ninguna planilla de equipamiento en …` | Los archivos no se llaman `ing-p<piso>…csv` | Revise el prefijo y la carpeta |
| `tipo no reconocido 'X'` | *Tipo* fuera de la tabla de tipos | Use un tipo aceptado |
| `rack sin número identificable` | Fila de rack sin número en *Rack* | Escriba `Rack-NN` |
| `el rack N aparece más de una vez` | Dos filas de rack con el mismo número | Cada rack, un número único en el edificio |
| `Racks inferidos, sin ficha en las planillas` | Un equipo o punto de datos nombra un rack sin fila | Agregue la fila del rack o corrija el número |
| `Rótulo duplicado … se registró como …-DUP2` | Dos puntos de datos con el mismo rótulo | Verifique en terreno cuál está mal rotulado |
| `rótulo 'X' no sigue el patrón …` | Rótulo mal escrito | Corrija a `P01-T1-R1-D01` |
| `el rótulo indica P01-T2 pero la columna Ubicación dice P01-T1` | Contradicción; se usó el rótulo | Corrija la columna que esté mal |
| `ubicación ilegible` | *Ubicación* de un punto de datos sin "Piso N" | Escriba `Piso 1 - Tramo 1` |
| `Puertos con prefijo sin servicio asignado` | Puertos que no empiezan con D, T o C | Informativo: no reciben VLAN por omisión |
| `IP inválida` / `MAC inválida` | Dato opcional mal escrito | Corríjalo o déjelo vacío |
| `no está en UTF-8` | CSV guardado en Windows-1252 | Guarde como CSV UTF-8 |
| `planilla sin elementos levantados` | Archivo solo con encabezado | Complete o borre el archivo |

## 7. Importar

```bash
.venv/bin/python -m app.scripts.importar_edificio ING
#   Importación completada
#     Pisos creados:        3
#     Tramos creados:       4
#     Equipos:              58
#     Puntos de datos:      210
#     …
```

Si el edificio ya tiene elementos, el comando se detiene sin tocar nada (ver
sección 11 para sumar tramos después). Luego cargue planos y fotos:

```bash
.venv/bin/python -m app.scripts.cargar_planos ING
.venv/bin/python -m app.scripts.cargar_fotografias ING
```

O, en vez de los tres comandos, `./iniciar.sh`: importa los edificios
nuevos, carga las fotos pendientes y los planos nuevos o modificados de todos,
y levanta el sistema.

Al cargar un plano se generan también sus **teselas**: el plano pre-dibujado
en imágenes chicas, que es lo que permite moverlo y acercarlo con fluidez en
el visor. Toma de 5 a 20 segundos por lámina y se hace una sola vez por
versión (`▦ ING P01 · Tramo 1 (12 s)`).

## 8. Ubicar lo pendiente en el visor

Al cargar las láminas (paso 7), cada elemento con su número de sala quedó en
su recinto, y lo que no se pudo ubicar se listó en la terminal:

```
Ubicación en los planos
  Ubicados en su recinto: 210
  Ubicados junto a otro elemento de su sala, que no tiene número en la lámina: 4
  Con un recinto que no aparece en las láminas de su piso (3): corrija el N° de recinto …
    - P01 «Recepción 1063»: ING-PD-P01-T2-R04-D16 … → en la lámina: 1082 (SECRETARÍA RECEPCIÓN)
  Sin número de recinto (2): complételo en el visor (Editar → N° de recinto) …
    - P02 «Sala Eléctrica»: ING-R05-P02-T1
```

En el visor (`http://localhost:8000`, o la dirección del servidor), elija
**Edificio**, **Piso** y **Tramo** en la barra superior. Lo pendiente lleva la
marca *sin ubicar* en el listado y un aviso en su ficha.

- **Falta el número, o está mal:** ficha → **Editar** → **N° de recinto**. El
  campo sugiere los recintos del piso. Al guardar, el elemento se ubica solo.
- **Su sala no tiene número en la lámina**, o el elemento no está donde dice su
  recinto: ubíquelo a mano, como se explica abajo.
- **Ubicar en su recinto**, en la ficha, devuelve a su sala un elemento que se
  movió a mano.

Para ubicar a mano:

1. **Racks primero.** En el listado lateral los racks aparecen arriba, con una
   flecha y el número de equipos montados. Seleccione un rack →
   **Ubicar en el plano** → clic sobre su posición en la lámina. Los equipos
   montados (switches, patch panels…) no se ubican por separado: se ven dentro
   del rack. Al hacer clic en el rack, la ficha muestra su **vista frontal** con
   los equipos y, aparte, lo **conectado** (AP, UPS), que sí lleva marcador
   propio.
2. **AP, UPS y otros equipos sueltos:** igual, cada uno en su lugar.
3. **Puntos de datos:** seleccione cada uno → *Ubicar en el plano*. Para
   dejar varios en la misma caja de pared, al ubicar el segundo haga clic
   **sobre el marcador del primero**: quedan agrupados en un solo marcador con
   el número de puntos.
4. El aviso "N elementos sin coordenadas sobre el plano" y la marca
   *sin ubicar* en cada fila indican lo pendiente.

**Elemento dibujado en otra lámina.** Si un elemento no aparece en la lámina de
su tramo (como la sala eléctrica del CADI), cámbielo desde su ficha, fila
**Lámina**. Si es un grupo completo, use `ing-laminas.csv` (sección 3.4) antes
de importar.

## 9. Completar las fichas

La barra de completitud de cada ficha mide los atributos obligatorios del SOP
§9 (IP, MAC, serie, datos propios del tipo…).

**Datos confidenciales.** Las direcciones MAC e IP, la configuración de los
equipos, la fecha de instalación, los datos del cableado y los responsables
se registran **solo en la instalación institucional del sistema**, desde
el visor. No los agregue a las planillas de `data/`, que se versionan en el
repositorio del proyecto. Para completarlos: ficha →
**Editar** → llene los campos → *Registrado por* y un *Comentario* (quedan en
el historial) → **Guardar cambios**. Solo se guarda lo que cambió.

Para ver lo pendiente del edificio:

- `http://localhost:8000/api/v1/reportes/resumen?edificio=ING` — totales por
  tipo, estado y piso, y la completitud promedio.
- `http://localhost:8000/api/v1/reportes/elementos-incompletos?edificio=ING` —
  cada elemento con lo que le falta (SOP §10.5).

## 10. Monitoreo (opcional)

Si la DSI usa Prometheus, Grafana o Zabbix, el edificio se incorpora así:

- **Prometheus / Grafana:** nada que hacer. Los elementos con IP de gestión
  entran solos a la vigilancia en el siguiente descubrimiento (cada 5 minutos),
  y el edificio aparece en el filtro *Edificio* del panel de Grafana.
- **Zabbix:** `cd backend && .venv/bin/python -m app.scripts.sincronizar zabbix
  --edificio ING` para ver qué hosts se crearían, y con `--aplicar` para
  crearlos.

Paso a paso completo en [manual-monitoreo.md](manual-monitoreo.md).

## 11. Después de la primera carga

| Situación | Qué hacer |
|---|---|
| Se levantó un tramo más (o más puntos de datos) | Deje la planilla nueva en `data/ing/` y ejecute `importar_edificio ING --agregar` (primero con `--solo-advertencias` para ensayar). Suma solo lo nuevo, ya ubicado en su recinto: no toca lo importado, sus posiciones ni su historial. Un rack que era inferido se completa con su fila y, si la planilla es de otro piso, pasa a ese piso con el código que le corresponde |
| Un dato está mal | Corríjalo en el visor con **Editar**: queda en el historial. No reimporte |
| Se hizo otra visita a terreno | Agregue su fila a `ing-levantamiento.csv` (sección 3.5) y ejecute `./iniciar.sh` |
| Se instaló algo nuevo: un switch, puntos de datos, un AP… | En el visor, **+ Agregar elemento**: elija el tipo, el piso y el tramo; el código lo asigna el sistema. Para varios puntos de datos seguidos, **Agregar y seguir** ([detalle](../README.md#agregar-un-elemento)) |
| Se retiró un equipo | En su ficha, **Eliminar elemento** (baja lógica: el código no se reutiliza; se recupera desde **Ver eliminados**). Un rack se vacía antes |
| Se cambió un equipo de lugar | En su ficha, **Cambiar piso o tramo**. Su código cambia y el anterior queda reservado: cambia también el rótulo físico si lo lleva |
| Hay una versión nueva de una lámina | Reemplace el archivo en `data/ing/planos/` (mismo nombre, pasado por `preparar_laminas`), vuelva a leer sus recintos (`extraer_recintos ING ing-p01-t1.svg`) y ejecute `cargar_planos ING` o `./iniciar.sh`: entra como versión nueva y la anterior queda como histórica. Si la lámina conserva su tamaño, las posiciones se mantienen. Si no, el dibujo es otro y los elementos ubicados en ella **quedan sin ubicar**: el comando los lista para volver a marcarlos, y las coordenadas anteriores quedan en su historial |
| Las planillas estaban muy mal y aún no se ubicó nada | `importar_edificio ING --recargar` reemplaza todo lo importado. **Se pierden las posiciones, el historial y lo agregado en el visor** |

## 12. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `No existe el edificio XXX en el catálogo` | Código mal escrito o no agregado | Sección 1 |
| `No existe la carpeta de planillas data/xxx` | La carpeta no se llama como el código en minúsculas | Renómbrela |
| `XXX ya tiene N elementos importados` | Se intentó importar de nuevo | Use `--agregar` (sección 11) |
| El edificio aparece sin pisos en el visor | La página se abrió antes de importar | Recargue la página |
| `«…» no sigue la nomenclatura …` al cargar planos | El nombre no dice edificio, piso y tramo (sección 4) | `preparar_laminas ING --aplicar` lo renombra si el aviso trae `renómbrela «…»`; si no, renómbrelo a mano |
| `«…» es una lámina del edificio XXX, no de ING` | La lámina está en la carpeta de otro edificio, o el prefijo está mal | Muévala a `data/xxx/planos/` o corrija el prefijo |
| `… ya tiene la lámina «…»` | Dos archivos para el mismo piso–tramo (por ejemplo, `ING-P01.svg` y `ing-p01.svg`) | Deje uno solo |
| La lámina se ve rota o en blanco | Caracteres inválidos o no es SVG válido | `preparar_laminas ING --aplicar` |
| El plano se ve de lado | Dibujo girado dentro de la hoja | `preparar_laminas ING --aplicar` |
| El plano se mueve lento o se ve borroso al acercarlo mucho | Lento: aún no tiene teselas (recién subido por la API, o `! … sin teselas` al cargar). Borroso: se acercó más allá del detalle de las teselas | Reinicie con `./iniciar.sh`, que genera las que falten. Revise que no esté `NETDOC_TESELAS=0` en `.env` |
| `el piso P0X no existe en el sistema` al cargar planos | Hay lámina pero ningún elemento en ese piso (los pisos se crean al importar) | Importe ese piso, o créelo en `http://localhost:8000/docs` → `POST /api/v1/edificios/ING/pisos` y vuelva a cargar los planos |
| Un punto de datos no aparece al elegir su tramo | Está dibujado en la lámina de otro tramo | Fila *Lámina* de su ficha, o `ing-laminas.csv` |
| No se puede ubicar un switch | Está montado en un rack | Ubique el rack; el switch se ve dentro |
| `… se leyó de otra versión de «…»` al arrancar | La lámina cambió después de leer sus recintos | `extraer_recintos ING <lámina>` |
| Un elemento con número de recinto queda *sin ubicar* | El número no está en las láminas de su piso (o el OCR no lo leyó) | Revise el informe de `extraer_recintos`: corrija el N° de recinto en el visor o agregue la fila a `ing-recintos.csv` |
| `Falta el OCR para leer las láminas` | No se instaló la dependencia opcional | `cd backend && .venv/bin/python -m pip install -r requirements-ocr.txt` |

## Glosario

- **Tramo:** subdivisión horizontal de un piso usada por la DSI (T1, T2…).
- **Lámina:** plano de un tramo o de un piso completo.
- **Montado / conectado:** un switch o patch panel va *montado* en el rack y
  se ve a través de él; un AP o una UPS solo se *conecta* al rack y tiene su
  propio lugar en el plano.
- **Punto de datos (PD):** cada conexión rotulada de la pared (las planillas
  las llaman "rosetas").
- **Rack inferido:** rack que aparece en los rótulos pero no tiene fila propia
  en las planillas; requiere verificación en terreno.
- **Completitud:** porcentaje de atributos obligatorios del SOP §9 que tiene la
  ficha de un elemento.
- **Recinto:** sala rotulada en la lámina con su número (`1083`; `0017` en el
  subterráneo). Es lo que ubica a los elementos en el plano sin hacer clic.
