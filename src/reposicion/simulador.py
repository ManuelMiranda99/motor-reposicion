"""Simulador del sistema de origen (bandeja) a partir de los CSV de Kaggle.

Genera dos salidas:

- **Carga histórica**: un CSV consolidado por fuente con todo lo que ya había sido entregado en
  `fecha_carga_historica` (se aplica la misma regla de entrega que en la bandeja).
- **Bandeja**: `<bandeja>/<fecha_entrega>/<fuente>_<fecha_dato>.csv`, un archivo por fecha y fuente,
  más los escenarios configurados (faltantes, tardíos, correcciones, duplicados e inválidos) y un
  `_escenarios.csv` que los documenta. Los archivos que empiezan con `_` no son datos del sistema
  de origen.

Todo es determinista: la aleatoriedad de cada archivo depende solo de (semilla, fuente, fecha_dato),
así que ampliar `hasta` agrega entregas sin alterar las ya generadas.
"""

from __future__ import annotations

import os
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator

from reposicion.config import cargar_yaml

ARCHIVO_ESCENARIOS = "_escenarios.csv"
TIENDA_DESCONOCIDA = 999

FuenteDatos = Literal["ventas", "promociones", "transacciones", "petroleo"]
Defecto = Literal[
    "ventas_negativas",
    "columna_faltante",
    "filas_duplicadas",
    "tienda_desconocida",
    "tipo_invalido",
]

# Columna de valor de cada fuente (la que se corrige o corrompe).
VALOR = {
    "ventas": "sales",
    "promociones": "onpromotion",
    "transacciones": "transactions",
    "petroleo": "dcoilwtico",
}
DECIMALES = {"sales": 3, "dcoilwtico": 2}  # el resto de columnas de valor son enteras


# --------------------------------------------------------------------------- configuración


class VentasCfg(BaseModel):
    lag_dias: int = Field(1, ge=0)


class PromocionesCfg(BaseModel):
    anticipacion_dias: int = Field(10, ge=0)


class TransaccionesCfg(BaseModel):
    lag_min_dias: int = Field(1, ge=0)
    lag_max_dias: int = Field(3, ge=0)

    @model_validator(mode="after")
    def _rango(self) -> TransaccionesCfg:
        if self.lag_min_dias > self.lag_max_dias:
            raise ValueError("lag_min_dias no puede ser mayor que lag_max_dias")
        return self


class PetroleoCfg(BaseModel):
    lag_dias: int = Field(1, ge=0)


class FeriadosCfg(BaseModel):
    anticipacion_trimestres: int = Field(1, ge=0)


class FuentesCfg(BaseModel):
    ventas: VentasCfg = VentasCfg()
    promociones: PromocionesCfg = PromocionesCfg()
    transacciones: TransaccionesCfg = TransaccionesCfg()
    petroleo: PetroleoCfg = PetroleoCfg()
    feriados: FeriadosCfg = FeriadosCfg()


class Faltante(BaseModel):
    fuente: FuenteDatos
    fecha_dato: date


class Tardio(BaseModel):
    fuente: FuenteDatos
    fecha_dato: date
    fecha_entrega: date


class Correccion(BaseModel):
    fuente: FuenteDatos
    fecha_dato: date
    fecha_entrega: date
    fraccion_filas: float = Field(0.05, gt=0, le=1)
    factor: float = Field(1.3, gt=0)


class Duplicado(BaseModel):
    fuente: FuenteDatos
    fecha_dato: date
    fecha_entrega: date


class Invalido(BaseModel):
    fuente: FuenteDatos
    fecha_dato: date
    defecto: Defecto
    correccion_entrega: date | None = None

    @model_validator(mode="after")
    def _defecto_aplicable(self) -> Invalido:
        if self.defecto == "tienda_desconocida" and self.fuente == "petroleo":
            raise ValueError("petroleo no tiene store_nbr: no aplica 'tienda_desconocida'")
        return self


class Escenarios(BaseModel):
    faltantes: list[Faltante] = []
    tardios: list[Tardio] = []
    correcciones: list[Correccion] = []
    duplicados: list[Duplicado] = []
    invalidos: list[Invalido] = []


class ConfigSimulador(BaseModel):
    semilla: int
    fecha_carga_historica: date
    hasta: date | None = None
    fuentes: FuentesCfg = FuentesCfg()
    tiendas_nuevas: dict[int, date] = {}
    escenarios: Escenarios = Escenarios()


def cargar_config(ruta: str | Path) -> ConfigSimulador:
    return ConfigSimulador.model_validate(cargar_yaml(ruta))


# --------------------------------------------------------------------------- entregas


