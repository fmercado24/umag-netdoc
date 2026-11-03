#!/usr/bin/env bash
# Instala o actualiza NetDoc en un servidor Ubuntu (24.04 o posterior).
#
#   sudo ./instalar-servidor.sh                    pregunta qué base de datos usar
#   sudo ./instalar-servidor.sh --base sqlite      sin servicios adicionales
#   sudo ./instalar-servidor.sh --base postgresql  instala PostgreSQL en este servidor
#
# Opciones:
#   --postgres-url URL        usa un PostgreSQL existente en vez de instalar uno:
#                             postgresql+psycopg://usuario:clave@servidor:5432/base
#   --cambiar-base            pasa los datos a la base indicada con --base o --postgres-url
#   --dominio NOMBRE          nombre con que se accede, p. ej. netdoc.umag.cl
#   --certificado ARCHIVO     certificado de la institución (con su cadena), en vez
#   --clave-certificado ARCHIVO   de uno autofirmado; van juntos
#
# Volver a ejecutarlo actualiza: respalda, copia el código nuevo, aplica las
# migraciones, importa lo nuevo de data/ y reinicia. Conserva la base, la
# contraseña y los certificados. Guía: docs/instalacion-servidor.md

set -euo pipefail
umask 022

ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=/opt/netdoc
DATOS=/var/lib/netdoc
ETC=/etc/netdoc
CONFIG="$ETC/netdoc.env"
INSTALACION="$ETC/instalacion.conf"
TLS="$ETC/tls"
USUARIO=netdoc
# El puerto interno de la API. Hacia afuera atiende nginx: 80 (redirige), 443 y
# 8000, el que usan Prometheus, Alertmanager y Zabbix (docs/manual-monitoreo.md).
PUERTO_API=8001
PY="$APP/backend/.venv/bin/python"
URL_SQLITE="sqlite:///$DATOS/netdoc.db"

if [[ -t 1 ]]; then
  AZUL=$'\e[1;34m' AMARILLO=$'\e[33m' ROJO=$'\e[31m' VERDE=$'\e[1;32m' NORMAL=$'\e[0m'
else
  AZUL='' AMARILLO='' ROJO='' VERDE='' NORMAL=''
fi
paso() { printf '\n%s==> %s%s\n' "$AZUL" "$*" "$NORMAL"; }
aviso() { printf '%s    %s%s\n' "$AMARILLO" "$*" "$NORMAL"; }
fallar() {
  printf '%sError: %s%s\n' "$ROJO" "$*" "$NORMAL" >&2
  exit 1
}
huella() { cat "$@" | sha256sum | cut -d' ' -f1; }
leer_config() { (set -a && source "$CONFIG" && printf '%s' "${!1:-}"); }
motor_de() {
  case "$1" in
    sqlite*) echo sqlite ;;
    postgresql*) echo postgresql ;;
    *) fallar "no reconozco la base de datos «${1%%:*}»" ;;
  esac
}

# --- Opciones -----------------------------------------------------------------
BASE="" POSTGRES_URL="" CAMBIAR_BASE=0 DOMINIO="" CERTIFICADO="" CLAVE_CERTIFICADO=""
while (($#)); do
  case "$1" in
    --base) BASE="${2:-}"; shift 2 ;;
    --postgres-url) POSTGRES_URL="${2:-}"; shift 2 ;;
    --cambiar-base) CAMBIAR_BASE=1; shift ;;
    --dominio) DOMINIO="${2:-}"; shift 2 ;;
    --certificado) CERTIFICADO="${2:-}"; shift 2 ;;
    --clave-certificado) CLAVE_CERTIFICADO="${2:-}"; shift 2 ;;
    -h | --help)
      sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) fallar "opción desconocida: $1 (usa --help)" ;;
  esac
done

# --- Antes de cambiar nada ------------------------------------------------------
((EUID == 0)) || fallar "este script instala servicios del sistema: ejecútalo con sudo"
command -v apt-get >/dev/null && command -v systemctl >/dev/null ||
  fallar "este script es para Ubuntu con systemd"
