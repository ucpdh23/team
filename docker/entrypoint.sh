#!/usr/bin/env bash
set -euo pipefail

# pi-link es el mecanismo de comunicación entre agentes: lo instalan todos los contenedores.
# PI_PACKAGES permite añadir paquetes/plugins extra específicos de cada rol (ver docker-compose.yml).
PACKAGES="npm:pi-link ${PI_PACKAGES:-}"

for pkg in $PACKAGES; do
  echo "[entrypoint] instalando paquete pi: $pkg"
  pi install "$pkg"
done

# Credencial de git para clonar/hacer push del repo real de este rol (REPO_URL) sobre HTTPS,
# sin dejar el token escrito en .git/config ni en el historial de shell: el helper lo lee de
# la variable de entorno GIT_TOKEN en el momento de cada petición de autenticación. Solo
# entra en juego con remotos https:// — si para algún rol prefieres configurar SSH a mano
# (deploy key, agent forwarding...), usa un REPO_URL git@... normal y este helper no interfiere.
if [ -n "${GIT_TOKEN:-}" ]; then
  echo "[entrypoint] configurando credential.helper de git (GIT_TOKEN presente)"
  git config --global credential.helper '!f() { echo "username=x-access-token"; echo "password=$GIT_TOKEN"; }; f'
fi

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

# Acceso remoto al Eclipse de arriba (mismo Xvfb, sin display propio): x11vnc sirve ese
# framebuffer por VNC en localhost:5900, y websockify lo reexpone por HTTP/WS en :6080 con
# los assets estáticos de noVNC (apt: paquete `novnc`), para entrar desde el navegador a
# http://<host>:<puerto-mapeado>/vnc.html sin cliente VNC nativo. Solo arranca si hay
# VNC_PASSWORD (ver docker-compose.yml/.env.example) — sin contraseña, mejor no exponer nada.
VNC_PASSWD_FILE="/root/.vnc/passwd"
X11VNC_PID=""
WEBSOCKIFY_PID=""

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

start_vnc() {
  [ -x "$ECLIPSE_BIN" ] || return 0
  if [ -z "${VNC_PASSWORD:-}" ]; then
    echo "[entrypoint] VNC_PASSWORD no definida, no se expone acceso VNC/noVNC a Eclipse"
    return 0
  fi
  mkdir -p "$(dirname "$VNC_PASSWD_FILE")"
  x11vnc -storepasswd "$VNC_PASSWORD" "$VNC_PASSWD_FILE" >/dev/null
  x11vnc -display "$ECLIPSE_DISPLAY" -rfbauth "$VNC_PASSWD_FILE" -rfbport 5900 \
    -forever -shared -noxdamage -quiet &
  X11VNC_PID=$!
  websockify --web=/usr/share/novnc 6080 localhost:5900 &
  WEBSOCKIFY_PID=$!
  echo "[entrypoint] noVNC listo en el puerto interno 6080 -> http://.../vnc.html (mapeo real en docker-compose.yml)"
}

term_handler() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  [ -n "$BROKER_PID" ] && kill "$BROKER_PID" 2>/dev/null || true
  [ -n "$ECLIPSE_PID" ] && kill "$ECLIPSE_PID" 2>/dev/null || true
  [ -n "$XVFB_PID" ] && kill "$XVFB_PID" 2>/dev/null || true
  [ -n "$X11VNC_PID" ] && kill "$X11VNC_PID" 2>/dev/null || true
  [ -n "$WEBSOCKIFY_PID" ] && kill "$WEBSOCKIFY_PID" 2>/dev/null || true
  exit 0
}
trap term_handler SIGTERM SIGINT

start_broker
start_eclipse
start_vnc

# Esperamos (con timeout corto) a que el broker resuelva si este contenedor es hub o spoke
# antes de arrancar pi, para minimizar la ventana de carrera en el primer arranque conjunto.
for _ in $(seq 1 50); do
  [ -s "$ADDR_FILE" ] && break
  sleep 0.2
done

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  start_session "$@"
fi

# Watchdog: si el broker, la sesión tmux, o (en backend) Eclipse/Xvfb/x11vnc/websockify
# mueren, se relanzan solos.
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
  if [ -x "$ECLIPSE_BIN" ] && [ -n "${VNC_PASSWORD:-}" ] \
     && { [ -z "$X11VNC_PID" ] || ! kill -0 "$X11VNC_PID" 2>/dev/null \
          || [ -z "$WEBSOCKIFY_PID" ] || ! kill -0 "$WEBSOCKIFY_PID" 2>/dev/null; }; then
    echo "[entrypoint] x11vnc/websockify caido, relanzando..."
    start_vnc
  fi
  sleep 5 &
  wait $!
done
