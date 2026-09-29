# Convención de nomenclatura

Implementación de la sección 8 de SOP-DSI-RED-001.
Código fuente: `backend/app/servicios/codigos.py`. Pruebas: `backend/tests/test_codigos.py`.

## Estructura

```
<UBICACIÓN GENERAL> - <EQUIPO> - <UBICACIÓN ESPECÍFICA> [- <DETALLE/PUERTO>]
```

| Bloque | Contenido | Ejemplo |
|---|---|---|
| Ubicación general | Sigla del edificio (`edificio.codigo`) | `CADI` |
| Equipo | Código del tipo + correlativo de dos dígitos | `R04`, `SW01` |
| Ubicación específica | Piso y, si aplica, tramo | `P01-T2` |
| Detalle/puerto | Condicional: hacia dónde va el cableado | `R01-T20` |

Ejemplos del SOP, ambos cubiertos por pruebas:

```
CADI-R04-P01-T2           Rack N°4 del CADI, Piso 1 Tramo 2
CADI-PD-P01-T3-R01-T20    Punto de datos conectado al puerto 20 del
                          patch panel de teléfono del Rack N°1
```

El punto de datos no lleva correlativo porque su tipo tiene
`usa_correlativo = false`: lo identifica el detalle, no un número de serie
propio. Es una propiedad del catálogo, así que un tipo terminal nuevo se
comporta igual sin tocar el código.

## Códigos de tipo

Los del SOP §8.4 (`SW`, `RT`, `AP`, `PP`, `PD`, `R`, `UPS`, `MC`, `ONT`,
`PBX`, `SV`) más dos que la taxonomía del §7 menciona pero que la tabla de
códigos no lista:

| Código | Tipo | Origen | Uso en el CADI |
|---|---|---|---|
| `ODF` | Distribuidor de fibra (cabecera F.O.) | SOP §7.2, elementos pasivos | 5 cabeceras |
| `PDU` | PDU | SOP §7.1, infraestructura de soporte | ninguno aún |

`ODF` era necesario de inmediato para cargar las planillas del CADI.
**Conviene incorporar los dos códigos a la tabla del §8.4 en la próxima
versión del SOP.**

## Asignación de correlativos

Regla del SOP §8.5: el correlativo crece en orden de documentación dentro del
trío **tipo + edificio + piso**, y un código nunca se reutiliza.

`siguiente_correlativo()` toma el máximo existente y le suma uno, **incluyendo
los elementos dados de baja**. La baja es lógica (`activo = false`), así que el
código de un equipo retirado permanece en la tabla y jamás se reasigna. Un
`POST` con un código ya usado responde `409 Conflict`.

Consecuencia visible: dentro de un mismo piso los correlativos son continuos
aunque los elementos estén en tramos distintos. En el CADI, el piso 1 tiene
`CADI-AP01-P01-T2` y `CADI-AP02-P01-T3`.

## Puntos de datos: el rótulo ya codifica el destino

Cada fila de la planilla de puntos de datos es un punto de datos (`PD`). La
planilla también los llama "rosetas" y en su primera columna anota el recinto
("Roseta Oficina 1083"): ese texto queda como ubicación descriptiva ("Oficina
1083"), no como un elemento aparte.

Las planillas del CADI rotulan cada punto de datos como `P<piso>-T<tramo>-R<rack>-<puerto>`
(por ejemplo `P01-T2-R4-D01`). Ese rótulo contiene exactamente los bloques que
el SOP pide, así que el código se arma sin información adicional:

```
P01-T2-R4-D01   →   CADI-PD-P01-T2-R04-D01
P1-T3-R1-T26    →   CADI-PD-P01-T3-R01-T26
P03-T1-R7-D01-ERM → CADI-PD-P03-T1-R07-D01-ERM
```

El detalle (`R04-D01`) es la referencia al rack y puerto de origen, igual que
en el ejemplo `CADI-PD-P01-T3-R01-T20` del SOP. El mismo dato se guarda además
como un `enlace` rack → punto de datos, que es el mapeo puerto → punto de datos
de la sección 9.2.3.

La letra inicial del puerto identifica el servicio: `D` datos, `T` telefonía,
`C` CCTV. El importador la usa para poblar `servicio` y `vlan_por_defecto`, y
**reporta** los prefijos que no sabe interpretar (`IMP`, `V07`) en vez de
adivinarlos.

Los puntos de datos rotulados "Sin etiqueta" reciben `CADI-PD-<piso>-<tramo>-SIN-ROTULO-<n>`
y quedan sin `puerto_origen`: hay que ir a terreno con el tester para saber a
qué patch panel llegan.

Cuando dos filas traen el mismo rótulo, el segundo elemento se registra con
sufijo `-DUP2` y la colisión se reporta, para no perder ninguno de los dos
registros antes de verificar cuál es el correcto. Ver
[hallazgos-cadi.md](hallazgos-cadi.md).

## Normalización de entradas

El importador y la API aceptan las formas en que la información aparece en las
planillas y las normalizan:

| Entrada | Resultado |
|---|---|
| `1`, `"Piso 1"`, `"p01"` | `P01` |
| `"exterior"` | `PXX` |
| `2`, `"Tramo 2"`, `"t2"` | `T2` |
| `"Rack-04"`, `"RACK 4"` | correlativo `4` → `R04` |

## Generación automática

`POST /api/v1/elementos` sin campo `codigo` lo construye solo:

```json
{ "tipo": "SW", "edificio": "CADI", "piso": "P01", "tramo": "T2" }
```
→ `CADI-SW01-P01-T2`

Si se entrega un `codigo` explícito, se valida contra la expresión regular de
la convención y se extrae el correlativo; un código malformado responde `422`.

## Rotulado físico

El SOP §8.5 exige rotular con etiquetadora sobre superficie limpia y visible, y
también dentro de la puerta del rack. El campo `elemento.etiqueta` guarda el
rótulo **observado en terreno**, que puede no coincidir con el código
normalizado: en el CADI conviven `CADI-AP01-P01-T2` (código del sistema) y
`WiFi-AP P1-T2-01` (rótulo existente). Mantener ambos permite que el técnico
encuentre el equipo por lo que dice la etiqueta real mientras el reetiquetado
avanza.
