"""Configuración de la operación con Airflow (`config/operacion.yaml`).

Las fechas de inicio y fin del periodo operado se pueden sobrescribir con las variables de entorno
`REPOSICION_INICIO` y `REPOSICION_FIN` (las define el `.env` del compose).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

from reposicion.config import cargar_yaml


class Autor(BaseModel):
    nombre: str
    correo: str


class ConfigOperacion(BaseModel):
    inicio: date
    fin: date
    push_remoto: Literal["auto", "siempre", "nunca"] = "auto"
    rama_publicaciones: str = "publicaciones"
    remoto_dvc: str = "r2"
    directorios_dvc: list[str]
    autor: Autor

    @model_validator(mode="after")
    def _periodo_valido(self) -> ConfigOperacion:
        if self.fin < self.inicio:
            raise ValueError(f"fin ({self.fin}) es anterior a inicio ({self.inicio})")
        return self


def cargar_operacion(ruta: str | Path, env: Mapping[str, str] | None = None) -> ConfigOperacion:
    """Carga `operacion.yaml`; las variables de entorno no vacías sobrescriben inicio y fin."""
    env = os.environ if env is None else env
    datos = dict(cargar_yaml(ruta))
    for clave, variable in (("inicio", "REPOSICION_INICIO"), ("fin", "REPOSICION_FIN")):
        valor = (env.get(variable) or "").strip()
        if valor:
            datos[clave] = date.fromisoformat(valor)
    return ConfigOperacion(**datos)


def es_primer_lunes(corte: date) -> bool:
    """¿`corte` es el primer lunes de su mes? (día de reentrenamiento programado)."""
    return corte.weekday() == 0 and corte.day <= 7


def ultimo_primer_lunes(corte: date) -> date:
    """Último primer lunes del mes que no es posterior a `corte` (el reentrenamiento vigente)."""
    anio, mes = corte.year, corte.month
    for _ in range(2):
        primero = date(anio, mes, 1)
        lunes = date(anio, mes, 1 + (7 - primero.weekday()) % 7)
        if lunes <= corte:
            return lunes
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    raise AssertionError("inalcanzable")  # el primer lunes del mes anterior siempre es <= corte
