# 05 — Orquestación con Airflow 3

## DAGs

| DAG | Schedule | Tareas (cada una llama a `reposicion.*`) | Produce (Asset) |
|---|---|---|---|
| `ingest_validate` | `@daily`, `catchup=True` | `scan_bandeja` → `ingest_new_files` (branch por fuente) → `validate` → `quarantine_invalid` → `update_ledger` → `detect_corrections` | `asset://clean_data`, `asset://corrections` |
| `prepare_features` | Asset `clean_data` + cron del lunes | `build_clean_tables(asof=T)` → `build_features(T)` | `asset://features` |
| `forecast_order` | semanal, lunes `0 6 * * 1`, `catchup=True` | `check_inputs_ready` (sensor/short-circuit) → `load_champion` → `predict_quantiles` → `build_order` → `sanity_checks` → `publish` → `version_outputs` (dvc add/push + commit a `publicaciones`) | `asset://published_forecast` |
| `monitor_performance` | `@daily` + Asset `corrections` | `collect_actuals_asof` → `score_published` (para cada corte con horizonte ya observado) → `update_report` → `version_outputs` | `asset://monitoring` |
| `train_evaluate` | mensual + manual | `build_training_set` → `backtest_baseline` / `backtest_lgbm` (en paralelo) → `compare` → `promote_if_better` → `version_model` | `asset://champion` |
| `reprocess_corrections` | Asset `corrections` | `affected_cutoffs` → re-features → (opcional) re-emitir `revision=2` → re-monitoreo | — |

> Airflow 3: se usan `airflow.sdk` (`@dag`, `@task`, `Asset`), el `api-server` (que reemplaza al
> webserver) y el `dag-processor` separado. En `logical_date` / `data_interval_end` está la fecha de
> corte, y **nunca** se usa `datetime.now()` dentro de la lógica.

## Idempotencia (requisito explícito)

- Toda tarea recibe la **fecha de corte** como parámetro y escribe en una **partición determinista**
  (`cutoff=YYYY-MM-DD`).
- Las escrituras son atómicas: primero a `*.tmp` y luego `os.replace`. Re-ejecutar sobrescribe la
  misma partición con el mismo contenido.
- La ingesta se deduplica por `sha256`: el mismo archivo dos veces equivale a una sola fila en el
  ledger.
- Semillas fijas (`seed`, `deterministic=True`, `num_threads` fijo en LightGBM) para que re-entrenar
  dé exactamente el mismo modelo.
- `version_outputs` hace commit solo si cambió algo. Con un `dvc add` sin cambios, git no tiene nada
  que commitear y el paso es no-op.
- La publicación es inmutable: si `published/cutoff=T/` ya existe con el mismo `manifest.inputs_hash`,
  la tarea es no-op. Si cambiaron las entradas, se trata como corrección (revision), no como
  sobrescritura.
- **Prueba de idempotencia** en `tests/integration`: correr el pipeline dos veces y comparar los
  hashes de todas las salidas.

## Backfill

- `catchup=True` + `start_date=2017-01-02` (primer lunes de la bandeja simulada).
- `airflow dags backfill forecast_order --start-date ... --end-date ...` produce todos los cortes,
  y cada uno ve solo `asof(T)`. **Esto debe funcionar aunque la bandeja ya tenga datos "del futuro"**,
  justamente porque se filtra por `fecha_disponible`.
- `max_active_runs=1` en `forecast_order` y `monitor_performance` para respetar el orden temporal y
  evitar choques en git/DVC. También un `pool` `dvc_git` de tamaño 1 para todas las tareas
  `version_outputs`.

## Fallas vs. situaciones esperadas

- Datos inválidos → la tarea `validate` deja el archivo en cuarentena. Si es imprescindible para el
  corte, `check_inputs_ready` falla con un mensaje claro; si no, el corte continúa en modo degradado.
- Situaciones esperadas (fin de semana sin petróleo, tienda cerrada, transacciones atrasadas, feriado)
  → nunca se lanza una excepción.
- Retries: 2, con backoff, solo para I/O (DVC push, git push). La lógica de datos no reintenta.
- Si `dvc push` o `git push` fallan, por ejemplo porque el docente no tiene credenciales, **no** se
  rompe el pronóstico: queda commit/cache local y un warning (configurable con `push_remoto: auto`).

## Evidencia a capturar (entregable)

- Capturas de la vista Grid de los 5 DAGs con un backfill completo en verde.
- Captura de un run con un archivo en cuarentena (falla controlada) y uno con una corrección
  reprocesada.
- Se guardan en `reports/evidencia/` (por DVC o como imágenes pequeñas en git; ver 07).
