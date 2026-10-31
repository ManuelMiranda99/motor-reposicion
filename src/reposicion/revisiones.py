"""Revisiones de pronósticos publicados cuando llega una corrección de datos.

Un publicado nunca se reescribe. Si una corrección (o un dato tardío) entregada en la última
semana afecta un corte cuyo horizonte sigue vigente, se emite `rev=N+1` con los datos visibles en
el corte de evaluación (`datos_hasta`). El seguimiento de las revisiones anteriores se recalcula
aparte (`seguimiento.evaluar_publicados`).

Idempotente: si ya existe una revisión del corte con `datos_hasta == corte_eval`, no se emite otra
(re-correr no crea `rev=N+2`); además `pronosticar_corte` es un no-op con las mismas entradas.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from reposicion.almacen import leer_ledger, ruta_ledger
from reposicion.correcciones import correcciones_entre, cortes_afectados
from reposicion.parametros import Configs
from reposicion.publicacion import directorio_publicacion, pronosticar_corte

log = logging.getLogger(__name__)


def _revisiones_de(dir_data: Path, corte: date) -> dict[int, dict]:
    base = directorio_publicacion(dir_data, corte, 1).parent
    return {
        int(m.parent.name.removeprefix("rev=")): json.loads(m.read_text(encoding="utf-8"))
        for m in sorted(base.glob("rev=*/manifest.json"))
    }


def cortes_publicados(dir_data: Path) -> list[date]:
    base = Path(dir_data) / "published"
    return sorted(
        date.fromisoformat(d.name.removeprefix("corte="))
        for d in base.glob("corte=*")
        if d.is_dir() and any(d.glob("rev=*/manifest.json"))
    )


def _motivo(correcciones, corte: date) -> str:
    """Texto determinista con las entregas que motivan la revisión."""
    items = sorted(
        {
            f"{c.fuente} {c.fecha_dato.date()} (entrega {c.fecha_entrega.date()})"
            for c in correcciones.itertuples()
            if c.fecha_entrega.date() > corte
        }
    )
    return "corrección/dato tardío: " + "; ".join(items)


def emitir_revisiones(corte_eval: date, dir_data: Path, cfgs: Configs) -> list[Path]:
    """Emite las revisiones que correspondan en `corte_eval`. Devuelve los `rev=N` nuevos."""
    dir_data = Path(dir_data)
    cfg = cfgs.monitoreo
    if not cfg.reemitir_si_corrige:
        log.info("revisiones desactivadas (reemitir_si_corrige: false)")
        return []
    if not ruta_ledger(dir_data).exists():
        return []
    ledger = leer_ledger(dir_data)
    desde = corte_eval - timedelta(days=cfg.ventana_correcciones_dias)
    correcciones = correcciones_entre(ledger, desde, corte_eval)
    if correcciones.empty:
        return []
    h = cfgs.modelo.horizonte_dias
    afectados = cortes_afectados(
        correcciones, cortes_publicados(dir_data), h, cfgs.modelo.ventana_features_dias
    )
    nuevos: list[Path] = []
    for p in afectados:
        if corte_eval > p + timedelta(days=h - 1):
            log.info("corte %s afectado, pero su horizonte ya terminó: no se emite revisión", p)
            continue
        existentes = _revisiones_de(dir_data, p)
        if any(m.get("datos_hasta") == corte_eval.isoformat() for m in existentes.values()):
            log.info("corte %s ya tiene una revisión emitida en %s: no-op", p, corte_eval)
            continue
        ultima = max(existentes)
        destino = pronosticar_corte(
            p,
            dir_data,
            cfgs,
            revision=ultima + 1,
            datos_hasta=corte_eval,
            motivo=_motivo(correcciones, p),
            revision_de=ultima,
        )
        previa = existentes[ultima]["sha256_archivos"]
        if previa == _revisiones_de(dir_data, p)[ultima + 1]["sha256_archivos"]:
            log.info("revisión %s sin cambios numéricos respecto de rev=%d", destino, ultima)
        else:
            log.info("revisión emitida: %s (cambia el pronóstico)", destino)
        nuevos.append(destino)
    return nuevos
