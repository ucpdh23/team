#!/usr/bin/env bash
# Genera /etc/tmux.conf en build-time, adaptado a la version de tmux instalada.
#
# - Truecolor/256 colores: sin esto, tmux no negocia bien el color de 24 bits entre el
#   cliente que se conecta (docker exec -it ... tmux attach) y el proceso `pi` de dentro,
#   y los grises tenues del tema de pi acaban colapsando a negro.
# - Extended keys: ver docs/tmux.md del propio pi. `extended-keys-format csi-u` solo existe
#   desde tmux 3.5; en versiones anteriores (3.2-3.4) se omite y basta con `extended-keys on`.
set -euo pipefail

CONF=/etc/tmux.conf
TMUX_VER=$(tmux -V | awk '{print $2}')

{
  echo 'set -g default-terminal "tmux-256color"'
  echo 'set -ag terminal-overrides ",*:RGB"'
  echo 'set -g extended-keys on'
} > "$CONF"

if dpkg --compare-versions "$TMUX_VER" ge "3.5" 2>/dev/null; then
  echo 'set -g extended-keys-format csi-u' >> "$CONF"
  echo "[generate-tmux-conf] tmux $TMUX_VER >= 3.5, extended-keys-format csi-u habilitado"
else
  echo "[generate-tmux-conf] tmux $TMUX_VER < 3.5, se omite extended-keys-format csi-u"
fi

echo "[generate-tmux-conf] contenido final de $CONF:"
cat "$CONF"
