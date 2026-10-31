"""Configuración de las fuentes de datos (`config/sources.yaml`) y su regla de disponibilidad."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from reposicion.config import cargar_yaml

TipoColumna = Literal["fecha", "entero", "texto", "decimal", "booleano"]
SIEMPRE_DISPONIBLE = date(1900, 1, 1)


class DisponibilidadHistorica(BaseModel):
    """Cuándo se considera disponible una fila de la carga histórica."""

    tipo: Literal["dias", "trimestre_anticipado", "siempre"]
    dias: int = 0
    trimestres: int = Field(0, ge=0)


class ConfigFuente(BaseModel):
    columnas: dict[str, TipoColumna]
    llave: list[str]
    no_negativas: list[str] = []
    nulos_permitidos: list[str] = []
    snapshot: bool = False
    disponibilidad_historica: DisponibilidadHistorica
    lag_esperado_dias: int | None = None
    # Anticipación máxima física: `fecha_dato + lag_minimo_dias <= fecha_entrega`. Un archivo que
    # describe un día posterior a lo que su entrega permite ("dato del futuro") va a cuarentena.
    # `None` = sin regla (promociones, feriados y maestro se publican por adelantado).
    lag_minimo_dias: int | None = None
    tolerancia_retraso_dias: int = Field(0, ge=0)
    imprescindible: bool = False

    @model_validator(mode="after")
    def _columnas_conocidas(self) -> ConfigFuente:
        conocidas = set(self.columnas)
        for campo in ("llave", "no_negativas", "nulos_permitidos"):
            faltan = set(getattr(self, campo)) - conocidas
            if faltan:
                raise ValueError(f"{campo} usa columnas inexistentes: {sorted(faltan)}")
        return self


class ConfigBandeja(BaseModel):
    variable_entorno: str
    ruta_defecto: str
    patron_carpeta: str
    patron_archivo: str
    prefijo_ignorado: str = "_"


class ConfigFuentes(BaseModel):
    fecha_carga_historica: date
    bandeja: ConfigBandeja
    fuentes: dict[str, ConfigFuente]


def cargar_fuentes(ruta: str | Path) -> ConfigFuentes:
    return ConfigFuentes.model_validate(cargar_yaml(ruta))


def inicio_trimestre(fecha_dato: date) -> date:
    """Primer día del trimestre calendario de `fecha_dato`."""
    return date(fecha_dato.year, 3 * ((fecha_dato.month - 1) // 3) + 1, 1)


def fecha_disponible_historica(cfg: ConfigFuente, fecha_dato: date) -> date:
    """Fecha en que el dato histórico habría estado disponible según la regla de su fuente.

    En `feriados`, `fecha_dato` es el inicio del trimestre que cubre el archivo.
    """
    regla = cfg.disponibilidad_historica
    if regla.tipo == "siempre":
        return SIEMPRE_DISPONIBLE
    if regla.tipo == "dias":
        return fecha_dato + timedelta(days=regla.dias)
    inicio = pd.Period(inicio_trimestre(fecha_dato), freq="Q") - regla.trimestres
    return inicio.start_time.date()
