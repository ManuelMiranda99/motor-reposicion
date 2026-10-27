# Decisiones técnicas y de producto

Cada decisión registra el contexto, las alternativas consideradas, la decisión tomada y su
justificación. Las decisiones sobre disponibilidad de la información en el tiempo, validación de datos
y manejo de correcciones se desarrollarán en las fases 2 y 3.

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
| 8 | Modelos, validación temporal y métricas | Aceptada (baseline; LightGBM en la fase 5) |
| 9 | Pedido sugerido (newsvendor) | Aceptada |
| 10 | Criterio de reemplazo de modelo | Pendiente |
| 11 | Versionado de publicaciones desde Airflow | Pendiente |

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
  entregada después de `fecha_dato + lag_esperado + tolerancia`.
- **Correcciones y publicados:** `correcciones_entre` y `cortes_afectados` (funciones puras) dicen
  qué cortes ya calculados cambiarían; la fase 7 los recalcula como una **nueva revisión** y nunca
  sobrescribe lo publicado.
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

## 9. Pedido sugerido (newsvendor)

- **Contexto:** convertir el pronóstico por cuantiles en una cantidad a pedir por tienda × familia.
- **Decisión:** τ = c_quiebre / (c_quiebre + c_merma) por grupo de familias, **redondeado a 2
  decimales** para que el modelo se entrene exactamente en el cuantil que usa el pedido. Tres
  grupos (`config/business.yaml`): perecederos (1.0 / 1.5, τ = 0.40), no perecederos (1.0 / 0.1,
  τ = 0.91) y default (1.0 / 0.5, τ = 0.67). El pedido es la suma de los cuantiles diarios τ sobre
  la cobertura (7 días, lead time 0, es decir h = 1..7), menos el inventario inicial (0, porque no
  hay datos de inventario), redondeada hacia arriba y nunca negativa.
- **Alternativas descartadas:** un solo grupo de costos (poco realista) y entrenar el cuantil τ de
  la demanda semanal (más correcto, pero agrega modelos; se evaluará en la fase 5). La suma de
  cuantiles supone dependencia perfecta entre días y es, por tanto, conservadora.
- **Si τ no está entre las columnas** del pronóstico, se interpola linealmente entre los cuantiles
  vecinos y se registra una advertencia.
