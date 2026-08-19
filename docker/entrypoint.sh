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

start_broker() {
  /usr/local/bin/pi-link-broker.sh &
  BROKER_PID=$!
}

start_session() {
  local quoted
  quoted=$(printf '%q ' pi "$@")
  tmux new-session -d -s "$SESSION" -x 220 -y 50 "$quoted"
}

term_handler() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  [ -n "$BROKER_PID" ] && kill "$BROKER_PID" 2>/dev/null || true
  exit 0
}
trap term_handler SIGTERM SIGINT

start_broker

# Esperamos (con timeout corto) a que el broker resuelva si este contenedor es hub o spoke
# antes de arrancar pi, para minimizar la ventana de carrera en el primer arranque conjunto.
for _ in $(seq 1 50); do
  [ -s "$ADDR_FILE" ] && break
  sleep 0.2
done

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  start_session "$@"
fi

# Watchdog: si el broker o la sesión tmux mueren, se relanzan solos.
while true; do
  if ! kill -0 "$BROKER_PID" 2>/dev/null; then
    echo "[entrypoint] broker pi-link caido, relanzando..."
    start_broker
  fi
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[entrypoint] sesion tmux '$SESSION' no encontrada, relanzando pi..."
    start_session "$@"
  fi
  sleep 5 &
  wait $!
done
