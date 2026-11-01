#!/usr/bin/env bash
# Configura las llaves de escritura del remoto DVC `r2` (S3 de Cloudflare R2) solo en
# .dvc/config.local, que está excluido de git. Solo lo necesita quien hace `dvc push`:
# `dvc pull` usa el remoto `publico` (HTTP, lectura anónima) y no pide credenciales.
# Las llaves salen de un token de API de R2 con permiso "Object Read & Write" sobre el bucket.
#
# Uso:  ./tools/dvc_auth.sh            (pide las llaves sin mostrarlas)
#       R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... ./tools/dvc_auth.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${R2_ACCESS_KEY_ID:-}" ]]; then
  read -r -p "Access Key ID de R2: " R2_ACCESS_KEY_ID
fi
if [[ -z "${R2_SECRET_ACCESS_KEY:-}" ]]; then
  read -r -s -p "Secret Access Key de R2: " R2_SECRET_ACCESS_KEY
  echo
fi

if [[ -z "$R2_ACCESS_KEY_ID" || -z "$R2_SECRET_ACCESS_KEY" ]]; then
  echo "ERROR: llave vacía" >&2
  exit 1
fi

dvc remote modify r2 --local access_key_id "$R2_ACCESS_KEY_ID"
dvc remote modify r2 --local secret_access_key "$R2_SECRET_ACCESS_KEY"

echo "Credenciales guardadas en .dvc/config.local. Probando conexión..."
dvc status --cloud -r r2
