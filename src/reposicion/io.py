"""Escritura determinista y atómica de parquet.

Dos ejecuciones con el mismo DataFrame producen bytes idénticos: esquema explícito, sin metadatos
de pandas y compresión fija.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Fecha centinela para datos "siempre disponibles" (en lugar de `date.min`).
SIEMPRE_DISPONIBLE = pd.Timestamp("1900-01-01")


def _tipo_arrow(serie: pd.Series) -> pa.DataType:
    dtype = serie.dtype
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return pa.date32()
    if pd.api.types.is_bool_dtype(dtype):
        return pa.bool_()
    if pd.api.types.is_integer_dtype(dtype):
        return pa.int64()
    if pd.api.types.is_float_dtype(dtype):
        return pa.float64()
    return pa.string()


def esquema_de(df: pd.DataFrame) -> pa.Schema:
    """Esquema explícito derivado de los dtypes: fechas → date32, enteros → int64, etc."""
    return pa.schema([pa.field(c, _tipo_arrow(df[c])) for c in df.columns])


def escribir_parquet(df: pd.DataFrame, ruta: str | Path) -> None:
    """Escribe `df` en `ruta` de forma determinista y atómica (archivo temporal + `os.replace`)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    esquema = esquema_de(df)
    tabla = pa.Table.from_pandas(
        df,
        preserve_index=False,
        schema=pa.schema(
            [
                pa.field(f.name, pa.timestamp("ns") if pa.types.is_date32(f.type) else f.type)
                for f in esquema
            ]
        ),
    ).cast(esquema)
    tabla = tabla.replace_schema_metadata(None)
    tmp = ruta.with_name(ruta.name + ".tmp")
    pq.write_table(tabla, tmp, compression="zstd")
    os.replace(tmp, ruta)
