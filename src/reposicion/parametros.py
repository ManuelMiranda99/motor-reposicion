"""Configuración del modelo (`config/model.yaml`) y del negocio (`config/business.yaml`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reposicion.config import cargar_yaml
from reposicion.fuentes import ConfigFuentes, cargar_fuentes
from reposicion.validacion import ConfigValidacion, cargar_validacion

MEDIANA = 0.5  # cuantil de la predicción puntual (WAPE, RMSLE, sesgo)


class ConfigBacktest(BaseModel):
    n_origenes: int = Field(8, ge=1)
    paso_dias: int = Field(7, ge=1)


class ReglaCeros(BaseModel):
    dias_sin_ventas: int = Field(56, ge=1)


class ConfigLightGBM(BaseModel):
    """Parámetros de LightGBM (sin bagging ni early stopping: reentrenar es determinista)."""

    learning_rate: float = Field(0.05, gt=0)
    num_leaves: int = Field(63, ge=2)
    min_data_in_leaf: int = Field(100, ge=1)
    feature_fraction: float = Field(0.8, gt=0, le=1)
    lambda_l2: float = Field(1.0, ge=0)
    num_boost_round: int = Field(400, ge=1)
    num_threads: int = Field(4, ge=1)
    deterministic: bool = True
    force_row_wise: bool = True
    seed: int = 2017
    verbose: int = -1


class ConfigLightGBMSemanal(BaseModel):
    """Sobrescrituras de `lightgbm` para la variante de demanda semanal (muchas menos filas)."""

    num_leaves: int = Field(31, ge=2)
    min_data_in_leaf: int = Field(50, ge=1)
    num_boost_round: int = Field(300, ge=1)


class ConfigModelo(BaseModel):
    horizonte_dias: int = Field(14, ge=1)
    dia_corte: int = Field(0, ge=0, le=6)
    cuantiles_reporte: list[float]
    ventana_origenes_semanas: int = Field(52, ge=1)
    semilla: int = 2017
    backtest: ConfigBacktest = ConfigBacktest()
    ventana_features_dias: int = Field(364, ge=1)
    # Días del año ("MM-DD") sin operación normal (Navidad, Año Nuevo): sus ventas no son demanda.
    # Las features los tratan como faltantes y los rezagos usan el último día con operación.
    dias_sin_operacion: list[str] = []
    regla_ceros: ReglaCeros = ReglaCeros()
    objetivo_transformado: Literal["log1p"] = "log1p"
    lightgbm: ConfigLightGBM = ConfigLightGBM()
    lightgbm_semanal: ConfigLightGBMSemanal = ConfigLightGBMSemanal()

    @model_validator(mode="after")
    def _cuantiles_validos(self) -> ConfigModelo:
        if not self.cuantiles_reporte or any(not 0 < q < 1 for q in self.cuantiles_reporte):
            raise ValueError("cuantiles_reporte debe tener valores en (0, 1)")
        if not any(abs(q - MEDIANA) < 1e-9 for q in self.cuantiles_reporte):
            raise ValueError(
                f"cuantiles_reporte debe incluir la mediana {MEDIANA}: WAPE, RMSLE, sesgo y el "
                "seguimiento se calculan sobre q0.50"
            )
        for d in self.dias_sin_operacion:
            try:
                datetime.strptime(f"2000-{d}", "%Y-%m-%d")
            except ValueError as e:
                raise ValueError(f"dias_sin_operacion: {d!r} no es un 'MM-DD' válido") from e
        return self


def cuantil_critico(c_quiebre: float, c_merma: float) -> float:
    """τ = c_quiebre / (c_quiebre + c_merma), redondeado a 2 decimales.

    El redondeo hace que el modelo se entrene exactamente en el cuantil que usa el pedido.
    """
    return round(c_quiebre / (c_quiebre + c_merma), 2)


class GrupoCosto(BaseModel):
    c_quiebre: float = Field(gt=0)
    c_merma: float = Field(gt=0)
    familias: list[str] = []

    @model_validator(mode="after")
    def _tau_valido(self) -> GrupoCosto:
        tau = cuantil_critico(self.c_quiebre, self.c_merma)
        if not 0 < tau < 1:
            raise ValueError(
                f"c_quiebre={self.c_quiebre} y c_merma={self.c_merma} dan un cuantil crítico "
                f"τ={tau} tras el redondeo a 2 decimales; debe quedar en (0, 1)"
            )
        return self


class ConfigNegocio(BaseModel):
    cobertura_dias: int = Field(7, ge=1)
    lead_time_dias: int = Field(0, ge=0)
    inventario_inicial: float = Field(0, ge=0)
    redondeo: Literal["entero_arriba", "entero_cercano"] = "entero_arriba"
    grupos: dict[str, GrupoCosto]

    @model_validator(mode="after")
    def _grupos_validos(self) -> ConfigNegocio:
        if "default" not in self.grupos:
            raise ValueError("grupos debe incluir el grupo 'default'")
        if self.grupos["default"].familias:
            raise ValueError("el grupo 'default' no lista familias: toma todas las demás")
        vistas: dict[str, str] = {}
        for nombre, grupo in self.grupos.items():
            for familia in grupo.familias:
                if familia in vistas:
                    raise ValueError(f"la familia {familia!r} está en {vistas[familia]} y {nombre}")
                vistas[familia] = nombre
        return self


class ConfigPromocion(BaseModel):
    """Criterio de reemplazo champion/challenger (`config/promotion.yaml`)."""

    costo_total_baja_min: float = Field(0.03, ge=0)
    wape_empeora_max: float = Field(0.01, ge=0)
    cobertura_p10_p90: tuple[float, float] = (0.70, 0.90)
    familia_volumen_min: float = Field(0.05, ge=0, le=1)
    familia_costo_empeora_max: float = Field(0.10, ge=0)
    checks_tecnicos: bool = True
    reentrenamiento: Literal["mensual_primer_lunes", "semanal", "manual"] = "mensual_primer_lunes"


class ConfigAlerta(BaseModel):
    """Alerta de degradación (solo advertencia): WAPE móvil vs WAPE del backtest del champion."""

    ventana_cortes: int = Field(4, ge=1)
    min_dias_con_real: int = Field(7, ge=1)
    umbral_degradacion: float = Field(0.20, ge=0)


class ConfigMonitoreo(BaseModel):
    """Seguimiento y revisiones (`config/monitoreo.yaml`)."""

    reemitir_si_corrige: bool = True
    alerta: ConfigAlerta = ConfigAlerta()


@dataclass(frozen=True)
class Configs:
    """Todas las configuraciones que necesitan features, modelos, backtest, pedido y publicación."""

    modelo: ConfigModelo
    negocio: ConfigNegocio
    fuentes: ConfigFuentes
    validacion: ConfigValidacion = field(default_factory=ConfigValidacion)
    promocion: ConfigPromocion = field(default_factory=ConfigPromocion)
    monitoreo: ConfigMonitoreo = field(default_factory=ConfigMonitoreo)

    def __post_init__(self) -> None:
        # La cobertura del pedido debe caber en el horizonte pronosticado; si no, el pedido
        # se truncaría en silencio.
        n = self.negocio
        if n.lead_time_dias + n.cobertura_dias > self.modelo.horizonte_dias:
            raise ValueError(
                f"lead_time_dias ({n.lead_time_dias}) + cobertura_dias ({n.cobertura_dias}) "
                f"supera horizonte_dias ({self.modelo.horizonte_dias}): el pedido no cabría "
                "en el pronóstico"
            )


def cargar_modelo(ruta: str | Path) -> ConfigModelo:
    return ConfigModelo.model_validate(cargar_yaml(ruta))


def cargar_negocio(ruta: str | Path) -> ConfigNegocio:
    return ConfigNegocio.model_validate(cargar_yaml(ruta))


def cargar_promocion(ruta: str | Path) -> ConfigPromocion:
    return ConfigPromocion.model_validate(cargar_yaml(ruta))


def cargar_monitoreo(ruta: str | Path) -> ConfigMonitoreo:
    return ConfigMonitoreo.model_validate(cargar_yaml(ruta))


def cargar_configs(dir_config: str | Path) -> Configs:
    d = Path(dir_config)
    return Configs(
        cargar_modelo(d / "model.yaml"),
        cargar_negocio(d / "business.yaml"),
        cargar_fuentes(d / "sources.yaml"),
        cargar_validacion(d / "validation.yaml"),
        cargar_promocion(d / "promotion.yaml"),
        cargar_monitoreo(d / "monitoreo.yaml"),
    )
