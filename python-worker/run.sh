#!/bin/bash
# run.sh — Script para cPanel Cron
# Executa o Python Worker de forma pontual
#
# Configurar no cPanel → Cron Jobs:
#   */2 * * * * /home/usuario/public_html/python-worker/run.sh >> /home/usuario/logs/worker.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Detectar Python 3
PYTHON=""
for cmd in python3.11 python3.10 python3.9 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[$(date)] ERRO: Python 3 não encontrado"
    exit 1
fi

echo "[$(date)] Executando worker com $PYTHON..."
$PYTHON worker.py
EXIT_CODE=$?
echo "[$(date)] Worker finalizado com código: $EXIT_CODE"
exit $EXIT_CODE