[[ -d "$ORIGEN/backend/app" ]] || fallar "no encuentro el código en $ORIGEN"
if [[ -n "$CERTIFICADO$CLAVE_CERTIFICADO" ]]; then
  [[ -r "$CERTIFICADO" && -r "$CLAVE_CERTIFICADO" ]] ||
    fallar "--certificado y --clave-certificado van juntos y deben ser archivos legibles"
  if command -v openssl >/dev/null && [[ "$(openssl x509 -in "$CERTIFICADO" -noout -pubkey 2>/dev/null | sha256sum)" != "$(openssl pkey -in "$CLAVE_CERTIFICADO" -pubout 2>/dev/null | sha256sum)" ]]; then
    fallar "el certificado y la clave no corresponden entre sí"
  fi
fi
grep -qi '^ID=ubuntu' /etc/os-release 2>/dev/null || aviso "Este sistema no es Ubuntu: se intenta igual."

URL_ACTUAL=""
[[ ! -f "$CONFIG" ]] || URL_ACTUAL="$(leer_config NETDOC_DATABASE_URL)"
MOTOR_ACTUAL=""
[[ -z "$URL_ACTUAL" ]] || MOTOR_ACTUAL="$(motor_de "$URL_ACTUAL")"
[[ ! -f "$INSTALACION" ]] || source "$INSTALACION"
DOMINIO="${DOMINIO:-${DOMINIO_GUARDADO:-}}"

if [[ -n "$POSTGRES_URL" ]]; then
  [[ "$POSTGRES_URL" == postgresql+psycopg://* ]] ||
    fallar "--postgres-url debe empezar con postgresql+psycopg://"
  [[ "${BASE:-postgresql}" == postgresql ]] || fallar "--base $BASE no calza con --postgres-url"
  BASE=postgresql
fi

if [[ -z "$BASE" ]]; then
  if [[ -n "$MOTOR_ACTUAL" ]]; then
    BASE="$MOTOR_ACTUAL"
  elif [[ -t 0 ]]; then
    cat <<'EOF'

¿Qué base de datos quieres usar?

  1) SQLite      Un archivo, sin servicios adicionales. Suficiente para NetDoc
                 con un solo servidor, que es lo habitual.
  2) PostgreSQL  Se instala en este servidor con usuario y contraseña propios.
                 Conviene si la DSI ya administra y respalda PostgreSQL.

EOF
    read -rp "Opción [1]: " OPCION
    case "${OPCION:-1}" in
      1) BASE=sqlite ;;
      2) BASE=postgresql ;;
      *) fallar "opción no válida: $OPCION" ;;
    esac
  else
    fallar "sin terminal no puedo preguntar: indica --base sqlite o --base postgresql"
  fi
fi
[[ "$BASE" == sqlite || "$BASE" == postgresql ]] || fallar "--base debe ser sqlite o postgresql"

CAMBIO_DE_BASE=0
if [[ -n "$MOTOR_ACTUAL" ]] && { [[ "$BASE" != "$MOTOR_ACTUAL" ]] ||
  { [[ -n "$POSTGRES_URL" ]] && [[ "$POSTGRES_URL" != "$URL_ACTUAL" ]]; }; }; then
  ((CAMBIAR_BASE)) || fallar "esta instalación ya usa $MOTOR_ACTUAL y tiene sus datos ahí. Para pasarlos a la nueva base, agrega --cambiar-base"
  CAMBIO_DE_BASE=1
fi
((CAMBIO_DE_BASE || !CAMBIAR_BASE)) || fallar "--cambiar-base: la instalación ya usa esa base"

