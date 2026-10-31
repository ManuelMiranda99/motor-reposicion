"""Helpers mínimos de los DAGs: fecha de corte, rutas y argumentos comunes.

Los DAGs solo orquestan: toda la lógica vive en `reposicion` (ver `reposicion.orquestacion`).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from airflow.sdk import get_current_context

from reposicion import orquestacion, rutas, versionado
from reposicion.operacion import ConfigOperacion

POOL = "escritura_datos"  # una sola tarea a la vez escribe en data/, DVC o git

OPERACION: ConfigOperacion = orquestacion.configuracion_operacion()

# Periodo operado: los DAGs hacen catchup entre estas fechas (REPOSICION_INICIO / REPOSICION_FIN).
START_DATE = datetime.combine(OPERACION.inicio, time.min, tzinfo=UTC)
END_DATE = datetime.combine(OPERACION.fin, time(23, 59, 59), tzinfo=UTC)

# Las tareas de lógica no se reintentan; solo las de I/O remoto (dvc push / git push).
ARGUMENTOS = {"retries": 0}
ARGUMENTOS_REMOTO = {"retries": 2, "retry_delay": timedelta(minutes=1)}


def corte() -> date:
    """Fecha de corte = fecha de `logical_date` del run (en Airflow 3 con cron es el disparo)."""
    logical_date = get_current_context().get("logical_date")
    if logical_date is None:
        raise ValueError("el run no tiene logical_date: dispáralo indicando la fecha de corte")
    return logical_date.date()


def dir_data() -> Path:
    return rutas.dir_data()


def bandeja() -> Path:
    return rutas.dir_bandeja()


def config() -> Path:
    return orquestacion.dir_config()


def versionar(evento: str) -> str | None:
    """`dvc add` + commit en la rama de publicaciones para el corte del run."""
    c = corte()
    registro = orquestacion.registro_evento(evento, c, dir_data())
    return versionado.versionar(evento, c, rutas.dir_repo(), OPERACION, registro)


def publicar_remoto() -> dict[str, str]:
    """`dvc push` y `git push` según `push_remoto` (sin credenciales: warning, no falla)."""
    return versionado.publicar_remoto(rutas.dir_repo(), OPERACION)
