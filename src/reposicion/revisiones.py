"""Revisiones de pronósticos publicados cuando llega una corrección de datos.

Un publicado nunca se reescribe. Si una corrección (o un dato que llegó después de su plazo)
afecta un corte cuyo horizonte sigue vigente, se emite `rev=N+1` con los datos visibles en el corte
de evaluación (`datos_hasta`). El seguimiento de las revisiones anteriores se recalcula aparte
(`seguimiento.evaluar_publicados`).

Qué hay "pendiente" se deriva del ledger **contra cada publicación**, no de una ventana fija: para
un corte P cuya última revisión se calculó con los datos entregados hasta `V` (`datos_hasta`, o P
en `rev=1`), son pendientes las correcciones y llegadas fuera de plazo con `V < entrega <=
corte_eval`. Así el resultado no depende de cuántos días pasaron entre dos seguimientos ni del
orden en que corrieron los DAGs.

Idempotente: tras emitir una revisión en `corte_eval` ya no queda nada pendiente para ese corte
(re-correr no crea `rev=N+2`); además `pronosticar_corte` es un no-op con las mismas entradas.
`asegurar_publicaciones` completa los `rev=1` que falten (los DAGs de un backfill no tienen orden
entre sí) antes de revisar.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from reposicion.almacen import leer_ledger, ruta_ledger
from reposicion.correcciones import correcciones_entre, cortes_afectados
from reposicion.parametros import Configs
from reposicion.publicacion import (
    DatosInsuficientes,
    cortes_con_publicacion,
    pronosticar_corte,
    revisiones_publicadas,
)

log = logging.getLogger(__name__)


def _revisiones_de(dir_data: Path, corte: date) -> dict[int, dict]:
    return {
        n: json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        for n, d in revisiones_publicadas(dir_data, corte).items()
    }


def cortes_publicados(dir_data: Path) -> list[date]:
    return cortes_con_publicacion(dir_data)


def _motivo(correcciones) -> str:
    """Texto determinista con las entregas que motivan la revisión."""
    items = sorted(
        {
            f"{c.fuente} {c.fecha_dato.date()} (entrega {c.fecha_entrega.date()})"
            for c in correcciones.itertuples()
        }
    )
    return "corrección/dato tardío: " + "; ".join(items)


def asegurar_publicaciones(
    cortes: list[date],
    dir_data: Path,
    cfgs: Configs,
    preparar: Callable[[date], None] | None = None,
) -> list[date]:
    """Publica `rev=1` de los `cortes` que todavía no tengan ninguna publicación.

    Un backfill corre los DAGs sin orden entre sí: el seguimiento de la semana W+1 puede llegar
    antes que el pronóstico de W. `rev=1` siempre se calcula as-of su corte, así que publicarlo
    aquí produce exactamente lo mismo que el DAG de pronóstico (que después es un no-op).
    `preparar(corte)` deja listo lo que el pronóstico necesita (el champion vigente). Un corte sin
    datos suficientes se omite con un aviso: el DAG de pronóstico fallará por su cuenta.
    """
    publicados = []
    for p in sorted(cortes):
        if revisiones_publicadas(dir_data, p):
            continue
        try:
            if preparar is not None:
                preparar(p)
            pronosticar_corte(p, dir_data, cfgs, revision=1)
        except DatosInsuficientes as e:
            log.warning("no se pudo asegurar la publicación del corte %s: %s", p, e)
            continue
        log.info("publicación del corte %s asegurada (rev=1)", p)
        publicados.append(p)
    return publicados


def emitir_revisiones(corte_eval: date, dir_data: Path, cfgs: Configs) -> list[Path]:
    """Emite las revisiones que correspondan en `corte_eval`. Devuelve los `rev=N` nuevos."""
    dir_data = Path(dir_data)
    if not cfgs.monitoreo.reemitir_si_corrige:
        log.info("revisiones desactivadas (reemitir_si_corrige: false)")
        return []
    if not ruta_ledger(dir_data).exists():
        return []
    ledger = leer_ledger(dir_data)
    h = cfgs.modelo.horizonte_dias
    lags = {n: f.lag_esperado_dias for n, f in cfgs.fuentes.fuentes.items()}
    nuevos: list[Path] = []
    for p in cortes_publicados(dir_data):
        if p >= corte_eval:  # un corte publicado en o después de la evaluación no se revisa aún
            continue
        existentes = _revisiones_de(dir_data, p)
        ultima = max(existentes)
        # Datos con los que se calculó la última revisión: lo entregado hasta esa fecha.
        visto = date.fromisoformat(existentes[ultima].get("datos_hasta", p.isoformat()))
        pendientes = correcciones_entre(ledger, visto, corte_eval)
        afectados = cortes_afectados(pendientes, [p], h, cfgs.modelo.ventana_features_dias, lags)
        if not afectados:
            continue
        if corte_eval > p + timedelta(days=h - 1):
            log.info("corte %s afectado, pero su horizonte ya terminó: no se emite revisión", p)
            continue
        previa = existentes[ultima]["sha256_archivos"]
        try:
            destino = pronosticar_corte(
                p,
                dir_data,
                cfgs,
                revision=ultima + 1,
                datos_hasta=corte_eval,
                motivo=_motivo(pendientes[pendientes["fecha_entrega"] > pd.Timestamp(p)]),
                revision_de=ultima,
            )
        except DatosInsuficientes as e:
            log.warning("no se pudo revisar el corte %s en %s: %s", p, corte_eval, e)
            continue
        if previa == _revisiones_de(dir_data, p)[ultima + 1]["sha256_archivos"]:
            log.info("revisión %s sin cambios numéricos respecto de rev=%d", destino, ultima)
        else:
            log.info("revisión emitida: %s (cambia el pronóstico)", destino)
        nuevos.append(destino)
    return nuevos