# --- Paquetes -------------------------------------------------------------------
python_al_dia() { python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }
# La misma condición que pone Vite: ^20.19 o >=22.12.
node_al_dia() {
  command -v npm >/dev/null && node -e '
    const [mayor, menor] = process.versions.node.split(".").map(Number);
    process.exit(mayor > 22 || (mayor === 22 && menor >= 12) || (mayor === 20 && menor >= 19) ? 0 : 1);
  ' 2>/dev/null
}
# Node de nodejs.org, verificado con su suma, para los Ubuntu cuyo Node es muy antiguo.
instalar_node_oficial() {
  local base="https://nodejs.org/dist/latest-v24.x" arquitectura archivo temporal
  case "$(uname -m)" in
    x86_64) arquitectura=x64 ;;
    aarch64) arquitectura=arm64 ;;
    *) fallar "no hay un Node oficial para $(uname -m): instala Node 22.12 o superior a mano" ;;
  esac
  temporal="$(mktemp -d)"
  (
    cd "$temporal"
    curl -fsSO "$base/SHASUMS256.txt"
    archivo="$(awk -v fin="-linux-$arquitectura.tar.gz" 'index($2, fin) { print $2 }' SHASUMS256.txt)"
    curl -fsSO "$base/$archivo"
    grep -F "  $archivo" SHASUMS256.txt | sha256sum --check --quiet
    tar -xzf "$archivo" -C /usr/local --strip-components=1 --no-same-owner --exclude='*.md' --exclude=LICENSE
  )
  rm -rf "$temporal"
}

paso "Instalando paquetes del sistema"
PAQUETES=(python3 python3-venv curl openssl ca-certificates nginx rsync)
if [[ "$BASE" == sqlite || -n "$MOTOR_ACTUAL" ]]; then PAQUETES+=(sqlite3); fi
if [[ "$BASE" == postgresql ]]; then
  if [[ -n "$POSTGRES_URL" ]]; then PAQUETES+=(postgresql-client); else PAQUETES+=(postgresql); fi
fi
# Sin preguntas: la salida de apt no se ve, y una pregunta dejaría esto colgado.
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1
apt-get update -qq || aviso "apt-get update informó errores: se intenta instalar igual."
NODE_POR_APT=0
if ! node_al_dia; then
  CANDIDATO="$(apt-cache policy nodejs | awk '/Candidate:/ { print $2 }')"
  if [[ "$CANDIDATO" =~ ^[0-9] ]] && dpkg --compare-versions "$CANDIDATO" ge 22.12; then
    PAQUETES+=(nodejs npm)
    NODE_POR_APT=1
  fi
fi
apt-get install -y -qq "${PAQUETES[@]}" >/dev/null
echo "    ${PAQUETES[*]}"
hash -r
if ! node_al_dia && ((!NODE_POR_APT)); then
  echo "    Node.js oficial en /usr/local (apt ofrece ${CANDIDATO:-ninguno})"
  instalar_node_oficial
  hash -r
fi
python_al_dia || fallar "se requiere Python 3.11 o superior (hay $(python3 --version 2>&1)): usa Ubuntu 24.04 o posterior"
node_al_dia || fallar "se requiere Node.js 20.19, 22.12 o superior (hay $(node --version 2>&1))"
echo "    Python $(python3 --version | cut -d' ' -f2), Node $(node --version), nginx $(nginx -v 2>&1 | cut -d/ -f2)"

# --- Respaldo previo, si ya estaba instalado -------------------------------------
if [[ -n "$URL_ACTUAL" && -x /usr/local/bin/netdoc ]]; then
  paso "Respaldando antes de actualizar"
  /usr/local/bin/netdoc respaldar | sed 's/^/    /'
fi

# --- Usuario y carpetas -----------------------------------------------------------
paso "Preparando el usuario $USUARIO y las carpetas"
id "$USUARIO" >/dev/null 2>&1 ||
  useradd --system --user-group --home-dir "$DATOS" --no-create-home --shell /usr/sbin/nologin "$USUARIO"
install -d -m 750 -o "$USUARIO" -g "$USUARIO" "$DATOS" "$DATOS/media" "$DATOS/media/planos" "$DATOS/media/fotografias"
install -d -m 700 -o root -g root "$ETC" "$TLS" "$DATOS/respaldos"
echo "    Código en $APP, datos en $DATOS, configuración en $ETC"

