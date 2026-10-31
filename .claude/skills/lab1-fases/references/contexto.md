# Contexto del proyecto (estado al cerrar la fase 5)

## Contenido

1. Usuario y forma de trabajo
2. Infraestructura
3. Estructura actual del repo
4. Datos: hechos verificados
5. Bandeja simulada y carga histórica (contrato de entrada)
6. Contratos compartidos entre fases (rutas, nombres, configs)
7. Decisiones ya tomadas (no volver a preguntar)
8. Trampas conocidas
9. Fase 4: lo que quedó implementado
10. Fase 5: lo que quedó implementado

---

## 1. Usuario y forma de trabajo

- Proyecto individual de maestría (Product Development, Universidad Galileo). El usuario habla
  español; toda la comunicación, documentación y commits van en español.
- Quiere que se le pregunte **cada decisión técnica relevante** (`AskUserQuestion`, opción
  recomendada primero).
- Flujo Git: rama por fase → PR → CI verde → squash merge. `main` está protegida (PR obligatorio,
  check `lint-y-pruebas`, historial lineal, sin force-push, `enforce_admins`).
- Enunciado: `Laboratorio_1_PD_26.pdf` en la raíz (ignorado por git). El plan completo está en
  `plan/` (01 a 07).

## 2. Infraestructura

| Cosa | Valor |
|---|---|
| GitHub | `ManuelMiranda99/motor-reposicion` (público). `gh` autenticado |
| DagsHub (remoto DVC) | `s3://dvc`, endpoint `https://dagshub.com/ManuelMiranda99/motor-reposicion.s3` |
| Credenciales DVC | `.dvc/config.local` (fuera de git), las crea `tools/dvc_auth.sh`. DagsHub **no** permite lectura anónima: con 401, el usuario debe correr el script |
| Python | 3.11 en `.venv` (pip + `requirements*.txt` con `==`) |
| DVC | `dvc[s3]==3.67.1` (en `requirements.txt`, porque Airflow también lo usará). `core.autostage = true` |
| CI | `.github/workflows/ci.yml`, job `lint-y-pruebas`: ruff check, ruff format --check, pytest. `ubuntu-24.04`, Python 3.11 |
| Docker | Docker Desktop disponible en la máquina del usuario (macOS) |

Versiones fijadas hoy: numpy 2.4.6, pandas **3.1.0**, pyarrow 26.0.0, pydantic 2.14.1, PyYAML 6.0.3,
pytest 9.1.1, ruff 0.17.3.

## 3. Estructura actual del repo

```
CLAUDE.md  README.md  DECISIONES.md  pyproject.toml  requirements.txt  requirements-dev.txt
.github/workflows/ci.yml
.claude/skills/lab1-fases/        # esta skill
config/simulador.yaml
src/reposicion/__init__.py        # __version__
src/reposicion/config.py          # cargar_yaml(ruta) -> dict
src/reposicion/simulador.py       # simulador de bandeja (fase 2)
src/reposicion/{rutas,io,fuentes,validacion,ingesta,almacen,asof,correcciones,cli}.py   # fase 3
config/sources.yaml  config/validation.yaml  config/model.yaml  config/business.yaml
src/reposicion/{parametros,datos,features,metricas,pedido,backtest}.py  src/reposicion/modelos/{base,baseline}.py   # fase 4
src/reposicion/{registro,entrenamiento,publicacion,comparacion}.py  src/reposicion/modelos/{lgbm,semanal}.py   # fase 5
config/promotion.yaml  reports/comparacion_modelos.md   # fase 5
tests/sinteticos.py  tests/conftest.py   # fixtures: kaggle_sintetico, config_sintetica, bandeja_sintetica, cfg_fuentes, cfg_validacion
tools/simulate_bandeja.py         # CLI del simulador
tools/dvc_auth.sh                 # configura el token de DagsHub
tests/unit/test_package.py
tests/unit/test_simulador.py      # muestra cómo armar datos sintéticos tipo Kaggle
data/kaggle.dvc  data/historico.dvc  bandeja_sim.dvc
plan/  (README, 01..07, ESTADO.md)
```

`DECISIONES.md` ya tiene las decisiones 1, 2, 3, 4 y 4b; las 5 a 11 están "Pendiente" en su índice.
Cada fase completa las suyas.

## 4. Datos: hechos verificados

