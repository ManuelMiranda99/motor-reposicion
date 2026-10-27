# Fase 5 — LightGBM, registro de modelos y publicación offline

**Rama:** `feat/lgbm` · **Estimado:** 1.5 días · **Prerequisitos:** fase 4.

Al final de esta fase el producto ya funciona **completo fuera de Airflow**: con un comando se
genera y publica el pronóstico y el pedido de un corte. La fase 6 solo lo orquesta.

## Objetivo

1. Un modelo LightGBM global por cuantil que supere al baseline en el mismo backtest.
2. Un criterio explícito de reemplazo (champion/challenger) y un registro de modelos con historial.
3. La comparación de modelos como evidencia en `reports/`.
4. Una función `pronosticar_corte` que publique en `data/published/` con un manifiesto.

## Decisiones para el usuario (preguntar al inicio)

1. **Umbrales del criterio de reemplazo** (`promotion.yaml`).
   - (Recommended) El challenger reemplaza al champion si: el costo de negocio total baja ≥ 3%,
     el WAPE no empeora más de 1%, la cobertura P10–P90 está en [0.70, 0.90], ninguna familia con
     más del 5% del volumen empeora su costo más de 10% y pasa los checks técnicos.
   - Solo por costo de negocio (≥ 3%).
   - Umbrales propios.
2. **Frecuencia de reentrenamiento** (se usará en la fase 6).
   - (Recommended) Mensual (primer lunes del mes) y manual. El pronóstico semanal solo usa el
     champion vigente.
   - Cada semana (más caro y más riesgo de inestabilidad).
3. **Costo del backtest de LightGBM** (son 6–7 cuantiles × 8 orígenes de entrenamiento).
   - (Recommended) Medir primero un origen. Si el backtest completo tarda más de ~20 minutos,
     reducir a 4 orígenes o bajar `num_boost_round`, y documentarlo.
   - Mantener 8 orígenes cueste lo que cueste.
4. **Evaluar la variante "cuantil de demanda semanal" para el pedido** (opcional, pendiente de la
   fase 4).
   - (Recommended) No en esta fase: dejarla como mejora futura en DECISIONES.
   - Sí: entrenar un modelo con la suma de 7 días como objetivo y comparar el costo de negocio.

## Dependencias

- `pip install lightgbm` y fija la versión en `requirements.txt`.
- **macOS:** LightGBM necesita OpenMP. Si `import lightgbm` falla con un error de `libomp`, pide al
  usuario que corra `! brew install libomp` (no lo instales tú sin preguntar).
- En Docker (fase 6), la imagen necesita `libgomp1` (`apt-get install -y libgomp1`).

## Configuración

Agrega a `config/model.yaml`:

```yaml
lightgbm:
  objective: quantile
  learning_rate: 0.05
  num_leaves: 63
  min_data_in_leaf: 100
  feature_fraction: 0.8
  lambda_l2: 1.0
  num_boost_round: 400
  num_threads: 4          # fijo: el determinismo depende de él
  deterministic: true
  force_row_wise: true
  seed: 2017
  verbose: -1
objetivo_transformado: log1p
```

Sin bagging aleatorio y sin early stopping sobre datos de validación, para que reentrenar con los
mismos datos produzca el mismo modelo.

`config/promotion.yaml` con los umbrales que elija el usuario.

## Módulos y contratos

### `src/reposicion/modelos/lgbm.py`

- Implementa `ModeloPronostico`: un `lgb.Booster` por cuantil (`alpha = q`), con el objetivo en
  `log1p(y)` y la predicción en `expm1`, recortada a ≥ 0. Usa `ordenar_cuantiles` y aplica la
  regla de ceros igual que el baseline (impórtala de un solo lugar).
- Categóricas: usa el dtype `category` con categorías **fijas**, guardadas en el modelo, para que
  los códigos sean iguales en entrenamiento y predicción.
- `guardar`: `modelo_<q>.txt` (formato texto nativo de LightGBM) + `meta.json` (features,
  categorías, cuantiles, parámetros). Sin pickle.

### `src/reposicion/registro.py`

```
data/models/<modelo_id>/          # modelo_id = "<tipo>-<corte_entrenamiento>-<hash8 de config+datos>"
    modelo_*.txt | baseline.*  meta.json  metricas_backtest.parquet
data/models/registro.parquet      # historial: modelo_id, tipo, corte_entrenamiento, evaluado_en,
                                  # promovido (bool), fecha_promocion, motivos, metricas principales
```

```python
def registrar(modelo, tipo, corte, metricas, dir_data) -> str          # devuelve modelo_id; idempotente
def evaluar_promocion(m_challenger, m_champion, cfg_promocion) -> Decision  # (promover, motivos: list[str])
def champion_vigente(corte: date, dir_data) -> str | None
    # último modelo con promovido=True y fecha_promocion <= corte → los backfills reproducen el
    # mismo modelo que se habría usado en su momento
def cargar_modelo(modelo_id, dir_data) -> ModeloPronostico
```

Si no hay champion vigente, `entrenar_y_evaluar` promueve automáticamente al baseline como
champion inicial (y lo deja registrado con ese motivo).

### `src/reposicion/entrenamiento.py`

```python
def entrenar_y_evaluar(corte: date, dir_data, cfgs) -> Decision
```