# --- Código -----------------------------------------------------------------------
# De root y solo lectura para el servicio: si la API se viera comprometida, no
# podría modificarse a sí misma.
paso "Copiando el código a $APP"
if [[ "$ORIGEN" != "$APP" ]]; then
  install -d -m 755 "$APP"
  rsync -a --delete --chown=root:root --chmod=go-w,go+rX \
    --exclude='.git/' --exclude='node_modules/' --exclude='backend/.venv/' \
    --exclude='frontend/dist/' --exclude='backend/media/' --exclude='backend/certs/' \
    --exclude='*.db' --exclude='*.log' --exclude='.env' --exclude='.env.local' \
    --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.ruff_cache/' \
    --exclude='*:Zone.Identifier' --exclude='docs/*.pdf' \
    "$ORIGEN/" "$APP/"
fi
install -m 755 "$APP/deploy/servidor/netdoc" /usr/local/bin/netdoc

# --- Dependencias -------------------------------------------------------------------
if [[ "$BASE" == postgresql ]]; then BLOQUEO="$APP/backend/requirements-postgres.lock"; else BLOQUEO="$APP/backend/requirements.lock"; fi
[[ -x "$PY" ]] || { paso "Creando el entorno de Python"; python3 -m venv "$APP/backend/.venv"; }
SELLO_PY="$APP/backend/.venv/.netdoc-requisitos"
HUELLA_PY="$(huella "$BLOQUEO")"
if [[ ! -f "$SELLO_PY" || "$(<"$SELLO_PY")" != "$HUELLA_PY" ]]; then
  paso "Instalando dependencias del backend (versiones y sumas fijadas)"
  "$PY" -m pip install --disable-pip-version-check -q --require-hashes -r "$BLOQUEO"
  echo "$HUELLA_PY" >"$SELLO_PY"
fi

SELLO_VISOR="$APP/frontend/dist/.netdoc-compilacion"
HUELLA_VISOR="$(
  find "$APP/frontend/src" "$APP/frontend"/*.html "$APP/frontend"/*.json "$APP/frontend/vite.config.ts" -type f -print0 |
    sort -z | xargs -0 cat | sha256sum | cut -d' ' -f1
)"
if [[ ! -f "$SELLO_VISOR" || "$(<"$SELLO_VISOR")" != "$HUELLA_VISOR" ]]; then
  paso "Compilando el visor"
  (
    cd "$APP/frontend"
    # ci: exactamente lo de package-lock.json, verificando sus sumas. Corre como
    # root, así que sin los scripts de instalación de los paquetes.
    npm ci --ignore-scripts --no-audit --no-fund --loglevel=error
    node_modules/.bin/vite build --logLevel warn
    # Node solo hace falta para compilar: en el servidor no queda nada de esto.
    rm -rf node_modules
  ) | sed 's/^/    /'
  echo "$HUELLA_VISOR" >"$SELLO_VISOR"
fi

# --- Base de datos -----------------------------------------------------------------
# Si algo falla de aquí en adelante, NetDoc no debe quedar detenido sin aviso.
al_terminar() {
  local codigo=$?
  ((codigo == 0)) && return
  printf '%sLa instalación no terminó. Lo anterior sigue respaldado en %s/respaldos.%s\n' "$ROJO" "$DATOS" "$NORMAL" >&2
  systemctl start netdoc 2>/dev/null || true
}
trap al_terminar EXIT
systemctl stop netdoc 2>/dev/null || true

preparar_postgres_local() {
  systemctl enable --now postgresql >/dev/null 2>&1
  local clave
  clave="$(openssl rand -hex 24)"
  # Por la entrada estándar: en la línea de comandos la vería cualquier usuario.
  runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 >/dev/null <<SQL
DO \$\$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'netdoc') THEN
    ALTER ROLE netdoc LOGIN PASSWORD '$clave';
  ELSE
    CREATE ROLE netdoc LOGIN PASSWORD '$clave';
  END IF;
END \$\$;
SQL
  # Sin -T template0, tomaría la codificación del sistema, que puede no ser UTF-8.
  runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'umag_netdoc'" | grep -q 1 ||
    runuser -u postgres -- createdb --owner=netdoc --encoding=UTF8 --template=template0 umag_netdoc
  URL_NUEVA="postgresql+psycopg://netdoc:$clave@127.0.0.1:5432/umag_netdoc"
}

paso "Preparando la base de datos ($BASE)"
if ((CAMBIO_DE_BASE)) || [[ -z "$URL_ACTUAL" ]]; then
  case "$BASE" in
    sqlite) URL_NUEVA="$URL_SQLITE" ;;
    postgresql)
      if [[ -n "$POSTGRES_URL" ]]; then URL_NUEVA="$POSTGRES_URL"; else preparar_postgres_local; fi
      ;;
  esac
else
  URL_NUEVA="$URL_ACTUAL"
  if [[ "$BASE" == postgresql && "$URL_ACTUAL" == *@127.0.0.1:* ]]; then
    systemctl enable --now postgresql >/dev/null 2>&1
  fi
fi

# La configuración solo la lee systemd, antes de bajar los privilegios del servicio.
if [[ ! -f "$CONFIG" ]]; then
  install -m 600 /dev/null "$CONFIG"
  cat >"$CONFIG" <<EOF
# Configuración de NetDoc en este servidor. Tiene secretos: solo root la lee.
# Variables disponibles: $APP/.env.example
NETDOC_ENTORNO=produccion
NETDOC_DIR_MEDIA=$DATOS/media
EOF
fi

# Lo que corre como el usuario del servicio, con su misma configuración.
export NETDOC_ARCHIVO_ENV="$CONFIG" PYTHONDONTWRITEBYTECODE=1 HOME="$DATOS"
set -a
source "$CONFIG"
set +a
export NETDOC_DATABASE_URL="$URL_NUEVA"
cd "$APP/backend"
# La base y las láminas no son para otros usuarios del servidor.
umask 027
como_servicio() { runuser -u "$USUARIO" -- "$PY" -m "$@"; }

como_servicio app.scripts.migrar 2>&1 | { grep -v "^INFO " || true; } | sed 's/^/    /'

if ((CAMBIO_DE_BASE)); then
  paso "Pasando los datos de $MOTOR_ACTUAL a $BASE"
  "$PY" -m app.scripts.copiar_base --origen "$URL_ACTUAL" --destino "$URL_NUEVA" --reemplazar | sed 's/^/    /'
  [[ "$MOTOR_ACTUAL" != sqlite ]] ||
    aviso "La base anterior sigue en ${URL_ACTUAL#sqlite:///}: bórrala cuando confirmes que todo está bien."
fi

sed -i '/^NETDOC_DATABASE_URL=/d' "$CONFIG"
printf "NETDOC_DATABASE_URL='%s'\n" "$URL_NUEVA" >>"$CONFIG"
chmod 600 "$CONFIG"

como_servicio app.scripts.cargar_catalogo | sed 's/^/    /'

# Como root, porque escribe en la configuración. Solo pregunta si aún no hay una.
paso "Revisando la contraseña del administrador"
"$PY" -m app.scripts.definir_clave --si-falta
set -a
source "$CONFIG"
set +a
# Puede haber quedado del proceso anterior.
chown -R "$USUARIO:$USUARIO" "$DATOS/media"
[[ "$BASE" != sqlite ]] || chown "$USUARIO:$USUARIO" "${URL_SQLITE#sqlite:///}" 2>/dev/null || true

paso "Importando los edificios nuevos"
como_servicio app.scripts.importar_edificio --pendientes | sed 's/^/    /'

paso "Revisando los planos (la primera vez los dibuja: puede tardar varios minutos)"
como_servicio app.scripts.cargar_planos | sed 's/^/    /'

paso "Cargando las fotografías"
como_servicio app.scripts.cargar_fotografias | sed 's/^/    /'

# --- Certificado --------------------------------------------------------------------
umask 022
paso "Preparando HTTPS"
RUTA_CERT="$TLS/netdoc.crt"
RUTA_CLAVE="$TLS/netdoc.key"
if [[ -n "$CERTIFICADO" ]]; then
  if [[ "$CERTIFICADO" == /etc/letsencrypt/* ]]; then
    # Se referencia en vez de copiarse, para que tome las renovaciones.
    RUTA_CERT="$CERTIFICADO"
    RUTA_CLAVE="$CLAVE_CERTIFICADO"
  else
    install -m 644 "$CERTIFICADO" "$RUTA_CERT"
    install -m 600 "$CLAVE_CERTIFICADO" "$RUTA_CLAVE"
  fi
  echo "    Certificado propio: $RUTA_CERT"
elif [[ -n "${RUTA_CERT_GUARDADA:-}" ]]; then
  RUTA_CERT="$RUTA_CERT_GUARDADA"
  RUTA_CLAVE="$RUTA_CLAVE_GUARDADA"
elif [[ ! -f "$RUTA_CERT" || ! -f "$RUTA_CLAVE" ]] ||
  { [[ "$(openssl x509 -in "$RUTA_CERT" -noout -issuer | cut -d= -f2-)" == "$(openssl x509 -in "$RUTA_CERT" -noout -subject | cut -d= -f2-)" ]] &&
    ! openssl x509 -checkend $((30 * 86400)) -noout -in "$RUTA_CERT" >/dev/null; }; then
  NOMBRES="DNS:localhost,DNS:host.docker.internal,DNS:$(hostname),IP:127.0.0.1,IP:::1"
  [[ -z "$DOMINIO" ]] || NOMBRES+=",DNS:$DOMINIO"
  COMPLETO="$(hostname -f 2>/dev/null || true)"
  [[ -z "$COMPLETO" || "$COMPLETO" == "$(hostname)" ]] || NOMBRES+=",DNS:$COMPLETO"
  for ip in $(hostname -I 2>/dev/null); do NOMBRES+=",IP:$ip"; done
  (
    umask 077
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -sha256 -nodes -days 397 \
      -subj "/O=NetDoc UMAG/CN=${DOMINIO:-$(hostname)}" -addext "subjectAltName=$NOMBRES" \
      -keyout "$RUTA_CLAVE" -out "$RUTA_CERT" 2>/dev/null
  )
  chmod 644 "$RUTA_CERT"
  aviso "Certificado autofirmado para: $NOMBRES"
  aviso "Para producción, usa uno de la institución: docs/instalacion-servidor.md"
else
  echo "    $RUTA_CERT"
fi
openssl x509 -checkend 86400 -noout -in "$RUTA_CERT" >/dev/null ||
  fallar "el certificado $RUTA_CERT vence en menos de un día: reemplázalo"
# Lo que monta el perfil "monitoreo" de docker-compose.yml. No es secreto.
install -d -m 755 "$APP/backend/certs"
install -m 644 "$RUTA_CERT" "$APP/backend/certs/netdoc.crt"

{
  printf 'DOMINIO_GUARDADO=%q\n' "$DOMINIO"
  if [[ "$RUTA_CERT" != "$TLS/netdoc.crt" ]]; then
    printf 'RUTA_CERT_GUARDADA=%q\nRUTA_CLAVE_GUARDADA=%q\n' "$RUTA_CERT" "$RUTA_CLAVE"
  fi
} >"$INSTALACION"

# --- Servicio -------------------------------------------------------------------------
paso "Configurando el servicio y nginx"
cat >/etc/systemd/system/netdoc.service <<EOF
# Generado por instalar-servidor.sh: se reescribe al actualizar.
[Unit]
Description=NetDoc UMAG, documentación de infraestructura de red
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$USUARIO
Group=$USUARIO
WorkingDirectory=$APP/backend
EnvironmentFile=$CONFIG
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=$DATOS
# Solo se le cree a nginx lo que dice del cliente (su IP, que llegó por HTTPS).
ExecStart=$PY -m uvicorn app.main:app --host 127.0.0.1 --port $PUERTO_API --no-server-header --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=3
UMask=0027

# Puede escribir solo sus datos, sin privilegios ni acceso al resto del sistema.
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$DATOS
InaccessiblePaths=$ETC
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
SystemCallArchitectures=native
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
EOF

# HTTP/2 se declara distinto desde nginx 1.25.1. Ayuda con las teselas de los planos.
VERSION_NGINX="$(nginx -v 2>&1 | sed -E 's#.*/([0-9.]+).*#\1#')"
if dpkg --compare-versions "$VERSION_NGINX" ge 1.25.1; then
  HTTP2_LISTEN="" HTTP2_DIRECTIVA="http2 on;"