- `train.csv`: del 2013-01-01 al 2017-08-15, 54 tiendas × 33 familias = 1,782 series. Faltan los
  25 de diciembre de todos los años.
- Tiendas que abren tarde (ventas en 0 antes): 20, 21, 22, 29, 36, 42, 53 (2013–2015) y **52 el
  2017-04-20**.
- En 2017 hay 161 combinaciones tienda-día con venta total 0 (53 de ellas el 2017-01-01).
- `oil.csv`: solo días hábiles, del 2013-01-01 al 2017-08-31, con 43 valores vacíos.
- `transactions.csv`: tiene huecos (12,097 tienda-días en 2017 de 12,258 posibles).
- `holidays_events.csv`: del 2012-03-02 al 2017-12-26. `type` ∈ {Holiday, Event, Additional,
  Transfer, Bridge, Work Day}; `locale` ∈ {National, Regional, Local}. La llave única es
  **(date, locale_name, description)**; `date` sola tiene 35 duplicados.
- En 2017, ~45% de las filas tienen `onpromotion > 0`.

## 5. Bandeja simulada y carga histórica (contrato de entrada)

**Carga histórica** `data/historico/<fuente>.csv`: todo lo entregado hasta el **2017-01-01**.

| Fuente | Columnas | Llega (regla de disponibilidad) |
|---|---|---|
| `ventas` | date, store_nbr, family, sales | D+1 |
| `promociones` | date, store_nbr, family, onpromotion | D−10 (anticipada) |
| `transacciones` | date, store_nbr, transactions | D+1 a D+3 (variable) |
| `petroleo` | date, dcoilwtico (puede venir vacío) | D+1, solo días hábiles |
| `feriados` | date, type, locale, locale_name, description, transferred | un archivo por trimestre, entregado al inicio del trimestre anterior |
| `tiendas` | store_nbr, city, state, type, cluster | el histórico tiene 53 tiendas (sin la 52); `tiendas_2017-04-13.csv` trae el maestro completo |

**Bandeja** `bandeja_sim/<fecha_entrega>/<fuente>_<fecha_dato>.csv`, con entregas del 2017-01-02 al
2017-09-01 (853 archivos):

- **`fecha_entrega` = nombre de la carpeta** = momento en que el archivo estuvo disponible. Nunca
  se usa el mtime.
- En `feriados`, `fecha_dato` es el **inicio del trimestre** que cubre el archivo (por ejemplo
  `feriados_2017-07-01.csv` llega en `2017-04-01/`). En `tiendas`, es la fecha del snapshot.
- Una **corrección** es el mismo nombre de archivo en una carpeta posterior.
- `bandeja_sim/_escenarios.csv` documenta los escenarios inyectados (en las filas `faltante`, `fecha_entrega` es la fecha en que **debió** llegar; ese archivo no existe). Todo archivo que empiece con
  `_` **no** es dato del sistema de origen y la ingesta debe ignorarlo.
- Escenarios (de `config/simulador.yaml`):

| Escenario | Fuente / fecha_dato | Entrega | Qué debe pasar |
|---|---|---|---|
| corrección | ventas 2017-02-03 | 2017-02-10 (5% de filas ×1.3) | versión 2; recalcular monitoreo |
| faltante | transacciones 2017-02-20 | nunca | sin falla |
| tardío | ventas 2017-03-09 | 2017-03-15 (esperada el 03-10) | el corte 2017-03-13 no la ve; el siguiente sí |
| duplicado idéntico | ventas 2017-04-05 | 2017-04-07 | se ignora (mismo sha256) |
| alta de tienda | tiendas 2017-04-13 | 2017-04-13 | la 52 pasa a ser válida desde ahí |
| corrección | petroleo 2017-05-02 | 2017-05-09 (×1.05) | versión 2 |
| inválido + reentrega | ventas 2017-05-10 | 05-11 negativos → 05-12 válido | cuarentena, luego versión válida |
| inválido | transacciones 2017-06-05 | 06-08, sin la columna `transactions` | cuarentena |
| inválido + reentrega | ventas 2017-06-21 | 06-22 filas duplicadas → 06-23 válido | cuarentena, luego válido |
| faltante | ventas 2017-07-04 | nunca | modo degradado / "real pendiente" |
| inválido | promociones 2017-07-20 | 07-10, tienda 999 | cuarentena |
| inválido + reentrega | ventas 2017-07-26 | 07-27 con `N/A` en sales → 07-28 válido | cuarentena, luego válido |

