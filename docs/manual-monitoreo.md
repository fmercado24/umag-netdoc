# Manual de monitoreo: Prometheus, Grafana y Zabbix

Para el equipo de la DSI que opere el monitoreo de la red. NetDoc documenta
**qué hay y dónde está**; el monitoreo informa **si responde**. Integrados,
cada equipo documentado queda vigilado y su estado en NetDoc se actualiza solo:
un equipo caído aparece "en falla" en el visor, con el motivo en su historial.

Las dos opciones son independientes: puede usar **Prometheus + Grafana**, la
**Zabbix** que ya tenga la DSI, o ambas. La referencia técnica está en
[integraciones.md](integraciones.md).

## Antes de empezar

1. **IP de gestión en los elementos.** Solo se vigila lo que tiene IP. Se carga
   con la columna `IP` de las planillas
   ([guía de edificios](guia-nuevo-edificio.md), sección 3.1)
   o desde la ficha del visor (**Editar** → *IP de gestión*).
2. **Un token para los avisos de estado.** Genere uno y guárdelo en `.env`, en
   la carpeta `umag-netdoc`:

   ```bash
   openssl rand -hex 24          # copie el resultado
   ```
   ```
   # umag-netdoc/.env
   NETDOC_MONITOREO_TOKEN=<el token>
   ```
   Reinicie NetDoc (`Ctrl+C` y `./iniciar.sh`). Sin token, NetDoc rechaza los
   avisos de estado (responde 503).
3. **Red.** El servidor de monitoreo debe llegar a NetDoc (puerto 8000) y a las
   IP de gestión de los equipos; Zabbix y Alertmanager deben poder enviar a
   NetDoc.

---

## Opción A: Prometheus + Alertmanager + Grafana (con Docker)

Cuatro servicios definidos en el perfil `monitoreo` de `docker-compose.yml`:

| Servicio | Puerto | Qué hace |
|---|---|---|
| Prometheus | 9090 | Lee las métricas de NetDoc y guarda el historial |
| blackbox | — | Hace ping a cada elemento con IP que Prometheus descubre en NetDoc |
| Alertmanager | 9093 | Recibe las alertas y avisa a NetDoc (y, si se configura, por correo) |
| Grafana | 3000 | Panel "NetDoc — Inventario y estado" |

### A.1 Instalar Docker (una vez)

En el servidor (Ubuntu):

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER        # cierre sesión y vuelva a entrar
docker compose version               # debe responder "Docker Compose version v2…"
```

### A.2 Configurar

1. **Clave de Grafana**, en el mismo `.env`:
   ```
   NETDOC_GRAFANA_CLAVE=<una clave segura>
   ```
2. **Token en Alertmanager** (el mismo `NETDOC_MONITOREO_TOKEN`):
   ```bash
   sed -i "s/CAMBIAR_POR_NETDOC_MONITOREO_TOKEN/<el token>/" deploy/alertmanager/alertmanager.yml
   ```
3. **Si NetDoc corre en otro equipo** que Docker, reemplace
   `host.docker.internal` por la IP o el nombre de ese equipo en
   `deploy/prometheus/prometheus.yml` (dos lugares) y en
   `deploy/alertmanager/alertmanager.yml` (uno).

### A.3 Levantar

```bash
# Terminal 1: NetDoc escuchando en la red, para que los contenedores lo alcancen
NETDOC_API_HOST=0.0.0.0 ./iniciar.sh --sin-navegador

# Terminal 2
docker compose --profile monitoreo up -d
docker compose --profile monitoreo ps      # los cuatro en estado "running"/"Up"
```

### A.4 Verificar Prometheus — `http://<servidor>:9090`

1. *Status → Target health*:
   - `netdoc`: **1 objetivo UP** (las métricas de NetDoc).
   - `netdoc-ping`: **un objetivo por elemento con IP**, con etiquetas
     `netdoc_codigo`, `netdoc_edificio`, `netdoc_piso`… Los que no responden a
     ping igual aparecen UP aquí (blackbox respondió); el resultado del ping es
     la métrica `probe_success`.