else
  HTTP2_LISTEN=" http2" HTTP2_DIRECTIVA=""
fi
if [[ -n "$DOMINIO" ]]; then
  NOMBRE_SITIO="$DOMINIO" PREDETERMINADO=""
else
  # Sin dominio atiende cualquier nombre: el sitio de ejemplo de nginx estorbaría.
  NOMBRE_SITIO="_" PREDETERMINADO=" default_server"
  rm -f /etc/nginx/sites-enabled/default
fi
# Con IPv6 apagado en el núcleo, nginx ni arrancaría con esas líneas.
ipv6() { [[ ! -e /proc/net/if_inet6 ]] || printf 'listen [::]:%s;' "$1"; }
cat >/etc/nginx/sites-available/netdoc <<EOF
# Generado por instalar-servidor.sh: se reescribe al actualizar.
server {
    listen 80$PREDETERMINADO;
    $(ipv6 "80$PREDETERMINADO")
    server_name $NOMBRE_SITIO;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl$HTTP2_LISTEN$PREDETERMINADO;
    $(ipv6 "443 ssl$HTTP2_LISTEN$PREDETERMINADO")
    # El que usan Prometheus, Alertmanager y Zabbix (docs/manual-monitoreo.md).
    listen 8000 ssl$HTTP2_LISTEN$PREDETERMINADO;
    $(ipv6 "8000 ssl$HTTP2_LISTEN$PREDETERMINADO")
    $HTTP2_DIRECTIVA
    server_name $NOMBRE_SITIO;

    ssl_certificate $RUTA_CERT;
    ssl_certificate_key $RUTA_CLAVE;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE+AESGCM:ECDHE+CHACHA20;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:netdoc:10m;
    ssl_session_tickets off;

    server_tokens off;
    # Lo mismo que NETDOC_CARGA_MAX_MB, más lo que ocupan los campos del formulario.
    client_max_body_size 101m;

    location / {
        proxy_pass http://127.0.0.1:$PUERTO_API;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host \$http_host;
        # Se reemplaza lo que venga del cliente: si no, podría falsear su IP y
        # esquivar el límite de intentos de ingreso.
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 300s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/netdoc /etc/nginx/sites-enabled/netdoc
nginx -t -q 2>&1 | sed 's/^/    /' || true
nginx -t -q 2>/dev/null || fallar "nginx rechazó la configuración: revisa los mensajes de arriba"

systemctl daemon-reload
systemctl enable --quiet netdoc nginx
systemctl restart netdoc
systemctl reload-or-restart nginx

if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow 80,443/tcp >/dev/null
  echo "    Firewall (ufw): abiertos los puertos 80 y 443"
fi

# --- Comprobación ------------------------------------------------------------------------
paso "Comprobando"
for _ in $(seq 60); do
  curl -fsk -o /dev/null https://127.0.0.1/salud && break
  sleep 1
done
curl -fsk -o /dev/null https://127.0.0.1/salud ||
  fallar "NetDoc no responde. Revisa: journalctl -u netdoc -n 50"
[[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${DOMINIO:-localhost}" http://127.0.0.1/)" == 301 ]] ||
  aviso "HTTP no está redirigiendo a HTTPS"
[[ "$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/edificios)" == 401 ]] ||
  fallar "la API respondió sin exigir sesión"
echo "    El servicio responde y exige iniciar sesión"

DIRECCION="${DOMINIO:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
printf '\n%sNetDoc está instalado y corriendo%s\n' "$VERDE" "$NORMAL"
printf '    Dirección:      https://%s\n' "${DIRECCION:-$(hostname)}"
printf '    Usuario:        %s\n' "$(cd "$APP/backend" && "$PY" -c 'from app.core.config import configuracion as c; print(c.admin_usuario)')"
printf '    Base de datos:  %s\n' "$BASE"
printf '    Datos:          %s\n' "$DATOS"
printf '    Administrar:    sudo netdoc ayuda\n\n'
