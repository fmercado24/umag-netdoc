# Hallazgos del levantamiento del CADI

Discrepancias detectadas al cargar las planillas de la DSI al sistema. Se
generan automáticamente y pueden volver a listarse en cualquier momento:

```bash
cd backend && .venv/bin/python -m app.scripts.importar_cadi --solo-advertencias
```

Corresponden al evento "detección de discrepancia entre lo documentado y lo
observado en terreno" del SOP §11.1, y son el insumo para cerrar el
levantamiento según §10.5.

## 1. Racks referenciados pero no documentados

| Rack | Evidencia | Qué falta |
|---|---|---|
| `CADI-R11-P01-T1` | El switch `LINKSYS LGS528P` de la Sala de Grabación 1015 lo declara como su rack, y 2 puntos de datos del Área de Espera 1011 terminan en él (`P01-T1-R11-C02`, `P01-T1-R11-T13`) | Ficha completa: tipo, U ocupadas, alimentación |
| `CADI-R06-P02-T2` | 22 puntos de datos del Piso 2 Tramo 2 terminan en él (`P02-T2-R6-*`) | Ficha completa y, además, **no existe planilla del Piso 2 Tramo 2**: el rack, sus switches y sus patch panels están sin levantar |

El importador los crea con una observación explícita para no romper el mapeo
de cableado, pero quedan sin ficha y aparecen en el reporte de incompletos.

## 2. Rótulos duplicados

Cuatro rótulos aparecían dos veces, en recintos distintos. El importador
conserva ambos registros y le agrega el sufijo `-DUP2` al segundo, para no
perder información hasta que se verifique en terreno cuál es el correcto.

| Rótulo | Recinto A | Recinto B | Estado |
|---|---|---|---|
| `P03-T1-R7-D11` | ~~Archivo Confidencial 3007~~ | Sala Archivo Confidencial 3017 | **Corregido**: era el mismo punto de datos con dos números de sala; se eliminó el duplicado y quedó la 3017 |
| `P03-T1-R7-T12` | ~~Archivo Confidencial 3007~~ | Sala Archivo Confidencial 3017 | **Corregido**, ídem |
| `P02-T1-R5-T02` | Gimnasio Box 2006 | Laboratorio Audiología 2030 | Pendiente de verificar en terreno |
| `P03-T2-R8-D35` | Cultivo Celular 3065 | Sala Citometría 3048 | Pendiente de verificar en terreno |

Los dos pendientes son puntos de datos en salas **distintas** que comparten rótulo,
así que una de las dos está mal etiquetada físicamente: hay que identificar
cuál con el tester antes de reetiquetar.

## 3. Ubicación inconsistente

El punto de datos `P02-T2-R6-D01` de la Hemeroteca 2041 está declarado en la
columna Ubicación como *Piso 2 - Tramo 1*, mientras que los otros cuatro de la
misma sala (`D02`–`D05`) dicen *Tramo 2*. El importador toma el tramo del rótulo,
que es el que coincide con el resto del grupo.

## 4. Puntos de datos sin rótulo

Seis puntos de datos registrados como "Sin etiqueta", todos fuera de servicio:

- Piso 1 Tramo 3 (5): Box 1 1025, Box 2 1028, Box 3 1031, Oficina Box 1 1026,
  Oficina Box 2 1029.
- Piso 2 Tramo 1 (1): Box de atención 3 2020.

Quedan cargadas con código `CADI-PD-<piso>-<tramo>-SIN-ROTULO-<n>` y sin
`puerto_origen`: no se puede reconstruir a qué patch panel llegan sin ir a
terreno con el tester.

## 5. Prefijos de puerto sin servicio asignado

El prefijo del rótulo identifica el servicio del punto de datos. Se mapean con
confianza `D` → datos, `T` → telefonía y `C` → CCTV, respaldados por la
leyenda de VLANs y por los rótulos de los switches (`SW-COM`, `SW-TEL`,
`SW CCTV/TEL`). Quedan dos sin interpretar:

- `P1-T3-R1-IMP` (Escalera 1019) — presumiblemente impresora.
- `P02-T1-R5-V07` (Gimnasio Box 2007) — presumiblemente video.