Regenerar: `python tools/simulate_bandeja.py --limpiar`. Es determinista y `--hasta` amplía la
bandeja sin alterar lo ya generado.

## 6. Contratos compartidos entre fases

Estas rutas y nombres conectan las fases. Si una fase anterior los implementó distinto, sigue al
código y actualiza esta tabla en tu PR. Esta tabla **reemplaza** a los nombres tentativos de
`plan/02-arquitectura.md` (por ejemplo, `data/processed` pasó a ser `data/limpio` y `cutoff=` pasó
a ser `corte=`).

### Rutas de datos (todo bajo DVC; raíz configurable con la variable `REPOSICION_DATA`, por defecto `data/`)

| Ruta | Escribe | Contenido |
|---|---|---|
| `data/historico/` | fase 2 (simulador) | carga histórica (CSV por fuente) |
| `data/raw/<fecha_entrega>/<archivo>` | ingesta (F3) | copia byte a byte de cada archivo leído de la bandeja |
| `data/ledger/ingesta.parquet` | ingesta (F3) | una fila por archivo visto (ver F3) |
| `data/limpio/<fuente>.parquet` | ingesta (F3) | todas las versiones válidas + `fecha_dato`, `fecha_disponible`, `version`, `origen` |
| `data/backtest/<modelo>/corte=YYYY-MM-DD/` | F4/F5 | `predicciones.parquet` (store_nbr, family, origen, fecha_objetivo, h, y, `q…`) y `metricas.parquet` (nivel/clave: global y por origen) |
| `data/models/<modelo_id>/` + `data/models/registro.parquet` | F5 | modelos entrenados y su historial de promoción |
| `data/published/corte=YYYY-MM-DD/rev=N/` | F5/F6 | `pronostico.parquet`, `pedido.parquet`, `manifest.json` |
| `data/monitoring/` | F7 | métricas por corte y reportes |
| `reports/` (en git, pequeño) | F5 y F8 | comparación de modelos y evidencias |

La bandeja se ubica con la variable `REPOSICION_BANDEJA` (por defecto `bandeja_sim/`).

### Utilidades compartidas (se crean en F3 y se usan en todas las fases siguientes)

- `reposicion.rutas`: `dir_data()` y `dir_bandeja()` resuelven las variables de entorno. Solo los
  llaman la CLI y los DAGs; la lógica recibe las rutas por parámetro.
- `reposicion.io.escribir_parquet(df, ruta)`: parquet determinista (esquema explícito, sin
  metadatos de pandas, atómico). Úsalo para **todo** parquet. La fecha centinela "siempre
  disponible" es `date(1900, 1, 1)`.
- `tests/sinteticos.py` + `tests/conftest.py`: datos tipo Kaggle sintéticos y una bandeja
  sintética con escenarios (fixtures `kaggle_sintetico`, `config_sintetica` y
  `bandeja_sintetica`).

### Configuración (`config/`)

| Archivo | Fase | Contenido |
|---|---|---|
| `simulador.yaml` | F2 | solo para el simulador |
| `sources.yaml` | F3 | fuentes, columnas, llaves, disponibilidad histórica, tolerancias |
| `validation.yaml` | F3 | umbrales de reglas blandas y del modo degradado |
| `model.yaml` | F4 | horizonte, cuantiles, origenes, ventanas, parámetros de modelos |
| `business.yaml` | F4 | costos de quiebre/merma por grupo de familias, cobertura, lead time |
| `promotion.yaml` | F5 | criterio champion/challenger |
| `operacion.yaml` | F6 | fechas de inicio/fin de la operación, push remoto |

Carga siempre con `reposicion.config.cargar_yaml` + un modelo pydantic, como en
`simulador.cargar_config`.

### Fecha de corte

Lunes. Un pronóstico con corte T usa todo lo que tenga `fecha_disponible <= T` (las entregas del
mismo día T cuentan, porque el flujo corre de madrugada después de la entrega nocturna) y pronostica
T, T+1, …, T+13 (h = 1..14). La ventas conocidas llegan hasta T−1.

## 7. Decisiones ya tomadas (no volver a preguntar)

