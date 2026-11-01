# Decisiones técnicas y de producto

Cada decisión registra el contexto, las alternativas consideradas, la decisión tomada y su
justificación. Las decisiones que el enunciado destaca están en las §5 (disponibilidad de la
información en el tiempo), §6 (validación de datos) y §7 (correcciones); la §12 cierra el ciclo con
el seguimiento y las revisiones, y la §13 con la entrega. Al final están las
[limitaciones conocidas](#limitaciones-conocidas).

## Índice

| # | Decisión | Estado |
|---|---|---|
| 1 | Cadencia semanal y horizonte de 14 días | Aceptada |
| 2 | Remoto DVC en DagsHub | Aceptada |
| 3 | Gestión de dependencias con pip + venv | Aceptada |
| 4 | Flujo Git: `main` protegida, ramas y PRs con CI | Aceptada |
| 4b | Simulación del sistema de origen (bandeja) y carga histórica | Aceptada |
| 5 | Disponibilidad de la información en el tiempo (as-of) | Aceptada |
| 6 | Validación de datos: reglas duras vs. blandas | Aceptada |
| 7 | Manejo de correcciones | Aceptada |
| 8 | Modelos, validación temporal y métricas | Aceptada (baseline y LightGBM) |
| 9 | Pedido sugerido (newsvendor) | Aceptada |
| 10 | Criterio de reemplazo de modelo, registro y publicación offline | Aceptada |
| 11 | Orquestación con Airflow y versionado de publicaciones | Aceptada |
| 12 | Seguimiento del desempeño, revisiones por corrección y alertas | Aceptada |
| 13 | Reproducibilidad y entrega (fase 8) | Aceptada |
| 14 | Correcciones de la revisión independiente | Aceptada |
| — | Limitaciones conocidas | Documentadas |

---

## 1. Cadencia semanal y horizonte de 14 días

- **Contexto:** operaciones pide una sugerencia de pedido cada semana. El enunciado deja el horizonte
  a criterio del equipo.
- **Alternativas:** horizonte de 7 días (solo la semana del pedido); 16 días (igual que Kaggle).
- **Decisión:** corte cada lunes y pronóstico diario de los 14 días siguientes.
- **Justificación:** el pedido cubre 7 días, y los 7 restantes dan margen para un lead time
  configurable y para ver la semana siguiente sin cambiar el modelo.

## 2. Remoto DVC en DagsHub

- **Contexto:** el remoto tiene que ser compartido y el equipo docente debe poder hacer `dvc pull`.
- **Alternativas:** S3/GCS (credenciales y costo), Google Drive (OAuth frágil para terceros).
- **Decisión:** DagsHub como remoto S3-compatible (`s3://dvc` con endpoint
  `https://dagshub.com/ManuelMiranda99/motor-reposicion.s3`) ligado al repo de GitHub. Las
  credenciales van solo en `.dvc/config.local` (fuera de git) y se configuran con
  `tools/dvc_auth.sh`.
- **Justificación:** es gratuito, se integra con el repo de GitHub y la autenticación es un solo token.
- **Limitación encontrada:** DagsHub exige iniciar sesión para cualquier acceso, incluso de lectura a
  repos públicos. Se probó `dvc pull` anónimo desde un clon limpio, por S3 (con
  `allow_anonymous_login`) y por HTTP (`.dvc`), y ambos devuelven 401. Por eso quien evalúe necesita
  una cuenta gratuita de DagsHub y su propio token. Como el repo es público, ese token le da lectura;
  no hace falta invitarlo como colaborador.
- **Alternativa descartada:** un bucket S3/R2 con lectura pública permitiría `dvc pull` sin cuenta,
  pero exige una cuenta cloud con tarjeta y administrar políticas del bucket. Se descartó para
  mantener la infraestructura mínima.

## 3. Gestión de dependencias con pip + venv

- **Contexto:** se necesita el mismo entorno en local, en CI y en la imagen de Airflow, sin modificar
  el Python global.
- **Alternativas:** uv, Poetry.
- **Decisión:** `python -m venv .venv` con `requirements.txt` (runtime) y `requirements-dev.txt`
  (desarrollo), ambos con versiones fijadas con `==`. `dvc[s3]` va en runtime porque Airflow lo usa
  para versionar las publicaciones.
- **Justificación:** es el estándar más simple y la imagen de Airflow lo consume directamente
  (`pip install -r requirements.txt`). Las versiones fijadas dan reproducibilidad.

## 4. Flujo Git: `main` protegida, ramas y PRs con CI

- **Contexto:** el enunciado exige trabajo con ramas y PRs, la rama principal protegida y pytest en
  cada PR.
- **Decisión:** `main` exige PR con el check `lint-y-pruebas` en verde y no permite force-push ni
  borrado. Como el proyecto es individual, no se exige aprobación de otra persona.
- **Justificación:** garantiza que todo cambio en `main` pasó las pruebas automatizadas.

## 4b. Simulación del sistema de origen (bandeja) y carga histórica

- **Contexto:** el equipo docente publicará una carga histórica y una bandeja con archivos por fecha
  y fuente, con frecuencias y anticipaciones distintas y con correcciones. Mientras no estén
  disponibles se necesita un sustituto realista para desarrollar y probar.
- **Decisión:** un simulador determinista (`src/reposicion/simulador.py`,
  `tools/simulate_bandeja.py`, `config/simulador.yaml`) que, a partir de los CSV de Kaggle, genera:
  - **Bandeja** `bandeja_sim/<fecha_entrega>/<fuente>_<fecha_dato>.csv`. La fecha en que un archivo
    estuvo disponible se toma de la **carpeta**, no del mtime (que no es reproducible). Una
    corrección es el mismo nombre de archivo en una carpeta posterior.
  - **Carga histórica** `data/historico/<fuente>.csv`: todo lo que ya se había entregado al
    2017-01-01, aplicando las mismas reglas de entrega (no un corte arbitrario por fecha).
- **Fuentes y anticipación:**

  | Fuente | Llega | Comentario |
  |---|---|---|
  | `ventas` (sales) | D+1 | |
  | `promociones` (onpromotion) | D−10 | Separada de ventas: el plan comercial se conoce de antemano |
  | `transacciones` | D+1 a D+3 | Lag variable (determinista por fecha) |
  | `petroleo` | D+1 | Solo días hábiles |
  | `feriados` | Un trimestre antes | Un archivo por trimestre |
  | `tiendas` | En la fecha de alta | Maestro completo; la tienda 52 (abre 2017-04-20) se da de alta el 2017-04-13 |

- **Escenarios inyectados** (documentados en `bandeja_sim/_escenarios.csv`): archivo que nunca
  llega, llegada tardía que cruza un corte, correcciones de ventas y petróleo, duplicado idéntico y
  archivos inválidos (ventas negativas, columna faltante, filas duplicadas, tienda desconocida,
  tipo inválido), algunos con reentrega válida posterior. Además están los escenarios naturales de
  los datos: tiendas cerradas el 1 de enero, transacciones con huecos y petróleo con faltantes.
- **Alternativas:** dejar `onpromotion` dentro de ventas (como Kaggle), descartado porque no habría
  información de promociones para el horizonte; usar una bandeja plana con ambas fechas en el
  nombre, descartado por ser menos legible.
- **Justificación:** la aleatoriedad de cada archivo depende solo de (semilla, fuente, fecha), así
  que el resultado es reproducible y la bandeja puede "ampliarse" (`--hasta`) sin alterar lo ya
  generado. Cuando llegue la bandeja oficial solo cambia el adaptador de ingesta.
- **Versionado:** `data/historico` y `bandeja_sim` se versionan con DVC (`data/historico.dvc`,
  `bandeja_sim.dvc`). La bandeja vive fuera de `data/` porque representa un sistema externo.

## 5. Disponibilidad de la información en el tiempo (as-of)

- **Contexto:** el pronóstico del corte T solo puede usar lo que existía en T; un dato corregido o
  tardío debe verse distinto según la fecha de consulta.
- **Alternativas:** usar el `mtime` del archivo (no es reproducible: cambia al copiar o restaurar) o
  la fecha en que se ingirió (depende de cuándo se corrió el flujo, no de cuándo llegó el dato).
- **Decisión:** cada fila del almacén limpio tiene `fecha_disponible` = la carpeta de entrega de la
  bandeja. `asof(fuente, T)` filtra `fecha_disponible <= T` (las entregas del propio T cuentan,
  porque el flujo corre de madrugada tras la entrega nocturna), conserva la versión máxima por
  `fecha_dato` y, en snapshots (`tiendas`), solo el más reciente. La fecha de corte siempre llega
  como parámetro.
- **Carga histórica:** sus filas no tienen fecha de entrega, así que se les aplica la regla de su
  fuente (ventas D+1, transacciones D+3 —el peor caso—, petróleo D+1, promociones D−10, feriados un
  trimestre antes, tiendas siempre disponibles con la fecha centinela 1900-01-01). Alternativa
  descartada: todo disponible el 2017-01-01, porque los backtests de 2016 tendrían leakage.
- **Almacén limpio:** un parquet por fuente con todas las versiones, reconstruido de forma
  determinista desde histórico + ledger + `data/raw` (idempotente por construcción). Alternativa
  descartada: particionar por `fecha_dato`, más complejo de mantener idempotente.
- **Maestro de tiendas durante la ingesta:** cada archivo se valida contra el último snapshot válido
  con `fecha_entrega <=` la del archivo (nunca `<= hasta`), para que ingerir por partes y de una vez
  dé lo mismo. Consecuencia: el origen no puede planificar promociones de una tienda antes de entregar
  su maestro, y se corrigió el simulador para respetarlo (las promociones de la tienda 52 empiezan
  en la entrega del 2017-04-13).
- **Prueba clave:** `test_asof_sin_leakage` ingiere la bandeja completa y una truncada en T y exige
  `asof(f, T)` idéntico para todas las fuentes.

## 6. Validación de datos: reglas duras vs. blandas

- **Contexto:** los archivos inválidos no deben contaminar los resultados, pero las situaciones
  esperadas del negocio no deben tumbar el flujo.
- **Decisión:** pandas puro (`validacion.py`), leyendo todo como texto para controlar `N/A` y vacíos.
  - *Duras* (cuarentena, el archivo queda en `data/raw` y en el ledger con sus errores): vacío o
    ilegible, columna requerida ausente, valor no convertible, `date` distinta de `fecha_dato`,
    llave duplicada, negativos, tienda fuera del maestro vigente, familia desconocida.
  - *Blandas* (advertencia): columnas extra (se descartan), ventas incompletas respecto a
    tiendas × familias, tienda con ventas totales en 0 (cerrada), petróleo vacío.
- **Alternativas descartadas:** pandera (dependencia nueva para reglas que son más claras como
  funciones: fecha del nombre, maestro vigente, llave); esquema estricto (cualquier columna extra a
  cuarentena); cuarentena por completitud mínima (queda disponible como `completitud_min_ventas` en
  `config/validation.yaml`, apagado, porque una tienda cerrada puede faltar legítimamente).
- **Modo degradado:** `ultima_fecha_disponible` (fuente detenida) y `fechas_faltantes` (huecos
  intermedios en una ventana, excepto `dias_sin_operacion`) se consumen en la fase 5; un hueco da
  advertencia, no falla. No se implementó una regla de variación de volumen: necesita historia
  dentro de la validación y complicaría la idempotencia (mejora futura).

## 7. Manejo de correcciones

- **Contexto:** el mismo archivo puede volver a llegar con otro contenido, igual o inválido.
- **Decisión:** el ledger (`data/ledger/ingesta.parquet`) registra una fila por archivo con
  `(archivo, sha256)` como llave de idempotencia. Versión por `(fuente, fecha_dato)`: primer válido =
  1; mismo sha256 que la última versión válida = `duplicado` (misma versión); contenido distinto =
  versión + 1 y `es_correccion` (aunque coincida con una versión más vieja: la fuente lo reenvió
  como vigente); inválido = `cuarentena` (versión 0). `es_tardio` marca la primera versión válida
  entregada después de `fecha_dato + lag_esperado` (sin tolerancia; ver §14, A1).
- **Correcciones y publicados:** `correcciones_entre` y `cortes_afectados` (funciones puras) dicen
  qué cortes ya calculados cambiarían. Un publicado **nunca se reescribe**. En el seguimiento
  semanal (fase 7, `revisiones.emitir_revisiones`): (a) el seguimiento se recalcula siempre con el
  dato corregido (lee las ventas as-of el corte de evaluación); (b) si el corte afectado sigue
  **vigente** (`corte_eval <= P + horizonte - 1`) y `reemitir_si_corrige: true`
  (`config/monitoreo.yaml`), se emite `rev=N+1` con `pronosticar_corte(P, revision=N+1,
  datos_hasta=corte_eval)`: el origen y el horizonte siguen siendo los de P, pero los datos son los
  visibles en `corte_eval`, y el modelo es el champion vigente en P. El manifiesto registra
  `revision_de`, `motivo`, `datos_hasta` y `emitido_en` (= el corte en que se detectó). Lo
  pendiente se deriva del ledger contra cada publicación (§14, A2); un corte cuyo horizonte ya
  terminó solo recalcula su seguimiento. Es idempotente: si ya existe una revisión con
  `datos_hasta == corte_eval` no se emite otra (no hay `rev=N+2` al re-correr) y
  `pronosticar_corte` es un no-op con las mismas entradas. Una revisión puede ser numéricamente
  idéntica a la anterior cuando la corrección no entra en las features (verificado con el petróleo
  del 2017-05-02: el modelo solo usa el último valor ≤ O−1); se emite igual y queda trazada.
- **Archivo modificado en la bandeja:** si un archivo ya ingerido cambia de contenido en su misma
  ruta, se ignora con una advertencia (una corrección real llega en una carpeta posterior).
- **Alternativa descartada:** sobrescribir la fila anterior (se perdería qué se sabía en cada corte).

## 8. Modelos, validación temporal y métricas

- **Contexto:** hace falta un piso de comparación y una validación que no filtre el futuro.
- **Features:** ancladas al origen O (el corte), sin recursión y con la misma regla de
  disponibilidad por fuente en entrenamiento e inferencia (ventas hasta O−1, transacciones hasta
  O−3, petróleo hasta O−1 con forward-fill, promociones del día objetivo solo hasta O+10; en
  entrenamiento se enmascaran igual que en inferencia, así h = 12..14 trae la promoción en NaN en
  ambos). Las distancias a feriados se acotan a 30 días: los feriados se conocen un trimestre antes,
  pero acotar garantiza que lo visto en entrenamiento coincida con lo visto en inferencia.
  Verificado con `test_features_iguales_en_entrenamiento_e_inferencia` y `test_features_sin_leakage`
  (esa prueba detectó un error real: el calendario de feriados no llegaba 30 días más allá del
  último día objetivo).
- **Baseline:** media de los últimos 4 días con el mismo día de semana; cuantiles con los residuos
  empíricos en espacio log por (familia, h), guardados en JSON (sin pickle). Regla de ceros: sin
  ventas en 56 días → pronóstico 0.
- **Validación:** rolling-origin con los últimos 8 lunes cuyos 14 días ya se conocen; cada origen
  entrena con las 52 semanas anteriores cuyo último día objetivo termina antes del origen. Mismos
  orígenes y misma ventana para todos los modelos. Alternativa descartada: k-fold aleatorio
  (mezcla pasado y futuro).
- **Datos revisados vs. as-of:** el backtest lee `asof(corte_final)`, es decir, datos con las
  correcciones ya aplicadas; la operación usa as-of estricto en cada corte. El backtest es por lo
  tanto ligeramente optimista frente a lo que ocurriría en vivo.
- **Métricas:** WAPE y RMSLE sobre la mediana, pinball por cuantil, cobertura P10–P90 y, sobre los
  pedidos, costo newsvendor, fill rate y % de unidades en merma. Una serie con ventas
  desconocidas (p. ej. el faltante del 2017-07-04) no cuenta en las métricas.
- **Resultado del baseline** (corte 2017-08-14, 199,584 predicciones): WAPE 0.143, RMSLE 0.452,
  cobertura P10–P90 84.3%, fill rate 97.4%, merma 10.6%. Es el piso que debe superar la fase 5.
  El WAPE queda por debajo del rango de referencia (0.2–0.5) porque pondera por volumen y las
  familias grandes son muy estables.

- **LightGBM (fase 5):** un `Booster` por cuantil (`objective=quantile`, `alpha=q`) sobre
  `log1p(y)`, con la predicción en `expm1` recortada a ≥ 0 y la misma regla de ceros del baseline
  (`aplicar_regla_ceros`, definida una sola vez en `modelos/base.py`). Cuantiles entrenados: los de
  reporte ∪ los τ del negocio (0.10, 0.40, 0.50, 0.67, 0.90, 0.91). Parámetros en
  `config/model.yaml`: `learning_rate 0.05`, `num_leaves 63`, `min_data_in_leaf 100`,
  `feature_fraction 0.8`, `lambda_l2 1.0`, 400 rondas, `num_threads 4`, `deterministic`,
  `force_row_wise`, semilla 2017; sin bagging ni early stopping, así que reentrenar con los mismos
  datos da el mismo modelo (verificado por `test_lgbm_determinista`). Las features son todas las
  del módulo `features` salvo el origen y el día objetivo; `store_nbr`, `family`, `city`, `state`,
  `type` y `cluster` son categóricas con **categorías fijas guardadas en el modelo** (una tienda o
  ciudad desconocida, como la tienda 52 si el modelo es anterior a su alta, pasa a "faltante" y no
  falla). Se guarda en el formato de texto nativo (`modelo_<q>.txt` + `meta.json`), sin pickle. El
  `Dataset` se construye una vez y se reutiliza en los seis cuantiles.
- **Costo de LightGBM (medido):** un origen del backtest (seis cuantiles, ~1.27 M filas) tarda
  ~75 s; el backtest completo de 8 orígenes, 606 s (~10 min) en un Mac de 10 núcleos con 4 hilos, por
  debajo del umbral de ~20 min, así que **se mantienen los 8 orígenes y las 400 rondas**. El
  baseline tarda 5 s y la variante semanal 23 s.
- **Resultado en el corte 2017-08-14** (mismo backtest, 199,584 predicciones por modelo; detalle en
  `reports/comparacion_modelos.md`):

  | Métrica | Baseline | LightGBM |
  |---|---|---|
  | WAPE | 0.1425 | 0.1207 (-15.3%) |
  | RMSLE | 0.4516 | 0.4000 |
  | Cobertura P10–P90 | 0.8431 | 0.7991 |
  | Costo de negocio total | 2,991,009 | 2,379,594 (-20.4%) |
  | Fill rate | 0.9741 | 0.9724 |
  | Merma | 10.6% | 6.0% |

  LightGBM mejora al baseline en todas las métricas de error y cuesta menos; el fill rate casi no
  cambia y la merma baja casi a la mitad. Cobertura ≈ 0.80 es la nominal de un P10–P90, es decir,
  mejor calibrado que el baseline (0.84, intervalos algo anchos). Las familias que empeoran
  (EGGS +10.6%, PREPARED FOODS +10.8%, BABY CARE +17.6%, BOOKS +84%) pesan en conjunto menos del
  2% del volumen.
- **Por qué no deep learning:** el costo (horas de entrenamiento y GPU) y el riesgo de
  irreproducibilidad no se justifican: LightGBM ya reduce 20% el costo con 10 min de backtest en
  CPU, entrena de forma determinista y sus archivos son texto plano. Con 1,782 series diarias y
  features tabulares, los árboles son el estándar fuerte; un modelo secuencial agregaría pesos
  binarios, GPU y menos interpretabilidad.
- **Una limitación conocida:** `sales` es demanda censurada por quiebres de stock (no hay datos de
  inventario); ningún modelo lo corrige.

## 9. Pedido sugerido (newsvendor)

- **Contexto:** convertir el pronóstico por cuantiles en una cantidad a pedir por tienda × familia.
- **Decisión:** τ = c_quiebre / (c_quiebre + c_merma) por grupo de familias, **redondeado a 2
  decimales** para que el modelo se entrene exactamente en el cuantil que usa el pedido. Tres
  grupos (`config/business.yaml`): perecederos (1.0 / 1.5, τ = 0.40), no perecederos (1.0 / 0.1,
  τ = 0.91) y default (1.0 / 0.5, τ = 0.67). El pedido es la suma de los cuantiles diarios τ sobre
  la cobertura (7 días, lead time 0, es decir h = 1..7), menos el inventario inicial (0, porque no
  hay datos de inventario), redondeada hacia arriba y nunca negativa.
- **Alternativas descartadas:** un solo grupo de costos (poco realista) y entrenar el cuantil τ de
  la demanda semanal (más correcto, pero agrega modelos; evaluada en la fase 5 y descartada, ver más abajo). La suma de
  cuantiles supone dependencia perfecta entre días y es, por tanto, conservadora.
- **Si τ no está entre las columnas** del pronóstico, se interpola linealmente entre los cuantiles
  vecinos y se registra una advertencia.

### Variante "cuantil de la demanda semanal" (evaluada en la fase 5)

- **Qué es:** un modelo LightGBM con objetivo = suma de las ventas de la cobertura (7 días) y una
  fila por (serie, origen), un cuantil por grupo de costos (0.40, 0.67, 0.91). Sus features son las
  del origen más agregados de la semana (suma de la media por día de semana, de las promociones y
  de los flags de feriado). Código en `modelos/semanal.py`; hiperparámetros propios en
  `config/model.yaml` (`lightgbm_semanal`).
- **Resultado** (mismos 8 orígenes, mismas series y solo los pedidos con los 7 días reales
  conocidos; `reports/comparacion_modelos.md`):

  | Pedido | Costo total | Fill rate | Merma |
  |---|---|---|---|
  | Baseline, suma de cuantiles diarios | 2,687,808 | 0.9750 | 10.9% |
  | LightGBM, suma de cuantiles diarios (vigente) | **2,121,607** | 0.9715 | 5.9% |
  | LightGBM, cuantil de la demanda semanal | 2,314,601 (+9.1%) | 0.9674 | 4.8% |

- **Decisión:** el pedido por defecto **no cambia**. La suma de cuantiles diarios es mejor en
  costo (9% menos) y en fill rate, y es la única que reutiliza los pronósticos diarios publicados
  (el pedido semanal exigiría otro modelo en el registro y en el manifiesto). La variante reduce la
  merma, pero a costa de más quiebres. Queda como mejora futura (por ejemplo, ajustar el τ del
  modelo semanal por grupo) y **no** está disponible en la publicación.
- **Nota metodológica:** la tabla global de métricas descarta los días sin dato real
  (p. ej. 2017-07-04) antes de armar el pedido; la comparación de la variante exige los 7 días
  reales, por eso sus costos totales difieren de los de la tabla global.

## 10. Criterio de reemplazo de modelo, registro y publicación offline

- **Contexto:** hace falta decidir cuándo un modelo nuevo reemplaza al vigente, poder reproducir
  qué modelo se habría usado en cada fecha y publicar sin riesgo de pisar resultados.
- **Criterio multicriterio** (`config/promotion.yaml`, `registro.evaluar_promocion`). El challenger
  reemplaza al champion solo si, en el **mismo backtest**: (1) el costo de negocio total baja ≥ 3%;
  (2) el WAPE no empeora más de 1% (relativo); (3) la cobertura P10–P90 está en [0.70, 0.90];
  (4) ninguna familia con más del 5% del volumen real empeora su costo más de 10%; (5) pasa los
  checks técnicos (sin NaN, sin negativos, cuantiles monótonos, sin duplicados). Cada regla deja un
  motivo en el registro. Alternativas: solo costo ≥ 3% (ignora que un modelo puede ganar en
  promedio y fallar en una familia grande) y umbrales propios.
- **Reentrenamiento:** mensual (primer lunes del mes) y manual; el pronóstico semanal usa el
  champion vigente (lo orquesta la fase 6). Alternativa: cada semana (más cómputo y más riesgo de
  inestabilidad entre publicaciones).
- **Registro** (`data/models/registro.parquet`, `data/models/<modelo_id>/`): `modelo_id` =
  `<tipo>-<corte>-<hash8 de config+huella de entradas>`. Registrar es idempotente. El champion
  inicial es el baseline: si no hay champion vigente, `entrenar_y_evaluar` lo registra y lo
  promueve con el motivo "champion inicial" y, a continuación, evalúa al challenger contra él.
- **`champion_vigente(corte)`:** último modelo con `promovido` y `fecha_promocion <= corte`
  (empate de fecha: el promovido después). `fecha_promocion` es **el corte de la evaluación**, no
  el reloj; así un backfill reproduce el modelo que se habría usado entonces. Es `<=` para que un
  modelo promovido el lunes T se use en el pronóstico del mismo lunes. Verificado con
  `test_champion_vigente_respeta_fecha`.
- **Publicación** (`data/published/corte=T/rev=N/`): `pronostico.parquet`, `pedido.parquet` y
  `manifest.json`. Escritura en `rev=N.tmp/` y `os.replace` del directorio. Modo degradado: si la
  última venta disponible es anterior a `corte - 1 - max_dias_sin_ventas` → `DatosInsuficientes`;
  huecos menores en ventas o una fuente no imprescindible atrasada más de su tolerancia →
  `calidad = "degradada"` con advertencias, sin fallar. Los checks (filas = series × 14, sin NaN,
  ≥ 0, monotonía) abortan la publicación si fallan.
- **Inmutabilidad:** una revisión existente con la misma `huella_entradas`, los mismos hashes de
  configuración y el mismo `modelo_id` es un no-op (bytes idénticos); si difiere en alguno, lanza
  `PublicacionInmutable` y no toca nada (`test_publicado_inmutable`). Incluir el `modelo_id` en la
  comparación es una decisión propia: un modelo distinto con las mismas entradas es otro pronóstico.
  La fase 7 decide cuándo emitir `rev=N+1`.
- **Manifiesto** (JSON, claves ordenadas, **sin timestamps**): `corte`, `revision`, `modelo_id`,
  `calidad`, `advertencias`, `git_commit` (`REPOSICION_GIT_COMMIT` o `git rev-parse HEAD`),
  `huella_entradas` (sha256 de las filas del ledger con `fecha_entrega <= corte`),
  `sha256_business` y `sha256_model` (sha256 de la configuración canónica en JSON, no del texto del
  YAML, para que comentarios y espacios no cuenten como cambios), `filas_pronostico`, `series` y
  `sha256_archivos`. `git_commit` no entra en la comparación de idempotencia: repetir el corte desde
  otro commit con las mismas entradas no reescribe la publicación.

## 11. Orquestación con Airflow y versionado de publicaciones

- **Contexto:** hay que orquestar la ingesta, el reentrenamiento, el pronóstico y el seguimiento
  sin poner lógica en los DAGs, de forma idempotente, con backfill y sin ensuciar el árbol de
  trabajo del desarrollador (el repo se monta en el contenedor y `main` está protegida).
- **Airflow 3.3.2, `LocalExecutor`** (imagen `apache/airflow:3.3.2-python3.11`, versión fijada por el
  usuario). Compose derivado del oficial, sin Celery/Redis: un solo host y un pool de un slot
  hacen innecesario un worker distribuido. La imagen agrega `libgomp1` (LightGBM), `git` y las
  dependencias de `requirements.txt` (`pip check` sin conflictos con pandas 3.1.0, numpy 2.4.6 y
  pydantic 2.14.1).
- **Cuatro DAGs con schedule por tiempo, sin Assets.** En Airflow 3, las ejecuciones disparadas por
  un Asset no tienen `logical_date`, y aquí todo depende de la fecha de corte. Con un cron,
  `logical_date` es el instante del disparo (verificado en el scheduler real: `scheduled__2017-01-09T05:00:00`
  → corte 2017-01-09), así que el corte es `logical_date.date()`. Alternativa descartada: un solo DAG
  semanal (cubre peor "un DAG por etapa").
- **Periodo no publicado:** `.env` con `BANDEJA_PATH`, `REPOSICION_INICIO` y `REPOSICION_FIN` (tienen
  prioridad sobre `config/operacion.yaml`); `catchup=True`, así que basta despausar los DAGs.
  `end_date` es las 23:59:59 del último día para que el corte de `REPOSICION_FIN` sí corra.
  Alternativa: disparo manual con parámetros (más pasos para el docente).
- **Reentrenamiento:** `0 4 * * 1` + `short_circuit` que deja pasar solo el primer lunes del mes
  (`es_primer_lunes`). No se usa `0 4 1-7 * 1`: cron combina día del mes y de la semana con O.
  También se puede disparar a mano con `forzar=true`.
- **`asegurar_champion` (decisión propia, no está en la referencia):** en un backfill los cuatro DAGs
  corren sin orden entre sí. Si el pronóstico del lunes T corriera antes que el reentrenamiento de
  T, usaría un champion distinto del que habría tenido en producción, y al reejecutarlo daría
  `PublicacionInmutable`. Para que el resultado no dependa del orden, `pronostico_semanal` asegura
  (con la misma función idempotente, `entrenar_y_evaluar`) la evaluación del último primer lunes
  `<= T`. Si el DAG `entrenamiento` ya la hizo, es un no-op (`ya fue evaluado`). Alternativas: un
  `ExternalTaskSensor` (se cuelga si se pausa el otro DAG) o confiar en el orden del scheduler
  (no determinista). Un reentrenamiento manual fuera de calendario sí afecta a los cortes
  posteriores: es lo que significa "manual".
- **Cada DAG asegura su ingesta** (`asegurar_ingesta(corte)`): `asof(corte)` lee el almacén limpio y
  `ingestar` es idempotente y no depende del orden; así ningún DAG depende de otro.
- **Pool `escritura_datos` (1 slot):** todo lo que escribe o lee `data/`, DVC o git va serializado.
  Solo las tareas `publicar_remoto_*` (red) se reintentan (2 veces, 1 minuto); la lógica no, porque
  un error de lógica no es transitorio. `DatosInsuficientes` y `PublicacionInmutable` fallan sin
  reintento (`AirflowFailException`); la cuarentena no falla.
- **Versionado con *plumbing* de git** (`versionado.py`): `dvc add` de las salidas y commit en
  `refs/heads/publicaciones` con un índice temporal (`GIT_INDEX_FILE`), sin checkout; el árbol de
  trabajo y el índice del desarrollador no se tocan (`core.autostage = false`). Autor fijo y fecha
  = el corte: mismo contenido → mismo commit; árbol igual al del padre → no-op. El commit lleva los
  `.dvc` (estado acumulado de `data/`) y `registro/<corte>/<evento>.json` con contenido
  determinista del evento (manifiestos del corte, decisiones del modelo). Alternativas: commitear
  a `main` (protegida, ensucia el árbol) o un worktree aparte (más piezas móviles).
- **`versionar` y `publicar_remoto` son dos tareas** (la referencia las junta): el commit local no
  se reintenta y el push de red sí.
- **`push_remoto: auto`:** con `GITHUB_TOKEN`, `git push` de `publicaciones` (token por entorno
  `http.extraheader`, no por argv ni en el log); con `DAGSHUB_TOKEN`, `dvc push`. Sin credenciales,
  warning y el commit local; nunca falla por eso. `siempre` y `nunca` existen en la configuración.
  Un token vacío en el `.env` cuenta como ausente.
- **Ingesta diaria sin versionar:** el commit ocurre en los eventos semanales/mensuales; como los
  `.dvc` son acumulados, igualmente capturan lo ingerido (evita 225 commits y `dvc add` diarios).
- **Seguimiento:** `evaluar_publicados` es un stub explícito hasta la fase 7.

## 12. Seguimiento del desempeño, revisiones por corrección y alertas

- **Contexto:** hay que comparar lo publicado con las ventas que van llegando, reaccionar a las
  correcciones sin tocar lo publicado y avisar si el modelo se degrada.
- **Seguimiento (`seguimiento.evaluar_publicados`).** Recálculo completo y determinista as-of
  `corte_eval`: une cada publicación `(corte, rev)` visible (con `corte <= corte_eval` y
  `emitido_en <= corte_eval`, para que evaluar un corte antiguo no dependa de revisiones emitidas
  después) con `asof("ventas", corte_eval)`. Por publicación: días con real (`completo` / `parcial` /
  `sin_datos`), WAPE, RMSLE, sesgo, pinball por cuantil, cobertura P10–P90 y costo newsvendor,
  este último solo si los 7 días de cobertura ya tienen real (si no, `pendiente`). También por
  familia y por horizonte. Un día sin real (el 2017-07-04 que nunca llega) queda como *real
  pendiente*, no como error. Las ventas corregidas se reflejan solas.
- **Partición por corte de evaluación:** `data/monitoring/corte=<corte_eval>/` (`metricas_por_corte`,
  `metricas_por_familia`, `metricas_por_h` y `resumen.json`) y `data/monitoring/reportes/<corte_eval>.md`
  (+ PNG). Se eligió una partición por corte (regla 5 de CLAUDE.md) en lugar de un único parquet
  sobrescrito: evaluar un corte viejo no pisa el estado del reciente, y cada evento de Airflow
  versiona su propio resultado. Alternativa descartada: un parquet acumulado (depende del orden de
  ejecución).
- **Reporte (decisión del usuario):** Markdown + PNG con matplotlib (backend Agg, `matplotlib==3.10.8`
  en `requirements.txt`, así también está en la imagen de Docker): WAPE y costo por corte, cobertura
  vs 80% y WAPE por familia. Los PNG no llevan marcas de tiempo (determinismo dentro de un mismo
  entorno). `publicar_reporte_reciente` copia el más reciente a `reports/seguimiento.md` (se usa en
  la fase 8). Alternativa descartada: HTML estático.
- **Alerta (decisión del usuario):** solo advertencia en el reporte y en el log de Airflow si el WAPE
  móvil agrupado de los últimos 4 cortes (última revisión de cada uno, con al menos 7 de 14 días con
  real) supera en más de 20% al WAPE del backtest del champion vigente (`data/models/registro.parquet`).
  No dispara el reentrenamiento. Sin 4 cortes en la ventana no hay alerta. Umbrales en
  `config/monitoreo.yaml`. Alternativa descartada: reentrenar automáticamente (el reentrenamiento
  es mensual + manual por decisión de la fase 5).
- **Limitación conocida:** el WAPE del backtest se calcula con datos revisados y 8 orígenes; el del
  seguimiento es el de la operación real con datos as-of, así que se esperan diferencias.

## 13. Reproducibilidad y entrega (fase 8)

- **Contexto:** el docente clonará el repo, hará `dvc pull`, levantará Airflow siguiendo solo el
  README y operará un periodo no publicado. Si `dvc pull` falla, el proyecto no es reproducible.
- **`reproducir --corte T [--rev N]` (`reproduccion.py`).** Recalcula una publicación en un
  directorio temporal (con `published/` vacío y enlaces simbólicos al resto de `data/`) usando la
  misma huella de entradas: ledger filtrado a `fecha_entrega <= datos_hasta`, donde `datos_hasta` es
  el del manifiesto (en `rev=1` no existe y vale el corte), el `modelo_id` registrado y la configuración
  actual (cuyo hash se compara con el del manifiesto). Compara los sha256 de `pronostico.parquet` y
  `pedido.parquet` y los campos del manifiesto (`modelo_id`, calidad, advertencias, huella, hashes de
  configuración, filas y series). Sale con código 1 si algo difiere. Si `git rev-parse HEAD` difiere
  del `git_commit` del manifiesto, avisa con el comando exacto (`git worktree add`). Alternativa
  descartada: reentrenar el modelo en la reproducción (más lento y no determinista entre entornos; el
  modelo registrado es parte de las entradas, identificado por su id).
- **Mismo entorno.** LightGBM no es bit a bit idéntico entre macOS y Linux. El estado entregado se
  generó en Docker (Linux) y se reproduce en Docker. En macOS, `modelo_id`, huella y baseline
  coinciden, pero el sha256 de los parquet de LightGBM puede diferir.
- **`git_commit` de los manifiestos.** El backfill entregado se corrió con `REPOSICION_GIT_COMMIT` =
  commit de `main` previo a la fase 8 (`e2ed976`), porque el commit de una rama de PR desaparece en
  el squash merge. La fase 8 no cambia la lógica que genera pronósticos (solo agrega `reproducir`).
- **Acceso del docente a DagsHub (decisión del usuario).** El docente usará **su propia cuenta de
  DagsHub** y `tools/dvc_auth.sh` (el repo es público, el token solo necesita lectura). No se migra
  el remoto a un bucket público (ver §2). **Pendiente del usuario:** confirmar con el docente que lo
  acepta y, si es posible, probar con una cuenta distinta a la del dueño.
- **Estado de datos en `main` (decisión del usuario).** Se commitean los `.dvc` de `data/` del
  final del **backfill completo** 2017-01-02 → 2017-08-14 (histórico, modelos, publicados y
  seguimiento) y se hace `dvc push` de todo, de modo que `dvc pull` trae el estado completo y se puede
  reproducir cualquier corte. Se verificó en un clon limpio (`dvc status -c`). Alternativa descartada:
  entregar solo las entradas (obligaría al docente a regenerar horas de entrenamiento).
  Para operar otra bandeja desde cero, `tools/limpiar_salidas.sh` borra las salidas regenerables.
- **Tag `entrega-lab1` (decisión del usuario).** No se crea desde la automatización: lo crea el
  usuario tras revisar (`git switch main && git pull && git tag -a entrega-lab1 -m "Entrega
  Laboratorio 1" && git push origin entrega-lab1`).
- **Incidente del primer backfill (causa raíz, descartada la hipótesis de deadlock).** El primer
  intento del backfill falló en el run `entrenamiento` 2017-03-06: la tarea quedó 2 h 17 min sin
  registrar nada tras "entrenando lgbm…" y terminó `failed`. No fue un deadlock de OpenMP ni falta de
  memoria: el `pmset` del host muestra que el Mac entró en hibernación (batería al 1%, "Low Power
  Sleep") a las 03:58 y despertó a las 06:14; la VM de Docker se congeló, el reloj saltó y Airflow marcó
  la tarea como fallida al despertar. Como los reentrenamientos son secuenciales y cada decisión
  champion/challenger depende de la anterior, un run fallido en medio dejaría un estado incoherente
  (el de abril se habría decidido sin el de marzo). Se descartó repararlo en el sitio: se borraron las
  salidas regenerables y la base de Airflow y se **repitió el backfill completo desde cero** con el
  equipo conectado a la corriente y `caffeinate`. El estado entregado proviene de esa segunda corrida,
  sin runs fallidos. Mitigación documentada en el README: no dejar que la máquina hiberne durante un
  backfill (los reentrenos toman horas).
- **Ensayo de la evaluación docente:** clon limpio desde GitHub, README literal, bandeja distinta
  (otra semilla, escenarios en otras fechas, dos correcciones seguidas del mismo dato y una fuente con
  5 días de retraso). Resultado y fricciones corregidas en el README (sección "Evidencias").
- **Capturas de la UI de Airflow:** no automatizadas (no había navegador controlable); la lista exacta
  está en `reports/evidencia/README.md`.

## 14. Correcciones de la revisión independiente

Una revisión adversarial del código (`tests/revision/INFORME.md`, sobre `main` @ `bbe2747`) dejó 19
pruebas que fallaban a propósito. Se corrigieron los hallazgos de severidad alta y media en la
primera ronda y los bajos (B1–B6) en una segunda (ver al final de esta sección). Las pruebas
viven en `tests/revision/` (el script de diagnóstico con datos reales, que el CI no puede correr,
pasó a `tools/diagnostico_corte_2017_01_02.py`).

**A1 — un dato que cruza un corte dentro de la tolerancia nunca generaba revisión.**
- *Contexto:* `es_tardio` exigía llegar después de `lag + tolerancia`. Ventas del domingo D
  reentregadas (tras cuarentena) o entregadas el martes D+2 quedaban sin marca, y el corte del lunes
  D+1, publicado sin ese día, nunca se revisaba.
- *Alternativas:* (a) marcar en el ledger toda primera versión válida con `fecha_entrega >
  fecha_dato + lag_esperado`; (b) una columna nueva `fuera_de_plazo`; (c) derivar la condición al
  vuelo en `revisiones.py` con la configuración de fuentes.
- *Decisión:* (a). `es_tardio` se mide **sin** tolerancia (`ingesta._es_tardio`); la tolerancia queda
  solo para la calidad de datos (modo degradado). Además `cortes_afectados` recibe `lags_esperados`:
  una llegada fuera de plazo solo afecta a los cortes que la habrían usado (`fecha_dato + lag <= P <
  fecha_entrega`), así una reentrega cuyo día cae dentro del horizonte de P no genera una revisión
  idéntica a la anterior. Las correcciones (`es_correccion`) conservan la regla conservadora de §7.
- *Justificación:* no cambia el esquema del ledger y es lo que mide el enunciado ("el corte se
  publicó con datos incompletos y llegó la reentrega"). Costo: `es_tardio` pasa a significar "fuera
  del plazo nominal", más amplio que "fuera de la tolerancia".
- *Prueba:* `test_dato_que_cruza_un_corte_dentro_de_la_tolerancia_genera_revision[2]` y
  `tests/unit/test_correcciones.py`.

**A2 — las revisiones y el seguimiento dependían del orden entre DAGs en el backfill.**
- *Alternativas:* (a) solo asegurar las publicaciones en el seguimiento; (b) solo derivar lo
  pendiente del ledger contra cada publicación; (c) ambas.
- *Decisión:* (c). (1) `revisiones.emitir_revisiones` ya no usa la ventana fija de 7 días
  (`ventana_correcciones_dias` desaparece de `monitoreo.yaml`): para cada corte publicado toma el
  `datos_hasta` de su última revisión (el corte en `rev=1`) y revisa las correcciones y llegadas
  fuera de plazo entregadas en `(datos_hasta, corte_eval]`. Tras emitir, ya no queda nada pendiente:
  es idempotente. (2) El DAG `seguimiento_desempeno` tiene una tarea nueva `asegurar_publicaciones`
  (`revisiones.asegurar_publicaciones`, `orquestacion.asegurar_publicaciones`) que publica `rev=1`
  de los cortes semanales de las últimas `alerta.ventana_cortes` semanas si faltan, con su champion
  (`asegurar_champion`); `rev=1` es as-of su corte, así que es idéntico al del DAG de pronóstico,
  que luego es un no-op. Un corte sin datos suficientes se omite con aviso.
- *Justificación:* (1) solo no basta: si el pronóstico de W corre después de que su horizonte ya
  terminó, la revisión se pierde; (2) solo no basta si el seguimiento se salta una semana. Juntas el
  resultado no depende del scheduler.
- *Prueba:* `test_revision_no_depende_del_orden_seguimiento_pronostico` y
  `test_correccion_pendiente_se_detecta_aunque_pasen_mas_de_siete_dias`.

**A3 — ingesta no atómica.**
- *Alternativas:* reconstruir `limpio/` en un directorio temporal y reemplazarlo; marcar el ledger
  como "pendiente" antes de empezar; guardar en `limpio/` la huella del ledger con el que se
  construyó.
- *Decisión:* `limpio/_ledger.sha256` guarda la huella lógica del ledger y se escribe **al final**
  de `reconstruir_limpio` (atómica). `ingestar` reconstruye siempre que falte la marca o no
  coincida (`almacen.limpio_al_dia`), aunque no haya archivos nuevos. El ledger sigue siendo el
  punto de confirmación.
- *Justificación:* un directorio no se reemplaza de forma atómica con `os.replace` si ya existe;
  la marca al final también detecta fuentes de generaciones distintas. Costo: la primera ingesta
  sobre un `limpio/` anterior (sin marca) lo reconstruye una vez (determinista).
- *Prueba:* `test_fallo_al_reconstruir_limpio_no_deja_el_almacen_obsoleto`.

**M1 — `lag_1` tomaba el 1-ene (día sin operación).**
- *Alternativas:* NaN en `lag_1`; declarar el día y rezagar al último día con operación; ajustar el
  modelo (más historia). El texto anterior hablaba de "leakage"; era incorrecto: el calendario de
  cierres es conocimiento anterior al corte (como el 25-dic).
- *Decisión:* `dias_sin_operacion: ["01-01", "12-25"]` pasó a `config/model.yaml` (una sola lista;
  `validation.yaml` ya no la duplica y `calidad_datos` la lee de ahí). En `features.construir_features`
  esos días son faltantes para todas las features de ventas (rezagos, medias, mediana, desviación,
  proporción de ceros, mismo día de la semana) y `lag_1` es el del último día con operación anterior
  al origen. El objetivo `y` sigue siendo la venta real. Misma regla en entrenamiento e inferencia.
- *Prueba:* `test_dia_sin_operacion_no_se_usa_como_lag_1` y
  `test_lag_1_es_el_del_ultimo_dia_con_operacion_...`.

**M2 — serie nueva (tienda 52) con pronóstico y pedido 0.**
- *Decisión:* si una serie no tiene ventas en la ventana, `dias_desde_venta` es `min(ventana+1, edad
  de la serie + 1)`, no siempre `ventana+1`. Una serie abierta hace 4 días (filas en 0) no se trata
  como "sin ventas hace un año" y la regla de ceros (> 56 días) no la fuerza a 0. Las series con
  más de 56 días de historia sin ventas siguen en 0. El arranque en frío (sin historia de ventas) lo
  resuelve el modelo con lo que haya; no hay un prior por tienda/familia (limitación).
- *Prueba:* `test_serie_nueva_no_se_trata_como_serie_sin_ventas_hace_un_anio`.

**M3 — datos del futuro.**
- *Decisión:* regla dura en `validar_archivo`: `fecha_dato + lag_minimo_dias <= fecha_entrega`, con
  `lag_minimo_dias` por fuente en `config/sources.yaml` (ventas, transacciones y petróleo: 0). Las
  fuentes que se publican por adelantado (promociones, feriados, maestro) no tienen regla.
  `lag_minimo_dias` es distinto de `lag_esperado_dias`: transacciones puede llegar antes que su
  rezago nominal de 3 días, nunca antes del día que describe. Con la regla no hace falta tocar
  `calidad_datos`: ningún archivo del futuro llega a `limpio/`.
- *Pruebas:* `test_ventas_con_fecha_dato_posterior_a_la_entrega_van_a_cuarentena`,
  `test_dato_del_futuro_no_desactiva_el_modo_degradado`.

**M4 — maestro de tiendas parcial.**
- *Alternativas:* advertencia (insuficiente: el snapshot igual reemplaza el maestro y las ventas
  siguientes van a cuarentena); cuarentena; fusionar el parcial con el vigente.
- *Decisión:* cuarentena si el snapshot omite tiendas del maestro vigente
  (`tiendas_permitir_bajas: false` en `validation.yaml` para cambiarlo). Las altas sí se permiten.
  Fusionar se descartó porque convierte un error del origen en un dato inventado.
- *Prueba:* `test_maestro_de_tiendas_parcial_no_contamina_las_ventas_posteriores`.

**M5 — `reproducir` no usaba el `modelo_id` del manifiesto.**
- *Decisión:* `pronosticar_corte(..., modelo_id=...)`; `reproducir` pasa el del manifiesto. Un
  baseline "sin registro" (no está en `data/models`) se sigue entrenando as-of el corte.
- *Prueba:* `test_reproducir_usa_el_modelo_registrado_en_el_manifiesto`.

**M6 — restos `rev=N.tmp`.**
- *Decisión:* `publicacion.revisiones_publicadas` / `cortes_con_publicacion` aceptan solo
  directorios `rev=<entero>` con manifiesto; los usan revisiones, seguimiento y el registro de
  eventos. Un `rev=N.tmp/` se ignora y el siguiente intento lo reescribe.
- *Pruebas:* `test_revision_interrumpida_se_puede_reintentar`,
  `test_publicacion_interrumpida_no_cuenta_como_publicada`.

**Resultado del backfill corregido (2017-01-02 → 2017-08-14, Docker, 324 runs en verde, 3 h 54 min):**

| | Antes | Después |
|---|---|---|
| WAPE del corte 2017-01-02 | 0.563 | 0.217 |
| WAPE global (suma de errores / suma de ventas) | 0.1547 | 0.1407 |
| WAPE de los demás cortes | 0.107–0.196 | 0.107–0.188 |
| WAPE móvil 4 cortes (08-14) vs backtest | 0.1370 vs 0.1742 | 0.1366 vs 0.1746 |
| Cobertura P10–P90 (media / mínima por corte) | 0.751 / 0.526 | 0.760 / 0.604 |
| Costo de negocio, suma de cortes completos | 16,926,751 | 14,061,939 |
| Pedido de la tienda 52, corte 04-17 / 04-24 | 0 / 55,613 | 619 / 51,007 |
| Alertas de degradación | 1 | 0 |
| Revisiones | 3 (02-06, 03-13, 05-08) | las mismas 3 |
| Promociones de modelo | baseline y LightGBM el 01-02; 7 challengers no superan el criterio | igual |
| Backtest 08-14 (baseline / LightGBM) | WAPE 0.1425 / 0.1207, costo -20.4% | WAPE 0.1412 / 0.1197, costo -19.9% |

La tienda 52 sigue en arranque en frío (619 unidades pedidas contra ~115 mil vendidas en su semana de
apertura): ya no se fuerza a 0, pero sin historia de ventas el modelo no tiene de dónde aprender.
Con la bandeja entregada A1 no cambia ningún resultado: las reentregas (05-12, 06-23, 07-28) llegan
antes del lunes siguiente, así que ningún corte publicado las echó en falta; se prueba con escenarios
sintéticos en otras fechas. `reproducir` da REPRODUCIDO en 6 publicaciones (3 `rev=1`, 3 revisiones).

### Segunda ronda: hallazgos bajos B1–B6 (rama `fix/hallazgos-bajos`)

Todos se corrigieron y sus pruebas dejaron de ser `xfail`. Ninguna cambia un resultado de la bandeja
entregada (se verificó re-ingestando, reemitiendo revisiones y reproduciendo; ver `plan/ESTADO.md`).

**B1 — feriados corregidos o tardíos no marcaban los cortes cuya vista adelante cambia.**
- *Alternativas:* (a) ampliar para todas las fuentes el alcance hacia adelante; (b) regla propia de
  las fuentes de calendario; (c) añadir un parámetro de alcance a `cortes_afectados`.
- *Decisión:* (b). `correcciones.FUENTES_CALENDARIO = {"feriados": TOPE_DIAS_FERIADO}` (la misma
  constante de `features.py`, así no hay dos números que mantener). Un archivo de feriados cubre un
  trimestre desde `fecha_dato`: el corte P se marca si ese trimestre se cruza con
  `[P - ventana_features, P + horizonte - 1 + TOPE_DIAS_FERIADO]` (ventana y horizonte salen de
  `model.yaml`). `TOPE_DIAS_FERIADO` es una constante del código de features, no un parámetro de
  YAML: moverla a config cambiaría los modelos entrenados.
- *Costo:* más revisiones posibles si un archivo de feriados se corrige; hoy ninguno lo hace.

**B2 — la versión vigente dependía del orden de ingesta.**
- *Alternativas:* (a) renumerar `version` por fecha de entrega (rompe versiones ya escritas y la
  huella de publicaciones); (b) ignorar archivos en carpetas anteriores a la última ingesta (pierde
  datos); (c) elegir la vigente por `(fecha_disponible, version)` sin tocar la numeración.
- *Decisión:* (c). `asof` toma por `fecha_dato` la fila de mayor `fecha_disponible` y, en empate, la
  de mayor `version`; `ingesta` calcula la vigente (detección de duplicados) con el mismo orden y
  numera `version` como `max(version) + 1` por orden de ingesta. Con entregas en orden ambos
  criterios coinciden, por eso los datos entregados no cambian.

**B3 — `lead_time + cobertura > horizonte` truncaba el pedido.**
- *Alternativas:* validar en `calcular_pedido`; validar en la configuración.
- *Decisión:* validar al armar `Configs` (`__post_init__`, por lo tanto en `cargar_configs`) con un
  error claro. En `calcular_pedido` no se valida: el backtest descarta las filas sin venta real (por
  ejemplo el 25-dic) antes de calcular el pedido y una comprobación ahí daría falsos positivos.

**B4 — τ redondeado a 0 o 1.** `cuantil_critico` se movió a `parametros.py` (se reexporta desde
`pedido.py`) y `GrupoCosto` rechaza una pareja de costos cuyo τ redondeado no quede en (0, 1).
Alternativa descartada: no redondear (rompe que el modelo se entrene exactamente en el cuantil del
pedido).

**B5 — la mediana es obligatoria.** `ConfigModelo` exige `0.5` en `cuantiles_reporte` (constante
`parametros.MEDIANA`). Los cuantiles 0.1 y 0.9 siguen siendo opcionales: sin ellos solo se omite la
cobertura P10–P90 (`metricas.py` ya lo contempla), y los τ del pedido salen de los costos.

**B6 — checks técnicos y familias ausentes.**
- `checks_tecnicos` verifica que cada (serie, origen) tenga todos los horizontes 1..H. Primera
  versión descartada: exigir el producto cartesiano series × orígenes × horizontes daba un falso
  positivo en los backtests reales de los cortes 05-01 y 06-05, porque una tienda nueva no existe en
  los orígenes viejos.
- `evaluar_promocion`: una familia grande del champion ausente en el challenger cuenta como falla
  ("ausente en el challenger"), ya no como `NaN > umbral` = falso.
- *Límite conocido:* una serie completa ausente en un origen no se detecta por sí sola (sí si es una
  familia grande).
- No se movió `COBERTURA_NOMINAL = 0.80` (solo dibuja la línea del gráfico y está ligada al nombre
  P10–P90 en reportes): moverla a config no aporta sin parametrizar también esos nombres.

## Limitaciones conocidas

- **Ventas censuradas:** `sales` es la demanda observada, censurada por quiebres de stock (no hay
  datos de inventario). Los modelos aprenden ventas, no demanda; en series con quiebres frecuentes el
  pronóstico subestima y el pedido sugerido también.
- **Inventario inicial 0:** el pedido sugerido cubre 7 días sin descontar existencias (no hay fuente
  de inventario). Es configurable (`config/business.yaml`) pero ningún dato real lo alimenta.
- **Backtest con datos revisados:** el backtest que decide la promoción de modelos usa los datos
  tal como están en el corte (con las correcciones ya aplicadas) y 8 orígenes; el seguimiento mide
  la operación as-of. Por eso el WAPE del seguimiento y el del backtest difieren, y la alerta de
  degradación compara contra el segundo con un umbral amplio (+20%).
- **Suma de cuantiles:** el pedido es la suma de los cuantiles diarios τ de los 7 días de cobertura.
  Eso supone comonotonía entre días; el cuantil τ de la suma es menor o igual, así que el pedido sobre-
  cubre algo. La variante "cuantil de la demanda semanal" se evaluó y empeoró el costo (+9.1%).
- **No determinismo de LightGBM entre plataformas:** distintos binarios/OpenMP (macOS vs Linux) dan
  parquet distintos. La idempotencia y `reproducir` valen dentro de un mismo entorno (Docker).
- **Corte 2017-01-02, el de peor desempeño:** el rezago de 1 día de ese corte caía en el 2017-01-01
  (ventas ~1% de un día normal, cierre de año). Era un defecto de las features, no una limitación
  inevitable: se corrigió con `dias_sin_operacion` (§14, M1). Aun así sigue siendo el corte con
  menos historia comparable (la ventana de entrenamiento nunca tuvo un lunes posterior al 1-ene) y
  su WAPE (0.217) queda por encima del resto (0.107–0.188).
- **Simulador, no la bandeja oficial:** las situaciones operativas son las inyectadas por el
  simulador (`bandeja_sim/_escenarios.csv`); un formato real distinto exige un adaptador en la ingesta
  y `config/sources.yaml`.
- **DagsHub exige cuenta** para `dvc pull` (ver §2 y §13).