@dataclass(frozen=True)
class Entrega:
    """Un archivo que el sistema de origen deposita (o debió depositar) en la bandeja."""

    fuente: str
    fecha_dato: str  # ISO; en feriados es el inicio del trimestre que cubre el archivo
    fecha_entrega: date
    tipo: str = "normal"  # normal | faltante | invalido | reentrega | correccion | duplicado
    escenario: str = ""
    detalle: str = ""
    defecto: str | None = None
    fraccion: float | None = None
    factor: float | None = None

    @property
    def nombre(self) -> str:
        return f"{self.fuente}_{self.fecha_dato}.csv"


def _fecha(iso: str) -> date:
    return date.fromisoformat(iso)


def _trimestre(fechas: pd.Series) -> pd.Series:
    """Clave de trimestre (fecha ISO de inicio) para cada fecha."""
    periodos = pd.PeriodIndex(pd.to_datetime(fechas), freq="Q")
    return pd.Series(
        [p.start_time.date().isoformat() for p in periodos], index=fechas.index, dtype=object
    )


def _clave(fuente: str, df: pd.DataFrame) -> pd.Series:
    """Fecha_dato de cada fila: la fecha, o el trimestre en feriados."""
    return _trimestre(df["date"]) if fuente == "feriados" else df["date"]


def _rng(semilla: int, etiqueta: str, fecha_dato: str) -> np.random.Generator:
    return np.random.default_rng(
        [semilla, zlib.crc32(etiqueta.encode()), int(fecha_dato.replace("-", ""))]
    )


def cargar_kaggle(
    directorio: str | Path, tiendas_nuevas: dict[int, date]
) -> dict[str, pd.DataFrame]:
    """Lee los CSV de Kaggle y los separa en las fuentes del sistema de origen.

    Las filas de tiendas nuevas anteriores a su fecha de alta se eliminan: antes del alta la tienda
    no existe para el sistema de origen.
    """
    d = Path(directorio)
    train = pd.read_csv(d / "train.csv", dtype={"date": str, "family": str}).drop(columns="id")
    datos = {
        "ventas": train[["date", "store_nbr", "family", "sales"]],
        "promociones": train[["date", "store_nbr", "family", "onpromotion"]],
        "transacciones": pd.read_csv(d / "transactions.csv", dtype={"date": str}),
        "petroleo": pd.read_csv(d / "oil.csv", dtype={"date": str}),
        "feriados": pd.read_csv(d / "holidays_events.csv", dtype={"date": str}),
        "tiendas": pd.read_csv(d / "stores.csv"),
    }
    for fuente in ("ventas", "promociones", "transacciones"):
        df = datos[fuente]
        antes_de_alta = pd.Series(False, index=df.index)
        for tienda, alta in tiendas_nuevas.items():
            antes_de_alta |= (df["store_nbr"] == tienda) & (df["date"] < alta.isoformat())
        datos[fuente] = df[~antes_de_alta].reset_index(drop=True)
    return datos


def _entregas_normales(
    datos: dict[str, pd.DataFrame], cfg: ConfigSimulador
) -> dict[tuple[str, str], Entrega]:
    f = cfg.fuentes
    normales: dict[tuple[str, str], Entrega] = {}

    def agregar(fuente: str, fecha_dato: str, entrega: date) -> None:
        normales[(fuente, fecha_dato)] = Entrega(fuente, fecha_dato, entrega)

    for d in datos["ventas"]["date"].unique():
        agregar("ventas", d, _fecha(d) + timedelta(days=f.ventas.lag_dias))
    for d in datos["promociones"]["date"].unique():
        agregar("promociones", d, _fecha(d) - timedelta(days=f.promociones.anticipacion_dias))
    for d in datos["transacciones"]["date"].unique():
        lag = int(
            _rng(cfg.semilla, "transacciones:lag", d).integers(
                f.transacciones.lag_min_dias, f.transacciones.lag_max_dias + 1
            )
        )
        agregar("transacciones", d, _fecha(d) + timedelta(days=lag))
    for d in datos["petroleo"]["date"].unique():
        agregar("petroleo", d, _fecha(d) + timedelta(days=f.petroleo.lag_dias))
    for q in _trimestre(datos["feriados"]["date"]).unique():
        anticipado = pd.Period(q, freq="Q") - f.feriados.anticipacion_trimestres
        agregar("feriados", q, anticipado.start_time.date())
    for alta in sorted(set(cfg.tiendas_nuevas.values())):
        agregar("tiendas", alta.isoformat(), alta)
    return normales