- Remoto DagsHub; los docentes necesitarán su propio token (pendiente confirmarlo con ellos).
- Corte semanal, horizonte de 14 días, cuantiles con LightGBM global (un modelo por cuantil).
- Bandeja simulada (hasta que llegue la oficial), con una carpeta por fecha de entrega y
  promociones como fuente separada anticipada.
- pip + venv; proyecto individual.
- Airflow versiona sus salidas con DVC y deja el registro en git en una rama `publicaciones` que
  **no** es `main` (ver F6 para el cómo).
- F3: las promociones de una tienda nueva solo se entregan desde la fecha de su maestro (el simulador descarta las anteriores); la tienda 52 tiene promociones desde la entrega del 2017-04-13. Ledger real: 853 archivos = 847 válidos, 5 cuarentena, 1 duplicado.
- F3: en memoria las fechas son `datetime64[ns]`; en disco `date32`. Leer parquet con `almacen.leer_parquet`; `asof` devuelve `fecha_dato` y `fecha_disponible`; `fechas_faltantes` recibe `dias_sin_operacion` como parámetro opcional.
- Supuestos: inventario inicial = 0 (configurable); `sales` = demanda observada (censurada por
  quiebres); deep learning descartado por costo/beneficio.

## 8. Trampas conocidas

- **`N/A` → NaN:** `pd.read_csv` convierte `N/A`, `NA`, `null` y vacío en NaN. Para validar, lee la
  bandeja con `dtype=str, keep_default_na=False` y convierte los tipos tú mismo.
- **pandas 3:** el dtype por defecto de texto es `str` (respaldado por pyarrow) y Copy-on-Write
  está activo (no encadenes asignaciones). `Timestamp.dayofweek` está deprecado: usa
  `day_of_week`.
- **CI que no arranca:** en este repo pasó que el primer push de una rama no disparó el workflow;
  un commit vacío lo destrabó.
- **Rutas con espacios:** la raíz del repo tiene espacios (`.../Cuarto Trimestre 2026/...`). Cita
  siempre las rutas.
- **zsh:** las URLs con `?` en `gh api` van entre comillas.
- **Datos reales grandes:** las ventas del histórico tienen 2.5 millones de filas. Usa
  `float32`/`category` donde se pueda y mide memoria y tiempo.
- **`*.csv` y `*.parquet` están en `.gitignore`:** a propósito.
- **LightGBM en macOS:** necesita OpenMP (`brew install libomp`); sin él, `import lightgbm` falla con
  `libomp.dylib`. En Docker, `libgomp1`. Los procesos lanzados con `nohup`/`env`/`sh` pierden
  `DYLD_FALLBACK_LIBRARY_PATH` (SIP): si hay que usar un workaround de libomp, exporta la variable
  dentro del mismo comando de Python, no a través de esos binarios.
- **DVC y archivos ignorados:** `dvc add` falla si el `.dvc` resultante queda ignorado por git
  (`FileIsGitIgnored`). Agrega las rutas de salida a `data/.gitignore` (lo hace DVC) y deja los
  `.dvc` fuera de los patrones ignorados.

## 9. Fase 4: lo que quedó implementado (para las fases 5 a 7)

- `parametros.cargar_configs(dir_config)` devuelve `Configs(modelo, negocio, fuentes)`; es el `cfgs` de
  `ejecutar_backtest`. `modelos.fabrica(nombre, cfgs)` crea modelos nuevos: registra ahí el LightGBM.
- `features.construir_features(datos, origenes, cfg_modelo, cfg_fuentes, con_objetivo)`: 1.28 M filas
  para 52 orígenes en ~1.5 s. Las columnas categóricas (`store_nbr`, `family`, `city`, `state`,
  `type`, `cluster`) usan las categorías de los datos recibidos; en la fase 5 alinéalas con las del
  entrenamiento antes de predecir (la tienda 52 solo existe en el maestro desde 2017-04-13).
- Cuantiles requeridos: [0.10, 0.40, 0.50, 0.67, 0.90, 0.91] (τ redondeado a 2 decimales en
  `pedido.cuantil_critico`). `pedido.calcular_pedido` espera `corte`, `store_nbr`, `family`,
  `fecha_objetivo` y columnas `q…`.
