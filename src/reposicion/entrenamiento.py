"""Entrenamiento del challenger y decisión champion/challenger.

`entrenar_y_evaluar(corte)`: entrena LightGBM con `asof(corte)`, hace el backtest del challenger y
del champion vigente (o del baseline, si no hay champion) con los **mismos** orígenes, aplica el
criterio de `promotion.yaml` y registra todo. Idempotente: si el `modelo_id` del challenger (que
depende de la configuración y de la huella de las entradas) ya fue evaluado, devuelve la decisión
guardada sin reentrenar.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from reposicion.asof import huella_entradas
from reposicion.backtest import ejecutar_backtest, guardar_backtest, origenes_entrenamiento
from reposicion.datos import cargar_datos_asof
from reposicion.features import construir_features
from reposicion.modelos import fabrica
from reposicion.modelos.base import ModeloPronostico
from reposicion.parametros import Configs
from reposicion.registro import (
    Decision,
    anotar_decision,
    champion_vigente,
    construir_modelo_id,
    decision_registrada,
    evaluar_promocion,
    hash_config,
    registrar,
    resumir_evaluacion,
    tipo_de,
)

log = logging.getLogger(__name__)

CHALLENGER = "lgbm"
BASELINE = "baseline"


def entrenar_modelo(
    tipo: str, corte: date, dir_data: Path, cfgs: Configs, datos: dict | None = None
) -> ModeloPronostico:
    """Entrena un modelo de `tipo` con lo que se sabía en `corte` (ventana de 52 orígenes)."""
    datos = datos or cargar_datos_asof(corte, dir_data)
    origenes = origenes_entrenamiento(corte, cfgs.modelo)
    X = construir_features(datos, origenes, cfgs.modelo, cfgs.fuentes, con_objetivo=True)
    X = X[X["y"].notna()]
    log.info("entrenando %s para el corte %s con %d filas", tipo, corte, len(X))
    return fabrica(tipo, cfgs)().ajustar(X, X["y"])


def _backtest_y_resumen(tipo: str, corte: date, dir_data: Path, cfgs: Configs):
    pred = ejecutar_backtest(fabrica(tipo, cfgs), corte, dir_data, cfgs)
    metricas = guardar_backtest(pred, tipo, corte, dir_data, cfgs)
    return metricas, resumir_evaluacion(pred, cfgs.negocio)


def entrenar_y_evaluar(corte: date, dir_data: Path, cfgs: Configs) -> Decision:
    """Entrena el challenger LightGBM, lo compara con el champion vigente y registra la decisión."""
    dir_data = Path(dir_data)
    huella = huella_entradas(corte, dir_data)
    config_hash = hash_config(cfgs.modelo, cfgs.negocio)
    id_chall = construir_modelo_id(CHALLENGER, corte, config_hash, huella)
    previa = decision_registrada(id_chall, dir_data)
    if previa is not None:
        log.info("el challenger %s ya fue evaluado: se reutiliza la decisión", id_chall)
        return previa

    datos = cargar_datos_asof(corte, dir_data)
    id_champ = champion_vigente(corte, dir_data)
    if id_champ is None:
        # Sin champion: el baseline pasa a ser el champion inicial (con este corte como fecha).
        baseline = entrenar_modelo(BASELINE, corte, dir_data, cfgs, datos)
        metricas_b, resumen_champ = _backtest_y_resumen(BASELINE, corte, dir_data, cfgs)
        id_champ = registrar(
            baseline, BASELINE, corte, metricas_b, dir_data, config_hash=config_hash, huella=huella
        )
        anotar_decision(
            id_champ,
            Decision(True, ["champion inicial: no había champion vigente"]),
            corte,
            dir_data,
        )
        log.info("baseline %s promovido como champion inicial", id_champ)
    else:
        _, resumen_champ = _backtest_y_resumen(tipo_de(id_champ), corte, dir_data, cfgs)

    modelo = entrenar_modelo(CHALLENGER, corte, dir_data, cfgs, datos)
    metricas, resumen_chall = _backtest_y_resumen(CHALLENGER, corte, dir_data, cfgs)
    decision = evaluar_promocion(resumen_chall, resumen_champ, cfgs.promocion)
    registrar(modelo, CHALLENGER, corte, metricas, dir_data, config_hash=config_hash, huella=huella)
    anotar_decision(id_chall, decision, corte, dir_data)
    log.info("challenger %s: promover=%s", id_chall, decision.promover)
    return decision


def modelos_entrenados(dir_data: Path) -> pd.DataFrame:
    """Historial de modelos (el contenido del registro)."""
    from reposicion.registro import leer_registro

    return leer_registro(dir_data)
