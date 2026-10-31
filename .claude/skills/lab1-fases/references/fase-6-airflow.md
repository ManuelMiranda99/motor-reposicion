# Fase 6 — Airflow 3 en Docker Compose

**Rama:** `feat/airflow` · **Estimado:** 2 días · **Prerequisitos:** fases 3 a 5 (todo funciona
desde la CLI).

## Objetivo

Orquestar con Airflow 3 lo que ya existe, sin poner lógica en los DAGs, de modo que:
backfill 2017-01-02 → 2017-08-14 en verde, idempotente, sin intervención manual, con cada corte
versionado (DVC) y registrado en git.

## Decisiones para el usuario (preguntar al inicio)

1. **Versión de Airflow.** Antes de preguntar, averigua la última 3.x estable
   (`pip index versions apache-airflow`).
   - (Recommended) La última 3.x estable, fijada (por ejemplo `apache/airflow:3.x.y-python3.11`).
   - Una versión específica que indique el curso.
2. **Cómo correrá el equipo docente el "periodo no publicado".**
   - (Recommended) `.env` con `BANDEJA_PATH`, `REPOSICION_INICIO` y `REPOSICION_FIN`. Los DAGs
     usan `catchup=True` entre esas fechas y basta con despausarlos (o correr
     `airflow backfill create`). El README lo explica paso a paso.
   - Disparo manual con parámetros (`corte`) desde la UI.
3. **Push de `publicaciones` a GitHub desde el contenedor.**
   - (Recommended) `push_remoto: auto`: si hay `GITHUB_TOKEN` en `.env`, hace push; si no, hace el
     commit local y deja un warning. `dvc push`, igual, con `DAGSHUB_TOKEN`.
   - Siempre hacer push (falla si no hay credenciales).
   - Nunca hacer push (solo local).
