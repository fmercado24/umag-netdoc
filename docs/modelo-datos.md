# Modelo de datos

Corresponde al objetivo específico 2 de la propuesta de memoria: *"Diseñar el
modelo de datos que soporte dichos atributos y sea extensible a nuevos tipos de
elementos"*.

## Diagrama

```mermaid
erDiagram
    EDIFICIO ||--o{ PISO : contiene
    PISO ||--o{ TRAMO : se_divide_en
    PISO ||--o{ PLANO : tiene
    PISO ||--o{ ELEMENTO : aloja
    EDIFICIO ||--o{ ELEMENTO : aloja
    EDIFICIO ||--o{ LEVANTAMIENTO : registra
    TRAMO ||--o{ ELEMENTO : ubica
    TRAMO |o--o{ PLANO : cubre
    PLANO ||--o{ ELEMENTO : georreferencia

    TIPO_ELEMENTO ||--o{ DEFINICION_ATRIBUTO : define
    TIPO_ELEMENTO ||--o{ ELEMENTO : clasifica

    ELEMENTO ||--o{ ELEMENTO : aloja
    ELEMENTO ||--o{ FOTOGRAFIA : evidencia
    ELEMENTO ||--o{ HISTORIAL_ELEMENTO : audita
    ELEMENTO ||--o{ IDENTIFICADOR_EXTERNO : se_conoce_en
    ELEMENTO ||--o{ ELEMENTO_VLAN : materializa
    ELEMENTO ||--o{ ENLACE : origina
    VLAN ||--o{ ELEMENTO_VLAN : agrupa
    PERSONA ||--o{ ELEMENTO : responde_por
    PERSONA ||--o{ LEVANTAMIENTO : dirige
```

