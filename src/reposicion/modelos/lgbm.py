"""LightGBM global por cuantil, entrenado en `log1p(y)`.

Un `lgb.Booster` por cuantil (`objective=quantile`, `alpha=q`). El cuantil es equivariante ante
transformaciones monótonas, así que el cuantil de `log1p(y)` es `log1p` del cuantil de `y`: la
predicción vuelve a unidades con `expm1`, recortada a >= 0. La regla de ceros es la misma del
baseline (`aplicar_regla_ceros`). Sin bagging ni early stopping: mismos datos → mismo modelo.

Las categóricas se guardan con categorías **fijas** (las del entrenamiento) para que los códigos
sean iguales al predecir con cualquier subconjunto de filas. Un valor desconocido pasa a NaN, que
LightGBM trata como "faltante".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from reposicion.features import CATEGORICAS
from reposicion.modelos.base import aplicar_regla_ceros, nombre_cuantil, ordenar_cuantiles
from reposicion.parametros import ConfigLightGBM, ConfigModelo

# `store_nbr`, `family` (categóricas) y `h` sí son features; el origen y el día objetivo no.
NO_FEATURES = {"origen", "fecha_objetivo", "y"}


def columnas_features(X: pd.DataFrame) -> list[str]:
    """Features del modelo: todo salvo origen, día objetivo y objetivo, en el orden de `X`."""
    return [c for c in X.columns if c not in NO_FEATURES]


def parametros_lgbm(cfg: ConfigLightGBM, alpha: float) -> dict:
    p = cfg.model_dump(exclude={"num_boost_round"})
    p.update({"objective": "quantile", "alpha": alpha, "metric": "quantile"})
    return p


class LightGBMCuantiles:
    nombre = "lgbm"

    def __init__(
        self,
        cfg_modelo: ConfigModelo,
        cuantiles: list[float],
        cfg_lgbm: ConfigLightGBM | None = None,
    ):
        self.cuantiles_entrenados = sorted({round(q, 2) for q in cuantiles})
        self.cfg_lgbm = cfg_lgbm or cfg_modelo.lightgbm
        self.dias_sin_ventas = cfg_modelo.regla_ceros.dias_sin_ventas
        self.features: list[str] = []
        self.categorias: dict[str, list] = {}
        self.boosters: dict[float, lgb.Booster] = {}

    # ------------------------------------------------------------------ preparación
    def _matriz(self, X: pd.DataFrame) -> pd.DataFrame:
        """Columnas del modelo en su orden, con categorías fijas y el resto en float32."""
        faltan = [c for c in self.features if c not in X.columns]
        if faltan:
            raise ValueError(f"faltan features: {faltan}")
        M = X[self.features].copy()
        for c in self.features:
            if c in self.categorias:
                conocido = M[c].astype(object)
                conocido = conocido.where(conocido.isin(self.categorias[c]))  # desconocido → NaN
                M[c] = pd.Categorical(conocido, categories=self.categorias[c])
            else:
                M[c] = M[c].astype(np.float32)
        return M

    # ------------------------------------------------------------------ interfaz
    def ajustar(self, X: pd.DataFrame, y: pd.Series) -> LightGBMCuantiles:
        """Entrena un Booster por cada cuantil de `self.cuantiles_entrenados`."""
        self.features = columnas_features(X)
        self.categorias = {
            c: X[c].cat.categories.tolist() for c in CATEGORICAS if c in self.features
        }
        yv = y.to_numpy(np.float64)
        ok = ~np.isnan(yv)
        M = self._matriz(X)[ok]
        etiqueta = np.log1p(yv[ok].clip(min=0))
        # El Dataset se construye (binning) una sola vez y se reutiliza en todos los cuantiles.
        ds = lgb.Dataset(
            M,
            label=etiqueta,
            categorical_feature=[c for c in self.features if c in self.categorias],
            free_raw_data=False,
            params={"verbose": -1, "num_threads": self.cfg_lgbm.num_threads, "max_bin": 255},
        )
        self.boosters = {}
        for q in self.cuantiles_entrenados:
            self.boosters[q] = lgb.train(
                parametros_lgbm(self.cfg_lgbm, q), ds, num_boost_round=self.cfg_lgbm.num_boost_round
            )
        return self

    def predecir_cuantiles(self, X: pd.DataFrame, cuantiles: list[float]) -> pd.DataFrame:
        M = self._matriz(X)
        salida = {}
        for q in cuantiles:
            qk = round(q, 2)
            if qk not in self.boosters:
                raise ValueError(f"el modelo no se entrenó en el cuantil {qk}")
            pred = np.expm1(self.boosters[qk].predict(M)).clip(min=0.0)
            salida[nombre_cuantil(q)] = aplicar_regla_ceros(pred, X, self.dias_sin_ventas)
        return ordenar_cuantiles(pd.DataFrame(salida, index=X.index))

    # ------------------------------------------------------------------ persistencia
    def guardar(self, ruta: Path) -> None:
        ruta = Path(ruta)
        ruta.mkdir(parents=True, exist_ok=True)
        for q, booster in self.boosters.items():
            destino = ruta / f"modelo_{q:.2f}.txt"
            tmp = destino.with_name(destino.name + ".tmp")
            booster.save_model(str(tmp))
            os.replace(tmp, destino)
        meta = {
            "features": self.features,
            "categorias": self.categorias,
            "cuantiles": self.cuantiles_entrenados,
            "dias_sin_ventas": self.dias_sin_ventas,
            "parametros": self.cfg_lgbm.model_dump(),
        }
        tmp = ruta / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        os.replace(tmp, ruta / "meta.json")

    @classmethod
    def cargar(cls, ruta: Path) -> LightGBMCuantiles:
        ruta = Path(ruta)
        meta = json.loads((ruta / "meta.json").read_text(encoding="utf-8"))
        m = cls.__new__(cls)
        m.cfg_lgbm = ConfigLightGBM.model_validate(meta["parametros"])
        m.dias_sin_ventas = meta["dias_sin_ventas"]
        m.features = meta["features"]
        m.categorias = meta["categorias"]
        m.cuantiles_entrenados = meta["cuantiles"]
        m.boosters = {
            q: lgb.Booster(model_file=str(ruta / f"modelo_{q:.2f}.txt")) for q in meta["cuantiles"]
        }
        return m
