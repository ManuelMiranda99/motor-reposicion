"""Detección de correcciones y de los cortes que afectan (funciones puras sobre el ledger)."""

from __future__ import annotations

from collections.abc import Mapping
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
    lags_esperados: Mapping[str, int | None] | None = None,
) -> list[date]:
    """Cortes ya calculados cuyo resultado cambiaría por las correcciones dadas.

    Un corte P está afectado si P < fecha_entrega (se calculó antes de la corrección) y
    P - ventana_features <= fecha_dato <= P + horizonte - 1 (regla conservadora para correcciones).

    Una **llegada fuera de plazo** (`es_tardio` sin `es_correccion`) es más precisa si se conocen
    los `lags_esperados` por fuente: solo afecta a los cortes que la habrían usado
    (`fecha_dato + lag_esperado <= P`), no a los que miran un día que aún no ocurría o no se
    necesitaba. Sin el lag de su fuente (o sin el parámetro) vale la regla conservadora.
    """
    afectados = set()
    for c in correcciones.itertuples():
        entrega, fecha_dato = c.fecha_entrega.date(), c.fecha_dato.date()
        lag = None if lags_esperados is None else lags_esperados.get(c.fuente)
        solo_tardio = bool(c.es_tardio) and not bool(c.es_correccion)
        for p in cortes:
            if p >= entrega:
                continue
            desde = p - timedelta(days=ventana_features_dias)
            if solo_tardio and lag is not None:
                if desde <= fecha_dato and fecha_dato + timedelta(days=lag) <= p:
                    afectados.add(p)
            elif desde <= fecha_dato <= p + timedelta(days=horizonte_dias - 1):
                afectados.add(p)
    return sorted(afectados)