4. **Estructura de los DAGs.**
   - (Recommended) Cuatro DAGs con schedule por tiempo (ver tabla). Sin scheduling por Assets: en
     Airflow 3, las ejecuciones disparadas por un Asset **no tienen `logical_date`**, y aquí
     todo depende de la fecha de corte.
   - Un solo DAG semanal que haga todo (más simple, pero cubre peor el requisito de "DAGs para
     cada etapa").

## Archivos nuevos

```
docker/Dockerfile
docker-compose.yaml
.env.example
config/operacion.yaml
dags/ingesta_validacion.py
dags/pronostico_semanal.py
dags/seguimiento_desempeno.py
dags/entrenamiento.py
dags/_comun.py                 # helpers mínimos: corte desde el contexto, rutas, pool
src/reposicion/versionado.py
tests/test_dags.py
```

## Docker

**`docker/Dockerfile`:**

```dockerfile
FROM apache/airflow:<3.x.y>-python3.11
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
```

- Después de construir la imagen, corre `docker compose run --rm airflow-cli pip check`. Si
  nuestras versiones fijadas (pandas 3, numpy 2.4, pydantic…) chocan con las de Airflow, **avisa
  al usuario** y propón bajar la versión conflictiva en `requirements.txt` (vuelve a correr
  `pytest` en el `.venv` después de cambiarla). No uses `--no-deps` para esconder el conflicto.

**`docker-compose.yaml`:** parte del oficial de esa versión
(`https://airflow.apache.org/docs/apache-airflow/<version>/docker-compose.yaml`) y:

- Usa `LocalExecutor`: elimina redis, worker y flower.
- Servicios: postgres, airflow-init, airflow-apiserver (puerto 8080), airflow-scheduler,
  airflow-dag-processor, airflow-triggerer.
- `build: {context: ., dockerfile: docker/Dockerfile}` en lugar de `image:`.
- Variables de entorno comunes:

```yaml
AIRFLOW__CORE__EXECUTOR: LocalExecutor
AIRFLOW__CORE__LOAD_EXAMPLES: "false"
AIRFLOW__CORE__DAGS_FOLDER: /opt/airflow/repo/dags
PYTHONPATH: /opt/airflow/repo/src
REPOSICION_REPO: /opt/airflow/repo
REPOSICION_DATA: /opt/airflow/repo/data
REPOSICION_BANDEJA: /opt/bandeja
REPOSICION_INICIO: ${REPOSICION_INICIO:-2017-01-02}
REPOSICION_FIN: ${REPOSICION_FIN:-2017-08-14}
AWS_ACCESS_KEY_ID: ${DAGSHUB_TOKEN:-}        # DVC (S3 de DagsHub) toma las credenciales de aquí
AWS_SECRET_ACCESS_KEY: ${DAGSHUB_TOKEN:-}
GITHUB_TOKEN: ${GITHUB_TOKEN:-}
```

- Volúmenes:

```yaml
- .:/opt/airflow/repo
- ${BANDEJA_PATH:-./bandeja_sim}:/opt/bandeja:ro      # read-only: garantiza que no se modifica
- ./logs:/opt/airflow/logs
```

- `airflow-init`: además de lo del oficial, ejecuta
  `airflow pools set escritura_datos 1 "serializa escrituras en data/, DVC y git"` y
  `git config --global --add safe.directory /opt/airflow/repo`.
- `AIRFLOW_UID` en `.env` = `id -u` del usuario. Sigue el método de autenticación de la UI del
  compose oficial de esa versión y documenta usuario y contraseña en el README.

**`.env.example`:** `AIRFLOW_UID`, `BANDEJA_PATH`, `REPOSICION_INICIO`, `REPOSICION_FIN`,
`DAGSHUB_TOKEN`, `GITHUB_TOKEN`, cada uno con un comentario. `.env` ya está en `.gitignore`.

## DAGs

Reglas para todos los DAGs:
- Importa con `from airflow.sdk import dag, task` (API de Airflow 3).
- `catchup=True`, `max_active_runs=1`, `start_date` y `end_date` desde `REPOSICION_INICIO` y
  `REPOSICION_FIN`.
- Toda tarea que escriba en `data/`, DVC o git usa `pool="escritura_datos"`.
- `retries=2` con `retry_delay` de 1 minuto solo en las tareas de I/O remoto (`dvc push`,
  `git push`); las de lógica van con `retries=0`.

**Fecha de corte:** en Airflow 3, con un schedule cron, `logical_date` es el instante del disparo,
porque el timetable por defecto es `CronTriggerTimetable`. Calcula el corte como
`context["logical_date"].date()` en `_comun.corte(context)`. **Verifícalo** con
`airflow dags test pronostico_semanal 2017-03-13` antes de seguir.

| DAG | Schedule | Tareas (cada una llama a una función de `reposicion`) |
|---|---|---|
| `ingesta_validacion` | `0 5 * * *` | `ingestar(hasta=corte)` → `reportar_calidad` (resumen del ledger del día en el log y XCom) |
| `pronostico_semanal` | `0 6 * * 1` | `asegurar_ingesta(corte)` (idempotente) → `verificar_datos` → `pronosticar_corte` → `versionar("pronostico", corte)` |
| `seguimiento_desempeno` | `0 7 * * 1` | `asegurar_ingesta` → `evaluar_publicados(corte)` (fase 7; en esta fase deja la tarea con un stub claro que diga "implementado en fase 7") → `versionar("seguimiento", corte)` |
| `entrenamiento` | `0 4 * * 1` + `@task.short_circuit` que sigue solo si `corte.day <= 7` (primer lunes del mes) | `es_primer_lunes` → `entrenar_y_evaluar(corte)` → `versionar("modelo", corte)` |

> Ojo: **no** uses `0 4 1-7 * 1`. Si se dan día del mes y día de la semana a la vez, cron los
> combina con O: correría del 1 al 7 de cada mes **y** todos los lunes.

- **Contrato de la fase 5:** `entrenar_y_evaluar(corte, dir_data, cfgs)` y
  `pronosticar_corte(corte, dir_data, cfgs, revision=1)` (ver `contexto.md` §10) reciben
  `cfgs = cargar_configs(<repo>/config)` (incluye `validation.yaml` y `promotion.yaml`) y leen
  `asof(corte)`: ambas tareas deben ir precedidas de `asegurar_ingesta(corte)`, también en el DAG
  `entrenamiento` (corre a las 04:00, antes de la ingesta diaria). `PublicacionInmutable` no se
  reintenta: es una señal para la fase 7 (revisión nueva), no un error transitorio. En la imagen:
  `libgomp1` y `lightgbm` (ya está en `requirements.txt`); define `REPOSICION_GIT_COMMIT`.
- `pronostico_semanal` no depende de otros DAGs, porque `asegurar_ingesta` deja todo listo hasta
  `corte` por su cuenta.
- El orden en un mismo lunes (entrenamiento 04:00 → ingesta 05:00 → pronóstico 06:00 →
  seguimiento 07:00) garantiza que un modelo promovido en T se use en T: `champion_vigente` usa
  `<=`.
- Fallas: `DatosInsuficientes` → la tarea falla con un mensaje claro (situación anómala real). Los
  archivos en cuarentena **no** fallan el DAG: quedan en el ledger y en el log.

## Versionado desde Airflow (`src/reposicion/versionado.py`)

Problema: el repo está montado en el contenedor y es el mismo working tree del desarrollador. Un
`git commit` normal ensuciaría su rama y además `main` está protegida. Solución: **commits con
plumbing de git** sobre la rama `publicaciones`, sin checkout:

```python
def versionar(evento: str, corte: date, repo: Path, push_remoto: str) -> str | None:
    # 1) dvc add de las salidas operativas (una .dvc por directorio, en data/):
    #    data/raw data/ledger data/limpio data/backtest data/models data/published data/monitoring
    # 2) dvc push (si hay credenciales; si push_remoto == "auto" y no hay, warning)
    # 3) commit en refs/heads/publicaciones SIN tocar el working tree ni el índice:
    #      GIT_INDEX_FILE=<tmp> git read-tree publicaciones   (si la rama existe; si no, árbol vacío)
    #      git update-index --add --cacheinfo 100644,<blob>,<ruta> para cada .dvc y para
    #          registro/<corte>/<evento>.json (copia del manifest o un resumen)
    #      tree=$(git write-tree); si es igual al árbol del padre → no-op (idempotencia)
    #      git commit-tree $tree -p <padre> -m "<evento> corte <T>"; git update-ref refs/heads/publicaciones
    #    Autor y committer fijos (GIT_AUTHOR_NAME="motor-reposicion[airflow]", con fechas fijas
    #    derivadas del corte) para que el commit sea determinista.
    # 4) si hay GITHUB_TOKEN: git push https://x-access-token:$GITHUB_TOKEN@github.com/... publicaciones
    # devuelve el sha del commit (o None si fue no-op)
```

- Los `.dvc` de `data/` quedan **trackeados en `main`** (son el estado que bajará el docente con
  `dvc pull`). Agrega sus rutas a `data/.gitignore` desde ahora para que DVC no tenga que
  modificarlo, y pon `core.autostage = false` en `.dvc/config`, para que Airflow no toque el
  índice del desarrollador. Documenta que los `.dvc` de `data/` cambian al operar y que se
  commitean a `main` mediante un PR en la entrega (fase 8).
- Pruebas: `tests/unit/test_versionado.py` con un repo git temporal (`git init` en `tmp_path`):
  el commit queda en `publicaciones`, el working tree y el índice no cambian, y repetir es un no-op.
  Haz un mock de DVC.
- Si DVC no permite `dvc add` de algún directorio (por ejemplo, porque la ruta está ignorada),
  **adapta y documenta**. No desactives las verificaciones de DVC.

## `tests/test_dags.py`

Usa `pytest.importorskip("airflow")`, carga `DagBag(dag_folder="dags", include_examples=False)` y
verifica: sin errores de import, los 4 DAGs presentes, `catchup=True`, `max_active_runs=1` y que
las tareas de escritura usen el pool. En el CI, agrega un **segundo job** `dags` que instale
`apache-airflow==<v>` con su constraints file
(`https://raw.githubusercontent.com/apache/airflow/constraints-<v>/constraints-3.11.txt`) y corra
solo `tests/test_dags.py`. Después de que corra una vez en verde, agrégalo a los checks requeridos
de `main`:

```bash
gh api -X PATCH "repos/ManuelMiranda99/motor-reposicion/branches/main/protection/required_status_checks" \
  -f strict=true -f "contexts[]=lint-y-pruebas" -f "contexts[]=dags"
```

(Esto cambia la configuración del repo: confírmalo con el usuario.)

## Verificación

```bash
cp .env.example .env    # el usuario completa los tokens; no los leas ni los imprimas
docker compose build && docker compose up -d
docker compose run --rm airflow-cli airflow dags list
docker compose run --rm airflow-cli airflow dags test pronostico_semanal 2017-03-13
# backfill completo (sintaxis de Airflow 3):
docker compose run --rm airflow-cli airflow backfill create --dag-id pronostico_semanal \
  --from-date 2017-01-02 --to-date 2017-08-14
```

Comprueba:
- todos los runs en verde;
- `data/published/` tiene 33 cortes, cada uno con su manifiesto;
- la rama `publicaciones` tiene un commit por evento y `git status` de `main` está limpio salvo
  los `.dvc` esperados;
- relanzar un run ya hecho (*Clear* en la UI) no cambia los hashes.

Pide al usuario que tome **capturas de la vista Grid** (o hazlas con las herramientas de
navegador, si están disponibles) y guárdalas en `reports/evidencia/` (PNG pequeños, en git).

## Documentación

- `README.md`: levantar desde cero (clonar → venv → `tools/dvc_auth.sh` → `dvc pull` → `.env` →
  `docker compose up` → UI en localhost:8080 → despausar o hacer backfill), con usuario y
  contraseña y cómo apuntar a otra bandeja.
- `DECISIONES.md` §11: LocalExecutor, schedules por tiempo en vez de Assets, plumbing sobre
  `publicaciones`, `push_remoto`, pool `escritura_datos`.

## Criterios de terminado

- [ ] `docker compose up` desde un clon limpio levanta Airflow sin pasos manuales extra (más allá
      de `.env`).
- [ ] Backfill de los 4 DAGs en verde, y re-ejecutarlos no cambia nada.
- [ ] La rama `publicaciones` tiene los registros y el working tree de `main` no se ensucia (salvo
      los `.dvc` de `data/`).
- [ ] El job `dags` corre en el CI.
- [ ] README y DECISIONES actualizados, y hay evidencias de la UI.
