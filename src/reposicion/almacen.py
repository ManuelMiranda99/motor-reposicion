"""Almacén limpio: todas las versiones válidas de cada fuente con su `fecha_disponible`.

Se reconstruye de forma determinista desde la carga histórica + el ledger + `data/raw`, así que
reconstruir N veces da los mismos bytes.

Layout bajo `dir_data`: `historico/<fuente>.csv`, `raw/<fecha_entrega>/<archivo>`,
`ledger/ingesta.parquet` y `limpio/<fuente>.parquet`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from reposicion.fuentes import ConfigFuente, ConfigFuentes, fecha_disponible_historica
from reposicion.io import SIEMPRE_DISPONIBLE, escribir_parquet
from reposicion.validacion import convertir_tipos, leer_texto

COLUMNAS_TECNICAS = ["fecha_dato", "fecha_disponible", "version", "origen"]


def ruta_ledger(dir_data: Path) -> Path:
    return Path(dir_data) / "ledger" / "ingesta.parquet"


def ruta_limpio(dir_data: Path, fuente: str) -> Path:
    return Path(dir_data) / "limpio" / f"{fuente}.parquet"


def leer_parquet(ruta: Path) -> pd.DataFrame:
    """Lee un parquet del proyecto con las fechas como datetime64[ns]."""
    df = pq.read_table(ruta).to_pandas(date_as_object=False)
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype("datetime64[ns]")
    return df


def leer_ledger(dir_data: Path) -> pd.DataFrame:
    """Lee el ledger de ingesta. Lanza `FileNotFoundError` si todavía no existe."""
    return leer_parquet(ruta_ledger(dir_data))


def _tipado(ruta: Path, cfg: ConfigFuente) -> pd.DataFrame:
    texto = leer_texto(ruta)
    faltan = [c for c in cfg.columnas if c not in texto.columns]
    if faltan:
        raise ValueError(f"{ruta}: columnas ausentes {faltan}")
    datos, errores = convertir_tipos(texto[list(cfg.columnas)], cfg)
    if errores:
        raise ValueError(f"{ruta}: {'; '.join(errores)}")
    return datos


def _historico(dir_data: Path, fuente: str, cfg: ConfigFuente) -> pd.DataFrame:
    datos = _tipado(Path(dir_data) / "historico" / f"{fuente}.csv", cfg)
    if fuente == "tiendas":
        fecha_dato = pd.Series(SIEMPRE_DISPONIBLE, index=datos.index)
    elif fuente == "feriados":
        fecha_dato = datos["date"].dt.to_period("Q").dt.start_time
    else:
        fecha_dato = datos["date"]
    unicas = pd.Series(fecha_dato.unique())
    disponible = {f: pd.Timestamp(fecha_disponible_historica(cfg, f.date())) for f in unicas}
    datos["fecha_dato"] = fecha_dato
    datos["fecha_disponible"] = fecha_dato.map(disponible)
    datos["version"] = 0
    datos["origen"] = "historico"
    return datos


def _bandeja(
    dir_data: Path, fuente: str, cfg: ConfigFuente, ledger: pd.DataFrame
) -> list[pd.DataFrame]:
    validos = ledger[(ledger["fuente"] == fuente) & (ledger["estado"] == "valido")]
    partes = []
    for fila in validos.itertuples():
        datos = _tipado(Path(dir_data) / "raw" / fila.archivo, cfg)
        datos["fecha_dato"] = fila.fecha_dato
        datos["fecha_disponible"] = fila.fecha_entrega
        datos["version"] = int(fila.version)
        datos["origen"] = "bandeja"
        partes.append(datos)
    return partes


def reconstruir_limpio(dir_data: Path, cfg_fuentes: ConfigFuentes) -> None:
    """Reconstruye `data/limpio/<fuente>.parquet` para todas las fuentes."""
    dir_data = Path(dir_data)
    ledger = leer_ledger(dir_data) if ruta_ledger(dir_data).exists() else None
    for fuente, cfg in cfg_fuentes.fuentes.items():
        partes = [_historico(dir_data, fuente, cfg)]
        if ledger is not None:
            partes += _bandeja(dir_data, fuente, cfg, ledger)
        todo = pd.concat(partes, ignore_index=True)
        todo = todo.sort_values(["fecha_dato", "version", *cfg.llave], kind="stable")
        escribir_parquet(todo.reset_index(drop=True), ruta_limpio(dir_data, fuente))


@lru_cache(maxsize=8)
def _leer_cacheado(ruta: str, mtime_ns: int) -> pd.DataFrame:
    return leer_parquet(Path(ruta))


def leer_limpio(dir_data: Path, fuente: str) -> pd.DataFrame:
    """Lee el almacén limpio de una fuente (con caché por ruta y mtime; el resultado no depende
    de ella). Devuelve una vista: modificarla no altera la caché."""
    ruta = ruta_limpio(dir_data, fuente)
    return _leer_cacheado(str(ruta), ruta.stat().st_mtime_ns).copy(deep=False)
