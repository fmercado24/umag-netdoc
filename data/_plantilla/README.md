# Plantillas para el levantamiento de un edificio

La forma más simple es llenar [`plantilla-levantamiento.xlsx`](plantilla-levantamiento.xlsx):
trae una hoja por archivo, listas desplegables para *Tipo*, *Estado Operativo* y *Estado
Condición*, e instrucciones con una fila de ejemplo. Cada hoja se guarda como CSV con su
nombre (*Archivo → Guardar como → CSV UTF-8*, hoja por hoja).

Si prefiere los CSV de esta carpeta, cópiela como `data/<código>/` (en minúsculas, por
ejemplo `data/ing/`), cambie `codigo` por el código del edificio en el nombre de cada
archivo (`ing-p01-t1.csv`, `ing-puntos-de-datos.csv`…) y borre las filas de ejemplo antes de
importar. Las columnas van en cualquier orden y se reconocen aunque tengan errores de tipeo.
Cargue primero los planos: así cada elemento se ubica en su **sala del plano**.

| Archivo | Obligatorio | Contenido |
|---|---|---|
| `codigo-p<piso>-t<tramo>.csv` | Sí, uno por piso–tramo | Equipamiento: racks, switches, patch panels, AP, UPS… Si el piso no tiene tramos: `codigo-p<piso>.csv` |
| `codigo-puntos-de-datos.csv` | No | Un punto de datos por fila |
| `codigo-vlans.csv` | No | Leyenda de VLANs y la VLAN de cada servicio |
| `codigo-laminas.csv` | No | Solo si hay elementos dibujados en la lámina de otro tramo |
| `codigo-levantamiento.csv` | No | Fechas de cada visita a terreno y pisos que cubrió: dan la fecha del último levantamiento de los elementos |
| `planos/` | No | Láminas SVG con nombre obligatorio `codigo-p<piso>[-t<tramo>].svg`: `codigo-p01-t1.svg`, `codigo-p02.svg` (piso completo), `codigo-p00.svg` (subterráneo) |
| `codigo-recintos.csv` | No: lo escribe `extraer_recintos` | Códigos de sala y rótulos de racks leídos de las láminas. Si los planos se cargan desde el visor, las salas se leen solas y este archivo no hace falta. Con ellas cada elemento se ubica en la **sala del plano** de su fila (`1083`, `09`, `Colección Jurídica`) |
| `fotos/` | No | Fotografías con el código del elemento: `ING-SW01-P01-T1.jpg` |

El detalle de cada columna y el procedimiento completo están en
[`docs/guia-nuevo-edificio.md`](../../docs/guia-nuevo-edificio.md).