def programar_entregas(datos: dict[str, pd.DataFrame], cfg: ConfigSimulador) -> list[Entrega]:
    """Calendario completo de entregas (normales + escenarios), ordenado por fecha de entrega."""
    normales = _entregas_normales(datos, cfg)
    esc = cfg.escenarios
    extras: list[Entrega] = []

    def clave(fuente: str, fecha_dato: date) -> tuple[str, str]:
        k = (fuente, fecha_dato.isoformat())
        if k not in normales:
            raise ValueError(f"Escenario sobre una entrega inexistente: {fuente} {fecha_dato}")
        return k

    for x in esc.faltantes:
        k = clave(x.fuente, x.fecha_dato)
        normales[k] = replace(
            normales[k], tipo="faltante", escenario="faltante", detalle="nunca se entrega"
        )
    for x in esc.tardios:
        k = clave(x.fuente, x.fecha_dato)
        e = normales[k]
        normales[k] = replace(
            e,
            fecha_entrega=x.fecha_entrega,
            escenario="tardio",
            detalle=f"entrega esperada {e.fecha_entrega.isoformat()}",
        )
    for x in esc.invalidos:
        k = clave(x.fuente, x.fecha_dato)
        normales[k] = replace(
            normales[k], tipo="invalido", escenario="invalido", detalle=x.defecto, defecto=x.defecto
        )
        if x.correccion_entrega is not None:
            extras.append(
                Entrega(
                    x.fuente,
                    k[1],
                    x.correccion_entrega,
                    tipo="reentrega",
                    escenario="reentrega_valida",
                    detalle=f"reemplaza archivo con {x.defecto}",
                )
            )
    for x in esc.correcciones:
        k = clave(x.fuente, x.fecha_dato)
        extras.append(
            Entrega(
                x.fuente,
                k[1],
                x.fecha_entrega,
                tipo="correccion",
                escenario="correccion",
                detalle=f"fraccion_filas={x.fraccion_filas} factor={x.factor}",
                fraccion=x.fraccion_filas,
                factor=x.factor,
            )
        )
    for x in esc.duplicados:
        k = clave(x.fuente, x.fecha_dato)
        extras.append(
            Entrega(
                x.fuente,
                k[1],
                x.fecha_entrega,
                tipo="duplicado",
                escenario="duplicado_identico",
                detalle="mismo contenido que la entrega original",
            )
        )

    entregas = list(normales.values()) + extras
    for e in entregas:
        if e.escenario and e.fecha_entrega <= cfg.fecha_carga_historica:
            raise ValueError(
                f"Escenario '{e.escenario}' de {e.fuente} {e.fecha_dato} cae dentro de la carga "
                f"histórica ({e.fecha_entrega} <= {cfg.fecha_carga_historica})"
            )
    repetidas = Counter(
        (e.fuente, e.fecha_dato, e.fecha_entrega) for e in entregas if e.tipo != "faltante"
    )
    choques = [k for k, n in repetidas.items() if n > 1]
    if choques:
        raise ValueError(f"Dos entregas del mismo archivo en el mismo día: {choques}")
    return sorted(entregas, key=lambda e: (e.fecha_entrega, e.fuente, e.fecha_dato, e.tipo))


# --------------------------------------------------------------------------- contenido


def _aplicar_correccion(
    df: pd.DataFrame, fuente: str, fraccion: float, factor: float, rng: np.random.Generator
) -> pd.DataFrame:
    col = VALOR[fuente]
    df = df.copy()
    candidatos = np.flatnonzero(df[col].fillna(0).to_numpy() > 0)
    if len(candidatos) == 0:
        return df
    k = max(1, round(fraccion * len(candidatos)))
    idx = np.sort(rng.choice(candidatos, size=k, replace=False))
    nuevos = df[col].to_numpy(dtype=float)[idx] * factor
    if col in DECIMALES:
        df.loc[idx, col] = np.round(nuevos, DECIMALES[col])
    else:
        df.loc[idx, col] = np.round(nuevos).astype(df[col].dtype)
    return df


def _aplicar_defecto(
    df: pd.DataFrame, fuente: str, defecto: str, rng: np.random.Generator
) -> pd.DataFrame:
    col = VALOR[fuente]
    df = df.copy()

    def filas(k: int) -> np.ndarray:
        return np.sort(rng.choice(len(df), size=min(k, len(df)), replace=False))

    if defecto == "ventas_negativas":
        i = filas(10)
        df.loc[i, col] = -(df.loc[i, col].abs() + 1)
    elif defecto == "columna_faltante":
        df = df.drop(columns=col)
    elif defecto == "filas_duplicadas":
        df = pd.concat([df, df.iloc[filas(20)]], ignore_index=True)
    elif defecto == "tienda_desconocida":
        df.loc[filas(5), "store_nbr"] = TIENDA_DESCONOCIDA
    elif defecto == "tipo_invalido":
        df[col] = df[col].astype(object)
        df.loc[filas(5), col] = "N/A"
    else:
        raise ValueError(f"Defecto desconocido: {defecto}")
    return df


