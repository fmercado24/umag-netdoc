# Hallazgos del levantamiento del CADI

Discrepancias detectadas al cargar las planillas de la DSI al sistema y al
cruzarlas con las láminas. Se generan automáticamente y pueden volver a
listarse en cualquier momento:

```bash
cd backend
.venv/bin/python -m app.scripts.importar_cadi --solo-advertencias   # planillas
.venv/bin/python -m app.scripts.cargar_planos CADI                   # planillas contra láminas
```

Corresponden al evento "detección de discrepancia entre lo documentado y lo
observado en terreno" del SOP §11.1, y son el insumo para cerrar el
levantamiento según §10.5.

## 1. Racks referenciados pero no documentados — resuelto

Los dos racks que solo aparecían en los rótulos ya tienen su planilla:

| Rack | Cómo se resolvió |
|---|---|
| `CADI-R06-P02-T2` | Se levantó el Piso 2 Tramo 2 (`cadi-p02-t2.csv`): el rack, 2 switches, 2 patch panels, 2 AP y una UPS |
| `CADI-R11-P00` | Se levantó el subterráneo (`cadi-p00.csv`): el rack 11 está en la **Exclusa 0017 del subterráneo**, no en el Piso 1 Tramo 1 donde se lo había inferido. Al importar con `--agregar`, `CADI-R11-P01-T1` pasó a `CADI-R11-P00` (el cambio de código queda en su historial). Los 2 puntos de datos del Área de Espera 1011 (`P01-T1-R11-C02`, `P01-T1-R11-T13`) siguen enlazados a él: el cableado sube por la «Subida a Piso 1» que dibuja la lámina del subterráneo |

Queda una consecuencia, descrita en el hallazgo 10.

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

Las láminas, además, rotulan la telefonía con **V** (voz: `V04 R11`), mientras
las planillas usan **T** (`SUB-R11-T04`). El sistema sigue la planilla.

## 6. Diferencias entre la planilla consolidada y las planillas por tramo

| Ubicación | Tipo | Consolidada | Por tramo | Interpretación |
|---|---|---|---|---|
| P01-T2 | AP | 1 | 2 | La planilla por tramo documenta `WIFI-AP-P1-T2--1078` y `WIFI-AP-P1-T2--1079`; la consolidada solo trae un AP sin modelo. **Las planillas por tramo están más actualizadas.** |
| P00 | Rack, switches, patch panels, AP | 0 | 1, 2, 2, 1 | La consolidada no incluye el subterráneo |
| P02-T2 | Rack, switches, patch panels, AP, UPS | 0 | 1, 2, 2, 2, 1 | La consolidada no incluye el Piso 2 Tramo 2 |

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

> **Actualización (octubre).** Con las láminas nuevas y la ubicación por
> recinto ya no hay que decidirlo a mano: cada elemento queda en la lámina
> donde está dibujado su recinto o su rack. De los 81 elementos ubicados que
> el rótulo pone en P01-T3, 68 quedaron en la lámina del tramo 1; 8 en la del
> tramo 2 (los racks 1, 2 y 10 con su AP y su UPS, el Hall 1061 y la Sala de
> Control y Tableros 1060), y 5 en la del tramo 3 (Escenario 1076 y Sala de
> Control 1072). `cadi-laminas.csv` solo decide qué lámina se mira primero.
> Lo que sigue describe la situación con las láminas anteriores.

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

## 9. Piso subterráneo sin levantar — resuelto

Se recorrió el 15 de octubre de 2026. `cadi-p00.csv` trae el rack 11 de la Exclusa 0017 con
2 switches, 2 patch panels y un AP, y `cadi-puntos-de-datos.csv` suma 16
puntos de datos en 6 recintos (salas de experimentación 0010 y 0011, salas 1 a
3 y oficina viverista 0022). Sus rótulos empiezan con `SUB` en vez del piso
(`SUB-R11-D05`), y la ubicación dice «Piso Subterráneo»: el importador
reconoce ambos como el piso P00.

## 10. Un switch del Piso 1 declara el rack del subterráneo

El switch `LINKSYS LGS528P` «SW CCTV/TEL» (`CADI-SW01-P01-T1`) está en la Sala
de Grabación 1015 del Piso 1, pero su planilla lo asocia al Rack-11, que está
en el subterráneo. Un equipo no puede verse a través de un rack de otro piso:
el importador no lo monta, lo ubica en su sala y deja la planilla como
observación. **Verificar en terreno** si el switch está en un gabinete propio
de la Sala de Grabación o si en realidad está montado en el rack 11.

## 11. Recintos de las planillas que no coinciden con las láminas

Al leer las láminas con OCR (`extraer_recintos`) y cruzarlas con las
planillas, algunos números de sala no aparecen en la lámina de su piso. Sus
elementos quedan sin ubicar hasta corregir el número (en el visor,
*Editar → N° de recinto*) o ubicarlos a mano:

