# Informe de revisión independiente — Laboratorio 1 (motor de reposición)

Revisión adversarial del código en `main` @ `bbe2747` (fases 0–8). No se modificó código de
producción: cada hallazgo confirmado tiene una prueba en `tests/revision/` que afirma el
comportamiento **correcto** y por eso **falla** hoy.

## Cómo reproducir

```bash
ruff check . && ruff format --check .
pytest --ignore=tests/revision          # suite del proyecto
pytest tests/revision                   # 19 pruebas que fallan a propósito (un hallazgo cada una)
python tests/revision/diagnostico_corte_2017_01_02.py data   # requiere el data/ real (solo lee)
```

## Estado de la suite

| Comando | Resultado |
|---|---|
| `ruff check .` / `ruff format --check .` | sin errores (97 archivos) |
| `pytest` (suite del proyecto) | **218 passed, 1 skipped** (`tests/test_dags.py`: Airflow no está instalado en el venv local) |
| `pytest tests/revision` | **19 failed** a propósito |

Docker/Airflow no se levantó en esta revisión; la parte "Airflow" de los hallazgos se razona sobre
el código de los DAGs y el historial real de la rama `publicaciones`.

Leyenda: **CONFIRMADO** = prueba que falla o evidencia reproducible; **PLAUSIBLE** = razonamiento
sólido sin reproducción completa.

---

## Severidad alta

### A1. Un dato que cruza un corte dentro de la tolerancia nunca genera revisión — CONFIRMADO

- **Dónde:** `src/reposicion/ingesta.py:244` (`es_tardio` solo si supera `lag + tolerancia`),
  `src/reposicion/correcciones.py:13-17` (`correcciones_entre` solo mira `es_correccion | es_tardio`).
- **Qué pasa:** la revisión se dispara por "tardío respecto de la tolerancia", pero lo que importa
  es si el dato llegó **después de un corte que lo necesitaba**. Ventas del domingo D que llegan el
  martes D+2 (tolerancia: D+3) o un archivo en cuarentena el lunes con reentrega válida el martes
  quedan con `es_tardio=False, es_correccion=False`.
- **Escenario:** ventas 2017-01-29 inválidas el lunes 01-30 y válidas el 01-31 (o simplemente
  entregadas el 01-31). El corte 01-30 se publica sin `lag_1`; el seguimiento del 02-06 no emite
  `rev=2`. Los escenarios del simulador entregado esquivan el caso (todas las reentregas caen entre
  semana), pero la bandeja del docente "con escenarios en otras fechas" puede tocarlo.
- **Evidencia:** `test_revisiones.py::test_dato_que_cruza_un_corte_dentro_de_la_tolerancia_genera_revision[reentrega_tras_cuarentena|retraso_tolerado]`.
- **Impacto docente:** el enunciado evalúa explícitamente "reentrega válida tras cuarentena" y
  "corrección → revisión"; un corte publicado con datos incompletos sin revisión es justo lo que
  se busca.
- **Sugerencia:** marcar en el ledger toda primera versión válida con `fecha_entrega` posterior a
  algún corte que la habría usado (o simplemente `fecha_entrega > fecha_dato + lag_esperado`, sin
  tolerancia) como candidata a revisión; la tolerancia debe servir solo para el modo degradado.

### A2. Revisiones y seguimiento dependen del orden entre DAGs en el backfill — CONFIRMADO (lógica) / PLAUSIBLE (Airflow)

- **Dónde:** `src/reposicion/revisiones.py:66-73` (solo mira `cortes_publicados` en ese momento
  y la ventana `(corte_eval-7, corte_eval]`), `src/reposicion/seguimiento.py:70-92`,
  `dags/seguimiento_desempeno.py` (sin dependencia de `pronostico_semanal`).
- **Qué pasa:** DECISIONES §11 reconoce que "en un backfill los cuatro DAGs corren sin orden entre
  sí" y lo resuelve para el champion (`asegurar_champion`), pero no para las revisiones: si
  `seguimiento` del lunes W+1 corre antes de que `pronostico` publique W, no hay nada que revisar;
  después W se publica as-of W (sin la corrección) y la siguiente ventana ya no la incluye. La
  revisión se pierde para siempre y `metricas_por_corte` de W+1 omite W.
- **Escenario:** corrección de ventas 01-05 entregada el 01-09; orden seguimiento(01-09) →
  pronóstico(01-02) → seguimiento(01-16) deja solo `rev=1`; el orden inverso deja `rev=1, rev=2`.
