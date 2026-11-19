#!/usr/bin/env bash
# Prueba, sin root ni red, lo que instalar-servidor.sh hace antes de instalar,
# y la poda de respaldos del comando netdoc:
#
#   devolver_carpeta       deja la carpeta del repositorio a nombre de quien
#                          ejecuta sudo, para que use git sin sudo;
#   buscar_version_nueva   revisa GitHub y pregunta si traer la versión nueva;
#   podar_respaldos        deja los respaldos de 30 días y uno por mes, un año.
#
# Un repositorio local hace de GitHub y su clon, de la carpeta del servidor; el
# instalador de esa carpeta es un sustituto que dice con qué se volvió a
# ejecutar. Lo corre backend/tests/test_instalador.py, o a mano:
#
#   bash deploy/servidor/probar-instalador.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export INSTALADOR="${INSTALADOR:-$RAIZ/instalar-servidor.sh}"
B="$(mktemp -d)"
trap 'rm -rf "$B"' EXIT
# Sin la configuración de git de quien prueba (firmas, ganchos).
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=Prueba GIT_AUTHOR_EMAIL=prueba@example.invalid
export GIT_COMMITTER_NAME=Prueba GIT_COMMITTER_EMAIL=prueba@example.invalid
FALLAS=0

# --- El escenario ------------------------------------------------------------
preparar() {
  rm -rf "$B/github.git" "$B/companero" "$B/servidor"
  git init -q --bare -b main "$B/github.git"
  git clone -q "$B/github.git" "$B/companero" 2>/dev/null
  printf '#!/usr/bin/env bash\necho "RE-EJECUTADO con: $* · REVISADA=${NETDOC_VERSION_REVISADA:-}"\n' \
    >"$B/companero/instalar-servidor.sh"
  echo v1 >"$B/companero/version"
  git -C "$B/companero" add -A
  git -C "$B/companero" commit -qm "Versión inicial"
  git -C "$B/companero" push -q origin main
  git clone -q "$B/github.git" "$B/servidor"
  touch "$B/netdoc.env"
}

VERSION=1
publicar() {
  local i
  for ((i = 1; i <= $1; i++)); do
    VERSION=$((VERSION + 1))
    echo "v$VERSION" >"$B/companero/version"
    git -C "$B/companero" commit -qam "Cambio $i del compañero"
  done
  git -C "$B/companero" push -q origin main
}

# Las funciones reales del instalador, con ORIGEN en la carpeta de prueba y sin
# root: runuser, chown, stat y find se simulan.
cat >"$B/correr.sh" <<'GUION'
set -euo pipefail
paso() { printf '\n==> %s\n' "$*"; }
aviso() { printf '    %s\n' "$*"; }
fallar() { printf 'Error: %s\n' "$*" >&2; exit 1; }
runuser() { shift 3; "$@"; }
chown() { echo "[chown $*]"; }
stat() { echo "${DUENO:-root}"; }
find() { [[ -z "${AJENO:-}" ]] || echo "$1/.git/objects/ajeno"; }
ORIGEN="$CARPETA" CONFIG="$CONFIGURACION" APP=/opt/netdoc
ARGUMENTOS=("$@")
# Las opciones del instalador y sus dos funciones, tal como están en él.
eval "$(sed -n '/^BUSCAR_VERSION=preguntar$/,/^done$/p; /^devolver_carpeta() {/,/^buscar_version_nueva$/p' "$INSTALADOR")"
echo "SIGUE con $(cat "$ORIGEN/version")"
GUION

correr() {  # sin terminal
  CARPETA="$B/servidor" CONFIGURACION="${CONFIGURACION:-$B/netdoc.env}" bash "$B/correr.sh" "$@" </dev/null 2>&1 || true
}

con_terminal() {  # respuesta, opciones…: como si alguien la escribiera
  local respuesta="$1"
  shift
  printf '%b' "$respuesta" |
    CARPETA="$B/servidor" CONFIGURACION="$B/netdoc.env" script -qec "bash $B/correr.sh $*" /dev/null 2>&1 |
    tr -d '\r' || true
}

dice() {  # descripción, salida, texto que debe aparecer
  if grep -qF -- "$3" <<<"$2"; then
    echo "ok     $1"
  else
    echo "FALLA  $1: falta «$3»"
    sed 's/^/         /' <<<"$2"
    FALLAS=$((FALLAS + 1))
  fi
}

no_dice() {  # descripción, salida, texto que no debe aparecer
  if grep -qF -- "$3" <<<"$2"; then
    echo "FALLA  $1: sobra «$3»"
    sed 's/^/         /' <<<"$2"
    FALLAS=$((FALLAS + 1))
  else
    echo "ok     $1"
  fi
}

# --- La carpeta, de quien ejecuta sudo -----------------------------------------
# Quien prueba hace de quien ejecuta sudo: el instalador exige que exista.
YO="$(id -un)"
preparar
s="$(SUDO_USER=$YO DUENO=root correr)"
dice "clonada con sudo: pasa a quien instala" "$s" "[chown -R $YO: $B/servidor]"
s="$(SUDO_USER=$YO DUENO=$YO correr)"
no_dice "ya es suya: no se toca" "$s" "[chown"
s="$(SUDO_USER=$YO DUENO=$YO AJENO=1 correr)"
dice "suya, con archivos de root de un «sudo git pull»: se arregla" "$s" "[chown -R $YO:"
s="$(SUDO_USER=$YO DUENO=otra correr)"
dice "de otra persona: se deja" "$s" "es de otra: se deja como está"
no_dice "de otra persona: sin chown" "$s" "[chown"
s="$(unset SUDO_USER; DUENO=root correr)"
no_dice "como root, sin sudo: no se toca" "$s" "[chown"

