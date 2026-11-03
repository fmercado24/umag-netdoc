# Zabbix ↔ NetDoc

Dos sentidos, independientes entre sí. El paso a paso completo, con
verificación y problemas frecuentes, está en
[`docs/manual-monitoreo.md`](../../docs/manual-monitoreo.md#opción-b-zabbix).

## 1. Zabbix → NetDoc: estado de los elementos

Cuando un host entra en problema o se recupera, Zabbix avisa a NetDoc y el
elemento documentado pasa a "en falla" o "activo", con la entrada en su
historial (SOP §11.3). Un elemento "en mantenimiento" no cambia.

1. En NetDoc, definir `NETDOC_MONITOREO_TOKEN` (en `.env`) y reiniciar con
   `NETDOC_API_HOST=0.0.0.0 ./iniciar.sh`: hacia la red, NetDoc solo atiende por
   HTTPS. Si Zabbix rechaza el certificado autofirmado, copiar
   `backend/certs/netdoc.crt` al servidor de Zabbix, en
   `/usr/local/share/ca-certificates/`, y ejecutar `sudo update-ca-certificates`.
2. En Zabbix (6.4 o 7.x): *Alertas → Tipos de medio → Crear tipo de medio*.
   - Tipo: **Webhook**. Nombre: `NetDoc`.
   - Script: el contenido de [`netdoc-webhook.js`](netdoc-webhook.js).
   - Parámetros:

     | Nombre | Valor |
     |---|---|
     | `netdoc_url` | `https://<servidor-netdoc>:8000/api/v1/integraciones/monitoreo/estado` |
     | `netdoc_token` | el valor de `NETDOC_MONITOREO_TOKEN` |
     | `host` | `{HOST.HOST}` |
     | `ip` | `{HOST.IP}` |
     | `event_value` | `{EVENT.VALUE}` |
     | `event_update_status` | `{EVENT.UPDATE.STATUS}` |
     | `event_name` | `{EVENT.NAME}` |
3. Asignar el medio a un usuario (por ejemplo `netdoc`, con "Enviar a" `netdoc`).
   Su grupo necesita permiso de lectura sobre los grupos de hosts vigilados:
   Zabbix solo notifica eventos de hosts que el usuario puede ver.
4. *Alertas → Acciones → Acciones de disparador*: una acción con la condición
   *Tag name* = `netdoc_codigo` (y, para limitarse a disponibilidad, *Event
   name* contiene "Unavailable by ICMP ping") que envíe al usuario `netdoc` por
   el medio `NetDoc`, **también en las operaciones de recuperación**.

El retardo del disparador hace de umbral: NetDoc no espera más. Si el evento
trae los minutos de caída (`minutos_caido`), aplica además
`NETDOC_MONITOREO_MINUTOS_FALLA`.

El elemento se reconoce por `{HOST.HOST}` si es su código (así se llaman los
hosts que crea el conector del punto 2) y, si no, por `{HOST.IP}`. Un host
que no está documentado en NetDoc no es un error: el envío queda como
exitoso con la nota "NetDoc no tiene documentado…".

## 2. NetDoc → Zabbix: hosts desde el inventario

Crea en Zabbix un host por cada elemento con IP de gestión, con el código
como nombre técnico, grupos `NetDoc/<edificio>` y `NetDoc/<edificio>/<piso>`
y etiquetas `netdoc_*`. Requiere Zabbix 6.4+ y un token de API con permiso
para administrar hosts y grupos.

```bash
# .env
NETDOC_ZABBIX_URL=https://zabbix.umag.cl/api_jsonrpc.php
NETDOC_ZABBIX_TOKEN=<token de API>
NETDOC_ZABBIX_PLANTILLAS=Network Generic Device by SNMP   # opcional, solo al crear

cd backend
.venv/bin/python -m app.scripts.sincronizar zabbix --edificio ING            # muestra el plan
.venv/bin/python -m app.scripts.sincronizar zabbix --edificio ING --aplicar  # lo ejecuta
```

Sin `--edificio` considera todos los edificios. El token debe ser de un usuario
Super admin (crear grupos de hosts lo exige).

NetDoc solo administra sus grupos (`NetDoc/…`) y sus etiquetas (`netdoc_*`):
los demás grupos, etiquetas, plantillas e interfaces que se agreguen en Zabbix
se conservan en cada pasada. El id de cada host queda en NetDoc
(`GET /api/v1/elementos/{codigo}` → `externos`).
