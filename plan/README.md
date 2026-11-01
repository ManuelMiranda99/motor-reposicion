# Plan — Laboratorio 1: Motor de Reposición de Inventario

Plan para completar el Laboratorio 1 de Product Development (Git + DVC + Airflow 3 sobre los datos de
Corporación Favorita). Es la guía de trabajo y no reemplaza al `DECISIONES.md` que se entrega: ese
archivo se escribirá a partir de lo que se defina aquí.

## Índice

| Archivo | Contenido |
|---|---|
| [01-decisiones-base.md](01-decisiones-base.md) | Decisiones ya tomadas (remoto, horizonte, modelo, etc.) y supuestos |
| [02-arquitectura.md](02-arquitectura.md) | Estructura del repo, capas de datos, imagen Docker, flujo Git/DVC |
| [03-datos-y-bandeja.md](03-datos-y-bandeja.md) | Disponibilidad en el tiempo (as-of), simulador de bandeja, validación, correcciones |
| [04-modelado-y-negocio.md](04-modelado-y-negocio.md) | Baseline, LightGBM por cuantiles, backtest, pedido newsvendor, criterio de reemplazo |
| [05-airflow.md](05-airflow.md) | DAGs, Assets, idempotencia, backfill, reprocesamiento |
| [06-fases-y-checklist.md](06-fases-y-checklist.md) | Hoja de ruta por fases/PRs con checklist de entregables |
| [07-riesgos-y-pendientes.md](07-riesgos-y-pendientes.md) | Riesgos, preguntas abiertas y cosas por confirmar con el equipo docente |

## Resumen en una página

- **Producto:** cada lunes (fecha de corte) entrega, por tienda × familia (54 × 33 = 1,782 series):
  1. un pronóstico diario a **14 días** con cuantiles (P10, P50, P90 y el cuantil crítico de cada familia);
  2. un **pedido sugerido** (newsvendor), con costos de quiebre y de merma en `config/business.yaml`;
  3. un **reporte de desempeño** de los pronósticos ya publicados contra las ventas reales que van llegando.
- **Stack:** Python 3.11 · pip + `requirements.txt` en `.venv` · pandas/pyarrow · pandera · LightGBM ·
  pytest · Airflow 3 (Docker Compose, LocalExecutor) · DVC con remoto en **Cloudflare R2** (antes DagsHub) · GitHub Actions.
- **Regla de oro:** toda la lógica vive en `src/reposicion/`, con pruebas, y los DAGs solo orquestan.
  Toda lectura de datos pasa por una función *as-of* que solo ve lo que ya había llegado en la fecha
  de corte.
- **Bandeja:** mientras el equipo docente no la publique, un simulador propio genera una a partir de
  Kaggle, con llegadas tardías, huecos y correcciones. La bandeja se monta **read-only** en Docker.
- **Trazabilidad:** cada corte publicado deja un manifiesto (commit de Git + hashes DVC de entradas,
  modelo y salidas). La última tarea del DAG hace `dvc add` / `dvc push` y un commit de los `.dvc`.
