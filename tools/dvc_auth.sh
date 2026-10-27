#!/usr/bin/env bash
# Configura las credenciales del remoto DVC (DagsHub) solo en .dvc/config.local,
# que está excluido de git. DagsHub exige iniciar sesión incluso para leer repos públicos:
# el token se obtiene en https://dagshub.com/user/settings/tokens
#
# Uso:  ./tools/dvc_auth.sh            (pide el token sin mostrarlo)
#       DAGSHUB_TOKEN=... ./tools/dvc_auth.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${DAGSHUB_TOKEN:-}" ]]; then
  read -r -s -p "Token de DagsHub: " DAGSHUB_TOKEN
  echo
fi

if [[ -z "$DAGSHUB_TOKEN" ]]; then
  echo "ERROR: token vacío" >&2
  exit 1
fi

dvc remote modify origin --local access_key_id "$DAGSHUB_TOKEN"
dvc remote modify origin --local secret_access_key "$DAGSHUB_TOKEN"

echo "Credenciales guardadas en .dvc/config.local. Probando conexión..."
dvc status --cloud
