"""Detección de correcciones y de los cortes que afectan (funciones puras sobre el ledger)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

import pandas as pd

from reposicion.features import TOPE_DIAS_FERIADO

# Fuentes de calendario: `fecha_dato` es el inicio del periodo que cubre el archivo (un
# trimestre) y las features miran sus fechas hasta `TOPE_DIAS_FERIADO` días más allá del
# horizonte (distancia al próximo feriado, acotada). Es la misma constante que usa `features`.
FUENTES_CALENDARIO = {"feriados": TOPE_DIAS_FERIADO}


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
    Las fuentes de calendario (feriados) cubren un trimestre completo desde `fecha_dato` y las
    features miran `TOPE_DIAS_FERIADO` días más allá del horizonte: el corte se marca si ese
    trimestre se cruza con `[P - ventana_features, P + horizonte - 1 + TOPE_DIAS_FERIADO]`.

    Una **llegada fuera de plazo** (`es_tardio` sin `es_correccion`) es más precisa si se conocen
    los `lags_esperados` por fuente: solo afecta a los cortes que la habrían usado
    (`fecha_dato + lag_esperado <= P`), no a los que miran un día que aún no ocurría o no se
    necesitaba. Sin el lag de su fuente (o sin el parámetro) vale la regla conservadora.
    """
    afectados = set()
    for c in correcciones.itertuples():
        entrega, fecha_dato = c.fecha_entrega.date(), c.fecha_dato.date()
        lag = None if lags_esperados is None else lags_esperados.get(c.fuente)
        solo_tardio = bool(getattr(c, "es_tardio", False)) and not bool(
            getattr(c, "es_correccion", False)
        )
        adelante = FUENTES_CALENDARIO.get(c.fuente)
        for p in cortes:
            if p >= entrega:
                continue
            desde = p - timedelta(days=ventana_features_dias)
            if adelante is not None:
                fin_periodo = pd.Timestamp(fecha_dato).to_period("Q").end_time.date()
                if fin_periodo >= desde and fecha_dato <= p + timedelta(
                    days=horizonte_dias - 1 + adelante
                ):
                    afectados.add(p)
            elif solo_tardio and lag is not None:
                if desde <= fecha_dato and fecha_dato + timedelta(days=lag) <= p:
                    afectados.add(p)
            elif desde <= fecha_dato <= p + timedelta(days=horizonte_dias - 1):
                afectados.add(p)
    return sorted(afectados)
