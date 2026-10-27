# 01 — Decisiones base

## Decisiones tomadas por ti

| # | Tema | Decisión | Alternativas descartadas | Motivo |
|---|---|---|---|---|
| D1 | Remoto DVC | **DagsHub** (S3-compatible, ligado al repo) | S3/GCS, Google Drive | Acceso simple para los docentes; Drive suele fallar con OAuth |
| D2 | Cadencia / horizonte | **Corte semanal (lunes), horizonte 14 días** | 7 o 16 días | 7 días de cobertura del pedido + margen para el lead time |
| D3 | Modelo ML | **LightGBM global por cuantiles** | statsforecast, deep learning | Rápido en CPU, estándar para este dataset, da cuantiles nativos |
| D4 | Bandeja | **Simulador propio** mientras llega la oficial | — | No bloquear el desarrollo; luego solo se adapta el lector |
| D5 | Equipo | **1 persona** | — | Igual se trabaja con ramas, PRs y `main` protegida |
| D6 | Dependencias | **pip + `requirements.txt`**, en un `.venv` local (`python -m venv`) | uv, Poetry | Tu preferencia; no tocar el Python global |
| D7 | Persistencia de publicaciones | **Airflow hace `dvc add` / `dvc push` + commit** del `.dvc` y del manifiesto | solo `dvc.yaml`, híbrido | Cada corte queda ligado a un commit y a hashes de datos |

## Decisiones que propongo yo (puedes cambiarlas)

| # | Tema | Propuesta | Por qué |
|---|---|---|---|
| P1 | Python | 3.11 (el que tienes en asdf), con la misma versión en la imagen de Airflow | Evita diferencias entre el entorno local y Docker |
| P2 | Formato interno | Parquet (pyarrow) particionado por fuente y fecha | Rápido, tipado y con escrituras atómicas por partición |
| P3 | Validación | **pandera** (esquemas en código, testeables con pytest) | Más liviano que Great Expectations |
| P4 | Ejecutor Airflow | **LocalExecutor** con Postgres, sin Celery ni Redis | Menos RAM; suficiente para 1,782 series |
| P5 | Fechas de los archivos de prueba | Los datos van de 2013-01-01 a 2017-08-15. **Carga histórica ≤ 2016-12-31; bandeja simulada 2017-01-01 → 2017-08-15** | Deja ~32 cortes semanales para operar y hacer backfill |
| P6 | Cuantiles | P10, P50, P90 + el cuantil crítico de cada grupo de costos | Dan la incertidumbre y el pedido directamente |
| P7 | Linter | ruff (format + lint) en CI, junto con pytest | Barato y mantiene el código limpio |
| P8 | Monitoreo | Reporte en Parquet + HTML/Markdown estático por corte, sin MLflow | Menos infraestructura; MLflow es opcional al final |
| P9 | Commits desde Airflow | A una rama dedicada **`publicaciones`**, no a `main` (que está protegida) | No rompe la protección de `main` y deja un historial auditable |

## Supuestos explícitos (van a DECISIONES.md)

- **Sin datos de inventario.** El pedido sugerido equivale a la demanda objetivo de la cobertura
  (stock inicial = 0), y queda un parámetro `inventario_inicial` preparado para el futuro.
- **Lead time configurable** (`lead_time_dias`, por defecto 0): el pedido cubre los días
  `[corte + lead_time + 1, corte + lead_time + 7]`.
- **`sales` es demanda observada.** Las ventas con quiebre de stock están censuradas; se documenta
  como limitación.
- `test.csv` y `sample_submission.csv` **no se usan**, tal como pide el enunciado.
