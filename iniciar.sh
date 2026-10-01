#!/usr/bin/env bash
# Prepara y levanta NetDoc completo: API, base de datos, edificios y visor.
#
#   ./iniciar.sh                  prepara lo que falte y levanta todo
#   ./iniciar.sh --sin-navegador  igual, pero sin abrir el navegador
#   NETDOC_API_HOST=0.0.0.0 ./iniciar.sh   la API escucha en la red (monitoreo)
#
# La primera vez crea el entorno de Python, instala las dependencias, crea la
# base con el catálogo e importa cada edificio de data/<código>/ con sus
# láminas y fotos. Las siguientes aplica las migraciones, instala lo que cambió
# e importa solo lo nuevo. Las láminas se revisan todas: una modificada en
# data/<código>/planos entra como versión nueva. Ctrl+C detiene todo.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$RAIZ/backend"
FRONTEND="$RAIZ/frontend"
PY="$BACKEND/.venv/bin/python"

# Deben coincidir con frontend/.env (VITE_API_URL) y con los orígenes CORS
# del backend, así que no se eligen puertos alternativos si están ocupados.
PUERTO_API=8000
PUERTO_VISOR=5173
# 0.0.0.0 para que la alcancen los contenedores del perfil "monitoreo"
# (Prometheus, Alertmanager) u otros equipos de la red.
HOST_API="${NETDOC_API_HOST:-127.0.0.1}"

ABRIR_NAVEGADOR=1
for argumento in "$@"; do
  case "$argumento" in
    --sin-navegador) ABRIR_NAVEGADOR=0 ;;
    -h | --help)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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

# --- Requisitos ---------------------------------------------------------------
paso "Revisando requisitos"

command -v python3 >/dev/null || fallar "falta python3 (se requiere 3.11 o superior)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
  fallar "se requiere Python 3.11 o superior (hay $(python3 --version 2>&1))"

# Con nvm, Node no queda en el PATH de los shells no interactivos.
if ! command -v node >/dev/null && [[ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]]; then
  set +eu
  # shellcheck source=/dev/null
  source "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  set -eu
fi
command -v node >/dev/null && command -v npm >/dev/null ||
  fallar "falta Node.js 20 o superior (por ejemplo, instalado con nvm)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' ||
  fallar "se requiere Node.js 20 o superior (hay $(node --version))"
command -v curl >/dev/null || fallar "falta curl"

for puerto in "$PUERTO_API" "$PUERTO_VISOR"; do
  if puerto_ocupado "$puerto"; then
    fallar "el puerto $puerto ya está en uso. ¿NetDoc ya está corriendo en otra terminal?"
  fi
done

echo "    Python $(python3 --version | cut -d' ' -f2), Node $(node --version)"

# --- Backend ------------------------------------------------------------------
if [[ ! -x "$PY" ]]; then
  paso "Creando el entorno de Python"
  python3 -m venv "$BACKEND/.venv" ||
    fallar "no se pudo crear el entorno. En Ubuntu: sudo apt install python3-venv"
fi
"$PY" -m pip --version >/dev/null 2>&1 ||
  fallar "el entorno $BACKEND/.venv no tiene pip. En Ubuntu: sudo apt install python3-venv, borra .venv y vuelve a intentar"

# Se reinstala solo cuando cambian los requisitos.
SELLO_PY="$BACKEND/.venv/.netdoc-requisitos"
HUELLA_PY="$(huella "$BACKEND"/requirements.txt "$BACKEND"/requirements-dev.txt)"
if [[ ! -f "$SELLO_PY" || "$(<"$SELLO_PY")" != "$HUELLA_PY" ]]; then
  paso "Instalando dependencias del backend"
  "$PY" -m pip install --disable-pip-version-check -q -r "$BACKEND/requirements-dev.txt"
  echo "$HUELLA_PY" >"$SELLO_PY"
fi

# --- Frontend -----------------------------------------------------------------
if [[ ! -f "$FRONTEND/.env" ]]; then
  cp "$FRONTEND/.env.example" "$FRONTEND/.env"
fi