Pasos: entrenar el challenger (LightGBM) con `asof(corte)` → backtest del challenger y del champion
actual (o del baseline) con los **mismos** orígenes → `evaluar_promocion` → registrar ambos →
escribir el reporte. Es idempotente: si `modelo_id` ya existe con el mismo hash, reutiliza el
modelo.

### `src/reposicion/publicacion.py`

```python
def pronosticar_corte(corte: date, dir_data, cfgs, revision: int = 1) -> Path
```

1. `datos = cargar_datos_asof(corte)`. Chequeo de modo degradado: si
   `ultima_fecha_disponible("ventas", corte) < corte - 1 - max_dias_sin_ventas`, lanza
   `DatosInsuficientes` con un mensaje claro. Si solo hay huecos menores (por ejemplo, el faltante
   del 2017-07-04), continúa y marca `calidad = "degradada"` con advertencias.
2. `modelo = champion_vigente(corte)`; si no hay, entrena el baseline en el momento (para no
   fallar) y lo anota en el manifiesto.
3. Features del origen `corte` → `predecir_cuantiles(cuantiles_requeridos)` → `calcular_pedido`.
4. Checks: 1,782 (o el número de series activas) × 14 filas, sin NaN, ≥ 0, cuantiles monótonos.
   Si falla un check, **no publica** (lanza un error).
5. Escribe en `data/published/corte=<T>/rev=<N>/`:
   - `pronostico.parquet`: corte, store_nbr, family, fecha_objetivo, h, q0.10, q0.50, q0.90,
     columnas q_τ, modelo_id.
   - `pedido.parquet` (formato de la fase 4).
   - `manifest.json`: corte, revision, modelo_id, calidad, advertencias, `git_commit` (de
     `git rev-parse HEAD`, o la variable `REPOSICION_GIT_COMMIT` dentro de Docker),
     `huella_entradas` (sha256 de las filas del ledger con `fecha_entrega <= corte`, ordenadas),
     sha256 de `business.yaml` y `model.yaml`, y sha256 de cada parquet publicado.
     **Sin timestamps de reloj**: así una re-ejecución produce un manifiesto idéntico.
6. **Inmutabilidad:** si `rev=N` ya existe con la misma `huella_entradas` y los mismos hashes de
   config, es un no-op. Si existe pero con otra huella, **no sobrescribas**: lanza un error. La
   fase 7 decide cuándo emitir una revisión nueva.
7. Escritura atómica: escribe a `rev=N.tmp/` y luego `os.replace` del directorio.

### CLI

- `python -m reposicion.cli entrenar --corte 2017-01-02`
- `python -m reposicion.cli comparar --corte 2017-08-14` → `reports/comparacion_modelos.md`
  (tabla global, por familia y por h; baseline vs LightGBM; métricas técnicas y de negocio;
  decisión de promoción).
- `python -m reposicion.cli pronosticar --corte 2017-03-13`

## Pruebas requeridas

- `test_lgbm_determinista`: entrenar dos veces con datos sintéticos da predicciones idénticas.
- `test_lgbm_guardar_cargar_misma_prediccion`.
- `test_categorias_fijas`: predecir con un subconjunto de tiendas da los mismos códigos.
- `test_evaluar_promocion`: un caso para cada regla (pasa, falla por costo, por WAPE, por cobertura,
  por familia).
- `test_champion_vigente_respeta_fecha`.
- `test_pronosticar_corte_idempotente`: dos ejecuciones dan bytes idénticos.
- `test_publicado_inmutable`: con otra huella de entradas → error, sin sobrescribir.
- `test_pronosticar_falla_sin_datos` y `test_pronosticar_degradado_con_hueco_menor`.
- `test_pedido_en_publicacion_usa_business_yaml`.

## Verificación con datos reales

```bash
python -m reposicion.cli comparar --corte 2017-08-14     # mide el tiempo
python -m reposicion.cli entrenar --corte 2017-01-02     # champion inicial para operar en 2017
python -m reposicion.cli pronosticar --corte 2017-03-13  # corte con el escenario tardío
python -m reposicion.cli pronosticar --corte 2017-03-13  # otra vez → no-op, mismos hashes
```

LightGBM debe mejorar al baseline en el costo de negocio. Si no lo hace, **no lo ocultes**:
revisa las features y la regla de ceros, y si aun así no mejora, reporta los números al usuario.
Commitea `reports/comparacion_modelos.md` (es pequeño y es evidencia). Al terminar,
`dvc add data/models data/published data/backtest` y `dvc push`.

## Documentación

- `DECISIONES.md` §8 (agregar LightGBM, sus parámetros y por qué no deep learning, con números de
  tiempo y costo), §10 (criterio de reemplazo y `champion_vigente` por fecha) y el formato del
  manifiesto.
- `README.md`: comandos `entrenar`, `comparar` y `pronosticar`.

## Criterios de terminado

- [ ] LightGBM supera al baseline en el mismo backtest (o la diferencia queda reportada y explicada).
- [ ] `reports/comparacion_modelos.md` está generado y commiteado.
- [ ] `pronosticar --corte` publica de forma idempotente, con manifiesto y sin timestamps.
- [ ] Existe un champion registrado con `fecha_promocion <= 2017-01-02`.
- [ ] `plan/ESTADO.md` y DECISIONES actualizados.