def _contenido(base: pd.DataFrame, e: Entrega, semilla: int) -> pd.DataFrame:
    if e.tipo == "correccion":
        rng = _rng(semilla, f"{e.fuente}:correccion", e.fecha_dato)
        return _aplicar_correccion(base, e.fuente, e.fraccion, e.factor, rng)
    if e.tipo == "invalido":
        rng = _rng(semilla, f"{e.fuente}:{e.defecto}", e.fecha_dato)
        return _aplicar_defecto(base, e.fuente, e.defecto, rng)
    return base


def _tiendas_vigentes(
    tiendas: pd.DataFrame, nuevas: dict[int, date], al: date | None
) -> pd.DataFrame:
    """Maestro de tiendas tal como existía en `al` (None = antes de cualquier alta)."""
    excluir = [t for t, alta in nuevas.items() if al is None or alta > al]
    return tiendas[~tiendas["store_nbr"].isin(excluir)].reset_index(drop=True)


def _escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    df.to_csv(tmp, index=False, lineterminator="\n")
    os.replace(tmp, ruta)


# --------------------------------------------------------------------------- generación


def generar(
    dir_kaggle: str | Path,
    cfg: ConfigSimulador,
    dir_historico: str | Path,
    dir_bandeja: str | Path,
) -> dict[str, int]:
    """Genera la carga histórica y la bandeja. Devuelve un resumen con conteos."""
    dir_historico, dir_bandeja = Path(dir_historico), Path(dir_bandeja)
    datos = cargar_kaggle(dir_kaggle, cfg.tiendas_nuevas)
    entregas = programar_entregas(datos, cfg)
    carga = cfg.fecha_carga_historica

    # Carga histórica: todo lo entregado hasta la fecha de carga, consolidado por fuente.
    en_historico: dict[str, set[str]] = defaultdict(set)
    for e in entregas:
        if e.fecha_entrega <= carga:
            en_historico[e.fuente].add(e.fecha_dato)
    for fuente in ("ventas", "promociones", "transacciones", "petroleo", "feriados"):
        df = datos[fuente]
        _escribir_csv(
            df[_clave(fuente, df).isin(en_historico[fuente])].reset_index(drop=True),
            dir_historico / f"{fuente}.csv",
        )
    altas_previas = [a for a in cfg.tiendas_nuevas.values() if a <= carga]
    _escribir_csv(
        _tiendas_vigentes(datos["tiendas"], cfg.tiendas_nuevas, max(altas_previas, default=None)),
        dir_historico / "tiendas.csv",
    )

    # Bandeja: un archivo por entrega posterior a la carga (y hasta `hasta`, si se indicó).
    en_bandeja = [
        e
        for e in entregas
        if e.fecha_entrega > carga and (cfg.hasta is None or e.fecha_entrega <= cfg.hasta)
    ]
    necesarias: dict[str, set[str]] = defaultdict(set)
    for e in en_bandeja:
        if e.tipo != "faltante":
            necesarias[e.fuente].add(e.fecha_dato)
    grupos: dict[str, dict[str, pd.DataFrame]] = {}
    for fuente, claves in necesarias.items():
        if fuente == "tiendas":
            continue
        df = datos[fuente]
        k = _clave(fuente, df)
        sub = df[k.isin(claves)]
        grupos[fuente] = {
            fecha: g.reset_index(drop=True) for fecha, g in sub.groupby(k[k.isin(claves)])
        }

    escritos = 0
    for e in en_bandeja:
        if e.tipo == "faltante":
            continue
        if e.fuente == "tiendas":
            base = _tiendas_vigentes(datos["tiendas"], cfg.tiendas_nuevas, _fecha(e.fecha_dato))
        else:
            base = grupos[e.fuente][e.fecha_dato]
        destino = dir_bandeja / e.fecha_entrega.isoformat() / e.nombre
        _escribir_csv(_contenido(base, e, cfg.semilla), destino)
        escritos += 1

    escenarios = pd.DataFrame(
        [
            {
                "fuente": e.fuente,
                "fecha_dato": e.fecha_dato,
                "fecha_entrega": e.fecha_entrega.isoformat(),
                "escenario": e.escenario,
                "detalle": e.detalle,
            }
            for e in en_bandeja
            if e.escenario
        ],
        columns=["fuente", "fecha_dato", "fecha_entrega", "escenario", "detalle"],
    )
    _escribir_csv(escenarios, dir_bandeja / ARCHIVO_ESCENARIOS)

    return {
        "archivos_bandeja": escritos,
        "dias_entrega": len({e.fecha_entrega for e in en_bandeja if e.tipo != "faltante"}),
        "escenarios": len(escenarios),
        "filas_historico_ventas": int(datos["ventas"]["date"].isin(en_historico["ventas"]).sum()),
    }