2. En *Query*, pruebe:

   | Consulta | Muestra |
   |---|---|
   | `sum(netdoc_elementos)` | Elementos documentados |
   | `sum by (edificio, estado_operativo) (netdoc_elementos)` | Por edificio y estado |
   | `probe_success{job="netdoc-ping"} == 0` | Equipos que **no** responden a ping ahora |
   | `netdoc_elemento_estado == 3` | Elementos "en falla" en NetDoc |
   | `netdoc_completitud_porcentaje` | Completitud de fichas por edificio |

3. *Alerts*: las reglas `NetDocElementoSinRespuesta` y `NetDocSinDatos`.

Un edificio nuevo entra solo: el descubrimiento se repite cada 5 minutos.

### A.5 Grafana — `http://<servidor>:3000`

1. Ingrese con `admin` y la clave de `NETDOC_GRAFANA_CLAVE`.
2. *Dashboards → NetDoc → **NetDoc — Inventario y estado***.
3. Arriba, **Edificio** filtra todo el panel (uno, varios o todos).

| Panel | Qué mirar |
|---|---|
| Elementos documentados | Tamaño del inventario |
| En falla | Debe estar en 0; en rojo si hay alguno |
| En mantenimiento | Intervenciones en curso |
| Sin ubicar en el plano | Trabajo pendiente de georreferenciación |
| Completitud de fichas | Avance de la documentación (verde desde 90 %) |
| Por estado / Por tipo | Composición del inventario |
| Elementos no disponibles | Lista con código, tipo, piso y tramo de lo inactivo o en falla |
| Elementos en falla en el tiempo | Cuándo empezó y cuánto duró una caída |
| Disponibilidad por ping | % de equipos que responden, por piso |
| Latencia de la API | Salud de NetDoc (p95 por ruta) |

El panel se puede modificar desde Grafana; los cambios quedan en Grafana (el
archivo `deploy/grafana/dashboards/netdoc.json` es el punto de partida).

### A.6 Qué pasa cuando un equipo se cae

1. blackbox deja de recibir respuesta: `probe_success` pasa a 0.
2. Tras **10 minutos** seguidos sin respuesta se activa
   `NetDocElementoSinRespuesta`. Es el umbral del SOP §11.3.
3. Alertmanager envía la alerta a NetDoc; el elemento queda **en falla**, en
   rojo en el visor, y su historial registra "Alertmanager:
   NetDocElementoSinRespuesta — … no responde a ping".
4. Cuando vuelve a responder, Alertmanager avisa la resolución y el elemento
   vuelve a **activo**.

Un elemento **en mantenimiento** no cambia de estado por estos avisos.

### A.7 Mantención programada

Antes de intervenir un equipo:

1. En NetDoc: ficha → **Editar** → *Estado operativo* = **En mantenimiento**
   (comentario: el motivo). NetDoc ignorará los avisos de caída.
2. Opcional, para no recibir la alerta: en Alertmanager
   (`http://<servidor>:9093`) → *New Silence* → matcher
   `netdoc_codigo="ING-SW01-P01-T1"` → duración.

Al terminar, vuelva el estado a **Activo / En línea**.

### A.8 Ajustes frecuentes

Después de editar un archivo de `deploy/`, valide y reinicie ese servicio:

```bash
docker compose --profile monitoreo exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose --profile monitoreo exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker compose --profile monitoreo restart prometheus alertmanager
```

| Quiero… | Dónde |
|---|---|
| Cambiar el umbral de 10 minutos | `for: 10m` en `deploy/prometheus/reglas.yml` |
| Hacer ping solo a ciertos tipos | En `prometheus.yml`, la URL de `http_sd_configs` admite filtros: `…/prometheus/objetivos?tipo=SW&tipo=RT&tipo=AP` |
| Vigilar solo un edificio | `…/prometheus/objetivos?edificio=ING` |
| Recibir las alertas por correo | Agregar un receptor en `alertmanager.yml` (ejemplo abajo) |

Ejemplo de correo, además del aviso a NetDoc:

```yaml
route:
  receiver: descartar
  group_by: [netdoc_codigo]
  routes:
    - receiver: netdoc
      matchers: [netdoc = "disponibilidad"]
      continue: true             # sigue evaluando: también va al correo
    - receiver: correo-dsi
      matchers: [severity = "critical"]

receivers:
  - name: descartar
  - name: netdoc
    webhook_configs: [...]       # el que ya está
  - name: correo-dsi
    email_configs:
      - to: redes@umag.cl
        from: alertas-netdoc@umag.cl
        smarthost: smtp.umag.cl:587
        auth_username: alertas-netdoc@umag.cl
        auth_password: <clave>
```

