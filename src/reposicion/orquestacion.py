"""Funciones que ejecutan las tareas de los DAGs de Airflow (`dags/`).

Los DAGs solo orquestan: calculan la fecha de corte (`logical_date`) y llaman a estas funciones.
Todas reciben el corte como parámetro, son idempotentes y nunca consultan el reloj.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from reposicion import rutas
from reposicion.almacen import leer_ledger, ruta_ledger
from reposicion.entrenamiento import entrenar_y_evaluar
from reposicion.fuentes import cargar_fuentes
from reposicion.ingesta import ResumenIngesta, ingestar
from reposicion.operacion import ConfigOperacion, cargar_operacion, ultimo_primer_lunes
from reposicion.parametros import Configs, cargar_configs
from reposicion.publicacion import (
    calidad_datos,
    pronosticar_corte,
    revisiones_publicadas,
)
from reposicion.registro import Decision, leer_registro
from reposicion.revisiones import asegurar_publicaciones as _asegurar_publicaciones
from reposicion.revisiones import emitir_revisiones as _emitir_revisiones
from reposicion.seguimiento import evaluar_publicados as _evaluar_publicados
from reposicion.seguimiento import leer_resumen
from reposicion.validacion import cargar_validacion

log = logging.getLogger(__name__)


def dir_config() -> Path:
    return rutas.dir_repo() / "config"


def configuracion_operacion() -> ConfigOperacion:
    return cargar_operacion(dir_config() / "operacion.yaml")


def asegurar_ingesta(corte: date, dir_data: Path, bandeja: Path, config: Path) -> ResumenIngesta:
    """Ingiere la bandeja hasta `corte` (idempotente: si ya estaba hecha, no cambia nada)."""
    resumen = ingestar(
        corte,
        dir_data,
        bandeja,
        cargar_fuentes(config / "sources.yaml"),
        cargar_validacion(config / "validation.yaml"),
    )
    log.info("ingesta hasta %s:\n%s", corte, resumen.texto())
    return resumen


def reportar_calidad(corte: date, dir_data: Path) -> dict:
    """Resumen del ledger de lo entregado el día `corte`. La cuarentena no hace fallar nada."""
    if not ruta_ledger(dir_data).exists():
        return {"corte": corte.isoformat(), "archivos": 0}
    ledger = leer_ledger(dir_data)
    dia = ledger[ledger["fecha_entrega"] == pd.Timestamp(corte)]
    por_estado = {str(k): int(v) for k, v in dia["estado"].value_counts().sort_index().items()}
    problemas = dia[dia["estado"] == "cuarentena"]
    resumen = {
        "corte": corte.isoformat(),
        "archivos": len(dia),
        "por_estado": por_estado,
        "correcciones": int(dia["es_correccion"].sum()),
        "tardios": int(dia["es_tardio"].sum()),
        "cuarentena": [f"{r.archivo}: {r.errores}" for r in problemas.itertuples()],
    }
    for linea in resumen["cuarentena"]:
        log.warning("cuarentena: %s", linea)
    log.info("calidad de la ingesta del %s: %s", corte, resumen)
    return resumen


def verificar_datos(corte: date, dir_data: Path, cfgs: Configs) -> dict:
    """Modo degradado: lanza `DatosInsuficientes` si no hay ventas recientes; si no, informa."""
    calidad, advertencias = calidad_datos(corte, dir_data, cfgs)
    for a in advertencias:
        log.warning("calidad degradada: %s", a)
    return {"calidad": calidad, "advertencias": advertencias}


def asegurar_champion(corte: date, dir_data: Path, bandeja: Path, config: Path) -> dict:
    """Garantiza que el reentrenamiento mensual vigente en `corte` ya esté evaluado.

    El pronóstico del lunes `corte` usa `champion_vigente(corte)`; en un backfill los DAGs corren
    sin orden entre sí, así que se asegura aquí (con la misma función idempotente que usa el DAG
    `entrenamiento`) que la evaluación del último primer lunes exista. Si ya existe, es un no-op.
    """
    base = ultimo_primer_lunes(corte)
    asegurar_ingesta(base, dir_data, bandeja, config)
    d = entrenar_y_evaluar(base, dir_data, cargar_configs(config))
    return {"corte_entrenamiento": base.isoformat(), "promover": d.promover}


def entrenar(corte: date, dir_data: Path, config: Path) -> dict:
    """Entrena el challenger en `corte` y decide si reemplaza al champion."""
    d: Decision = entrenar_y_evaluar(corte, dir_data, cargar_configs(config))
    log.info("entrenamiento %s: promover=%s; %s", corte, d.promover, "; ".join(d.motivos))
    return {"promover": d.promover, "motivos": list(d.motivos)}


def publicar_pronostico(corte: date, dir_data: Path, config: Path) -> str:
    """Publica `rev=1` del corte (no-op si ya existe con las mismas entradas)."""
    return str(pronosticar_corte(corte, dir_data, cargar_configs(config), revision=1))


def asegurar_publicaciones(
    corte: date, dir_data: Path, bandeja: Path, config: Path, inicio: date
) -> dict:
    """Garantiza que existan los `rev=1` que el seguimiento de `corte` necesita (idempotente).

    En un backfill los DAGs corren sin orden entre sí: el seguimiento del lunes W puede llegar antes
    que el pronóstico de W-7. Se aseguran los cortes semanales de las últimas
    `alerta.ventana_cortes` semanas (los vigentes para revisar y los de la alerta), desde `inicio`.
    Cada uno se publica as-of su propio corte con su champion, igual que el DAG de pronóstico.
    """
    cfgs = cargar_configs(config)
    paso = timedelta(days=cfgs.modelo.backtest.paso_dias)
    cortes = [corte - k * paso for k in range(cfgs.monitoreo.alerta.ventana_cortes + 1)]
    cortes = [c for c in cortes if c >= inicio]

    def preparar(p: date) -> None:
        asegurar_champion(p, dir_data, bandeja, config)

    publicados = _asegurar_publicaciones(cortes, dir_data, cfgs, preparar)
    return {"publicados": [c.isoformat() for c in publicados]}


def emitir_revisiones(corte: date, dir_data: Path, config: Path) -> dict:
    """Emite `rev=N+1` de los cortes vigentes afectados por correcciones recientes (idempotente)."""
    nuevas = _emitir_revisiones(corte, dir_data, cargar_configs(config))
    for ruta in nuevas:
        log.info("revisión emitida en %s: %s", corte, ruta)
    return {"revisiones": [f"{r.parent.name}/{r.name}" for r in nuevas]}


def evaluar_publicados(corte: date, dir_data: Path, config: Path) -> dict:
    """Seguimiento del desempeño de lo publicado (as-of `corte`); advierte si hay degradación."""
    por_corte = _evaluar_publicados(corte, dir_data, cargar_configs(config))
    resumen = leer_resumen(dir_data, corte) or {}
    alerta = resumen.get("alerta", {})
    if alerta.get("alerta"):
        log.warning("%s", alerta["mensaje"])
    return {
        "publicaciones": len(por_corte),
        "alerta": bool(alerta.get("alerta")),
        "mensaje": alerta.get("mensaje"),
    }


def registro_evento(evento: str, corte: date, dir_data: Path) -> dict:
    """Contenido determinista de `registro/<corte>/<evento>.json` en la rama de publicaciones."""
    if evento == "pronostico":
        manifiestos = {
            d.name: json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            for d in revisiones_publicadas(dir_data, corte).values()
        }
        return {"manifiestos": manifiestos}
    if evento == "modelo":
        reg = leer_registro(dir_data)
        reg = reg[reg["corte_entrenamiento"] == pd.Timestamp(corte)]
        cols = ["modelo_id", "tipo", "promovido", "motivos", "costo_total", "wape", "fill_rate"]
        return {"modelos": json.loads(reg[cols].to_json(orient="records"))}
    if evento == "seguimiento":
        resumen = leer_resumen(dir_data, corte)
        return resumen if resumen is not None else {"estado": "sin seguimiento calculado"}
    raise ValueError(f"evento desconocido: {evento}")
