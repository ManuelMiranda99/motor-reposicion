"""Baseline: media de los últimos días con el mismo día de semana + residuos empíricos.

Punto: `media_dds_4`. Cuantiles: en espacio log, `r = log1p(y) - log1p(punto)`, con los cuantiles
empíricos de `r` por (familia, h); la predicción es `expm1(log1p(punto) + r_q)` recortada a >= 0.
Si la serie no vendió en `dias_sin_ventas` días, todos sus cuantiles son 0.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from reposicion.modelos.base import nombre_cuantil, ordenar_cuantiles
from reposicion.parametros import ConfigModelo

# Rejilla de cuantiles de los residuos; se interpola linealmente entre puntos.
REJILLA = np.round(np.linspace(0.0, 1.0, 101), 2)
GLOBAL = "__global__"


class Baseline:
    nombre = "baseline"

    def __init__(self, cfg_modelo: ConfigModelo):
        self.dias_sin_ventas = cfg_modelo.regla_ceros.dias_sin_ventas
        # (familia, h) -> residuos en la rejilla; ("__global__", 0) para combinaciones sin datos.
        self.residuos: dict[tuple[str, int], np.ndarray] = {}

    @staticmethod
    def _punto(X: pd.DataFrame) -> np.ndarray:
        return np.log1p(X["media_dds_4"].fillna(0.0).to_numpy(np.float64).clip(min=0))

    def ajustar(self, X: pd.DataFrame, y: pd.Series) -> Baseline:
        y = y.to_numpy(np.float64)
        ok = ~np.isnan(y)
        r = pd.DataFrame(
            {
                "family": X["family"].astype(str).to_numpy()[ok],
                "h": X["h"].to_numpy()[ok],
                "r": np.log1p(y[ok].clip(min=0)) - self._punto(X)[ok],
            }
        )
        self.residuos = {}
        for (familia, h), g in r.groupby(["family", "h"]):
            self.residuos[(familia, int(h))] = np.quantile(g["r"].to_numpy(), REJILLA)
        self.residuos[(GLOBAL, 0)] = np.quantile(r["r"].to_numpy(), REJILLA)
        return self

    def predecir_cuantiles(self, X: pd.DataFrame, cuantiles: list[float]) -> pd.DataFrame:
        punto = self._punto(X)
        familias = X["family"].astype(str).to_numpy()
        hs = X["h"].to_numpy()
        # índice de la tabla de residuos de cada fila (-1 si no hay → global)
        claves = list(self.residuos)
        pos = {k: j for j, k in enumerate(claves)}
        tabla = np.vstack([self.residuos[k] for k in claves])
        filas = np.array(
            [pos.get((f, int(h)), pos[(GLOBAL, 0)]) for f, h in zip(familias, hs, strict=True)]
        )
        sin_ventas = X["dias_desde_venta"].to_numpy() > self.dias_sin_ventas
        salida = {}
        for q in cuantiles:
            rq = np.array([np.interp(q, REJILLA, fila) for fila in tabla])[filas]
            pred = np.expm1(punto + rq).clip(min=0.0)
            salida[nombre_cuantil(q)] = np.where(sin_ventas, 0.0, pred)
        return ordenar_cuantiles(pd.DataFrame(salida, index=X.index))

    def guardar(self, ruta: Path) -> None:
        ruta = Path(ruta)
        ruta.mkdir(parents=True, exist_ok=True)
        contenido = {
            "dias_sin_ventas": self.dias_sin_ventas,
            "rejilla": REJILLA.tolist(),
            "residuos": [
                {"family": f, "h": h, "valores": v.tolist()}
                for (f, h), v in sorted(self.residuos.items())
            ],
        }
        tmp = ruta / "baseline.json.tmp"
        tmp.write_text(json.dumps(contenido, sort_keys=True), encoding="utf-8")
        os.replace(tmp, ruta / "baseline.json")

    @classmethod
    def cargar(cls, ruta: Path) -> Baseline:
        contenido = json.loads((Path(ruta) / "baseline.json").read_text(encoding="utf-8"))
        modelo = cls.__new__(cls)
        modelo.dias_sin_ventas = contenido["dias_sin_ventas"]
        modelo.residuos = {
            (r["family"], r["h"]): np.array(r["valores"]) for r in contenido["residuos"]
        }
        return modelo
