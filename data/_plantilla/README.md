# Plantillas para el levantamiento de un edificio

Copie esta carpeta como `data/<código>/` (en minúsculas, por ejemplo
`data/ing/`) y cambie `codigo` por el código del edificio en el nombre de cada
archivo (`ing-p01-t1.csv`, `ing-puntos-de-datos.csv`…). Borre las filas de
ejemplo antes de importar.

| Archivo | Obligatorio | Contenido |
|---|---|---|
| `codigo-p<piso>-t<tramo>.csv` | Sí, uno por piso–tramo | Equipamiento: racks, switches, patch panels, AP, UPS… Si el piso no tiene tramos: `codigo-p<piso>.csv` |
| `codigo-puntos-de-datos.csv` | No | Un punto de datos por fila |
| `codigo-vlans.csv` | No | Leyenda de VLANs y la VLAN de cada servicio |
| `codigo-laminas.csv` | No | Solo si hay elementos dibujados en la lámina de otro tramo |
| `planos/` | No | Láminas SVG con nombre obligatorio `codigo-p<piso>[-t<tramo>].svg`: `codigo-p01-t1.svg`, `codigo-p02.svg` (piso completo), `codigo-p00.svg` (subterráneo) |
| `fotos/` | No | Fotografías con el código del elemento: `ING-SW01-P01-T1.jpg` |

El detalle de cada columna y el procedimiento completo están en
[`docs/guia-nuevo-edificio.md`](../../docs/guia-nuevo-edificio.md).
