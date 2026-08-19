#!/usr/bin/env bash
# Broker de coordinación de pi-link.
#
# pi-link solo sabe hablar con 127.0.0.1:9900 (hardcoded, no configurable, y solo bindea
# loopback: nunca acepta conexiones que lleguen por la interfaz de red del contenedor). Este
# script decide, entre todos los contenedores del proyecto, cuál de ellos ejerce de hub real
# (deja su 127.0.0.1:9900 libre para que pi-link lo bindee directamente) y monta dos tipos de
# relay TCP con socat según el rol:
#
#   - Hub:   "expose" -> escucha en 0.0.0.0:$MESH_PORT (interfaz real del contenedor) y
#            reenvía a 127.0.0.1:9900 (donde pi-link bindea). Es lo que hace visible al hub
#            desde el resto de contenedores.
#   - Spoke: "relay"  -> escucha en 127.0.0.1:9900 (local, lo que pi-link espera encontrar) y
#            reenvía hacia <hub>:$MESH_PORT a través de la red normal de docker-compose.
#
# $MESH_PORT (9901) es un puerto propio de esta malla, distinto del 9900 de pi-link: si el
# hub reenvíase también en el puerto 9900 de su propia interfaz, chocaría con el propio bind
# de pi-link en 127.0.0.1:9900 (0.0.0.0 y 127.0.0.1 no pueden compartir puerto de forma
# fiable). Ningún componente de pi-link sabe nada de $MESH_PORT ni de estos relays: solo ve
# su 127.0.0.1:9900 local funcionando o no, y reacciona con su propia lógica de reconexión
# (backoff aleatorio de 2-5s). Este script no toca nunca el proceso `pi` ni le manda nada;
# solo gestiona qué hay detrás de su puerto.
#
# Elección de hub: flock exclusivo y no bloqueante sobre un fichero en un volumen compartido
# entre todos los contenedores. El lock lo sostiene el descriptor de fichero abierto en este
# mismo proceso durante toda su vida; si el contenedor-hub muere, el kernel del host libera
# el lock automáticamente y el resto compite de nuevo por el rol.
set -uo pipefail

COORD_DIR="/var/run/pi-link"
LOCK_FILE="$COORD_DIR/hub.lock"
ADDR_FILE="$COORD_DIR/hub.addr"
LOCK_FD=200
POLL_INTERVAL="${PI_LINK_POLL_INTERVAL:-0.3}"
SELF="${PI_LINK_SELF:?PI_LINK_SELF no definido}"
MESH_PORT=9901

mkdir -p "$COORD_DIR"
touch "$LOCK_FILE"

IS_HUB=0
RELAY_PID=""  # spoke: 127.0.0.1:9900 (local) -> <hub>:$MESH_PORT
EXPOSE_PID="" # hub:   0.0.0.0:$MESH_PORT -> 127.0.0.1:9900 (local, donde bindea pi-link)
CURRENT_TARGET=""

stop_relay() {
  if [ -n "$RELAY_PID" ] && kill -0 "$RELAY_PID" 2>/dev/null; then
    kill "$RELAY_PID" 2>/dev/null || true
    wait "$RELAY_PID" 2>/dev/null || true
  fi
  RELAY_PID=""
  CURRENT_TARGET=""
}

stop_expose() {
  if [ -n "$EXPOSE_PID" ] && kill -0 "$EXPOSE_PID" 2>/dev/null; then
    kill "$EXPOSE_PID" 2>/dev/null || true
    wait "$EXPOSE_PID" 2>/dev/null || true
  fi
  EXPOSE_PID=""
}

start_relay() {
  local target="$1"
  stop_relay
  socat TCP-LISTEN:9900,bind=127.0.0.1,fork,reuseaddr "TCP:${target}:${MESH_PORT}" 2>/dev/null &
  RELAY_PID=$!
  CURRENT_TARGET="$target"
}

start_expose() {
  socat "TCP-LISTEN:${MESH_PORT},bind=0.0.0.0,fork,reuseaddr" "TCP:127.0.0.1:9900" 2>/dev/null &
  EXPOSE_PID=$!
}

cleanup() {
  stop_relay
  stop_expose
  # Al morir este proceso se cierra el fd 200 y con él se libera el flock si éramos el hub.
  exit 0
}
trap cleanup SIGTERM SIGINT

# El fd 200 queda abierto durante toda la vida de este script: es lo que sostiene el lock.
exec 200>"$LOCK_FILE"

echo "[pi-link-broker] arrancando como '$SELF'"

while true; do
  if [ "$IS_HUB" -eq 0 ] && flock -n -x "$LOCK_FD"; then
    IS_HUB=1
    stop_relay # liberamos 127.0.0.1:9900 local para que pi-link lo bindee de verdad
    start_expose
    echo "$SELF" > "$ADDR_FILE"
    echo "[pi-link-broker] promovido a hub ($SELF), expuesto en :${MESH_PORT}"
  fi

  if [ "$IS_HUB" -eq 1 ] && ! kill -0 "$EXPOSE_PID" 2>/dev/null; then
    echo "[pi-link-broker] expose caido, relanzando en :${MESH_PORT}"
    start_expose
  fi

  if [ "$IS_HUB" -eq 0 ]; then
    target=$(cat "$ADDR_FILE" 2>/dev/null || true)
    if [ -n "$target" ] && [ "$target" != "$CURRENT_TARGET" ]; then
      echo "[pi-link-broker] spoke -> apuntando relay a ${target}:${MESH_PORT}"
      start_relay "$target"
    elif [ -n "$CURRENT_TARGET" ] && ! kill -0 "$RELAY_PID" 2>/dev/null; then
      echo "[pi-link-broker] relay caido, reintentando contra ${CURRENT_TARGET}:${MESH_PORT}"
      start_relay "$CURRENT_TARGET"
    fi
  fi

  sleep "$POLL_INTERVAL"
done
