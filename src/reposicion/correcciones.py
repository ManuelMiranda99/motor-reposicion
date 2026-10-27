"""Detección de correcciones y de los cortes que afectan (funciones puras sobre el ledger)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def correcciones_entre(ledger: pd.DataFrame, desde: date, hasta: date) -> pd.DataFrame:
    """Filas del ledger que son corrección o llegada tardía, entregadas en `(desde, hasta]`."""
    entrega = ledger["fecha_entrega"]
    mascara = (
        (ledger["es_correccion"] | ledger["es_tardio"])
        & (entrega > pd.Timestamp(desde))
        & (entrega <= pd.Timestamp(hasta))
    )
    return ledger[mascara].reset_index(drop=True)


def cortes_afectados(
    correcciones: pd.DataFrame,
    cortes: list[date],
    horizonte_dias: int,
    ventana_features_dias: int,
) -> list[date]:
    """Cortes ya calculados cuyo resultado cambiaría por las correcciones dadas.

    Un corte P está afectado si P < fecha_entrega (se calculó antes de la corrección) y
    P - ventana_features <= fecha_dato <= P + horizonte - 1.
    """
    afectados = set()
    for c in correcciones.itertuples():
        entrega, fecha_dato = c.fecha_entrega.date(), c.fecha_dato.date()
        for p in cortes:
            if p < entrega and p - timedelta(
                days=ventana_features_dias
            ) <= fecha_dato <= p + timedelta(days=horizonte_dias - 1):
                afectados.add(p)
    return sorted(afectados)