No se les asignó servicio ni VLAN para no inventar datos.

## 6. Diferencias entre la planilla consolidada y las planillas por tramo

| Ubicación | Tipo | Consolidada | Por tramo | Interpretación |
|---|---|---|---|---|
| P01-T2 | AP | 1 | 2 | La planilla por tramo documenta `WIFI-AP-P1-T2--1078` y `WIFI-AP-P1-T2--1079`; la consolidada solo trae un AP sin modelo. **Las planillas por tramo están más actualizadas.** |
| P01-T1 | Rack | 0 | 1 | Rack-11, ausente en la consolidada |
| P02-T2 | Rack | 0 | 1 | Rack-06, ausente en la consolidada |

Por eso el importador usa las planillas por tramo como fuente autoritativa y
la consolidada solo para contrastar.

## 7. Errores de transcripción — corregidos

| Error | Corrección aplicada |
|---|---|
| "Roseta Comedor **Estufiantes** 1050" (3 filas) frente a "Estudiantes" (1 fila); el sistema las trataba como dos recintos distintos | Unificado a "Roseta Comedor Estudiantes 1050"; ahora es **un solo recinto con 4 puntos de datos** |
| "Roseta Box Fisiopatología **2022**" en el Piso 3 Tramo 1, con numeración de sala del Piso 2 | Corregido a **3022** |
| "Archivo Confidencial 3007" / "Sala Archivo confidencial 3017" | Unificado a "Sala Archivo Confidencial 3017"; eliminadas las 2 filas duplicadas |

Queda pendiente: la numeración inconsistente entre "Oficina 1083" y
"oficina 1083.2" en el Piso 1 Tramo 2. Son dos recintos reales distintos (8
puntos de datos en total), pero conviene normalizar el nombre de la sala.

## 8. El tramo del rótulo no es la lámina donde está dibujado

En el Piso 1, la sala eléctrica de los racks 01, 02 y 10 se considera tramo 3.
Los racks, sus equipos y los puntos de datos que llegan a ellos llevan por eso
T3 en el rótulo, pero están dibujados en la lámina del **tramo 1**; la del
tramo 3 solo muestra el auditorio. El sistema conserva el tramo del rótulo y
registra aparte la lámina (ver [modelo-datos.md](modelo-datos.md)):

| Recintos | Lámina |
|---|---|
| Todo lo rotulado P01-T3, salvo lo que sigue | Tramo 1 (72 elementos, más los 21 equipos de los racks) |
| Escenario Auditorio 1076, Sala de Control 1072 y el AP del auditorio | Tramo 3 (6) |
| Hall 1061 y Sala de control y tableros 1060 | Tramo 2 (3): están dibujados en esa lámina, no en la del tramo 1 |

La regla está en `LAMINA_POR_TRAMO` y `LAMINA_POR_RECINTO` del importador; un
caso puntual se corrige desde la ficha del elemento en el visor.

## 9. Piso subterráneo sin levantar

`cadi-p00.csv` tiene encabezado pero ninguna fila, así que el piso P00 ni
siquiera se crea en el sistema. Queda por confirmar si el subterráneo
realmente no tiene infraestructura de red o si está pendiente de levantar.

## Resumen del estado del dato

| Indicador | Valor |
|---|---|
| Elementos cargados | 470 |
| Completitud promedio | 46,9 % |
| Elementos con ficha completa | 0 |
| Elementos con coordenadas sobre el plano | 0 |
| Racks inferidos | 2 |
| Rótulos duplicados pendientes | 2 (eran 4) |
| Puntos de datos sin rótulo | 6 |
| Tramos sin levantar | 1 (Piso 2 Tramo 2) |

Ningún elemento alcanza el mínimo obligatorio del SOP §9 porque las
planillas no registran número de serie, MAC, IP de gestión, fecha de
instalación, responsable ni coordenadas. Esa es la brecha que el sistema
debe cerrar, y el reporte `/api/v1/reportes/elementos-incompletos` la
persigue elemento por elemento.
