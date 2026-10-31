# Motor de Reposición de Inventario

Laboratorio 1 — Product Development (Maestría en Data Science, Universidad Galileo).

Producto de ML que, cada semana (fecha de corte: lunes), transforma los datos de ventas que llegan
diariamente en:

1. un **pronóstico diario a 14 días** por tienda × familia, con cuantiles;
2. un **pedido sugerido** derivado del pronóstico y de los costos de quiebre y de merma
   (`config/business.yaml`);
3. un **reporte de seguimiento** de los pronósticos publicados contra las ventas reales.

Se basa en los datos de Corporación Favorita ([Kaggle — Store Sales](https://www.kaggle.com/competitions/store-sales-time-series-forecasting/data)).

Ruta rápida para quien evalúa: [Inicio rápido](#inicio-rápido-evaluación-docente) → [Operar con
Airflow](#operar-con-airflow) → [Otro periodo u otra bandeja](#otro-periodo-u-otra-bandeja-por-ejemplo-el-periodo-no-publicado)
→ [Reproducir un pronóstico publicado](#reproducir-un-pronóstico-publicado) →
[Evidencias](#evidencias).

## Inicio rápido (evaluación docente)

Probado en un clon limpio (macOS, Docker Desktop con ≥ 6 GB de RAM; ver
[Ensayo](#ensayo-de-la-evaluación-docente)). Necesitas: Git, Python 3.11, Docker con Compose v2 y una
cuenta gratuita de DagsHub (para `dvc pull`, ver [Datos](#datos-dvc--dagshub)).

```bash
git clone https://github.com/ManuelMiranda99/motor-reposicion.git && cd motor-reposicion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -e .
./tools/dvc_auth.sh                  # pide el token de DagsHub (sin mostrarlo)
dvc pull                             # entradas + estado entregado (~600 MB, ~1 min)
cp .env.example .env                 # edita AIRFLOW_UID (el resultado de `id -u`) y, si quieres, los tokens
docker compose up -d --build         # primera vez: construye la imagen (~3 min)
```

Abre <http://localhost:8080> (usuario `airflow`, contraseña `airflow`) y despausa los cuatro DAGs.
Para operar **otra bandeja** (el periodo no publicado) sigue
[esta sección](#otro-periodo-u-otra-bandeja-por-ejemplo-el-periodo-no-publicado).

## Requisitos

- Python 3.11, Git y DVC (se instala con `pip install -r requirements.txt`).
- Docker con Compose v2 (para Airflow). Docker Desktop: asigna **≥ 6 GB de RAM** (el reentrenamiento de
  LightGBM sobre ~1.3 M filas lo necesita) y 10 GB de disco para la imagen y los datos.
- Cuenta gratuita de DagsHub para `dvc pull` (ver Datos).
- Puerto 8080 libre (UI de Airflow).
- Solo para correr LightGBM **fuera** de Docker en macOS: `brew install libomp`.

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
| `data/raw/`, `data/ledger/`, `data/limpio/` | Ingesta: copia de lo recibido, ledger y almacén limpio (estado al 2017-08-14) |
| `data/backtest/`, `data/models/` | Backtests y modelos entrenados con su registro champion/challenger |
| `data/published/corte=…/rev=…/` | Pronósticos y pedidos **publicados** (inmutables) con su `manifest.json` |
| `data/monitoring/` | Seguimiento por corte de evaluación y reportes (`reportes/<corte>.md` + PNG) |

`dvc pull` trae **todo el estado entregado**: el backfill completo 2017-01-02 → 2017-08-14, de modo
que puedes inspeccionar o [reproducir](#reproducir-un-pronóstico-publicado) cualquier corte sin
reentrenar. Solo las entradas (sin las salidas): `dvc pull data/kaggle.dvc data/historico.dvc bandeja_sim.dvc`.

> **Pendiente de confirmar con el docente:** DagsHub no permite lectura anónima (401), así que la
> evaluación usa **su propia cuenta de DagsHub** + `./tools/dvc_auth.sh` (el repo de GitHub es público, el
> token solo necesita lectura). Ver [DECISIONES §2 y §13](DECISIONES.md).

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

### Modelos: entrenar, comparar y pronosticar

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

## Seguimiento y revisiones

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

## Operar con Airflow

Airflow 3.3.2 (imagen `apache/airflow:3.3.2-python3.11` + las dependencias del proyecto) con
`LocalExecutor` en Docker Compose. Los DAGs solo orquestan: toda la lógica vive en
`src/reposicion/` (`orquestacion.py`, `versionado.py`).

### Levantar (después del [Inicio rápido](#inicio-rápido-evaluación-docente))

- `AIRFLOW_UID` en `.env` debe ser tu `id -u` (en macOS, 501; en Linux suele ser 1000): evita archivos
  de `root` dentro del repo. Con el valor por defecto (50000) en Linux, `data/` queda con otro dueño.
- Tras cambiar `requirements.txt` o `docker/Dockerfile`: `docker compose build` y
  `docker compose up -d`.

1. Abre <http://localhost:8080> (usuario `airflow`, contraseña `airflow`).
2. Despausa los cuatro DAGs (interruptor de cada uno) o, por la línea de comandos:
   `docker compose run --rm airflow-cli airflow dags unpause <dag_id>`.
   Con `catchup=True`, Airflow ejecuta todos los cortes entre `REPOSICION_INICIO` y
   `REPOSICION_FIN`, sin intervención. (Alternativa: un backfill explícito,
   `airflow backfill create --dag-id pronostico_semanal --from-date 2017-01-02 --to-date 2017-08-14`.)
3. Los resultados quedan en `data/published/corte=YYYY-MM-DD/rev=N/` y los registros en la rama
   `publicaciones` (`git log publicaciones`). Para bajar: `docker compose down` (conserva la base de
   Airflow; con `-v` también la borra).

**Tiempos:** un reentrenamiento (primer lunes de cada mes) tarda ~15–28 min en Docker y todo lo que
escribe en `data/` está serializado (pool de 1 slot): un backfill de 8 meses toma varias horas
(2017-01-02 → 2017-08-14: ~4 h, ver [Evidencias](#evidencias)); una ventana de 4 semanas, ~25 min. **No dejes que el equipo hiberne durante un backfill** (conéctalo a la corriente): la VM de Docker se congela y Airflow marca la tarea en curso como fallida. Los
DAGs semanales se atrasan mientras entrena el primero; es normal (ver la columna *Duration* del Grid).

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
por defecto están en `config/operacion.yaml`. Dos casos:

1. **La bandeja continúa la entregada** (fechas posteriores al 2017-08-14; la carga histórica es la
   misma): no hay nada más que hacer. La ingesta agrega los archivos nuevos al ledger y los DAGs
   producen los cortes nuevos sobre el estado que trajo `dvc pull`.
2. **La bandeja es otra** que cubre fechas ya operadas (por ejemplo, la regenerada con otra semilla
   para una prueba): los archivos con el mismo nombre pero otro contenido se leerían como
   *correcciones* de lo ya ingerido. Para empezar de cero, antes de levantar Airflow:

   ```bash
   docker compose down                  # si estaba arriba
   ./tools/limpiar_salidas.sh           # borra raw, ledger, limpio, backtest, models, published, monitoring
   docker compose up -d
   ```

   (conserva `data/kaggle` y `data/historico`; lo borrado se recupera con `dvc pull`). Si la carga
   histórica también cambia, reemplaza `data/historico/`.

Si el periodo nuevo empieza tarde (por ejemplo, 5 semanas después del inicio de la bandeja), no hay
que correr los cortes anteriores: `REPOSICION_INICIO` fija el primer corte y la ingesta del primer
run lee todo lo entregado hasta ese día. El primer corte entrena el primer champion (el baseline es el
champion inicial hasta que LightGBM lo supera).

Generar una bandeja distinta con el simulador (otra semilla y escenarios en otras fechas). La carga
histórica **depende de la semilla** (el lag de las transacciones decide qué cae antes del 2017-01-01),
así que se genera junto con la bandeja y se usa en lugar de `data/historico`:

```bash
cp config/simulador.yaml /ruta/simulador_alt.yaml     # edita `semilla` y `escenarios`
python tools/simulate_bandeja.py --config /ruta/simulador_alt.yaml \
    --bandeja /ruta/bandeja_alt --historico /ruta/historico_alt
./tools/limpiar_salidas.sh && rm -rf data/historico && cp -R /ruta/historico_alt data/historico
# .env: BANDEJA_PATH=/ruta/bandeja_alt, REPOSICION_INICIO=..., REPOSICION_FIN=...
```

(Se necesita `data/kaggle`, que trae `dvc pull`. Para tener dos copias del proyecto a la vez, define
`COMPOSE_PROJECT_NAME=otro` en el `.env` de la segunda y cambia el puerto `8080` del compose.)

Los escenarios que cubre el sistema (y se pueden inyectar en el simulador): archivo faltante, tardío,
corrección (también dos correcciones seguidas del mismo día), duplicado idéntico, inválido con o sin
reentrega, tienda nueva y fuente atrasada más allá de su tolerancia (`config/sources.yaml`).

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
| `tools/` | Utilidades: `simulate_bandeja.py`, `dvc_auth.sh`, `limpiar_salidas.sh` |
| `reports/` | Evidencias versionadas en git (comparación de modelos, seguimiento, capturas) |
| `plan/` | Plan de trabajo del laboratorio y `ESTADO.md` |
| `DECISIONES.md` | Decisiones técnicas y de producto (y limitaciones conocidas) |
| `CLAUDE.md` | Reglas del proyecto y comandos |

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Pronóstico diario por cuantiles | `data/published/corte=YYYY-MM-DD/rev=N/pronostico.parquet` |
| Pedido sugerido (tienda × familia) | `data/published/corte=YYYY-MM-DD/rev=N/pedido.parquet` |
| Manifiesto (modelo, commit, huella de entradas, sha256, calidad, advertencias) | `.../manifest.json` |
| Seguimiento de lo publicado vs. lo real | `data/monitoring/reportes/<corte>.md` (copia final: `reports/seguimiento.md`) |
| Modelos y su historial champion/challenger | `data/models/`, `data/models/registro.parquet` |
| Archivos en cuarentena, correcciones y tardíos | `data/ledger/ingesta.parquet` (`estado`, `version`, `es_correccion`, `es_tardio`) |
| Registro versionado de cada evento | rama `publicaciones`: `git log publicaciones -- registro/<corte>/` |

Cada `rev=N` es inmutable: una corrección de datos emite `rev=N+1` y deja intacta la anterior
(`manifest.json` de las revisiones trae `datos_hasta`, `emitido_en`, `revision_de` y `motivo`).

## Reproducir un pronóstico publicado

Cada publicación guarda en su `manifest.json` el `git_commit` del código, la **huella de las
entradas** (sha256 de los archivos de la bandeja entregados hasta la fecha de lectura), los hashes de
la configuración, el `modelo_id` y el sha256 de sus archivos. `reproducir` vuelve a calcularlo en un
directorio temporal (sin tocar `data/published`) y compara:

```bash
python -m reposicion.cli reproducir --corte 2017-03-13            # rev=1
python -m reposicion.cli reproducir --corte 2017-02-06 --rev 2    # una revisión
# → REPRODUCIDO ✓   (o NO REPRODUCIDO ✗ con las diferencias; código de salida 1)
```

- Una revisión se reproduce con el `datos_hasta` de su manifiesto; en `rev=1` el manifiesto no trae
  `datos_hasta` y vale el corte. Se usa el modelo registrado (`modelo_id`) y el ledger filtrado a
  `fecha_entrega <= datos_hasta`, así que una corrección llegada después **no** cambia el resultado.
- Si `git rev-parse HEAD` difiere del `git_commit` del manifiesto, el comando avisa con la receta
  exacta: `git worktree add ../repro <git_commit> && cd ../repro && dvc pull` y se repite el comando
  allí. El commit correcto de un corte también está en la rama `publicaciones`:
  `git log publicaciones -- registro/2017-03-13/` (ahí se ven el commit del evento y los `.dvc`
  de ese momento: `git show <commit>:data/published.dvc`).
- **Mismo entorno:** LightGBM no es bit a bit idéntico entre macOS y Linux (distinto OpenMP y
  aritmética de punto flotante). Los publicados de este repo se generaron **en Docker (Linux)**:
  reprodúcelos en Docker (`docker compose --profile debug run --rm airflow-cli python -m
  reposicion.cli reproducir --corte 2017-03-13`) o en Linux. En macOS, el `modelo_id`, la huella
  de entradas y los pedidos del baseline coinciden, pero los parquet de LightGBM pueden diferir en los
  últimos decimales y el comando lo reportará como diferencia de sha256.

## Evidencias

| Evidencia | Archivo |
|---|---|
| Baseline vs. LightGBM (backtest, decisión de promoción) | [`reports/comparacion_modelos.md`](reports/comparacion_modelos.md) |
| Seguimiento final del desempeño (métricas por corte, familia y horizonte, alertas) | [`reports/seguimiento.md`](reports/seguimiento.md) |
| Capturas de la UI de Airflow (Grid, cuarentena, revisión por corrección) | [`reports/evidencia/`](reports/evidencia/README.md) |
| Decisiones y limitaciones | [`DECISIONES.md`](DECISIONES.md) |
| Registro de cada evento semanal/mensual | rama `publicaciones` |

### Backfill entregado (2017-01-02 → 2017-08-14, Airflow en Docker)

El estado de `data/` en `main` es el de un único backfill completo, desde cero, con los cuatro DAGs
despausados a la vez (sin intervención):

| Concepto | Resultado |
|---|---|
| Runs | 324, todos en verde: 225 `ingesta_validacion` (diarios) + 33 × 3 DAGs semanales |
| Duración | 3 h 53 min de reloj (12:38 → 16:31 UTC), con las tareas de escritura serializadas |
| Reentrenamientos | 8 (primer lunes de cada mes, enero–agosto), ~15–28 min cada uno |
| Promociones de modelo | baseline como champion inicial y LightGBM promovido el 2017-01-02; los 7 challengers siguientes no superaron el criterio (`config/promotion.yaml`) y el champion vigente al 2017-08-14 es `lgbm-2017-01-02-496d76f4` |
| Publicaciones | 36: 33 `rev=1` + 3 revisiones por corrección (`2017-02-06/rev=2`, `2017-03-13/rev=2`, `2017-05-08/rev=2`); 7 de los `rev=1` salen `degradada` (ventas atrasadas o faltantes, promociones que acaban el 08-15) |
| Ingesta | 834 archivos hasta el 08-14: 828 válidos, 5 en cuarentena (ventas 05-10, transacciones 06-05, ventas 06-21, promociones 07-20, ventas 07-26), 1 duplicado idéntico |
| Registro en git | 74 commits en la rama `publicaciones` (33 pronósticos + 33 seguimientos + 8 modelos) |
| Alertas de degradación | 1 (corte 2017-01-30: el WAPE móvil incluye el corte 2017-01-02, de WAPE 0.563 por el 01-01 casi en cero) |
| Desempeño (seguimiento al 2017-08-14) | WAPE por corte 0.107–0.196 (salvo el corte 01-02); WAPE móvil de 4 cortes 0.1370 vs 0.1742 del backtest; cobertura P10–P90 0.69–0.82 |
| Reproducción | `reproducir` da `REPRODUCIDO ✓` (en Docker) para `2017-03-13/rev=1`, `2017-08-14/rev=1`, `2017-02-06/rev=2`, `2017-03-13/rev=2` y `2017-05-08/rev=2` |

Un primer intento del backfill falló por un incidente ajeno al código (el equipo hibernó) y se repitió
completo desde cero: ver [DECISIONES §13](DECISIONES.md).

### Ensayo de la evaluación docente

Ensayo hecho **siguiendo este README** en un clon limpio desde GitHub (venv nuevo, `dvc pull`, Docker
con otro nombre de proyecto), con una bandeja distinta generada con el simulador (semilla 777 y
escenarios en otras fechas) y una ventana corta: cortes 2017-06-05 → 2017-06-26 (4 semanas, ~25 min
con el reentrenamiento de junio). Resultado: 4 + 4 + 4 + 22 runs en verde, sin intervención.

- `dvc pull` en el clon: ~1 min, 544 MB; `dvc status -c` limpio. (En el ensayo, las credenciales de DVC
  se copiaron de `.dvc/config.local` del repo principal en lugar de pedir el token.)
- Escenarios nuevos que el sistema absorbió: **dos correcciones seguidas del mismo dato** (ventas del
  06-06: versión 2 el 06-12 y versión 3 el 06-14; cada una produjo su revisión y se conservaron las
  anteriores), **fuente con 5 días de retraso** (ventas del 06-15, entregadas el 06-20: el corte 06-19
  salió `degradada` y su `rev=2` ya incluye el dato), transacciones tardías, un duplicado idéntico,
  3 archivos en cuarentena (ventas negativas con reentrega, transacciones sin columna, promociones con
  tienda desconocida) y un faltante. Todos resueltos sin fallas.
- Fricciones encontradas y corregidas en este README: (1) la carga histórica **depende de la semilla**
  del simulador (el lag de transacciones cambia lo que cae antes del 2017-01-01), así que con otra
  bandeja hay que reemplazar también `data/historico` (se documentó, junto con
  `tools/limpiar_salidas.sh` para partir de un `data/` limpio); (2) un archivo con el mismo nombre
  pero otro contenido en una bandeja distinta se leería como corrección del estado entregado: se
  documentó cuándo limpiar las salidas; (3) cómo correr dos copias a la vez
  (`COMPOSE_PROJECT_NAME` y puerto); (4) el tamaño real del `dvc pull` (~600 MB, ~1 min) y la
  advertencia de no dejar que la máquina hiberne durante un backfill.
- No se probó: `dvc pull` con una cuenta de DagsHub distinta de la del dueño (no había otra) ni la
  construcción de la imagen sin caché (~3 min la primera vez).

### Pruebas

```bash
source .venv/bin/activate
ruff check . && ruff format --check . && pytest      # el CI corre lo mismo
```

Incluyen pruebas unitarias, e2e sin Airflow (`tests/integration/`: idempotencia, backfill = operación
en vivo, sin *leakage*, correcciones y `reproducir`) y de los DAGs (`tests/test_dags.py`).
