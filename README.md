# Motor de Reposición de Inventario

Laboratorio 1 — Product Development (Maestría en Data Science, Universidad Galileo).

Producto de ML que, cada semana (fecha de corte: lunes), transforma los datos de ventas que llegan
diariamente en:

1. un **pronóstico diario a 14 días** por tienda × familia, con cuantiles;
2. un **pedido sugerido** derivado del pronóstico y de los costos de quiebre y de merma
   (`config/business.yaml`);
3. un **reporte de seguimiento** de los pronósticos publicados contra las ventas reales.

Se basa en los datos de Corporación Favorita ([Kaggle — Store Sales](https://www.kaggle.com/competitions/store-sales-time-series-forecasting/data)).

> 🚧 En construcción. La sección "Operar con Airflow" explica cómo levantar el producto con Docker;
> "Reproducir un pronóstico publicado" se completará en la fase 8.

## Requisitos

- Python 3.11
- Docker + Docker Compose (para Airflow)
- Git y DVC

## Desarrollo local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -e .
ruff check . && pytest
```

## Datos (DVC + DagsHub)

Los datos, modelos y pronósticos se versionan con DVC; el remoto es
[DagsHub](https://dagshub.com/ManuelMiranda99/motor-reposicion). Aunque el repositorio es público,
**DagsHub exige iniciar sesión para cualquier descarga**, así que se necesita un token (gratis):

1. Crear una cuenta en [dagshub.com](https://dagshub.com) (se puede entrar con GitHub).
2. Copiar el token en <https://dagshub.com/user/settings/tokens>.
3. Configurarlo y descargar los datos (el token queda solo en `.dvc/config.local`, fuera de git):

```bash
source .venv/bin/activate
./tools/dvc_auth.sh      # pide el token sin mostrarlo en pantalla
dvc pull
```

| Ruta | Contenido |
|---|---|
| `data/kaggle/` | CSV originales de Kaggle (insumo del simulador de bandeja) |
| `data/historico/` | Carga histórica inicial: todo lo entregado hasta 2017-01-01, un CSV por fuente |
| `bandeja_sim/` | Bandeja simulada: `<fecha_entrega>/<fuente>_<fecha_dato>.csv` (2017-01-02 → 2017-09-01) |

### Regenerar la carga histórica y la bandeja simulada

`dvc pull` ya las trae. Para regenerarlas (son deterministas, `config/simulador.yaml`):

```bash
python tools/simulate_bandeja.py --limpiar                     # completa
python tools/simulate_bandeja.py --limpiar --hasta 2017-06-30  # bandeja parcial (luego se puede ampliar)
```

Los escenarios inyectados (faltantes, tardíos, correcciones, duplicados, inválidos) quedan listados
en `bandeja_sim/_escenarios.csv`.

### Ingesta (bandeja → almacén limpio)

```bash
python -m reposicion.cli ingestar --hasta 2017-09-01   # idempotente; repetirlo no cambia nada
```

Copia a `data/raw/` cada archivo nuevo de la bandeja (que es de solo lectura), lo valida y lo
registra en el **ledger** `data/ledger/ingesta.parquet` (hash, versión, estado `valido` /
`cuarentena` / `duplicado`, correcciones y llegadas tardías). Con los válidos reconstruye
`data/limpio/<fuente>.parquet`, que se consulta con `reposicion.asof.asof(fuente, corte, dir_data)`:
exactamente lo que se sabía en la fecha de corte.

### Backtest de un modelo

```bash
python -m reposicion.cli backtest --modelo baseline --corte 2017-08-14
```

Entrena y evalúa con rolling-origin (los últimos 8 lunes cuyos 14 días ya se conocen en el corte;
cada origen entrena con las 52 semanas anteriores) y escribe
`data/backtest/<modelo>/corte=<corte>/predicciones.parquet` y `metricas.parquet` (WAPE, RMSLE,
pinball, cobertura P10–P90 y, sobre el pedido, costo newsvendor, fill rate y % de merma). Los
costos, la cobertura y el lead time del pedido están en `config/business.yaml`; el horizonte, los
cuantiles y la ventana de entrenamiento, en `config/model.yaml`.

### Modelos: entrenar, comparar y pronosticar (fase 5)

LightGBM necesita OpenMP. En macOS: `brew install libomp` (en Docker, `libgomp1`).

```bash
python -m reposicion.cli comparar --corte 2017-08-14    # backtest baseline vs LightGBM → reports/comparacion_modelos.md
python -m reposicion.cli entrenar --corte 2017-01-02    # entrena el challenger y decide si reemplaza al champion
python -m reposicion.cli pronosticar --corte 2017-03-13 # publica data/published/corte=.../rev=1/ (idempotente)
```

- `comparar` hace el backtest de ambos modelos y de la variante "cuantil de la demanda semanal" y
  escribe el reporte (tablas global, por familia y por horizonte, y la decisión de promoción).
- `entrenar` registra el modelo en `data/models/` y en `data/models/registro.parquet`. El criterio
  de reemplazo está en `config/promotion.yaml`. Si no hay champion, el baseline lo es por defecto.
- `pronosticar` usa el champion vigente en el corte (`champion_vigente`), escribe
  `pronostico.parquet`, `pedido.parquet` y `manifest.json` (sin marcas de tiempo) y nunca
  sobrescribe una revisión publicada con otras entradas (`--revision N` para una nueva).

## Seguimiento y revisiones (fase 7)

```bash
python -m reposicion.cli seguimiento --corte 2017-08-14 --revisiones   # emite revisiones y evalúa
python -m reposicion.cli seguimiento --corte 2017-08-14 --copiar-reporte  # además copia a reports/
```

- `seguimiento` compara cada pronóstico publicado con las ventas reales visibles en el corte de
  evaluación y escribe, en `data/monitoring/corte=<corte>/`, las métricas por corte, familia y
  horizonte, y en `data/monitoring/reportes/<corte>.md` el reporte (con PNG): **ahí se ve el
  desempeño**. Los días sin real figuran como *real pendiente*.
- `--revisiones` (en Airflow, la tarea `emitir_revisiones`) emite `rev=N+1` de los cortes todavía
  vigentes que afecta una corrección entregada en la última semana. Nunca se reescribe un publicado.
- Si el WAPE móvil de 4 cortes supera en más de 20% al del backtest del champion, el reporte y el
  log traen una advertencia (no reentrena). Los umbrales están en `config/monitoreo.yaml`.

## Operar con Airflow (fase 6)

Airflow 3.3.2 (imagen `apache/airflow:3.3.2-python3.11` + las dependencias del proyecto) con
`LocalExecutor` en Docker Compose. Los DAGs solo orquestan: toda la lógica vive en
`src/reposicion/` (`orquestacion.py`, `versionado.py`).

### Levantar desde cero

```bash
git clone https://github.com/ManuelMiranda99/motor-reposicion.git && cd motor-reposicion
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt -e .
./tools/dvc_auth.sh            # token de DagsHub (ver "Datos")
dvc pull                       # baja data/historico, data/kaggle y bandeja_sim/
cp .env.example .env           # completa AIRFLOW_UID (id -u) y, si quieres, los tokens
docker compose up -d --build   # primera vez: construye la imagen (~2 min)
```

1. Abre <http://localhost:8080> (usuario `airflow`, contraseña `airflow`).
2. Despausa los cuatro DAGs (interruptor de cada uno) o, por la línea de comandos:
   `docker compose run --rm airflow-cli airflow dags unpause <dag_id>`.
   Con `catchup=True`, Airflow ejecuta todos los cortes entre `REPOSICION_INICIO` y
   `REPOSICION_FIN`, sin intervención. (Alternativa: un backfill explícito,
   `airflow backfill create --dag-id pronostico_semanal --from-date 2017-01-02 --to-date 2017-08-14`.)
3. Los resultados quedan en `data/published/corte=YYYY-MM-DD/rev=1/` y los registros en la rama
   `publicaciones` (`git log publicaciones`). Para bajar: `docker compose down` (conserva la base de
   Airflow; con `-v` también la borra).

Requisito en macOS para correr LightGBM **fuera** de Docker: `brew install libomp`.

### Los DAGs

Todos usan `catchup=True`, `max_active_runs=1` y un schedule por tiempo (cron). En Airflow 3 con un
cron, `logical_date` es el instante del disparo: la **fecha de corte** es `logical_date.date()`.

| DAG | Schedule (UTC) | Tareas |
|---|---|---|
| `ingesta_validacion` | `0 5 * * *` | `ingestar` → `reportar_calidad` |
| `entrenamiento` | `0 4 * * 1` | `es_momento` (primer lunes del mes, o `forzar`) → `asegurar_ingesta` → `entrenar_y_evaluar` → `versionar_modelo` → `publicar_remoto_modelo` |
| `pronostico_semanal` | `0 6 * * 1` | `asegurar_ingesta` → `asegurar_champion` → `verificar_datos` → `pronosticar` → `versionar_pronostico` → `publicar_remoto_pronostico` |
| `seguimiento_desempeno` | `0 7 * * 1` | `asegurar_ingesta` → `emitir_revisiones` → `evaluar_publicados` → `versionar_seguimiento` → `publicar_remoto_seguimiento` |

- Las tareas que escriben en `data/`, DVC o git usan el pool `escritura_datos` (1 slot): una sola
  escritura a la vez. Solo `publicar_remoto_*` se reintenta (2 veces, 1 minuto).
- Reentrenamiento **manual**: dispara `entrenamiento` desde la UI con el parámetro `forzar=true`
  (el corte es la `logical_date` del disparo).
- Un archivo inválido va a cuarentena y se anota en el log y en el ledger, sin fallar el DAG; un
  corte sin ventas recientes (`DatosInsuficientes`) sí falla, porque es una situación anómala.
  `PublicacionInmutable` (la revisión existe con otras entradas) también falla, sin reintento: la
  corrección se publica como revisión nueva (`emitir_revisiones`, ver "Seguimiento").

### Otro periodo u otra bandeja (por ejemplo, el periodo no publicado)

Edita `.env` y reinicia (`docker compose up -d`):

```bash
BANDEJA_PATH=/ruta/a/la/bandeja     # carpeta con una subcarpeta por fecha de entrega (solo lectura)
REPOSICION_INICIO=2017-09-04        # primer corte (lunes)
REPOSICION_FIN=2017-12-25           # último corte
```

La bandeja se monta en `/opt/bandeja` con `:ro`: ningún proceso puede escribir en ella. Las fechas
por defecto están en `config/operacion.yaml`.

### Versionado y push

Tras cada evento (`pronostico`, `modelo`, `seguimiento`) el DAG hace `dvc add` de `data/raw`,
`ledger`, `limpio`, `backtest`, `models`, `published` y `monitoring`, y confirma los `.dvc` y un
`registro/<corte>/<evento>.json` en la rama **`publicaciones`** con comandos de bajo nivel de git
(sin checkout y sin tocar el índice ni tu árbol de trabajo). Repetir un corte es un no-op. Los
`.dvc` de `data/` sí cambian en tu árbol de trabajo al operar: se commitean a `main` con un PR.

`push_remoto: auto` (`config/operacion.yaml`): con `DAGSHUB_TOKEN` en `.env` se hace `dvc push`; con
`GITHUB_TOKEN`, `git push` de la rama `publicaciones`. Sin ellos, queda el commit local y un
warning (no falla). Opciones: `siempre` (falla sin credenciales) y `nunca`.

## Estructura

| Ruta | Contenido |
|---|---|
| `src/reposicion/` | Lógica del producto (ingesta, validación, features, modelos, pedido, monitoreo) |
| `dags/` | DAGs de Airflow (solo orquestación) |
| `docker/`, `docker-compose.yaml` | Imagen y servicios de Airflow (LocalExecutor) |
| `config/` | Configuración versionada (costos de negocio, modelo, validación) |
| `tests/` | Pruebas (pytest) |
| `tools/` | Utilidades (simulador de bandeja) |
| `plan/` | Plan de trabajo del laboratorio |
| `DECISIONES.md` | Decisiones técnicas y de producto |

## Reproducir un pronóstico publicado

_Pendiente (fase 8)._
