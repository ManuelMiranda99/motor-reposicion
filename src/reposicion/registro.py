"""Registro de modelos con historial y criterio de reemplazo champion/challenger.

```
data/models/<modelo_id>/   # modelo_id = "<tipo>-<corte>-<hash8 de config+datos>"
    modelo_*.txt | baseline.json  meta.json  metricas_backtest.parquet
data/models/registro.parquet      # una fila por modelo; ver COLUMNAS
```

`champion_vigente(corte)` devuelve el último modelo promovido con `fecha_promocion <= corte`: un
backfill reproduce el modelo que se habría usado en su momento. Todo es determinista: las fechas
son cortes (nunca el reloj) y registrar dos veces el mismo modelo no cambia nada.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from reposicion.almacen import leer_parquet
from reposicion.io import escribir_parquet
from reposicion.metricas import resumen_metricas
from reposicion.modelos import clase_de
from reposicion.modelos.base import ModeloPronostico
from reposicion.parametros import ConfigNegocio, ConfigPromocion

COLUMNAS = [
    "modelo_id", "tipo", "corte_entrenamiento", "evaluado_en", "promovido", "fecha_promocion",
    "orden_promocion", "motivos", "costo_total", "wape", "cobertura_p10_p90", "fill_rate",
]  # fmt: skip


# ---------------------------------------------------------------------------- evaluación
@dataclass(frozen=True)
class ResumenEvaluacion:
    """Lo que el criterio de reemplazo necesita saber de un modelo en un backtest."""

    costo_total: float
    wape: float
    cobertura_p10_p90: float
    fill_rate: float
    # familia -> (volumen real, costo de negocio)
    familias: dict[str, tuple[float, float]] = field(default_factory=dict)
    problemas_tecnicos: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    promover: bool
    motivos: list[str]


def checks_tecnicos(pred: pd.DataFrame) -> list[str]:
    """Problemas de las predicciones de un backtest (lista vacía = todo bien)."""
    qs = sorted(
        (c for c in pred.columns if c.startswith("q") and c[1:2].isdigit()),
        key=lambda c: float(c[1:]),
    )
    if not qs:
        return ["sin columnas de cuantiles"]
    problemas = []
    vals = pred[qs].to_numpy(np.float64)
    if np.isnan(vals).any():
        problemas.append("hay NaN en los cuantiles")
    if (vals < 0).any():
        problemas.append("hay cuantiles negativos")
    if (np.diff(vals, axis=1) < -1e-9).any():
        problemas.append("hay cuantiles no monótonos")
    if pred.duplicated(["store_nbr", "family", "origen", "h"]).any():
        problemas.append("hay filas duplicadas por (serie, origen, h)")
    return problemas


def resumir_evaluacion(pred: pd.DataFrame, cfg_negocio: ConfigNegocio) -> ResumenEvaluacion:
    """Resumen global y por familia de las predicciones de un backtest."""
    glob = resumen_metricas(pred, cfg_negocio).iloc[0]
    fam = resumen_metricas(pred, cfg_negocio, ["family"])
    volumen = pred.dropna(subset=["y"]).groupby(pred["family"].astype(str))["y"].sum()
    familias = {
        str(r.family): (float(volumen.get(str(r.family), 0.0)), float(r.costo_total))
        for r in fam.itertuples()
    }
    return ResumenEvaluacion(
        costo_total=float(glob["costo_total"]),
        wape=float(glob["wape"]),
        cobertura_p10_p90=float(glob["cobertura_p10_p90"]),
        fill_rate=float(glob["fill_rate"]),
        familias=familias,
        problemas_tecnicos=checks_tecnicos(pred),
    )


def evaluar_promocion(
    m_challenger: ResumenEvaluacion, m_champion: ResumenEvaluacion, cfg: ConfigPromocion
) -> Decision:
    """Aplica el criterio multicriterio de `config/promotion.yaml`. Promueve solo si cumple todo."""
    fallas: list[str] = []
    ok: list[str] = []

    baja = (m_champion.costo_total - m_challenger.costo_total) / m_champion.costo_total
    texto = f"el costo total baja {baja:.1%} (se exige al menos {cfg.costo_total_baja_min:.0%})"
    (ok if baja >= cfg.costo_total_baja_min else fallas).append(texto)

    peor_wape = (m_challenger.wape - m_champion.wape) / m_champion.wape
    texto = f"el WAPE cambia {peor_wape:+.1%} (se tolera hasta {cfg.wape_empeora_max:+.0%})"
    (ok if peor_wape <= cfg.wape_empeora_max else fallas).append(texto)

    lo, hi = cfg.cobertura_p10_p90
    cob = m_challenger.cobertura_p10_p90
    texto = f"cobertura P10-P90 {cob:.3f} (rango [{lo}, {hi}])"
    (ok if lo <= cob <= hi else fallas).append(texto)

    total = sum(v for v, _ in m_champion.familias.values()) or 1.0
    malas = []
    for familia, (volumen, costo_champ) in sorted(m_champion.familias.items()):
        if volumen / total <= cfg.familia_volumen_min or costo_champ <= 0:
            continue
        costo_chall = m_challenger.familias.get(familia, (volumen, float("nan")))[1]
        if (costo_chall - costo_champ) / costo_champ > cfg.familia_costo_empeora_max:
            malas.append(f"{familia} ({(costo_chall - costo_champ) / costo_champ:+.1%})")
    if malas:
        fallas.append(
            f"familias con más de {cfg.familia_volumen_min:.0%} del volumen cuyo costo empeora más "
            f"de {cfg.familia_costo_empeora_max:.0%}: {', '.join(malas)}"
        )
    else:
        ok.append("ninguna familia grande empeora su costo de forma material")

    if cfg.checks_tecnicos:
        if m_challenger.problemas_tecnicos:
            fallas.append("checks técnicos: " + "; ".join(m_challenger.problemas_tecnicos))
        else:
            ok.append("checks técnicos sin problemas")

    if fallas:
        return Decision(False, [f"NO cumple: {m}" for m in fallas] + [f"cumple: {m}" for m in ok])
    return Decision(True, [f"cumple: {m}" for m in ok])


# ---------------------------------------------------------------------------- identificadores
def hash_config(*configs: object) -> str:
    """sha256 (primeros 64 hex) de configuraciones pydantic, en JSON canónico."""
    partes = [c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in configs]
    return hashlib.sha256(json.dumps(partes, sort_keys=True).encode("utf-8")).hexdigest()


def construir_modelo_id(tipo: str, corte: date, config_hash: str, huella: str) -> str:
    h8 = hashlib.sha256(f"{config_hash}|{huella}".encode()).hexdigest()[:8]
    return f"{tipo}-{corte.isoformat()}-{h8}"


def tipo_de(modelo_id: str) -> str:
    return modelo_id.split("-", 1)[0]


# ---------------------------------------------------------------------------- registro
def ruta_registro(dir_data: Path) -> Path:
    return Path(dir_data) / "models" / "registro.parquet"


def leer_registro(dir_data: Path) -> pd.DataFrame:
    ruta = ruta_registro(dir_data)
    if not ruta.exists():
        return pd.DataFrame(
            {
                "modelo_id": pd.Series(dtype="str"),
                "tipo": pd.Series(dtype="str"),
                "corte_entrenamiento": pd.Series(dtype="datetime64[ns]"),
                "evaluado_en": pd.Series(dtype="datetime64[ns]"),
                "promovido": pd.Series(dtype="bool"),
                "fecha_promocion": pd.Series(dtype="datetime64[ns]"),
                "orden_promocion": pd.Series(dtype="int64"),
                "motivos": pd.Series(dtype="str"),
                "costo_total": pd.Series(dtype="float64"),
                "wape": pd.Series(dtype="float64"),
                "cobertura_p10_p90": pd.Series(dtype="float64"),
                "fill_rate": pd.Series(dtype="float64"),
            }
        )
    return leer_parquet(ruta)


def _guardar_registro(df: pd.DataFrame, dir_data: Path) -> None:
    df = df[COLUMNAS].sort_values("modelo_id").reset_index(drop=True)
    escribir_parquet(df, ruta_registro(dir_data))


def registrar(
    modelo: ModeloPronostico,
    tipo: str,
    corte: date,
    metricas: pd.DataFrame,
    dir_data: Path,
    *,
    config_hash: str = "",
    huella: str = "",
) -> str:
    """Guarda el modelo y sus métricas de backtest y lo anota en el registro. Idempotente.

    `metricas` es la tabla de `guardar_backtest` (la fila `nivel == "global"` alimenta el
    registro). Si el `modelo_id` ya existe no se toca nada (ni el modelo ni su promoción).
    """
    modelo_id = construir_modelo_id(tipo, corte, config_hash, huella)
    destino = Path(dir_data) / "models" / modelo_id
    if not (destino / "metricas_backtest.parquet").exists():
        tmp = destino.with_name(destino.name + ".tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        modelo.guardar(tmp)
        escribir_parquet(metricas, tmp / "metricas_backtest.parquet")
        if destino.exists():
            shutil.rmtree(destino)
        os.replace(tmp, destino)
    reg = leer_registro(dir_data)
    if modelo_id not in set(reg["modelo_id"]):
        g = metricas[metricas["nivel"] == "global"].iloc[0]
        fila = {
            "modelo_id": modelo_id,
            "tipo": tipo,
            "corte_entrenamiento": pd.Timestamp(corte),
            "evaluado_en": pd.Timestamp(corte),
            "promovido": False,
            "fecha_promocion": pd.NaT,
            "orden_promocion": 0,
            "motivos": "",
            "costo_total": float(g["costo_total"]),
            "wape": float(g["wape"]),
            "cobertura_p10_p90": float(g["cobertura_p10_p90"]),
            "fill_rate": float(g["fill_rate"]),
        }
        reg = pd.concat([reg, pd.DataFrame([fila])], ignore_index=True)
        _guardar_registro(reg, dir_data)
    return modelo_id


def anotar_decision(
    modelo_id: str, decision: Decision, fecha_promocion: date, dir_data: Path
) -> None:
    """Guarda los motivos y, si se promueve, `fecha_promocion` = el corte de la evaluación.

    Idempotente: un modelo ya promovido conserva su fecha y su orden.
    """
    reg = leer_registro(dir_data)
    i = reg.index[reg["modelo_id"] == modelo_id]
    if len(i) != 1:
        raise KeyError(f"modelo no registrado: {modelo_id}")
    i = i[0]
    reg.loc[i, "motivos"] = " | ".join(decision.motivos)
    if decision.promover and not reg.loc[i, "promovido"]:
        reg.loc[i, "promovido"] = True
        reg.loc[i, "fecha_promocion"] = pd.Timestamp(fecha_promocion)
        reg.loc[i, "orden_promocion"] = int(reg["orden_promocion"].max()) + 1
    _guardar_registro(reg, dir_data)


def decision_registrada(modelo_id: str, dir_data: Path) -> Decision | None:
    """La decisión ya guardada de `modelo_id`, o `None` si todavía no se evaluó."""
    reg = leer_registro(dir_data)
    f = reg[reg["modelo_id"] == modelo_id]
    if f.empty or not f.iloc[0]["motivos"]:
        return None
    return Decision(bool(f.iloc[0]["promovido"]), str(f.iloc[0]["motivos"]).split(" | "))


def champion_vigente(corte: date, dir_data: Path) -> str | None:
    """Último modelo promovido con `fecha_promocion <= corte` (empates: el promovido después)."""
    reg = leer_registro(dir_data)
    v = reg[reg["promovido"] & (reg["fecha_promocion"] <= pd.Timestamp(corte))]
    if v.empty:
        return None
    v = v.sort_values(["fecha_promocion", "orden_promocion"])
    return str(v.iloc[-1]["modelo_id"])


def cargar_modelo(modelo_id: str, dir_data: Path) -> ModeloPronostico:
    ruta = Path(dir_data) / "models" / modelo_id
    if not ruta.exists():
        raise FileNotFoundError(f"no existe el modelo {modelo_id} en {ruta}")
    return clase_de(tipo_de(modelo_id)).cargar(ruta)