### A.9 Operación

| Tarea | Comando |
|---|---|
| Ver el estado | `docker compose --profile monitoreo ps` |
| Ver los mensajes de un servicio | `docker compose --profile monitoreo logs -f prometheus` |
| Detener (conserva los datos) | `docker compose --profile monitoreo down` |
| Actualizar versiones | Cambiar la etiqueta de la imagen en `docker-compose.yml`, luego `docker compose --profile monitoreo pull && docker compose --profile monitoreo up -d` |

Los datos de Prometheus y Grafana quedan en los volúmenes `netdoc_prometheus` y
`netdoc_grafana`.

---

## Opción B: Zabbix

Requiere Zabbix **6.4 o posterior**. Son dos integraciones independientes.

### B.1 Zabbix → NetDoc: estado de los elementos

Zabbix avisa a NetDoc cuando un host entra en problema o se recupera.

1. **Tipo de medio.** *Alerts → Media types → Create media type*:
   - Name: `NetDoc`. Type: **Webhook**.
   - Script: pegue el contenido de
     [`deploy/zabbix/netdoc-webhook.js`](../deploy/zabbix/netdoc-webhook.js).
   - Parameters:

     | Name | Value |
     |---|---|
     | `netdoc_url` | `http://<servidor-netdoc>:8000/api/v1/integraciones/monitoreo/estado` |
     | `netdoc_token` | el `NETDOC_MONITOREO_TOKEN` |
     | `host` | `{HOST.HOST}` |
     | `ip` | `{HOST.IP}` |
     | `event_value` | `{EVENT.VALUE}` |
     | `event_update_status` | `{EVENT.UPDATE.STATUS}` |
     | `event_name` | `{EVENT.NAME}` |

   - Guarde y use **Test** con valores de prueba: `host` = un código real de
     NetDoc, `event_value` = `1`, `event_update_status` = `0`. Debe responder
     `OK` y el elemento quedar en falla en NetDoc (vuélvalo a activo con
     `event_value` = `0`).
2. **Usuario.** *Users → Users → Create user* `netdoc`; en *Media*, agregue
   `NetDoc` con *Send to* `netdoc`. Su grupo de usuarios necesita permiso de
   **lectura** sobre los grupos de hosts a vigilar (por ejemplo `NetDoc`,
   incluyendo subgrupos): Zabbix solo notifica eventos de hosts que el usuario
   puede ver.
3. **Acción.** *Alerts → Actions → Trigger actions → Create action*:
   - Conditions: *Tag name* equals `netdoc_codigo` (la tienen los hosts que
     crea NetDoc) y, para limitarse a disponibilidad, *Event name* contains
     `Unavailable by ICMP ping` (o el nombre de su disparador de
     disponibilidad).
   - Operations: enviar al usuario `netdoc` por `NetDoc`.
   - **Recovery operations**: lo mismo. Sin esto el elemento no vuelve a
     "activo".

El retardo del disparador cumple el papel del umbral del SOP. Un host que NetDoc
no conoce no es un error: el envío queda exitoso con la nota "NetDoc no tiene
documentado…". Los hosts creados a mano en Zabbix se reconocen por su IP.

### B.2 NetDoc → Zabbix: crear los hosts desde el inventario

1. **Token de API.** *Users → API tokens → Create API token* para un usuario
   **Super admin** (crear grupos de hosts lo exige). Alternativa: cree usted
   los grupos `NetDoc/<EDIFICIO>` y `NetDoc/<EDIFICIO>/<PISO>` y use un Admin
   con escritura sobre ellos.
2. **Configuración** en `.env`:
   ```
   NETDOC_ZABBIX_URL=https://zabbix.umag.cl/api_jsonrpc.php
   NETDOC_ZABBIX_TOKEN=<token de API>
   NETDOC_ZABBIX_PLANTILLAS=ICMP Ping,Network Generic Device by SNMP
   ```
   Las plantillas se asignan solo al crear el host. La interfaz SNMP usa la
   macro `{$SNMP_COMMUNITY}`: defínala en *Administration → Macros*.
