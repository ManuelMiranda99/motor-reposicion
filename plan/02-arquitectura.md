# 02 — Arquitectura

## Estructura del repositorio

```
lab-1/                              # raíz del repo GitHub
├── CLAUDE.md                       # reglas del proyecto para el agente (requisito 1)
├── README.md                       # levantar y ejecutar desde cero (requisito 5)
├── DECISIONES.md                   # decisiones, alternativas y justificación (requisito 5)
├── requirements.txt                # deps de runtime (fijadas con ==)
├── requirements-dev.txt            # pytest, ruff, pandera[...]; incluye -r requirements.txt
├── pyproject.toml                  # solo config de pytest/ruff y paquete instalable (pip install -e .)
├── docker/
│   └── Dockerfile                  # FROM apache/airflow:3.x.y-python3.11 + git + dvc + requirements
├── docker-compose.yaml             # Airflow 3: postgres, api-server, scheduler, dag-processor, triggerer
├── .env.example                    # AIRFLOW_UID, BANDEJA_PATH, DAGSHUB_TOKEN, GIT_*...
├── config/
│   ├── business.yaml               # costos de quiebre/merma por familia o grupo, lead time, cobertura
│   ├── model.yaml                  # horizonte, cuantiles, hiperparámetros, features
│   ├── validation.yaml             # umbrales de reglas duras/blandas
│   ├── sources.yaml                # fuentes, patrón de archivo, frecuencia, lag esperado
│   └── promotion.yaml              # criterio de reemplazo champion/challenger
├── src/reposicion/                 # TODA la lógica
│   ├── config.py                   # carga y valida los YAML (pydantic)
│   ├── io.py                       # escrituras atómicas (tmp + rename), rutas por partición
│   ├── ingest/                     # leer bandeja → raw/ con ledger de versiones
│   ├── validate/                   # esquemas pandera + reglas de negocio
│   ├── asof.py                     # vista "lo que se sabía en la fecha T"
│   ├── features/                   # lags, rolling, calendario, feriados, petróleo, promos
│   ├── models/                     # baseline.py, lgbm.py, interfaz común fit/predict_quantiles
│   ├── backtest.py                 # rolling-origin, métricas, comparación
│   ├── order.py                    # newsvendor → pedido sugerido
│   ├── monitor.py                  # pronóstico publicado vs real, métricas por corte
│   ├── registry.py                 # champion/challenger, manifiesto de publicaciones
│   └── versioning.py               # wrappers dvc add/push + git commit (usados por Airflow)
├── dags/                           # solo orquestación (importan reposicion.*)
├── tools/
│   └── simulate_bandeja.py         # genera la bandeja simulada a partir de Kaggle
├── tests/
│   ├── unit/                       # por módulo
│   ├── integration/                # mini-pipeline end-to-end con datos sintéticos pequeños
│   └── test_dags.py                # DagBag importa sin errores, sin ciclos
├── data/                           # TODO bajo DVC (gitignored salvo los .dvc)
│   ├── historico/                  # carga histórica inicial (raw, inmutable)
│   ├── raw/                        # copia ingerida de la bandeja, por fuente/fecha/versión
│   ├── ledger/                     # registro de ingesta: archivo, hash, fecha_dato, fecha_recibido, estado
│   ├── processed/                  # tablas limpias + features por corte
│   ├── models/                     # modelos entrenados por versión + champion.json
│   ├── published/cutoff=YYYY-MM-DD/  # forecast.parquet, order.parquet, manifest.json
│   └── monitoring/                 # métricas acumuladas + reportes
├── reports/                        # comparación de modelos, evidencias (capturas de Airflow)
└── .github/workflows/ci.yml        # ruff + pytest en cada PR
```

> Los CSV de Kaggle que hoy están en `store-sales-time-series-forecasting/` se mueven a
> `data/kaggle/` (bajo DVC). Son solo el insumo del simulador, no del producto. El PDF del
> enunciado se agrega a `.gitignore`.

## Capas de datos

```
bandeja (externa, RO) ──ingest──▶ raw/ + ledger ──validate──▶ processed/clean
                                                          │
                                       asof(corte) ◀──────┘
                                           │
                               features ──▶ modelo champion ──▶ forecast (cuantiles)
                                                                    │
                                                    business.yaml ─▶ order
                                                                    │
                                                    published/cutoff=… ──▶ monitor (vs reales)
```

- **raw/** nunca se sobrescribe: una corrección se guarda como versión nueva (`v2`) y el ledger
  apunta a cuál es la vigente según la fecha de recepción.
- **published/** también es inmutable. Si se reemite un corte por correcciones, queda como
  `revision=2` y el original se conserva.

## Docker / Airflow 3

- Se parte del `docker-compose.yaml` oficial de Airflow 3 y se recorta a LocalExecutor (sin
  Redis/Celery ni flower).
- Imagen propia: `apache/airflow:3.x.y-python3.11` (versión fijada) más `git`, `dvc[s3]` y
  `pip install -r requirements.txt`.
- Volúmenes:
  - `./dags`, `./src`, `./config` → código.
  - `./data` → workspace DVC (lectura/escritura).
  - `${BANDEJA_PATH}` → `/opt/bandeja:ro`. **Read-only**, así queda garantizado que la bandeja nunca
    se modifica.
  - El repo completo se monta para que DVC y git operen desde dentro del contenedor.
- Secretos en `.env` (no se versiona): token de DagsHub y token de GitHub (o deploy key) para hacer
  push a la rama `publicaciones`.

## Flujo Git

- `main` protegida: exige PR, CI en verde y nada de force-push. Al trabajar solo, no se exige
  aprobación de otra persona, solo el check de CI.
- Ramas `feat/<tema>`, una por fase (ver 06). Merge por squash.
- Rama `publicaciones`: solo la escribe Airflow (manifiestos + `.dvc` de los cortes publicados).
- Tag final `entrega-lab1` sobre `main`.

## Flujo DVC

- `dvc remote add -d origin s3://dvc` con endpoint de DagsHub. Las credenciales van en
  `.dvc/config.local` (no se versiona).
- Bajo DVC: `data/kaggle`, `data/historico`, `data/raw`, `data/processed`, `data/models`,
  `data/published`, `data/monitoring`.
- **Reproducir un corte pasado:** `git checkout <commit del manifiesto>` → `dvc pull` →
  `python -m reposicion.cli reproduce --cutoff 2017-05-01`, y se comparan los hashes contra
  `manifest.json`. Esto queda como prueba de integración y como sección del README.
