// Tipo de medio "Webhook" de Zabbix → NetDoc (SOP 11.3).
//
// Informa a NetDoc cuando un host entra en problema o se recupera, para que
// el elemento documentado cambie de estado. Parámetros del tipo de medio (ver
// README.md de esta carpeta):
//
//   netdoc_url           http://<servidor>:8000/api/v1/integraciones/monitoreo/estado
//   netdoc_token         el valor de NETDOC_MONITOREO_TOKEN
//   host                 {HOST.HOST}
//   ip                   {HOST.IP}
//   event_value          {EVENT.VALUE}          1 = problema, 0 = recuperación
//   event_update_status  {EVENT.UPDATE.STATUS}  1 = actualización (se ignora)
//   event_name           {EVENT.NAME}
//
// Zabbix ejecuta el script con Duktape (ES5): nada de let, const ni flechas.

var p = JSON.parse(value);

if (!p.netdoc_url || !p.netdoc_token) {
    throw 'Faltan los parámetros netdoc_url o netdoc_token del tipo de medio';
}
if (p.event_update_status === '1') {
    return 'Actualización del problema: NetDoc no cambia';
}

// Los hosts que crea el conector de NetDoc se llaman como el código del
// elemento; en los creados a mano, NetDoc lo busca por la IP.
var cuerpo = {
    codigo: p.host,
    direccion_ip: p.ip,
    estado: p.event_value === '0' ? 'up' : 'down',
    comentario: 'Zabbix: ' + (p.event_name || 'evento')
};

var solicitud = new HttpRequest();
solicitud.addHeader('Content-Type: application/json');
solicitud.addHeader('X-NetDoc-Token: ' + p.netdoc_token);
var respuesta = solicitud.post(p.netdoc_url, JSON.stringify(cuerpo));
var codigo = solicitud.getStatus();
Zabbix.log(4, '[NetDoc] HTTP ' + codigo + ': ' + respuesta);

if (codigo === 404) {
    // No es un error del envío: el host no está documentado en NetDoc.
    return 'NetDoc no tiene documentado ' + p.host + ' (' + p.ip + ')';
}
if (codigo < 200 || codigo >= 300) {
    throw 'NetDoc respondió ' + codigo + ': ' + respuesta;
}
return 'OK';
