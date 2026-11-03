#!/usr/bin/env bash
# Prepara y levanta NetDoc completo: entorno, base de datos, edificios y visor.
#
#   ./iniciar.sh                  prepara lo que falte y levanta todo
#   ./iniciar.sh --sin-navegador  igual, pero sin abrir el navegador
#   NETDOC_API_HOST=0.0.0.0 ./iniciar.sh   atiende en la red, solo por HTTPS
#   NETDOC_PROXY_CONFIABLE=127.0.0.1 ./iniciar.sh   detrás de un proxy propio
#
# La primera vez instala con sudo los paquetes del sistema que falten (es lo
# único que requiere permisos de administrador: NetDoc corre con tu usuario),
# crea el entorno de Python, compila el visor, crea la base con el catálogo,
# pide la contraseña del administrador e importa cada edificio de
# data/<código>/ con sus láminas y fotos. Las siguientes aplica las migraciones,
# instala lo que cambió e importa solo lo nuevo. Las láminas se revisan todas:
# una modificada en data/<código>/planos entra como versión nueva. Ctrl+C
# detiene todo.

set -euo pipefail

# Lo que se cree aquí (base, láminas, certificado) queda solo para tu usuario.
umask 077

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$RAIZ/backend"
FRONTEND="$RAIZ/frontend"
PY="$BACKEND/.venv/bin/python"

PUERTO=8000
# Por omisión solo este equipo. Otra dirección (0.0.0.0 para los contenedores
# del perfil "monitoreo" u otros equipos de la red) exige HTTPS.
HOST_API="${NETDOC_API_HOST:-127.0.0.1}"
# Para usar un certificado propio, déjalo en estas rutas; si faltan, se genera
# uno autofirmado.
CERT_TLS="$BACKEND/certs/netdoc.crt"
CLAVE_TLS="$BACKEND/certs/netdoc.key"
# Solo afecta a TLS 1.2 (el mínimo que acepta Python): cifrado autenticado y
# secreto perfecto hacia adelante. Los de TLS 1.3 ya lo son todos.
CIFRADOS_TLS='ECDHE+AESGCM:ECDHE+CHACHA20'

ABRIR_NAVEGADOR=1
for argumento in "$@"; do
  case "$argumento" in
    --sin-navegador) ABRIR_NAVEGADOR=0 ;;
    -h | --help)
      sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Opción desconocida: $argumento (usa --help)" >&2
      exit 2
      ;;
  esac
done

if [[ -t 1 ]]; then
  AZUL=$'\e[1;34m' AMARILLO=$'\e[33m' ROJO=$'\e[31m' VERDE=$'\e[1;32m' TENUE=$'\e[2m' NORMAL=$'\e[0m'
else
  AZUL='' AMARILLO='' ROJO='' VERDE='' TENUE='' NORMAL=''
fi

paso() { printf '\n%s==> %s%s\n' "$AZUL" "$*" "$NORMAL"; }
fallar() {
  printf '%sError: %s%s\n' "$ROJO" "$*" "$NORMAL" >&2
  exit 1
}
sangrar() { sed -u 's/^/    /'; }
prefijar() { sed -u "s/^/${TENUE}[$1]${NORMAL} /"; }
huella() { cat "$@" | sha256sum | cut -d' ' -f1; }
puerto_ocupado() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# --- Paquetes del sistema -----------------------------------------------------
# Lo único que requiere permisos de administrador: si este script corriera
# entero como root, también la API lo haría y los archivos quedarían de root.
((EUID != 0)) ||
  fallar "no ejecutes este script con sudo ni como root: pide los permisos solo para instalar lo que falte"

python_al_dia() { python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }
# La misma condición que pone Vite: ^20.19 o >=22.12.
node_al_dia() {
  command -v npm >/dev/null && node -e '
    const [mayor, menor] = process.versions.node.split(".").map(Number);
    process.exit(mayor > 22 || (mayor === 22 && menor >= 12) || (mayor === 20 && menor >= 19) ? 0 : 1);
  ' 2>/dev/null
}