# --- La versión nueva --------------------------------------------------------
s="$(correr --base sqlite)"
dice "al día" "$s" "Esta es la versión más reciente"
dice "al día: sigue" "$s" "SIGUE con v1"

publicar 2
if command -v script >/dev/null; then
  s="$(con_terminal 'n\n' --base sqlite)"
  dice "con cambios, responde n: los muestra" "$s" "Cambio 2 del compañero"
  dice "con cambios, responde n: no los trae" "$s" "Se sigue con la versión de esta carpeta."
  dice "con cambios, responde n: sigue con lo que hay" "$s" "SIGUE con v1"
  s="$(con_terminal '\n' --base sqlite --dominio netdoc.umag.cl)"
  dice "responde Enter: los trae" "$s" "Actualizado a"
  dice "responde Enter: sigue el instalador nuevo, con las mismas opciones" "$s" \
    "RE-EJECUTADO con: --base sqlite --dominio netdoc.umag.cl · REVISADA=1"
else
  echo "omitidas las pruebas con terminal: falta «script» (util-linux)"
  git -C "$B/servidor" pull -q
fi

publicar 1
s="$(correr)"
dice "sin terminal: no pregunta" "$s" "Sin terminal no puedo preguntar"
no_dice "sin terminal: no los trae" "$s" "Actualizado a"
s="$(correr --actualizar)"
dice "sin terminal, con --actualizar: los trae" "$s" "RE-EJECUTADO con: --actualizar · REVISADA=1"

publicar 1
s="$(NETDOC_VERSION_REVISADA=1 correr --actualizar)"
no_dice "el instalador nuevo no vuelve a revisar" "$s" "Revisando si hay una versión nueva"
s="$(correr --sin-buscar-version)"
no_dice "--sin-buscar-version" "$s" "Revisando si hay una versión nueva"
s="$(CONFIGURACION="$B/no-existe" correr)"
no_dice "primera instalación: no revisa" "$s" "Revisando si hay una versión nueva"

git -C "$B/servidor" remote set-url origin "$B/no-existe.git"
s="$(correr)"
dice "GitHub no responde: lo dice" "$s" "No se pudo consultar GitHub"
dice "GitHub no responde: sigue" "$s" "SIGUE con"
git -C "$B/servidor" remote set-url origin "$B/github.git"

echo "editado en el servidor" >"$B/servidor/version"
s="$(correr --actualizar)"
dice "cambios propios que chocan: no se cambia nada" "$s" "actualización cancelada: no se cambió nada"
dice "cambios propios que chocan: se conservan" "$(cat "$B/servidor/version")" "editado en el servidor"

# --- Respaldos (deploy/servidor/netdoc) --------------------------------------
# Uno cada noche durante más de un año, más los que se hacen antes de
# actualizar, y un archivo que no es un respaldo.
mkdir -p "$B/respaldos"
seq 0 480 | sed 's/.*/2026-11-18 -& days/' |
  date -f - "+$B/respaldos/netdoc-%Y%m%d-023000.tar.gz" | xargs touch
touch "$B/respaldos/netdoc-20261110-150000.tar.gz" "$B/respaldos/netdoc-20261001-150000.tar.gz" \
  "$B/respaldos/otro.txt"
(
  set -euo pipefail
  eval "$(grep -E '^(DIAS|MESES)=' "$RAIZ/deploy/servidor/netdoc")"
  eval "$(sed -n '/^podar_respaldos() {/,/^}/p' "$RAIZ/deploy/servidor/netdoc")"
  RESPALDOS="$B/respaldos" HOY=2026-11-18 podar_respaldos
)
quedan="$(ls "$B/respaldos")"
# Los de los últimos 30 días (19-10 al 18-11: 31, más el de antes de actualizar)…
dice "respaldos: los de los últimos 30 días" "$quedan" "netdoc-20261019-023000.tar.gz"
no_dice "respaldos: el día 31 hacia atrás ya no" "$quedan" "netdoc-20261018-023000.tar.gz"
dice "respaldos: también el de antes de actualizar" "$quedan" "netdoc-20261110-150000.tar.gz"
# …y el primero de cada mes durante un año: de diciembre de 2025 a octubre de 2026.
dice "respaldos: el primero de diciembre de 2025" "$quedan" "netdoc-20251201-023000.tar.gz"
dice "respaldos: el primero de octubre" "$quedan" "netdoc-20261001-023000.tar.gz"
no_dice "respaldos: el segundo del mes no" "$quedan" "netdoc-20261001-150000.tar.gz"
no_dice "respaldos: los meses de hace más de un año no" "$quedan" "netdoc-20251101-023000.tar.gz"
dice "respaldos: lo que no es un respaldo no se toca" "$quedan" "otro.txt"
dice "respaldos: en total, 32 de días y 11 mensuales" "$(grep -c '^netdoc-' <<<"$quedan")" "43"

if ((FALLAS)); then
  echo "$FALLAS prueba(s) fallaron"
  exit 1
fi
echo "Todas las pruebas del instalador pasaron"
