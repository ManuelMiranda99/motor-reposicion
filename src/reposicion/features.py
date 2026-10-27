"""Features ancladas al origen, idénticas en entrenamiento e inferencia.

Para un origen O (el corte) y cada día objetivo `O + h - 1`, h = 1..horizonte, todas las features
se calculan solo con la información que existía en O según el rezago de cada fuente (ver
`sources.yaml`). Sin recursión: nada se alimenta de pronósticos anteriores.

| Fuente | Se usa en el origen O |
|---|---|
| ventas | `date <= O - 1` |
| transacciones | `date <= O - lag_esperado` |
| petróleo | `date <= O - 1`, con forward-fill (solo hacia adelante) |
| promociones | del día objetivo solo si `fecha_objetivo <= O + anticipación`; si no, NaN |
| feriados | todos (se conocen de antemano); las distancias se acotan a `TOPE_DIAS_FERIADO` |

Implementación: matrices anchas (series × fechas) y un ciclo por origen con operaciones
vectorizadas. Las fechas fuera de rango son NaN (relleno a los lados de cada matriz).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from reposicion.fuentes import ConfigFuentes
from reposicion.parametros import ConfigModelo

LAGS = (1, 7, 14, 28, 364)
MEDIAS = (7, 14, 28, 56)
# Los feriados de un trimestre se entregan un trimestre antes (≥ 91 días de visibilidad); acotar
# las distancias a 30 días garantiza que entrenamiento e inferencia vean lo mismo.
TOPE_DIAS_FERIADO = 30
COLS_ID = ["store_nbr", "family", "origen", "fecha_objetivo", "h"]
CATEGORICAS = ["store_nbr", "family", "city", "state", "type", "cluster"]
TIPOS_FERIADO = {"Holiday", "Transfer", "Additional"}
_MARGEN_IZQ = 400  # ≥ lag máximo (364) + ventana más larga
_MARGEN_DER = 60


class _Matriz:
    """Matriz (filas × fechas) en `float32` con relleno NaN a ambos lados del eje de fechas."""

    def __init__(self, fecha0: pd.Timestamp, n_fechas: int, n_filas: int):
        self.fecha0 = fecha0
        self.n_fechas = n_fechas
        self.v = np.full((n_filas, _MARGEN_IZQ + n_fechas + _MARGEN_DER), np.nan, np.float32)

    def col(self, fecha: pd.Timestamp) -> int:
        """Columna (con relleno) de `fecha`."""
        c = _MARGEN_IZQ + (fecha - self.fecha0).days
        if not 0 <= c < self.v.shape[1]:
            raise ValueError(f"fecha {fecha.date()} fuera del rango de los datos")
        return c

    def poner(self, filas: np.ndarray, fechas: pd.Series, valores: np.ndarray) -> None:
        cols = _MARGEN_IZQ + (fechas - self.fecha0).dt.days.to_numpy()
        self.v[filas, cols] = valores


def _nanstat(f, a: np.ndarray, axis: int) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return f(a, axis=axis)


def _flags_feriados(
    feriados: pd.DataFrame, tiendas: pd.DataFrame, dias: pd.DatetimeIndex
) -> tuple[np.ndarray, dict[int, int]]:
    """Arreglo (combos, 6, días) con las features de feriado por (ciudad, estado) y día.

    Orden: es_feriado, es_puente, es_dia_laboral_extra, es_evento, dias_al_proximo,
    dias_desde_anterior. Un feriado `transferred=True` no cuenta en su fecha original.
    """
    combos = tiendas[["city", "state"]].drop_duplicates().sort_values(["city", "state"])
    combos = list(combos.itertuples(index=False, name=None))
    salida = np.zeros((len(combos), 6, len(dias)), np.float32)
    for k, (ciudad, estado) in enumerate(combos):
        nac = feriados["locale"] == "National"
        reg = (feriados["locale"] == "Regional") & (feriados["locale_name"] == estado)
        loc = (feriados["locale"] == "Local") & (feriados["locale_name"] == ciudad)
        f = feriados[nac | reg | loc]
        reglas = (
            f["type"].isin(TIPOS_FERIADO) & ~f["transferred"],
            f["type"] == "Bridge",
            f["type"] == "Work Day",
            f["type"] == "Event",
        )
        for j, regla in enumerate(reglas):
            salida[k, j] = dias.isin(f.loc[regla, "date"])
        es = salida[k, 0].astype(bool)
        pos = np.arange(len(dias))
        # Días al próximo feriado (≥ hoy) y desde el anterior (≤ hoy), acotados.
        sig = np.where(es, pos, len(dias) + 10 * TOPE_DIAS_FERIADO)
        sig = np.minimum.accumulate(sig[::-1])[::-1] - pos
        ant = np.where(es, pos, -10 * TOPE_DIAS_FERIADO)
        ant = pos - np.maximum.accumulate(ant)
        salida[k, 4] = np.minimum(sig, TOPE_DIAS_FERIADO)
        salida[k, 5] = np.minimum(ant, TOPE_DIAS_FERIADO)
    return salida, {tienda: k for k, c in enumerate(combos) for tienda in _tiendas_de(tiendas, c)}


def _tiendas_de(tiendas: pd.DataFrame, combo: tuple[str, str]) -> list[int]:
    m = (tiendas["city"] == combo[0]) & (tiendas["state"] == combo[1])
    return tiendas.loc[m, "store_nbr"].tolist()


def construir_features(
    datos: dict[str, pd.DataFrame],
    origenes: Sequence[date],
    cfg_modelo: ConfigModelo,
    cfg_fuentes: ConfigFuentes,
    con_objetivo: bool,
) -> pd.DataFrame:
    """Una fila por (tienda, familia, origen, día objetivo). Ver el docstring del módulo.

    Una serie participa en un origen si tiene ventas registradas antes de O y su tienda está en el
    maestro. Con `con_objetivo` agrega `y` (ventas reales del día objetivo; NaN si no se conocen).
    """
    h_max = cfg_modelo.horizonte_dias
    ventas, tiendas = datos["ventas"], datos["tiendas"]
    if ventas.empty:
        raise ValueError("no hay ventas para construir features")
    lag_trx = cfg_fuentes.fuentes["transacciones"].lag_esperado_dias or 0
    anticipacion = -(cfg_fuentes.fuentes["promociones"].lag_esperado_dias or 0)
    origenes_ts = [pd.Timestamp(o) for o in origenes]

    # --- ejes
    fecha0 = min(ventas["date"].min(), min(origenes_ts))
    fecha1 = max(ventas["date"].max(), max(origenes_ts) + pd.Timedelta(days=h_max))
    n_fechas = (fecha1 - fecha0).days + 1
    ejes = pd.date_range(fecha0, fecha1)

    series = (
        ventas[["store_nbr", "family"]].drop_duplicates().sort_values(["store_nbr", "family"])
    ).reset_index(drop=True)
    series = series[series["store_nbr"].isin(tiendas["store_nbr"])].reset_index(drop=True)
    familias = sorted(ventas["family"].unique())
    n = len(series)
    clave = pd.MultiIndex.from_frame(series)

    def filas_de(df: pd.DataFrame) -> np.ndarray:
        return clave.get_indexer(pd.MultiIndex.from_frame(df[["store_nbr", "family"]]))

    # --- matrices anchas
    ventas_m = _Matriz(fecha0, n_fechas, n)
    f = filas_de(ventas)
    ok = f >= 0
    ventas_m.poner(f[ok], ventas["date"][ok], ventas["sales"].to_numpy(np.float32)[ok])

    promo_m = _Matriz(fecha0, n_fechas, n)
    promo = datos["promociones"]
    f = filas_de(promo)
    ok = f >= 0
    promo_m.poner(f[ok], promo["date"][ok], promo["onpromotion"].to_numpy(np.float32)[ok])

    tiendas_ord = sorted(series["store_nbr"].unique())
    fila_tienda = pd.Series(range(len(tiendas_ord)), index=tiendas_ord)
    trx_m = _Matriz(fecha0, n_fechas, len(tiendas_ord))
    trx = datos["transacciones"]
    ok = trx["store_nbr"].isin(fila_tienda.index).to_numpy()
    trx_m.poner(
        fila_tienda.loc[trx["store_nbr"][ok]].to_numpy(),
        trx["date"][ok],
        trx["transactions"].to_numpy(np.float32)[ok],
    )

    petroleo = datos["petroleo"].set_index("date")["dcoilwtico"].reindex(ejes).ffill()
    petroleo_m = _Matriz(fecha0, n_fechas, 1)
    petroleo_m.v[0, _MARGEN_IZQ : _MARGEN_IZQ + n_fechas] = petroleo.to_numpy(np.float32)
    # El forward-fill llena también el relleno derecho, pero ninguna feature lo lee (≤ O - 1).

    hay = ~np.isnan(ventas_m.v)
    primera_venta = np.where(hay.any(axis=1), np.argmax(hay, axis=1), np.iinfo(np.int32).max)

    # --- atributos estáticos y feriados
    tiendas_u = tiendas.drop_duplicates("store_nbr").reset_index(drop=True)
    est = series.merge(tiendas_u[["store_nbr", "city", "state", "type", "cluster"]], on="store_nbr")
    # el calendario llega TOPE días más allá del último día objetivo para ver el próximo feriado
    dias_cal = pd.date_range(
        fecha0 - pd.Timedelta(days=TOPE_DIAS_FERIADO), fecha1 + pd.Timedelta(days=TOPE_DIAS_FERIADO)
    )
    flags, combo_de = _flags_feriados(datos["feriados"], tiendas_u, dias_cal)
    combo_serie = series["store_nbr"].map(combo_de).to_numpy()
    cats = {
        "store_nbr": sorted(tiendas_u["store_nbr"].unique()),
        "family": familias,
        "city": sorted(tiendas_u["city"].unique()),
        "state": sorted(tiendas_u["state"].unique()),
        "type": sorted(tiendas_u["type"].unique()),
        "cluster": sorted(tiendas_u["cluster"].unique()),
    }
    hs = np.arange(1, h_max + 1)
    partes = []
    for o in origenes_ts:
        i = ventas_m.col(o)
        activas = np.flatnonzero(primera_venta < i)
        if activas.size == 0:
            continue
        v = ventas_m.v[activas]
        w = {k: v[:, i - k : i] for k in (28, 56, 364)}  # ventana que termina en O - 1
        cols: dict[str, np.ndarray] = {}
        for k in LAGS:
            cols[f"lag_{k}"] = v[:, i - k]
        for k in MEDIAS:
            cols[f"media_{k}"] = _nanstat(np.nanmean, w[56][:, -k:], 1)
        cols["mediana_28"] = _nanstat(np.nanmedian, w[28], 1)
        cols["desv_28"] = _nanstat(np.nanstd, w[28], 1)
        validos = np.sum(~np.isnan(w[28]), axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            cols["prop_ceros_28"] = np.sum(w[28] == 0, axis=1) / validos
        con_venta = np.nan_to_num(w[364], nan=0.0) > 0
        desde = np.argmax(con_venta[:, ::-1], axis=1) + 1
        cols["dias_desde_venta"] = np.where(con_venta.any(axis=1), desde, w[364].shape[1] + 1)

        # media del mismo día de semana que el día objetivo, hasta O - 1
        sem = np.ceil(hs / 7).astype(int)  # semanas hacia atrás hasta caer en ≤ O - 1
        desp = (hs - 1)[:, None] - 7 * (sem[:, None] + np.arange(8)[None, :])
        mismo = v[:, i + desp]  # (series, h, 8)
        cols["media_dds_4"] = _nanstat(np.nanmean, mismo[:, :, :4], 2)
        cols["media_dds_8"] = _nanstat(np.nanmean, mismo, 2)

        # promociones
        p = promo_m.v[activas]
        objetivo_p = p[:, i : i + h_max].copy()
        objetivo_p[:, hs - 1 > anticipacion] = np.nan
        cols["onpromotion"] = objetivo_p
        cols["promo_media_28"] = _nanstat(np.nanmean, p[:, i - 28 : i], 1)

        # petróleo y transacciones (nivel tienda → serie)
        pet = petroleo_m.v[0]
        cols["petroleo"] = np.full(len(activas), pet[i - 1], np.float32)
        with np.errstate(invalid="ignore", divide="ignore"):
            cols["petroleo_cambio_28"] = np.full(len(activas), pet[i - 1] / pet[i - 29] - 1)
        t_tienda = _nanstat(np.nanmean, trx_m.v[:, i - lag_trx - 27 : i - lag_trx + 1], 1)
        cols["trx_media_28"] = t_tienda[fila_tienda.loc[series["store_nbr"].to_numpy()[activas]]]

        # calendario y feriados del día objetivo
        fechas_obj = o + pd.to_timedelta(hs - 1, unit="D")
        cal = {
            "dia_semana": fechas_obj.day_of_week,
            "dia_mes": fechas_obj.day,
            "mes": fechas_obj.month,
            "semana_anio": fechas_obj.isocalendar().week.to_numpy(),
            "es_quincena": (fechas_obj.day == 15) | fechas_obj.is_month_end,
        }
        for nombre, valor in cal.items():
            cols[nombre] = np.broadcast_to(np.asarray(valor, np.float32), (len(activas), h_max))
        offs = (fechas_obj - dias_cal[0]).days.to_numpy()
        nombres_f = ["es_feriado", "es_puente", "es_dia_laboral_extra", "es_evento",
                     "dias_al_feriado", "dias_desde_feriado"]  # fmt: skip
        for j, nombre in enumerate(nombres_f):
            cols[nombre] = flags[combo_serie[activas][:, None], j, offs[None, :]]

        # a formato largo: (series × h)
        n_a = len(activas)
        datos_o = {
            nombre: np.broadcast_to(a.reshape(n_a, -1), (n_a, h_max)).astype(np.float32).ravel()
            for nombre, a in cols.items()
        }
        df = pd.DataFrame(datos_o)
        df.insert(0, "h", np.tile(hs, n_a).astype(np.int16))
        df.insert(0, "fecha_objetivo", np.tile(fechas_obj.to_numpy(), n_a))
        df.insert(0, "origen", o)
        df.insert(0, "family", series["family"].to_numpy()[activas].repeat(h_max))
        df.insert(0, "store_nbr", series["store_nbr"].to_numpy()[activas].repeat(h_max))
        if con_objetivo:
            df["y"] = ventas_m.v[activas][:, i : i + h_max].ravel()
        partes.append(df)

    if not partes:
        raise ValueError("ningún origen tiene series con historia")
    out = pd.concat(partes, ignore_index=True)
    est = est.set_index(["store_nbr", "family"])
    llaves = pd.MultiIndex.from_frame(out[["store_nbr", "family"]])
    for c in ("city", "state", "type", "cluster"):
        out[c] = est[c].reindex(llaves).to_numpy()
    for c in CATEGORICAS:
        out[c] = pd.Categorical(out[c], categories=cats[c])
    return out
