"""Validación de archivos de la bandeja con pandas puro.

Reglas duras (errores) mandan el archivo a cuarentena; las blandas (advertencias) solo se registran.
Los archivos se leen como texto (`dtype=str, keep_default_na=False`) para que `N/A` y los vacíos no
se conviertan en NaN sin que lo decidamos nosotros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from reposicion.config import cargar_yaml
from reposicion.fuentes import ConfigFuente, ConfigFuentes, inicio_trimestre

MAX_EJEMPLOS = 5


class ModoDegradadoCfg(BaseModel):
    max_dias_sin_ventas: int = Field(3, ge=0)
    ventana_huecos_dias: int = Field(28, ge=1)


class ConfigValidacion(BaseModel):
    modo_degradado: ModoDegradadoCfg = ModoDegradadoCfg()
    completitud_min_ventas: float | None = Field(None, gt=0, le=1)
    # Un snapshot del maestro de tiendas que omite tiendas del maestro vigente se rechaza (suele
    # ser un archivo incremental o truncado, no una baja real).
    tiendas_permitir_bajas: bool = False


def cargar_validacion(ruta: str | Path) -> ConfigValidacion:
    return ConfigValidacion.model_validate(cargar_yaml(ruta))


@dataclass
class ResultadoValidacion:
    valido: bool
    errores: list[str] = field(default_factory=list)  # reglas duras → cuarentena
    advertencias: list[str] = field(default_factory=list)  # reglas blandas → solo registro
    datos: pd.DataFrame | None = None  # tipado, solo si es válido
    filas: int = 0


def leer_texto(ruta: str | Path) -> pd.DataFrame:
    """Lee un CSV como texto puro. Lanza `ValueError` si está vacío o es ilegible."""
    try:
        return pd.read_csv(ruta, dtype=str, keep_default_na=False)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as e:
        raise ValueError(f"archivo ilegible: {e}") from e


def _ejemplos(valores: pd.Series) -> str:
    return ", ".join(repr(v) for v in valores.unique()[:MAX_EJEMPLOS])


def _convertir(serie: pd.Series, tipo: str, nulo_ok: bool) -> tuple[pd.Series, pd.Series]:
    """Convierte una columna de texto. Devuelve (valores, máscara de valores inválidos)."""
    vacio = serie.str.strip() == ""
    if tipo == "fecha":
        v = pd.to_datetime(serie, format="%Y-%m-%d", errors="coerce")
        malo = v.isna() & ~vacio
    elif tipo in ("entero", "decimal"):
        v = pd.to_numeric(serie, errors="coerce")
        malo = (v.isna() & ~vacio) | (v.notna() & ~np.isfinite(v))
        if tipo == "entero":
            malo = malo | (v.notna() & (v != np.floor(v.where(v.notna(), 0))))
    elif tipo == "booleano":
        v = serie.str.strip().str.lower().map({"true": True, "false": False})
        malo = v.isna() & ~vacio
    else:
        v = serie
        malo = pd.Series(False, index=serie.index)
    if not nulo_ok:
        malo = malo | vacio
    return v, malo


def convertir_tipos(texto: pd.DataFrame, cfg: ConfigFuente) -> tuple[pd.DataFrame, list[str]]:
    """Tipa las columnas de `cfg` desde texto. Devuelve (datos, errores de conversión)."""
    errores: list[str] = []
    salida: dict[str, pd.Series] = {}
    for col, tipo in cfg.columnas.items():
        v, malo = _convertir(texto[col], tipo, col in cfg.nulos_permitidos)
        if malo.any():
            errores.append(
                f"columna '{col}': {int(malo.sum())} valores no convertibles a {tipo} "
                f"(ej.: {_ejemplos(texto[col][malo])})"
            )
            continue
        if tipo == "entero":
            v = v.astype("int64")
        elif tipo == "decimal":
            v = v.astype("float64")
        elif tipo == "booleano":
            v = v.astype(bool)
        salida[col] = v
    if errores:
        return pd.DataFrame(), errores
    return pd.DataFrame(salida), []


def validar_archivo(
    texto: pd.DataFrame,
    fuente: str,
    fecha_dato: date,
    cfg: ConfigFuentes,
    tiendas_validas: set[int],
    familias_validas: set[str],
    completitud_min: float | None = None,
    fecha_entrega: date | None = None,
    permitir_bajas_tiendas: bool = False,
) -> ResultadoValidacion:
    """Valida un archivo leído como texto. `datos` solo viene si no hay errores.

    Con `fecha_entrega` aplica la regla de "dato del futuro" (`lag_minimo_dias` de la fuente).
    Para `tiendas`, `tiendas_validas` es el maestro vigente: el snapshot no puede omitir tiendas
    salvo que `permitir_bajas_tiendas`.
    """
    fcfg = cfg.fuentes[fuente]
    if len(texto) == 0:
        return ResultadoValidacion(False, errores=["archivo vacío (sin filas)"])
    faltan = [c for c in fcfg.columnas if c not in texto.columns]
    if faltan:
        return ResultadoValidacion(False, errores=[f"columnas requeridas ausentes: {faltan}"])
    advertencias: list[str] = []
    extra = [c for c in texto.columns if c not in fcfg.columnas]
    if extra:
        advertencias.append(f"columnas extra descartadas: {extra}")

    datos, errores = convertir_tipos(texto[list(fcfg.columnas)], fcfg)
    if errores:
        return ResultadoValidacion(False, errores, advertencias)

    if (
        fecha_entrega is not None
        and fcfg.lag_minimo_dias is not None
        and fecha_dato + timedelta(days=fcfg.lag_minimo_dias) > fecha_entrega
    ):
        errores.append(
            f"fecha_dato {fecha_dato} posterior a lo que permite la entrega del {fecha_entrega} "
            f"(lag mínimo {fcfg.lag_minimo_dias} día(s)): dato del futuro"
        )

    if "date" in datos.columns:
        ref = pd.Timestamp(fecha_dato)
        if fuente == "feriados":
            inicio = pd.Period(inicio_trimestre(fecha_dato), freq="Q")
            fuera = (datos["date"] < inicio.start_time) | (datos["date"] >= (inicio + 1).start_time)
        else:
            fuera = datos["date"] != ref
        if fuera.any():
            errores.append(
                f"{int(fuera.sum())} filas con 'date' fuera de {fecha_dato} "
                f"(ej.: {_ejemplos(datos['date'][fuera].dt.date)})"
            )

    dup = datos.duplicated(subset=fcfg.llave, keep=False)
    if dup.any():
        errores.append(f"{int(dup.sum())} filas con llave {fcfg.llave} duplicada")

    for col in fcfg.no_negativas:
        neg = datos[col] < 0
        if neg.any():
            errores.append(f"columna '{col}': {int(neg.sum())} valores negativos")

    if fuente != "tiendas" and "store_nbr" in datos.columns:
        desconocidas = sorted(set(datos["store_nbr"]) - tiendas_validas)
        if desconocidas:
            errores.append(f"store_nbr desconocido(s) en el maestro vigente: {desconocidas}")
    if "family" in datos.columns:
        desconocidas = sorted(set(datos["family"]) - familias_validas)
        if desconocidas:
            errores.append(f"family desconocida(s): {desconocidas[:MAX_EJEMPLOS]}")

    if fuente == "tiendas" and not permitir_bajas_tiendas:
        omitidas = sorted(tiendas_validas - set(datos["store_nbr"]))
        if omitidas:
            errores.append(
                f"el maestro omite {len(omitidas)} tienda(s) del maestro vigente "
                f"(ej.: {omitidas[:MAX_EJEMPLOS]}): ¿archivo incremental o truncado?"
            )

    # Reglas blandas.
    if fuente == "ventas":
        esperadas = len(tiendas_validas) * len(familias_validas)
        if len(datos) < esperadas:
            msg = f"ventas incompletas: {len(datos)} de {esperadas} filas (tiendas × familias)"
            if completitud_min is not None and len(datos) / esperadas < completitud_min:
                errores.append(f"{msg}; mínimo exigido {completitud_min:.0%}")
            else:
                advertencias.append(msg)
        total = datos.groupby("store_nbr")["sales"].sum()
        cerradas = sorted(int(s) for s in total[total == 0].index)
        if cerradas:
            advertencias.append(f"tiendas con ventas totales en 0 (¿cerradas?): {cerradas}")
    if fuente == "petroleo" and datos["dcoilwtico"].isna().any():
        advertencias.append("petróleo sin valor (día no hábil)")

    if errores:
        return ResultadoValidacion(False, errores, advertencias, filas=len(datos))
    return ResultadoValidacion(True, [], advertencias, datos, len(datos))