- **Evidencia:** `test_revisiones.py::test_revision_no_depende_del_orden_seguimiento_pronostico`.
  Que los DAGs sí se desfasan está en el historial real de `publicaciones`: `modelo corte
  2017-02-06` se confirmó antes que `pronostico corte 2017-01-16` (y `modelo 2017-03-06` antes que
  `seguimiento 2017-02-13`). En esa corrida el seguimiento siempre quedó detrás del pronóstico, pero
  nada lo garantiza (pool de 1 slot, `priority_weight` por defecto: las tareas iniciales del
  seguimiento pesan más que las finales del pronóstico).
- **Impacto docente:** el docente opera un periodo no publicado con `catchup=True`; el número de
  revisiones y los reportes de seguimiento pueden diferir entre corridas.
- **Sugerencia:** en `seguimiento_desempeno`, una tarea `asegurar_publicacion(corte_eval - 7)` y
  `asegurar_publicacion(corte_eval)` (mismo patrón que `asegurar_champion`, `pronosticar_corte` es
  idempotente), o derivar las correcciones pendientes del ledger contra cada publicación
  (`fecha_entrega > emitido_en` de su última revisión) en vez de una ventana de 7 días.

### A3. Ingesta no atómica: si falla la reconstrucción de `limpio/`, el almacén queda obsoleto para siempre — CONFIRMADO

- **Dónde:** `src/reposicion/ingesta.py:276-279` (escribe el ledger y luego `reconstruir_limpio`),
  `src/reposicion/ingesta.py:209-213` (sin archivos nuevos solo reconstruye si `limpio/` no existe).
- **Escenario:** el worker muere (OOM, disco lleno, kill por timeout) durante
  `reconstruir_limpio`; el reintento no ve archivos nuevos (ya están en el ledger) y no reconstruye.
  En la prueba, tras el reintento `ultima_fecha_disponible("ventas", 01-10)` es 01-04 aunque el
  ledger tiene como válidas las ventas hasta el 01-09. Además `reconstruir_limpio` escribe fuente
  por fuente: un fallo a mitad deja fuentes de distintas generaciones.
- **Evidencia:** `test_ingesta_validacion.py::test_fallo_al_reconstruir_limpio_no_deja_el_almacen_obsoleto`.
- **Impacto docente:** viola la regla 5 (idempotencia/atomicidad) y produce pronósticos con datos
  viejos sin error visible (a lo sumo "degradada").
- **Sugerencia:** guardar en `limpio/` (o en un `_estado.json`) el sha256 del ledger con el que se
  construyó y reconstruir siempre que no coincida; o reconstruir `limpio/` en un directorio temporal
  y reemplazarlo antes de escribir el ledger.

---

## Severidad media

### M1. Corte 2017-01-02 (WAPE 0.563): no es una limitación legítima, es `lag_1` = 1-ene — CONFIRMADO (datos reales)

- **Dónde:** `src/reposicion/features.py:205-206` (`lag_1 = v[:, i-1]` sin considerar días sin
  operación), `config/validation.yaml` (`dias_sin_operacion: ["12-25"]`, sin el 01-01, y las
  features no lo consultan). Explicación actual en `DECISIONES.md` → "Limitaciones conocidas".
- **Evidencia** (`python tests/revision/diagnostico_corte_2017_01_02.py data`, macOS; el publicado
  en Linux da 0.563):

  | Variante con el modelo publicado `lgbm-2017-01-02-496d76f4` | WAPE | Sesgo |
  |---|---|---|
  | tal cual | 0.519 | −0.512 |
  | `lag_1` = NaN | 0.522 | −0.516 |
  | `lag_1` = ventas del 2016-12-31 (último día con operación) | **0.228** | −0.142 |
  | solo `lag_1` tomado del corte 01-09 (resto igual) | 0.219 | −0.137 |
  | baseline entrenado en el mismo corte | 0.299 | −0.026 |

  Ninguna otra feature mueve el WAPE más de ±0.01. Las ventas del 1-ene son ~1% de un día normal
  todos los años (8.6 k, 12.8 k, 16.4 k y 12.1 k en 2014–2017 frente a ~1 M), y la ventana de
  entrenamiento (52 orígenes de 2016) nunca tuvo un lunes después del 1-ene.
- **Qué está mal en la explicación:** DECISIONES dice que "el pronóstico de los primeros días sale
  muy bajo" y que corregirlo "sería leakage". El sesgo es −50% a −75% en **todos** los horizontes
  h = 1..14 (`metricas_por_h`), y saber que el 1-ene es un cierre es información de calendario
  conocida de antemano (igual que el 25-dic ya declarado), no leakage.
