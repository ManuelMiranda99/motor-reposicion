#!/usr/bin/env bash
# Borra las salidas regenerables de data/ (raw, ledger, limpio, backtest, models, published,
# monitoring) para operar otra bandeja desde cero. NO toca data/kaggle, data/historico ni la
# bandeja. Las salidas borradas siguen en DVC: `dvc pull` las recupera.
#
# Uso:  ./tools/limpiar_salidas.sh
set -euo pipefail

cd "$(dirname "$0")/.."

for d in raw ledger limpio backtest models published monitoring; do
  rm -rf "data/$d"
done
echo "Salidas de data/ borradas (se conservan data/kaggle y data/historico)."
