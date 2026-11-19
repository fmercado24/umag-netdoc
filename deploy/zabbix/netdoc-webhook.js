// Tipo de medio "Webhook" de Zabbix → NetDoc (SOP 11.3).
//
// Informa a NetDoc cuando un host entra en problema o se recupera, para que
// el elemento documentado cambie de estado. Parámetros del tipo de medio (ver
// README.md de esta carpeta):
//
//   netdoc_url           https://<servidor>:8000/api/v1/integraciones/monitoreo/estado
//   netdoc_token         el valor de NETDOC_MONITOREO_TOKEN
//   host                 {HOST.HOST}
//   ip                   {HOST.IP}
//   event_value          {EVENT.VALUE}          1 = problema, 0 = recuperación
//   event_update_status  {EVENT.UPDATE.STATUS}  1 = actualización (se ignora)
//   event_name           {EVENT.NAME}
//   latido               {EVENT.TAGS.netdoc_latido}   1 = solo latido (RNF5)
//
// Zabbix ejecuta el script con Duktape (ES5): nada de let, const ni flechas.

var p = JSON.parse(value);

if (!p.netdoc_url || !p.netdoc_token) {
    throw 'Faltan los parámetros netdoc_url o netdoc_token del tipo de medio';
}
if (p.event_update_status === '1') {
    return 'Actualización del problema: NetDoc no cambia';
}

// Latido: un problema que siempre está abierto, con una acción que repite el
// envío cada pocos minutos, dice a NetDoc que Zabbix sigue funcionando aunque
// no haya fallas que informar.
if (p.latido === '1') {
    var latido = new HttpRequest();
    latido.addHeader('Content-Type: application/json');
    latido.addHeader('X-NetDoc-Token: ' + p.netdoc_token);
    var respuestaLatido = latido.post(
        p.netdoc_url.replace(/\/monitoreo\/estado\/?$/, '/monitoreo/latido'),
        JSON.stringify({ fuente: 'zabbix' })
    );
    if (latido.getStatus() < 200 || latido.getStatus() >= 300) {
        throw 'NetDoc respondió ' + latido.getStatus() + ' al latido: ' + respuestaLatido;
    }
    return 'Latido enviado';
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