- **Prueba sintética:** `test_modelo_config.py::test_dia_sin_operacion_no_se_usa_como_lag_1`.
- **Impacto docente:** el corte con peor desempeño queda explicado con un argumento incorrecto; un
  revisor que mire `metricas_por_h` lo nota.
- **Sugerencia:** declarar `01-01` como día sin operación y que las features de rezago usen el
  último día con operación (o NaN de forma consistente en entrenamiento e inferencia), o, como
  mínimo, corregir el texto de la limitación con estos números.

### M2. Tienda nueva (52): pedido 0 en su semana de apertura por la regla de ceros — CONFIRMADO

- **Dónde:** `src/reposicion/features.py:214-216` (`dias_desde_venta` = 365 si no hubo venta en la
  ventana, aunque la serie exista hace días), `src/reposicion/modelos/base.py:51-54`.
- **Escenario real:** la tienda 52 tiene filas en 0 desde el 04-13 y vende desde el 04-20. En el
  corte 2017-04-17 sus 33 series son "activas" con `dias_desde_venta = 365 > 56` → pronóstico y
  **pedido 0**, contra 114,797 unidades vendidas en esa cobertura. El 04-24 pide 55,613 contra
  180,385 (arranque en frío).
- **Evidencia:** `test_modelo_config.py::test_serie_nueva_no_se_trata_como_serie_sin_ventas_hace_un_anio`
  y lectura de `data/published/corte=2017-04-17/rev=1/pedido.parquet`.
- **Impacto docente:** el enunciado menciona la tienda 52 como caso borde; DECISIONES solo trata su
  categoría desconocida, no el pedido 0.
- **Sugerencia:** acotar `dias_desde_venta` por la edad de la serie y no aplicar la regla de ceros a
  series con menos de `dias_sin_ventas` días de historia; documentar el arranque en frío.

### M3. Archivos con `fecha_dato` posterior a su entrega se aceptan y desactivan el modo degradado — CONFIRMADO

- **Dónde:** `src/reposicion/validacion.py:131-142` (solo compara el contenido con el nombre),
  `src/reposicion/publicacion.py:91-97` (`calidad_datos` usa la `fecha_dato` máxima visible).
- **Escenario:** `2017-01-10/ventas_2017-03-15.csv` (bien formado) entra como `valido`. Si después
  las ventas reales dejan de llegar, el corte 01-20 no lanza `DatosInsuficientes` (la "última venta"
  es del 03-15) y se publica con datos de hace 11 días; el seguimiento además compararía ese "real"
  con el pronóstico del 03-15.
- **Evidencia:** `test_ingesta_validacion.py::test_ventas_con_fecha_dato_posterior_a_la_entrega_van_a_cuarentena`
  y `::test_dato_del_futuro_no_desactiva_el_modo_degradado`.
- **Impacto docente:** "fechas fuera de rango" es uno de los casos de validación pedidos.
- **Sugerencia:** regla dura `fecha_dato + lag_esperado <= fecha_entrega` (con la anticipación
  negativa de promociones y la regla trimestral de feriados), y que `calidad_datos` mire la última
  fecha **contigua**.

### M4. Un maestro de tiendas parcial se acepta y manda a cuarentena todas las ventas posteriores — CONFIRMADO

- **Dónde:** `src/reposicion/validacion.py:153-156` (no hay reglas para `tiendas`),
  `src/reposicion/ingesta.py:252-255` (el snapshot reemplaza el maestro vigente).
- **Escenario:** el origen manda `tiendas_2017-01-25.csv` solo con el alta de la tienda 3 (archivo
  incremental en vez de snapshot). Se acepta sin advertencia y, desde ese día, las 11 entregas de
  ventas válidas quedan en cuarentena ("store_nbr desconocido"): el corte siguiente termina en
  `DatosInsuficientes` y las tiendas 1–2 desaparecen de las features.
- **Evidencia:** `test_ingesta_validacion.py::test_maestro_de_tiendas_parcial_no_contamina_las_ventas_posteriores`.
- **Impacto docente:** regla 8 (datos inválidos → cuarentena sin contaminar resultados).
- **Sugerencia:** cuarentena (o al menos advertencia) si el snapshot pierde tiendas con ventas en
  los últimos N días.

### M5. `reproducir` no usa el `modelo_id` del manifiesto — CONFIRMADO

- **Dónde:** `src/reposicion/reproduccion.py:131-139` → `src/reposicion/publicacion.py:161`
  (`champion_vigente(corte)` se resuelve de nuevo con el registro actual).