| Planilla | Elementos | En la lámina | Qué hacer |
|---|---|---|---|
| Recepción 1063 (P01-T2) | 6 puntos de datos (`R04-D16` a `D18`, `T16` a `T18`) | La sala se rotula SECRETARÍA RECEPCIÓN **1082** | Confirmar el número; si es 1082, corregirlo |
| Administración Oficina Médica 3006 (P03-T1) | 2 puntos de datos (`R07-D20`, `R07-T21`) | ADMINISTRACIÓN OFICINA MÉDICA **3016** | Ídem |
| Oficina 3014 (P03-T1) | 2 puntos de datos (`R07-D03`, `R07-T03`) | La lámina rotula **tres oficinas contiguas como OFICINAS 3012**, con D05, D04 y D03 dibujados uno en cada una: es un rótulo copiado en el CAD | Corregir la lámina; mientras tanto, ubicarlos a mano. Los de «Oficina 3012» quedaron en una de las tres |
| Oficina 2048 (P02-T2) | 4 puntos de datos (`R06-D06`, `D07`, `T01`, `T02`) | No hay oficina 2048: `D07 R6` está dibujado en un laboratorio | Verificar en terreno |

Otros recintos tienen el mismo número en la planilla y en la lámina, pero con
otro nombre. Se ubicaron bien y solo conviene unificar el nombre: la Oficina
1078 es BIBLIOTECA 1078 en la lámina, y el Laboratorio Microscopía 1085 es
«OCUPADO POR PISO -1» 1085.

La lámina del Piso 3 Tramo 1 repite también ESCALERA 3001; la del subterráneo,
BAÑO Y CAMARÍN 0044; y la del Piso 1 Tramo 2, OFICINA SUBDIRECTOR 1081. El
OCR usó el primero de cada par.

## 12. Salas eléctricas sin número en las láminas

Las salas de los racks aparecen en las láminas sin número («SALA ELÉCTRICA»,
«SALA TÉCNICA ELÉCTRICO»), aunque las planillas les asignan 1068 (Piso 1),
3082 y 3083 (Piso 3), o ninguno (Pisos 2 y 4). En el Piso 1, los racks 1, 2 y
10 están dibujados en la sala **SERVIDORES 1067**, no en una 1068.

Los racks sí están rotulados en las láminas (RACK 05, RACK 06, RACK 07,
RACK 09, RACK 10, Rack 11), y el sistema los ubica sobre su rótulo; el AP y la
UPS de cada sala quedan junto a su rack. Los rótulos RACK 1 y RACK 2
(Piso 1) y RACK 08 (Piso 3) están tapados por el achurado de la canalización
y el OCR no los lee:

- los racks 1 y 2 quedaron junto al rack 10, que la planilla pone en la misma
  sala;
- **el rack 8 hay que ubicarlo a mano**. Al hacerlo, sus 3 AP y sus 2 UPS
  quedan solos a su lado.

## Resumen del estado del dato

| Indicador | Valor |
|---|---|
| Elementos cargados | 389 (81 equipos y 308 puntos de datos), en 5 pisos y 8 tramos |
| Completitud del levantamiento | 100 % de los atributos obligatorios, incluidos los confidenciales, según el registro del levantamiento |
| Completitud promedio en este sistema | 63,3 %: sin los datos confidenciales, que aún no se cargan en el sistema |
| Atributos publicables completos | 98,7 %: ubicación, estado, condición, coordenadas y fecha del levantamiento |
| Elementos con ficha completa | 0 |
| Elementos ubicados en el plano | 317 de los 337 con marcador propio; los 52 montados se ven en su rack |
| Racks inferidos | 0 (eran 2) |
| Rótulos duplicados pendientes | 2 (eran 4) |
| Puntos de datos sin rótulo | 6 |
| Tramos sin planilla | 0 (el subterráneo y el Piso 2 Tramo 2 ya están) |
| Elementos con fecha del levantamiento | 389: los pisos 1 a 4 se recorrieron el 15 y 16 de septiembre de 2026, y el subterráneo, el 15 de octubre (`cadi-levantamiento.csv`) |
| Recintos de las planillas que no aparecen en las láminas | 7 (hallazgos 11 y 12) |

Ningún elemento alcanza todavía el mínimo obligatorio del SOP §9 en el
sistema porque los datos confidenciales —MAC, IP, configuración de los
equipos, fecha de instalación, datos del cableado y responsables— se
levantaron, pero no van en las planillas del repositorio: se registran solo en
la instalación institucional del sistema. Las coordenadas y la fecha del levantamiento ya no
son parte de esa brecha: salen del número de sala de cada planilla y de
`cadi-levantamiento.csv`. El reporte
`/api/v1/reportes/elementos-incompletos` persigue el resto elemento por
elemento.
