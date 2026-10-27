"""Configuración del modelo (`config/model.yaml`) y del negocio (`config/business.yaml`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reposicion.config import cargar_yaml
from reposicion.fuentes import ConfigFuentes, cargar_fuentes


class ConfigBacktest(BaseModel):
    n_origenes: int = Field(8, ge=1)
    paso_dias: int = Field(7, ge=1)


class ReglaCeros(BaseModel):
    dias_sin_ventas: int = Field(56, ge=1)


class ConfigModelo(BaseModel):
    horizonte_dias: int = Field(14, ge=1)
    dia_corte: int = Field(0, ge=0, le=6)
    cuantiles_reporte: list[float]
    ventana_origenes_semanas: int = Field(52, ge=1)
    semilla: int = 2017
    backtest: ConfigBacktest = ConfigBacktest()
    ventana_features_dias: int = Field(364, ge=1)
    regla_ceros: ReglaCeros = ReglaCeros()

    @model_validator(mode="after")
    def _cuantiles_validos(self) -> ConfigModelo:
        if not self.cuantiles_reporte or any(not 0 < q < 1 for q in self.cuantiles_reporte):
            raise ValueError("cuantiles_reporte debe tener valores en (0, 1)")
        return self


class GrupoCosto(BaseModel):
    c_quiebre: float = Field(gt=0)
    c_merma: float = Field(gt=0)
    familias: list[str] = []


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


@dataclass(frozen=True)
class Configs:
    """Todas las configuraciones que necesitan features, modelos, backtest y pedido."""

    modelo: ConfigModelo
    negocio: ConfigNegocio
    fuentes: ConfigFuentes


def cargar_modelo(ruta: str | Path) -> ConfigModelo:
    return ConfigModelo.model_validate(cargar_yaml(ruta))


def cargar_negocio(ruta: str | Path) -> ConfigNegocio:
    return ConfigNegocio.model_validate(cargar_yaml(ruta))


def cargar_configs(dir_config: str | Path) -> Configs:
    d = Path(dir_config)
    return Configs(
        cargar_modelo(d / "model.yaml"),
        cargar_negocio(d / "business.yaml"),
        cargar_fuentes(d / "sources.yaml"),
    )
