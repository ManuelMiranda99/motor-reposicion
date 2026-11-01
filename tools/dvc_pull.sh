#!/usr/bin/env bash
# `dvc pull` desde el remoto `publico` (URL r2.dev de Cloudflare R2, lectura anónima) con reintentos.
# r2.dev limita la tasa de peticiones: tras unos ~600 objetos responde 429 por unos segundos y DVC
# no reintenta ese código. Cada intento retoma lo que falta (lo descargado queda en la caché), así
# que basta repetir tras una pausa. Un clon desde cero termina en ~1–2 min (2–3 intentos).
#
# Uso:  ./tools/dvc_pull.sh [argumentos de dvc pull]
#       ./tools/dvc_pull.sh data/kaggle.dvc data/historico.dvc bandeja_sim.dvc
set -uo pipefail

cd "$(dirname "$0")/.."

INTENTOS=${INTENTOS:-10}
PAUSA=${PAUSA:-20}

for ((i = 1; i <= INTENTOS; i++)); do
  if dvc pull "$@"; then
    exit 0
  fi
  if ((i < INTENTOS)); then
    echo "dvc pull: intento $i/$INTENTOS incompleto (límite de tasa de r2.dev); reintento en ${PAUSA} s..." >&2
    sleep "$PAUSA"
  fi
done

echo "ERROR: dvc pull no terminó tras $INTENTOS intentos" >&2
exit 1