- **Escenario:** se publica el corte T; ese mismo lunes se dispara `entrenamiento` con `forzar`
  y el nuevo modelo se promueve con `fecha_promocion = T`. `reproducir --corte T` dice
  "NO REPRODUCIDO" (otro `modelo_id`, otros sha256) aunque la publicación y su modelo estén intactos.
  El docstring del módulo y DECISIONES §13 dicen que la entrada es "el `modelo_id` registrado".
- **Evidencia:** `test_modelo_config.py::test_reproducir_usa_el_modelo_registrado_en_el_manifiesto`.
- **Impacto docente:** la reproducibilidad es un criterio central de la fase 8.
- **Sugerencia:** parámetro `modelo_id` opcional en `pronosticar_corte` y que `reproducir` pase el
  del manifiesto.

### M6. Restos de una escritura interrumpida (`rev=N.tmp/`) rompen las revisiones y el seguimiento — CONFIRMADO

- **Dónde:** `src/reposicion/publicacion.py:249-253` (el manifiesto se escribe dentro de
  `rev=N.tmp/` antes del `os.replace`), `src/reposicion/revisiones.py:27-32`
  (`glob("rev=*/manifest.json")` + `int("2.tmp")`), `src/reposicion/seguimiento.py:78`,
  `src/reposicion/revisiones.py:40`.
- **Escenario:** el worker muere entre el manifiesto y el `os.replace` de una revisión: cada
  reintento de `emitir_revisiones` falla con `ValueError: invalid literal for int() ... '2.tmp'`
  (hay que borrar a mano) y `listar_publicaciones` cuenta `rev=2.tmp` como publicada.
- **Evidencia:** `test_revisiones.py::test_revision_interrumpida_se_puede_reintentar` y
  `::test_publicacion_interrumpida_no_cuenta_como_publicada`.
- **Sugerencia:** glob `rev=[0-9]*` con filtro `name.removeprefix("rev=").isdigit()` en todos los
  lectores, o temporal fuera del patrón (`.rev=N.tmp`).

---

## Severidad baja

### B1. Corrección/llegada tardía de feriados no marca los cortes cuya vista adelante cambia — CONFIRMADO

- **Dónde:** `src/reposicion/correcciones.py:36-38` (`fecha_dato <= P + h - 1`; en feriados
  `fecha_dato` es el inicio del trimestre) frente a `features.py:181-185` (mira 30 días más allá
  del último día objetivo).
- **Escenario:** el archivo del 2º trimestre agrega un feriado el 04-03; `dias_al_feriado` del corte
  03-06 cambia, pero `cortes_afectados` no lo marca. Lo mismo si el archivo trimestral llega tarde
  (`lag_esperado_dias` es `None` para feriados: nunca es tardío).
- **Evidencia:** `test_revisiones.py::test_correccion_de_feriados_marca_los_cortes_cuya_vista_adelante_cambia`.
- **Sugerencia:** para feriados, comparar el rango del trimestre `[inicio, fin]` con
  `[P - ventana, P + h - 1 + TOPE_DIAS_FERIADO]`.

### B2. La versión vigente depende del orden de ingesta, no de la fecha de entrega — CONFIRMADO

- **Dónde:** `src/reposicion/ingesta.py:242` (versión = última versión ingerida + 1),
  `src/reposicion/asof.py:31-33` (gana la versión máxima).
- **Escenario:** si un archivo aparece después en una carpeta de entrega antigua (bandeja no
  append-only), recibe una versión mayor que una corrección entregada después: `asof(01-10)` muestra
  lo entregado el 01-07 en vez de la corrección del 01-09, y cambia retroactivamente la huella de
  cortes ya publicados (→ `PublicacionInmutable` al re-ejecutarlos).
- **Evidencia:** `test_ingesta_validacion.py::test_version_vigente_es_la_ultima_entregada_aunque_se_ingiera_despues`.
- **Sugerencia:** en `asof`, desempatar por `(fecha_disponible, version)`; ignorar (y advertir) los
  archivos nuevos en carpetas con fecha anterior a la última ingesta.

### B3. `lead_time_dias + cobertura_dias > horizonte_dias` trunca el pedido en silencio — CONFIRMADO

- **Dónde:** `src/reposicion/pedido.py:60-63`; sin validación cruzada en `parametros.py`.
- **Escenario:** lead time 10, cobertura 7, horizonte 14 → el pedido suma 4 días (pedido 4 en vez
  de 7 con demanda 1/día).