3. **Plan y aplicación:**
   ```bash
   cd backend
   .venv/bin/python -m app.scripts.sincronizar zabbix --edificio ING
   #   + crear      ING-SW01-P01-T1  10.40.0.2 en NetDoc/ING, NetDoc/ING/P01
   #   zabbix: 12 por crear, 0 por actualizar, 0 sin cambios (12 elementos)
   #   Nada se modificó. Para ejecutar el plan: --aplicar
   .venv/bin/python -m app.scripts.sincronizar zabbix --edificio ING --aplicar
   ```

Cada host se llama como el código del elemento, con el nombre visible
"código + etiqueta", en los grupos `NetDoc/ING` y `NetDoc/ING/P01`, y con las
etiquetas `netdoc_codigo`, `netdoc_tipo`, `netdoc_piso`, `netdoc_tramo`,
`netdoc_criticidad`. Se puede repetir cuando cambie el inventario: actualiza
nombre, grupos y etiquetas de NetDoc, y **no toca** lo que el equipo de Zabbix
haya agregado (otros grupos, etiquetas, plantillas, interfaces). El id de cada
host queda en la ficha de NetDoc, sección *En otros sistemas*.

### B.3 Mantención programada

Además de dejar el elemento **En mantenimiento** en NetDoc, cree un periodo de
mantenimiento en Zabbix (*Data collection → Maintenance*) si no quiere recibir
notificaciones durante la intervención.

---

## Verificación de extremo a extremo

- [ ] NetDoc arranca con `NETDOC_MONITOREO_TOKEN` definido.
- [ ] Hay elementos con IP de gestión en el edificio.
- [ ] (A) En Prometheus, `netdoc` está UP y `netdoc-ping` lista esos elementos.
- [ ] (A) En Grafana, el panel muestra el edificio en el filtro.
- [ ] (B) El **Test** del tipo de medio `NetDoc` responde `OK`.
- [ ] Al desconectar un equipo de prueba, pasado el umbral queda **en falla**
      en el visor, con el aviso en su historial; al reconectarlo vuelve a
      **activo**.

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| Target `netdoc` DOWN: *connection refused* | NetDoc escucha solo en 127.0.0.1 | Arrancar con `NETDOC_API_HOST=0.0.0.0 ./iniciar.sh` |
| Target DOWN: *no such host host.docker.internal* | Docker antiguo o NetDoc en otro equipo | Reemplazar `host.docker.internal` (sección A.2) |
| `netdoc-ping` sin objetivos | Ningún elemento tiene IP de gestión | Cargar IP (sección "Antes de empezar") |
| Todos los ping fallan | blackbox sin permiso ICMP o sin ruta a los equipos | Revisar `cap_add: NET_RAW` y la red del servidor |
| Grafana dice *No data* | Prometheus aún no reúne datos o no llega a NetDoc | Revisar *Target health*; esperar un par de minutos |
| La alerta llega a Alertmanager pero NetDoc no cambia | Token distinto o NetDoc inalcanzable | `docker compose --profile monitoreo logs alertmanager`; revisar el token de A.2 |
| NetDoc responde **401** | Token incorrecto | Mismo valor en `.env`, en Alertmanager y en Zabbix |
| NetDoc responde **503** | `NETDOC_MONITOREO_TOKEN` vacío | Definirlo y reiniciar NetDoc |
| El elemento no cambia de estado | Está **en mantenimiento** | Volverlo a activo cuando termine la intervención |
| Zabbix no vuelve el elemento a activo | Faltan las *Recovery operations* | Agregarlas en la acción (B.1) |
| `sincronizar zabbix`: *Zabbix rechazó hostgroup.create* | El token no es de Super admin | Ver B.2, paso 1 |
| `sincronizar zabbix`: *No existen en Zabbix las plantillas* | Nombre distinto en su Zabbix | Copiar el nombre exacto desde *Data collection → Templates* |

## Direcciones

| Servicio | Dirección |
|---|---|
| Visor NetDoc | `http://<servidor>:5173` |
| API NetDoc y su documentación | `http://<servidor>:8000/docs` |
| Métricas de NetDoc | `http://<servidor>:8000/metrics` |
| Objetivos para Prometheus | `http://<servidor>:8000/api/v1/integraciones/prometheus/objetivos` |
| Prometheus | `http://<servidor>:9090` |
| Alertmanager | `http://<servidor>:9093` |
| Grafana | `http://<servidor>:3000` |
