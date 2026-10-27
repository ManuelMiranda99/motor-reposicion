"""Genera la carga histórica y la bandeja simulada a partir de los CSV de Kaggle.

Uso (desde la raíz del repo, con el .venv activo):

    python tools/simulate_bandeja.py                      # todo, según config/simulador.yaml
    python tools/simulate_bandeja.py --hasta 2017-06-30   # bandeja solo hasta esa entrega
    python tools/simulate_bandeja.py --limpiar            # borra la bandeja antes de generar
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from reposicion.simulador import cargar_config, generar

RAIZ = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--config", type=Path, default=RAIZ / "config/simulador.yaml")
    p.add_argument("--kaggle", type=Path, default=RAIZ / "data/kaggle")
    p.add_argument("--historico", type=Path, default=RAIZ / "data/historico")
    p.add_argument("--bandeja", type=Path, default=RAIZ / "bandeja_sim")
    p.add_argument("--hasta", type=date.fromisoformat, default=None)
    p.add_argument("--limpiar", action="store_true", help="borra la bandeja antes de generar")
    args = p.parse_args()

    cfg = cargar_config(args.config)
    if args.hasta is not None:
        cfg = cfg.model_copy(update={"hasta": args.hasta})
    if args.limpiar and args.bandeja.exists():
        shutil.rmtree(args.bandeja)

    resumen = generar(args.kaggle, cfg, args.historico, args.bandeja)
    for clave, valor in resumen.items():
        print(f"{clave}: {valor}")


if __name__ == "__main__":
    main()
