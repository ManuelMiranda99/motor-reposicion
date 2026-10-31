"""Diagnóstico (revisión independiente) del WAPE 0.563 del corte 2017-01-02 con los datos REALES.

No es una prueba de pytest (no empieza con `test_`): necesita el `data/` real (solo lo LEE).

    python tests/revision/diagnostico_corte_2017_01_02.py <ruta a data/>

Carga el modelo publicado en ese corte (`lgbm-2017-01-02-496d76f4`), arma las features del corte
y compara el WAPE/sesgo contra las ventas reales en varios contrafactuales:
1. tal cual; 2. `lag_1` = NaN; 3. `lag_1` = ventas del 2016-12-31 (último día con operación);
4. cada feature numérica reemplazada por la del corte 2017-01-09 (una a la vez);
5. el baseline entrenado en el mismo corte.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from reposicion.asof import asof  # noqa: E402
from reposicion.datos import cargar_datos_asof  # noqa: E402
from reposicion.entrenamiento import entrenar_modelo  # noqa: E402
from reposicion.features import CATEGORICAS, construir_features  # noqa: E402
from reposicion.metricas import wape  # noqa: E402
from reposicion.parametros import cargar_configs  # noqa: E402
from reposicion.registro import cargar_modelo  # noqa: E402


def main(dir_data: Path) -> None:
    cfgs = cargar_configs(RAIZ / "config")
    lgbm = cargar_modelo("lgbm-2017-01-02-496d76f4", dir_data)
    reales = asof("ventas", date(2017, 2, 1), dir_data)[["date", "store_nbr", "family", "sales"]]

    def feats(corte: date) -> pd.DataFrame:
        datos = cargar_datos_asof(corte, dir_data)
        X = construir_features(datos, [corte], cfgs.modelo, cfgs.fuentes, con_objetivo=False)
        X = X.assign(store_nbr=X.store_nbr.astype(int), family=X.family.astype(str))
        X = X.merge(
            reales,
            left_on=["fecha_objetivo", "store_nbr", "family"],
            right_on=["date", "store_nbr", "family"],
        ).sort_values(["store_nbr", "family", "h"])
        X = X.reset_index(drop=True)
        for c in CATEGORICAS:
            X[c] = pd.Categorical(X[c], categories=lgbm.categorias[c])
        return X

    A, B = feats(date(2017, 1, 2)), feats(date(2017, 1, 9))

    def ev(modelo, M) -> str:
        q = modelo.predecir_cuantiles(M, [0.5])["q0.50"].to_numpy()
        return f"WAPE={wape(A['sales'], q):.3f} sesgo={q.sum() / A['sales'].sum() - 1:+.3f}"

    print("1. tal cual:                     ", ev(lgbm, A))
    print("2. lag_1 = NaN:                  ", ev(lgbm, A.assign(lag_1=np.nan)))
    v = asof("ventas", date(2017, 1, 2), dir_data)
    d31 = v[v["date"] == "2016-12-31"][["store_nbr", "family", "sales"]].rename(
        columns={"sales": "v31"}
    )
    d31 = d31.assign(store_nbr=d31.store_nbr.astype(int), family=d31.family.astype(str))
    m = A[["store_nbr", "family"]].astype({"store_nbr": int, "family": str})
    m = m.merge(d31, on=["store_nbr", "family"], how="left")
    print("3. lag_1 = ventas del 12-31:     ", ev(lgbm, A.assign(lag_1=m["v31"].to_numpy())))
    print("4. feature por feature (valor del corte 01-09):")
    for c in [f for f in lgbm.features if f not in lgbm.categorias and f != "h"]:
        M = A.copy()
        M[c] = B[c].to_numpy()
        print(f"   {c:22s} medias {A[c].mean():10.2f} -> {B[c].mean():10.2f}   {ev(lgbm, M)}")
    base = entrenar_modelo("baseline", date(2017, 1, 2), dir_data, cfgs)
    print("5. baseline mismo corte:         ", ev(base, A))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