El diagrama completo, con columnas, tipos, índices y reglas de borrado, está
en [`modelo-datos.dbml`](modelo-datos.dbml). Para verlo, abrir
[dbdiagram.io](https://dbdiagram.io), entrar al editor (*Create your diagram*)
y pegar el contenido en el panel izquierdo. El archivo se genera desde los
modelos. Después de cambiar el esquema se regenera, y las pruebas fallan si
quedó desactualizado:

```bash
cd backend
.venv/bin/python -m app.scripts.exportar_dbml -o ../docs/modelo-datos.dbml
```

## Las tres decisiones estructurales

### 1. Atributos híbridos: columnas + JSON dirigido por catálogo

El SOP distingue dos conjuntos de atributos y el modelo los trata distinto:

| | Atributos comunes (SOP §9.1) | Ficha específica (SOP §9.2) |
|---|---|---|
| Dónde viven | Columnas de `elemento` | `elemento.atributos` (JSON) |
| Por qué | Se filtran, ordenan e indexan en cada consulta | Cambian por tipo y evolucionan |
| Quién los valida | El propio esquema de la tabla | `definicion_atributo` + `servicios/validacion.py` |

`definicion_atributo` actúa como **esquema de datos almacenado como datos**:
declara clave, etiqueta, tipo de dato, obligatoriedad, opciones y unidad de
cada campo de la ficha. Con eso:

- el backend valida la carga sin conocer los tipos de antemano;
- el reporte de completitud sabe qué es obligatorio para cada tipo;
- el panel de detalle del visor rotula los campos sin tener nada codificado.

Incorporar un tipo nuevo es un `POST /api/v1/catalogo/tipos`. No hay migración
de esquema, ni despliegue de backend, ni cambio en el frontend.

El costo de la decisión: los atributos de ficha no se pueden indexar ni
consultar con la misma eficiencia que una columna. Si alguno pasa a ser
transversal y consultado con frecuencia (ocurrió con `direccion_ip`), la salida
es promoverlo a columna en una migración.

### 2. Anidamiento por contención

`elemento.padre_id` apunta a otro elemento. Resuelve el punto 20 de la sección
10.3 del SOP: varios elementos comparten una coordenada del plano, así que el
contenedor lleva el marcador y los demás cuelgan de él. Solo los tipos con
`es_contenedor = true` pueden ser padres.

En el CADI el contenedor es el rack (`R`): aloja switches, routers, patch
panels, ODF, servidores y PBX (10 racks). El rack lleva el marcador y, al
seleccionarlo, el visor despliega su vista frontal con los equipos montados.

Los puntos de datos (`PD`) no tienen contenedor: cada uno es una fila de la
planilla, con su propio marcador, y el recinto donde está queda como ubicación
descriptiva.

**Montado o conectado.** Lo montado dentro de su contenedor no se ubica por
separado: la API rechaza darle coordenadas propias, el visor lo dibuja a través
del marcador del contenedor y su completitud toma las coordenadas de este
(`Elemento.representante_en_plano`). Las planillas, sin embargo, anotan en la
columna *Rack* también el rack al que se **conecta** un AP o una UPS de torre,
que están en otro lugar. Esos tipos (`TIPOS_CONECTADOS_AL_CONTENEDOR`) conservan
el `padre_id`, pero se ubican por su cuenta y la ficha del rack los lista como
"conectados".

Una versión anterior agrupaba los puntos de datos de un mismo recinto bajo un
tipo `FP` (*faceplate*), tomando como elemento la "roseta" de la primera
columna de la planilla. Se eliminó: `FP` no existe en el SOP §8.4 y, para la
DSI, la roseta **es** el punto de datos.

### 3. Historial campo a campo

Cada modificación deja una fila en `historial_elemento` con el campo, el valor
anterior, el valor nuevo y el **origen** (`manual`, `monitoreo`, `importacion`,
`sistema`). El origen es lo que permite distinguir un cambio hecho por un
técnico de una sincronización automática de Zabbix, y es la base del registro
de retención permanente que exige la sección 12 del SOP.

## Tablas

### Territorio

| Tabla | Rol |
|---|---|
| `edificio` | Catálogo del SOP §8.2. `codigo` es la sigla que abre todo código de elemento |
| `piso` | `P00`…`PXX` (SOP §8.3), con `orden` para la navegación |
| `tramo` | Subdivisión horizontal del piso (`T1`, `T2`…), usada en el código |
| `plano` | Imagen base del piso o de uno de sus tramos (`tramo_id` nulo = piso completo). `ancho_px` y `alto_px` definen el sistema de coordenadas. Solo uno vigente por piso–tramo; los anteriores quedan como histórico |
| `persona` | Responsables (SOP §4) |
| `levantamiento` | Bitácora por edificio (SOP §10.5 punto 24) |

### Catálogo

| Tabla | Rol |
|---|---|
| `tipo_elemento` | Taxonomía del SOP §7.2 con su código del §8.4, categoría, color e íconos, y las banderas `es_contenedor` y `usa_correlativo` |
| `definicion_atributo` | Esquema de la ficha de cada tipo (SOP §9.2) |

### Elementos

| Tabla | Rol |
|---|---|
| `elemento` | Unidad documentada. Identificación, ubicación, coordenadas, estado, identidad de red, trazabilidad y ficha JSON |
| `fotografia` | Evidencia (SOP §10.4), nombrada `<código>_<n>.<ext>` |
| `historial_elemento` | Bitácora campo a campo |

### Lógica y conectividad

| Tabla | Rol |
|---|---|
| `vlan` | VLAN y subred (SOP §7.1, categoría lógica). El número es único **por edificio**: la VLAN 3 del CADI y la de otro edificio son registros distintos |
| `elemento_vlan` | Qué elemento materializa qué VLAN y en qué rol |
| `identificador_externo` | Id del elemento en otro sistema (NetBox, GLPI, Zabbix…): uno por sistema y elemento. Lo usan los conectores para sincronizar sin duplicar ([integraciones](integraciones.md)) |
| `enlace` | Conexión física. Cubre tanto el uplink de un switch (§9.2.1) como el mapeo puerto de patch panel → punto de datos (§9.2.3). `destino_descripcion` permite registrar el destino como texto mientras no exista como elemento documentado |

## Enumeraciones

Se almacenan como `VARCHAR` con restricción `CHECK`, no como tipos nativos de
PostgreSQL. Agregar un valor a la taxonomía es entonces una migración simple en
ambos motores, sin el ciclo de `CREATE TYPE` / `ALTER TYPE`.

| Enumeración | Valores |
|---|---|
| `categoria_elemento` | activo, pasivo, soporte, logico |
| `estado_operativo` | activo, inactivo, en_falla, en_mantenimiento, retirado |
| `estado_condicion` | excelente, regular, malo, obsoleto |
| `criticidad` | alta, media, baja |
| `tipo_dato` | texto, numero, booleano, fecha, enum, ip, mac, lista, referencia |
| `origen_cambio` | manual, monitoreo, importacion, sistema |
| `medio_enlace` | cobre, fibra, inalambrico |

## Coordenadas sobre el plano

`elemento.pos_x` y `pos_y` se expresan en las unidades declaradas por el plano
(`ancho_px` × `alto_px`), con el origen en la **esquina superior izquierda**,
que es como se numeran los planos.

Leaflet mide la latitud hacia arriba, así que el visor convierte en el borde:

```
latlng = (alto_px - y, x)
```

La conversión vive únicamente en `frontend/src/components/VisorPlano.tsx`
(`aLatLng` / `aCoordenadas`). El backend almacena siempre coordenadas de plano,
nunca coordenadas de Leaflet: si mañana el visor cambia a Konva o a SVG, los
datos siguen siendo válidos.

### Láminas por tramo

La DSI dibuja los pisos grandes del CADI en una lámina por tramo (el Piso 1 en
tres, los pisos 2 y 3 en dos), y cada lámina tiene su propio sistema de
coordenadas. Por eso un plano puede cubrir el piso completo o un solo tramo, y
la posición de un elemento solo se dibuja sobre la lámina del mismo
piso–tramo en que se fijó. Un tramo sin lámina propia se ve sobre el plano del
piso completo, como el Piso 4.

El tramo del código y la lámina donde está dibujado un elemento no siempre
coinciden. En el Piso 1, la sala eléctrica de los racks se considera tramo 3, así
que los racks y los puntos de datos que llegan a ellos llevan T3 en el rótulo,
pero están dibujados en la lámina del tramo 1: la del tramo 3 solo muestra el
auditorio. Por eso `elemento.tramo_lamina_id` guarda, cuando hace falta, el
tramo de la lámina que lo muestra (nulo = la de su propio tramo). Lo montado
sigue la lámina de su rack. La vista de un tramo muestra lo dibujado en su
lámina, el backend rechaza ubicar un elemento sobre otra lámina, y la ficha del
visor permite cambiarla; al hacerlo se borra la posición anterior, que era
sobre la otra lámina.

**Grupos de puntos de datos.** Los puntos de datos con exactamente la misma
posición forman un grupo: un solo marcador con cuántos son y una sola fila en
el listado. Al ubicar un punto de datos, un clic sobre otro ya ubicado toma su
posición exacta. El grupo no se guarda: se deriva de las coordenadas, así que
mover un punto de datos lo saca del grupo.

Se optó por coordenadas simples y no por PostGIS porque un plano de piso no
tiene sistema de referencia geográfico y la única operación espacial requerida
es "dibujar un punto donde el usuario hizo clic".