- Piso del baseline (corte 2017-08-14): WAPE 0.1425, RMSLE 0.4516, cobertura P10–P90 0.8431,
  costo total 2,991,009, fill rate 0.9741, merma 0.1062.
- Las distancias a feriados se acotan a 30 días (ver `DECISIONES.md` §8).

## 10. Fase 5: lo que quedó implementado (para las fases 6 a 8)

- **Configs:** `parametros.Configs(modelo, negocio, fuentes, validacion, promocion)`;
  `cargar_configs(dir)` carga los cinco YAML (`validation.yaml` y `promotion.yaml` incluidos).
  `ConfigModelo` tiene ahora `lightgbm`, `lightgbm_semanal` y `objetivo_transformado`.
- **Modelos:** `modelos.fabrica("baseline"|"lgbm", cfgs)`; `modelos.clase_de(tipo)`.
  `LightGBMCuantiles(cfg_modelo, cuantiles)` entrena un cuantil por cada valor de
  `cuantiles_requeridos`. `aplicar_regla_ceros` vive en `modelos/base.py`.
- **Registro** (`registro.py`): `registrar(modelo, tipo, corte, metricas, dir_data, *, config_hash,
  huella) -> modelo_id`, `anotar_decision(modelo_id, Decision, fecha_promocion, dir_data)`,
  `evaluar_promocion(m_chall, m_champ, cfg_promocion) -> Decision(promover, motivos)`,
  `champion_vigente(corte, dir_data) -> str | None`, `cargar_modelo(modelo_id, dir_data)`,
  `leer_registro(dir_data)`. `fecha_promocion` = corte de la evaluación (nunca el reloj).
  `registro.parquet`: modelo_id, tipo, corte_entrenamiento, evaluado_en, promovido, fecha_promocion,
  orden_promocion, motivos, costo_total, wape, cobertura_p10_p90, fill_rate.
- **Entrenamiento:** `entrenamiento.entrenar_y_evaluar(corte, dir_data, cfgs) -> Decision` e
  `entrenar_modelo(tipo, corte, dir_data, cfgs)`. Idempotente por `modelo_id` (config + huella).
  Lee `asof(corte)`: **la ingesta debe estar hecha hasta `corte` antes de llamarla** (en Airflow,
  `asegurar_ingesta(corte)` también en el DAG `entrenamiento`).
- **Publicación:** `publicacion.pronosticar_corte(corte, dir_data, cfgs, revision=1) -> Path` (el
  directorio `rev=N`). Excepciones: `DatosInsuficientes` (anómalo: que falle la tarea),
  `PublicacionInmutable` (la revisión existe con otras entradas, config o modelo) y
  `PublicacionInvalida` (no pasa los checks). Mismas entradas → no-op. Sin champion vigente entrena
  el baseline en el momento y lo anota en `advertencias`. Variable `REPOSICION_GIT_COMMIT` para el
  commit dentro de Docker.
- **Manifiesto:** corte, revision, modelo_id, calidad (`ok`|`degradada`), advertencias, git_commit,
  huella_entradas, sha256_business, sha256_model (sha256 de la configuración canónica, no del
  YAML), filas_pronostico, series, sha256_archivos. Sin timestamps. `asof.huella_entradas(corte,
  dir_data)` calcula la huella.
- **Pronóstico:** `pronostico.parquet` = corte, store_nbr, family, fecha_objetivo, h, un `q…` por
  cuantil requerido (q0.10, q0.40, q0.50, q0.67, q0.90, q0.91), modelo_id; `pedido.parquet` = salida
  de `calcular_pedido` + modelo_id.
- **CLI:** `entrenar --corte`, `comparar --corte` (escribe `reports/comparacion_modelos.md`),
  `pronosticar --corte [--revision N]`.
- **Reentrenamiento:** mensual (primer lunes) + manual, criterio multicriterio en
  `config/promotion.yaml`. La variante "cuantil de demanda semanal" se evaluó y no se adoptó
  (+9.1% de costo); no existe en la publicación.
- **Métricas verificadas (corte 2017-08-14):** baseline WAPE 0.1425 / costo 2,991,009; LightGBM
  WAPE 0.1207 / cobertura 0.799 / costo 2,379,594 (-20.4%) / fill rate 0.9724. Backtest completo
  de LightGBM: ~10 min (8 orígenes × 6 cuantiles, 4 hilos); baseline 5 s.