# Node de nodejs.org, verificado con su suma: para los Ubuntu que traen uno más
# antiguo que el que exige el visor (24.04 trae el 18).
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
    sudo tar -xzf "$archivo" -C /usr/local --strip-components=1 --no-same-owner \
      --exclude='*.md' --exclude=LICENSE
  )
  rm -rf "$temporal"
}

paso "Revisando requisitos"

# Con nvm, Node no queda en el PATH de los shells no interactivos.
if ! command -v node >/dev/null && [[ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]]; then
  set +eu
  # shellcheck source=/dev/null
  source "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  set -eu
fi

FALTAN=()
python_al_dia || FALTAN+=(python3)
python3 -c 'import ensurepip' 2>/dev/null || FALTAN+=(python3-venv)
command -v curl >/dev/null || FALTAN+=(curl)
command -v openssl >/dev/null || FALTAN+=(openssl)
FALTA_NODE=0
node_al_dia || FALTA_NODE=1

if ((${#FALTAN[@]} + FALTA_NODE)); then
  if ! command -v apt-get >/dev/null || ! command -v sudo >/dev/null; then
    fallar "faltan ${FALTAN[*]:-} $( ((FALTA_NODE)) && echo 'Node.js 22.12+'): instálalos a mano (este script solo sabe hacerlo con apt y sudo)"
  fi
  paso "Instalando lo que falta con sudo (puede pedir tu contraseña y tardar unos minutos)"
  # Un repositorio de terceros caído lo hace fallar, aunque lo necesario se pueda instalar.
  sudo apt-get update -qq || echo "    Aviso: apt-get update informó errores; se intenta instalar igual"
  if ((FALTA_NODE)); then
    candidato="$(apt-cache policy nodejs | awk '/Candidate:/ { print $2 }')"
    if [[ "$candidato" =~ ^[0-9] ]] && dpkg --compare-versions "$candidato" ge 22.12; then
      FALTAN+=(nodejs npm)
      FALTA_NODE=0
    fi
  fi
  if ((${#FALTAN[@]})); then
    echo "    apt: ${FALTAN[*]}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${FALTAN[@]}" >/dev/null
  fi
  if ((FALTA_NODE)); then
    echo "    Node.js oficial (apt ofrece ${candidato:-ninguno}) en /usr/local"
    instalar_node_oficial
  fi
  hash -r
fi

python_al_dia || fallar "se requiere Python 3.11 o superior (hay $(python3 --version 2>&1))"
node_al_dia || fallar "se requiere Node.js 20.19, 22.12 o superior con npm (hay $(node --version 2>&1))"

if puerto_ocupado "$PUERTO"; then
  fallar "el puerto $PUERTO ya está en uso. ¿NetDoc ya está corriendo en otra terminal?"
fi

echo "    Python $(python3 --version | cut -d' ' -f2), Node $(node --version)"

# --- Backend ------------------------------------------------------------------
if [[ ! -x "$PY" ]]; then
  paso "Creando el entorno de Python"
  python3 -m venv "$BACKEND/.venv" || fallar "no se pudo crear el entorno de Python"
fi
"$PY" -m pip --version >/dev/null 2>&1 ||
  fallar "el entorno $BACKEND/.venv no tiene pip: bórralo y vuelve a intentar"

# Se reinstala solo cuando cambian los requisitos. El archivo de bloqueo fija
# las versiones y sus sumas: un paquete alterado no se instala.
SELLO_PY="$BACKEND/.venv/.netdoc-requisitos"
HUELLA_PY="$(huella "$BACKEND/requirements.lock")"
if [[ ! -f "$SELLO_PY" || "$(<"$SELLO_PY")" != "$HUELLA_PY" ]]; then
  paso "Instalando dependencias del backend"
  "$PY" -m pip install --disable-pip-version-check -q --require-hashes -r "$BACKEND/requirements.lock"
  echo "$HUELLA_PY" >"$SELLO_PY"
fi

# --- Frontend -----------------------------------------------------------------
SELLO_JS="$FRONTEND/node_modules/.netdoc-paquetes"
if [[ ! -f "$SELLO_JS" || "$(<"$SELLO_JS")" != "$(huella "$FRONTEND/package-lock.json")" ]]; then
  paso "Instalando dependencias del visor"
  # ci: exactamente lo de package-lock.json, verificando sus sumas.
  (cd "$FRONTEND" && npm ci --no-audit --no-fund --loglevel=error) | sangrar
  huella "$FRONTEND/package-lock.json" >"$SELLO_JS"
fi

# La API sirve el visor compilado: se vuelve a compilar solo si cambió.
SELLO_VISOR="$FRONTEND/dist/.netdoc-compilacion"
HUELLA_VISOR="$(
  find "$FRONTEND/src" "$FRONTEND"/*.html "$FRONTEND"/*.json "$FRONTEND/vite.config.ts" -type f -print0 |
    sort -z | xargs -0 cat | sha256sum | cut -d' ' -f1
)"
if [[ ! -f "$SELLO_VISOR" || "$(<"$SELLO_VISOR")" != "$HUELLA_VISOR" ]]; then
  paso "Compilando el visor"
  (cd "$FRONTEND" && node_modules/.bin/vite build --logLevel warn) | sangrar
  echo "$HUELLA_VISOR" >"$SELLO_VISOR"
fi

# --- Base de datos ------------------------------------------------------------
# Todos los pasos son idempotentes: crean lo que falta y no tocan lo existente.
cd "$BACKEND"

paso "Preparando la base de datos"
# Esquema vía migraciones de Alembic: sirve igual para SQLite y PostgreSQL.
"$PY" -m app.scripts.migrar 2>&1 | { grep -v "^INFO " || true; } | sangrar
"$PY" -m app.scripts.cargar_catalogo | sangrar

# La contraseña no está en el repositorio: su hash vive en .env. La primera vez
# se pide aquí (sin sangrar: necesita la terminal).
paso "Revisando la contraseña del administrador"
"$PY" -m app.scripts.definir_clave --si-falta
[[ ! -f "$RAIZ/.env" ]] || chmod 600 "$RAIZ/.env"

# Cada carpeta data/<código>/ con planillas es un edificio: se importa si aún
# no tiene elementos (lo ya importado nunca se reemplaza desde aquí).
paso "Importando los edificios nuevos"
"$PY" -m app.scripts.importar_edificio --pendientes | sangrar

# Compara cada lámina de data/<código>/planos con las versiones registradas:
# carga las nuevas y las modificadas. Si una cambió de tamaño, los elementos
# ubicados sobre ella quedan sin ubicar y se listan aquí. Después carga los
# recintos de cada lámina (<código>-recintos.csv) y deja en su recinto cada
# elemento que aún no está en el plano; lo que no pudo ubicar, lo lista.
paso "Revisando los planos y ubicando los elementos en su recinto"
"$PY" -m app.scripts.cargar_planos | sangrar

paso "Cargando las fotografías"
"$PY" -m app.scripts.cargar_fotografias | sangrar

# --- Conexión -----------------------------------------------------------------
# En este equipo basta HTTP, porque el tráfico no sale de él. Hacia la red, la
# contraseña y los tokens solo viajan cifrados.
ESQUEMA=http
OPCIONES_API=(--host "$HOST_API" --port "$PUERTO" --no-server-header)
case "$HOST_API" in
  127.* | localhost | ::1) ;;
  *)
    ESQUEMA=https
    if [[ ! -f "$CERT_TLS" || ! -f "$CLAVE_TLS" ]]; then
      paso "Generando un certificado autofirmado"
      NOMBRES="DNS:localhost,DNS:host.docker.internal,DNS:$(hostname),IP:127.0.0.1,IP:::1"
      for ip in $(hostname -I 2>/dev/null); do NOMBRES+=",IP:$ip"; done
      mkdir -p "$(dirname "$CERT_TLS")"
      openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -sha256 -nodes -days 397 \
        -subj "/O=NetDoc UMAG/CN=$(hostname)" -addext "subjectAltName=$NOMBRES" \
        -keyout "$CLAVE_TLS" -out "$CERT_TLS" 2>/dev/null
      # No es secreto: Prometheus y Alertmanager lo usan para reconocer a NetDoc.
      chmod 644 "$CERT_TLS"
      echo "    $CERT_TLS"
    fi
    openssl x509 -checkend 86400 -noout -in "$CERT_TLS" >/dev/null ||
      fallar "el certificado $CERT_TLS vence en menos de un día: reemplázalo, o bórralo para generar otro"
    OPCIONES_API+=(--ssl-certfile "$CERT_TLS" --ssl-keyfile "$CLAVE_TLS" --ssl-ciphers "$CIFRADOS_TLS")
    ;;
esac
# Lo que un proxy dice del cliente (su IP, si llegó por HTTPS) solo se cree si
# se indicó ese proxy: si no, cualquiera podría falsearlo y esquivar el límite
# de intentos.
if [[ -n "${NETDOC_PROXY_CONFIABLE:-}" ]]; then
  OPCIONES_API+=(--proxy-headers --forwarded-allow-ips "$NETDOC_PROXY_CONFIABLE")
else
  OPCIONES_API+=(--no-proxy-headers)
fi

# --- Arranque -----------------------------------------------------------------
PID_API=""
detener() {
  trap '' INT TERM
  [[ -n "$PID_API" ]] || return 0
  paso "Deteniendo NetDoc"
  kill "$PID_API" 2>/dev/null || true
  wait "$PID_API" 2>/dev/null || true
}
trap detener EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

paso "Levantando NetDoc"

# También a un archivo: si la API cae, lo de la terminal puede haberse perdido.
REGISTRO="$BACKEND/netdoc.log"
[[ ! -f "$REGISTRO" ]] || mv -f "$REGISTRO" "$BACKEND/netdoc.anterior.log"

(cd "$BACKEND" && PYTHONUNBUFFERED=1 exec "$PY" -m uvicorn app.main:app "${OPCIONES_API[@]}") \
  > >(tee "$REGISTRO" | prefijar api) 2>&1 &
PID_API=$!

# -k: esta comprobación es contra este mismo equipo.
for _ in $(seq 120); do
  curl -fsk -o /dev/null "$ESQUEMA://127.0.0.1:$PUERTO/salud" && break
  kill -0 "$PID_API" 2>/dev/null || fallar "la API se detuvo al arrancar (revisa los mensajes de arriba)"
  sleep 0.5
done
curl -fsk -o /dev/null "$ESQUEMA://127.0.0.1:$PUERTO/salud" || fallar "la API no respondió en 60 segundos"

URL_VISOR="$ESQUEMA://localhost:$PUERTO"
printf '\n%sNetDoc está corriendo%s\n' "$VERDE" "$NORMAL"
printf '    Visor:          %s\n' "$URL_VISOR"
printf '    API (docs):     %s/docs\n' "$URL_VISOR"
if [[ "$ESQUEMA" == https ]]; then
  printf '    %sCon el certificado autofirmado, el navegador pedirá aceptarlo la primera vez.%s\n' "$AMARILLO" "$NORMAL"
fi
printf '    %sDeja esta terminal abierta: al cerrarla o con Ctrl+C, NetDoc se detiene.%s\n\n' "$AMARILLO" "$NORMAL"

if ((ABRIR_NAVEGADOR)); then
  if command -v wslview >/dev/null; then
    wslview "$URL_VISOR" >/dev/null 2>&1 || true
  elif command -v explorer.exe >/dev/null; then
    explorer.exe "$URL_VISOR" >/dev/null 2>&1 || true # en WSL devuelve 1 aunque abra
  elif command -v xdg-open >/dev/null && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    xdg-open "$URL_VISOR" >/dev/null 2>&1 || true
  fi
fi

CODIGO=0
wait "$PID_API" || CODIGO=$?
PID_API=""
fallar "la API se detuvo inesperadamente (código $CODIGO): detalle en $REGISTRO"
