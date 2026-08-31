#!/usr/bin/env bash
# Lanzador headless de Eclipse JDT Language Server (motor de inteligencia de código Java de
# Eclipse, sin GUI). Habla el protocolo LSP por stdio — pensado para que una extensión/cliente
# LSP se conecte a él, no para invocarlo directamente como si fuera un comando de una sola vez.
#
# La ruta del launcher jar de Equinox embebe la versión en el nombre, así que se busca en vez
# de fijarla a mano. JDTLS_DATA_DIR debe ser específico por proyecto (el workspace/índice de
# jdtls vive ahí); si no se indica, cae en un directorio temporal genérico.
set -euo pipefail

JDTLS_HOME="${JDTLS_HOME:-/opt/jdtls}"
LAUNCHER_JAR=$(find "$JDTLS_HOME/plugins" -name 'org.eclipse.equinox.launcher_*.jar' | sort | tail -n1)

if [ -z "$LAUNCHER_JAR" ]; then
  echo "jdtls: no se encontró el launcher jar de Equinox en $JDTLS_HOME/plugins" >&2
  exit 1
fi

CONFIG_DIR="$JDTLS_HOME/config_linux"
DATA_DIR="${JDTLS_DATA_DIR:-/tmp/jdtls-workspace}"

exec java \
  -Declipse.application=org.eclipse.jdt.ls.core.id1 \
  -Dosgi.bundles.defaultStartLevel=4 \
  -Declipse.product=org.eclipse.jdt.ls.core.product \
  -Dlog.level=ALL \
  -jar "$LAUNCHER_JAR" \
  -configuration "$CONFIG_DIR" \
  -data "$DATA_DIR" \
  "$@"