- **Evidencia:** `test_modelo_config.py::test_cobertura_mas_lead_time_mayor_que_el_horizonte_no_se_trunca_en_silencio`.
- **Sugerencia:** validar en `cargar_configs` que `lead_time + cobertura <= horizonte`.

### B4. τ redondeado puede valer 0 o 1 — CONFIRMADO

- **Dónde:** `src/reposicion/pedido.py:16-21`, `src/reposicion/parametros.py:69-71`.
- **Escenario:** `c_merma: 0.004` → τ = 1.0 → `cuantiles_requeridos` incluye 1.0 (LightGBM con
  `alpha=1`). Los cuantiles de reporte sí se validan en (0, 1); los τ no.
- **Evidencia:** `test_modelo_config.py::test_tau_redondeado_queda_dentro_de_0_1`.

### B5. La mediana es obligatoria pero no se valida — CONFIRMADO

- **Dónde:** `src/reposicion/parametros.py:62-66`; uso directo de `q0.50` en
  `src/reposicion/metricas.py:81` y `src/reposicion/seguimiento.py:108`.
- **Escenario:** `cuantiles_reporte: [0.1, 0.9]` se acepta y falla tarde con `KeyError: 'q0.50'`.
- **Evidencia:** `test_modelo_config.py::test_cuantiles_reporte_sin_mediana_se_rechaza`.

### B6. Checks técnicos sin "filas completas" y familia ausente ignorada en el criterio — CONFIRMADO

- **Dónde:** `src/reposicion/registro.py:60-78` (no verifica completitud, aunque
  `config/promotion.yaml` lo documenta) y `registro.py:125-127` (costo NaN → `NaN > x` es False).
- **Escenario:** un challenger al que le falta una familia con 50% del volumen se promueve si el
  resto mejora. Hoy no ocurre porque ambos modelos se evalúan sobre la misma matriz `X`.
- **Evidencia:** `test_modelo_config.py::test_checks_tecnicos_detectan_filas_faltantes` y
  `::test_familia_grande_ausente_en_el_challenger_no_permite_promover`.

---

## Detalles menores (no son bugs)

- `almacen.leer_limpio` cachea por `(ruta, mtime_ns)`: no afecta resultados salvo dos reescrituras
  con el mismo `mtime_ns` (improbable); la regla 2 prohíbe el mtime "en la lógica".
- Constantes que podrían ir a `config/`: `COBERTURA_NOMINAL = 0.80` (`seguimiento.py:52`, debería
  derivarse de los cuantiles), `max_bin 255` (`modelos/lgbm.py:91`), `TOPE_DIAS_FERIADO`,
  `LAGS`/`MEDIAS`. `ventana_features_dias: 364` (`model.yaml`) duplica el `364` de `LAGS`: si se
  cambia solo uno, `cortes_afectados` deja de corresponder a las features.
- La ventana fija `ventana_correcciones_dias: 7` no se deriva del horizonte ni de la cadencia; con
  h = 14 y corte semanal no pierde nada, pero con otro horizonte sí.

## Descartados (revisados sin encontrar problema)

- **As-of / leakage:** no hay `now()`/`today()` en `src/` ni `dags/`; lags y medias usan `≤ O−1`,
  transacciones `≤ O−3`, petróleo con `ffill` solo hacia adelante, promociones enmascaradas más
  allá de `O+10` igual en entrenamiento e inferencia, feriados por trimestre visibles a tiempo,
  tienda 52 validada con el maestro vigente en la entrega. Las revisiones con `datos_hasta` siguen
  anclando las features a `O−1`.
- **Archivos raros:** vacío, solo encabezado, `;`, Latin-1, filas con columnas de más → cuarentena;
  BOM UTF-8 y CRLF → se leen bien; `_*` y nombres/carpetas inválidos → se ignoran con warning.
- **Duplicados idénticos, duplicados de llave no idénticos, dos correcciones seguidas, corrección
  después del horizonte** (solo recalcula seguimiento), petróleo NaN de fin de semana, tienda
  cerrada (advertencia), `max_dias_sin_ventas`.
- **Airflow:** `es_primer_lunes`/`ultimo_primer_lunes` correctos cuando el 1 es lunes; cron en UTC
  (`start_date` con `tzinfo=UTC`); `forzar` solo en `entrenamiento`; `PublicacionInmutable` →
  `AirflowFailException`; sin tokens en modo `auto` no falla; `.env.example` coincide con lo que
  leen `rutas.py`/`operacion.py`/`versionado.py`.
- **Revisiones redundantes** (corrección que no entra en las features genera `rev=N+1` idéntica):
  documentado y aceptado en DECISIONES §7.