SELLO_JS="$FRONTEND/node_modules/.netdoc-paquetes"
if [[ ! -f "$SELLO_JS" || "$(<"$SELLO_JS")" != "$(huella "$FRONTEND/package-lock.json")" ]]; then
  paso "Instalando dependencias del visor"
  (cd "$FRONTEND" && npm install --no-audit --no-fund --loglevel=error) | sangrar
  huella "$FRONTEND/package-lock.json" >"$SELLO_JS"
fi

# --- Base de datos ------------------------------------------------------------
# Todos los pasos son idempotentes: crean lo que falta y no tocan lo existente.
cd "$BACKEND"

paso "Preparando la base de datos"
# Esquema vía migraciones de Alembic: sirve igual para SQLite y PostgreSQL.
"$PY" -m app.scripts.migrar 2>&1 | { grep -v "^INFO " || true; } | sangrar
"$PY" -m app.scripts.cargar_catalogo | sangrar

# Cada carpeta data/<código>/ con planillas es un edificio: se importa si aún
# no tiene elementos (lo ya importado nunca se reemplaza desde aquí).
paso "Importando los edificios nuevos"
"$PY" -m app.scripts.importar_edificio --pendientes | sangrar

# Compara cada lámina de data/<código>/planos con las versiones registradas:
# carga las nuevas y las modificadas. Si una cambió de tamaño, los elementos
# ubicados sobre ella quedan sin ubicar y se listan aquí.
paso "Revisando los planos (nuevos y modificados)"
"$PY" -m app.scripts.cargar_planos | sangrar

paso "Cargando las fotografías"
"$PY" -m app.scripts.cargar_fotografias | sangrar

# --- Arranque -----------------------------------------------------------------
PIDS=()
detener() {
  trap '' INT TERM
  ((${#PIDS[@]})) || return 0
  paso "Deteniendo NetDoc"
  kill "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
}
trap detener EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

esperar() {
  local url="$1" pid="$2" nombre="$3"
  for _ in $(seq 120); do
    curl -fs -o /dev/null "$url" && return 0
    kill -0 "$pid" 2>/dev/null || fallar "$nombre se detuvo al arrancar (revisa los mensajes de arriba)"
    sleep 0.5
  done
  fallar "$nombre no respondió en 60 segundos"
}

paso "Levantando la API y el visor"

(cd "$BACKEND" && PYTHONUNBUFFERED=1 exec "$PY" -m uvicorn app.main:app \
  --host "$HOST_API" --port "$PUERTO_API") > >(prefijar api) 2>&1 &
PID_API=$!
PIDS+=("$PID_API")
esperar "http://127.0.0.1:$PUERTO_API/salud" "$PID_API" "La API"

# Sin --clearScreen false, Vite borraría la terminal y con ella los
# mensajes de la API.
(cd "$FRONTEND" && exec node_modules/.bin/vite --port "$PUERTO_VISOR" --strictPort \
  --clearScreen false) > >(prefijar visor) 2>&1 &
PID_VISOR=$!
PIDS+=("$PID_VISOR")
esperar "http://127.0.0.1:$PUERTO_VISOR/" "$PID_VISOR" "El visor"

URL_VISOR="http://localhost:$PUERTO_VISOR"
printf '\n%sNetDoc está corriendo%s\n' "$VERDE" "$NORMAL"
printf '    Visor:          %s\n' "$URL_VISOR"
printf '    API (docs):     http://localhost:%s/docs\n' "$PUERTO_API"
printf '    %sCtrl+C para detener todo.%s\n\n' "$AMARILLO" "$NORMAL"

if ((ABRIR_NAVEGADOR)); then
  if command -v wslview >/dev/null; then
    wslview "$URL_VISOR" >/dev/null 2>&1 || true
  elif command -v explorer.exe >/dev/null; then
    explorer.exe "$URL_VISOR" >/dev/null 2>&1 || true # en WSL devuelve 1 aunque abra
  elif command -v xdg-open >/dev/null && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    xdg-open "$URL_VISOR" >/dev/null 2>&1 || true
  fi
fi

# Si cualquiera de los dos servicios cae, se detiene el otro.
while kill -0 "$PID_API" 2>/dev/null && kill -0 "$PID_VISOR" 2>/dev/null; do
  sleep 1
done
fallar "uno de los servicios se detuvo inesperadamente; se cierra el resto"
