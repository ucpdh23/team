#!/usr/bin/env bash
set -euo pipefail

# pi-link es el mecanismo de comunicación entre agentes: lo instalan todos los contenedores.
# PI_PACKAGES permite añadir paquetes/plugins extra específicos de cada rol (ver docker-compose.yml).
PACKAGES="npm:pi-link ${PI_PACKAGES:-}"

for pkg in $PACKAGES; do
  echo "[entrypoint] instalando paquete pi: $pkg"
  pi install "$pkg"
done

# pi corre dentro de una sesión tmux persistente en vez de como proceso en primer plano:
# así la sesión sigue viva aunque nadie esté conectado, y te enganchas cuando quieras con
#   docker exec -it <contenedor> tmux attach -t pi
# Ctrl-b d para desconectarte sin matar la sesión. El login del proveedor (/login) se hace
# de forma interactiva la primera vez dentro de esa sesión y queda persistido en el volumen
# montado en /root/.pi/agent.
SESSION="pi"
ADDR_FILE="/var/run/pi-link/hub.addr"
BROKER_PID=""

# Eclipse + jdtbridge (solo backend: se activa solo si /opt/eclipse existe en la imagen, no
# aplica a manager/frontend/devops/cypress). Corre headless bajo Xvfb, con workspace
# persistente para no perder el índice de JDT en cada reinicio del contenedor. El plugin
# jdtbridge, ya instalado en la imagen, expone su API por 127.0.0.1 en cuanto Eclipse arranca;
# la CLI `jdt` la descubre sola vía ~/.jdtbridge/instances/.
ECLIPSE_BIN="/opt/eclipse/eclipse"
ECLIPSE_WORKSPACE="${ECLIPSE_WORKSPACE:-/root/eclipse-workspace}"
ECLIPSE_DISPLAY=":99"
ECLIPSE_PID=""
XVFB_PID=""

start_broker() {
  /usr/local/bin/pi-link-broker.sh &
  BROKER_PID=$!
}

start_session() {
  local quoted
  # --approve: bypassea el prompt interactivo de "¿confías en este proyecto?" de pi, ya que
  # aquí no hay ningún humano delante para responderlo en el primer arranque.
  quoted=$(printf '%q ' pi --approve "$@")
  tmux new-session -d -s "$SESSION" -x 220 -y 50 "$quoted"
}

start_eclipse() {
  [ -x "$ECLIPSE_BIN" ] || return 0
  Xvfb "$ECLIPSE_DISPLAY" -screen 0 1024x768x24 &
  XVFB_PID=$!
  mkdir -p "$ECLIPSE_WORKSPACE"
  DISPLAY="$ECLIPSE_DISPLAY" "$ECLIPSE_BIN" -data "$ECLIPSE_WORKSPACE" -nosplash &
  ECLIPSE_PID=$!
}

term_handler() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  [ -n "$BROKER_PID" ] && kill "$BROKER_PID" 2>/dev/null || true
  [ -n "$ECLIPSE_PID" ] && kill "$ECLIPSE_PID" 2>/dev/null || true
  [ -n "$XVFB_PID" ] && kill "$XVFB_PID" 2>/dev/null || true
  exit 0
}
trap term_handler SIGTERM SIGINT

start_broker
start_eclipse

# Esperamos (con timeout corto) a que el broker resuelva si este contenedor es hub o spoke
# antes de arrancar pi, para minimizar la ventana de carrera en el primer arranque conjunto.
for _ in $(seq 1 50); do
  [ -s "$ADDR_FILE" ] && break
  sleep 0.2
done

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  start_session "$@"
fi

# Watchdog: si el broker, la sesión tmux, o (en backend) Eclipse/Xvfb mueren, se relanzan solos.
while true; do
  if ! kill -0 "$BROKER_PID" 2>/dev/null; then
    echo "[entrypoint] broker pi-link caido, relanzando..."
    start_broker
  fi
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[entrypoint] sesion tmux '$SESSION' no encontrada, relanzando pi..."
    start_session "$@"
  fi
  if [ -x "$ECLIPSE_BIN" ] && { [ -z "$ECLIPSE_PID" ] || ! kill -0 "$ECLIPSE_PID" 2>/dev/null; }; then
    echo "[entrypoint] eclipse (jdtbridge) caido, relanzando..."
    start_eclipse
  fi
  sleep 5 &
  wait $!
done
