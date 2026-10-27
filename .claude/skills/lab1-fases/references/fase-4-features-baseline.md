# Fase 4 — Features, baseline, backtest, métricas y pedido

**Rama:** `feat/features-baseline` · **Estimado:** 1.5 días · **Prerequisitos:** fase 3 (`asof`).

## Objetivo

1. Construir features **ancladas al origen** (sin recursión) que se calculen igual en el
   entrenamiento y en la inferencia.
2. Un **baseline** simple con cuantiles, detrás de una interfaz común de modelo.
3. Un **backtest rolling-origin** idéntico para todos los modelos, con métricas técnicas y de
   negocio.
4. El **pedido sugerido** (newsvendor) a partir del pronóstico y de `business.yaml`.

## Decisiones para el usuario (preguntar al inicio)

1. **Costos de negocio** por unidad, que definen el cuantil crítico τ = c_quiebre / (c_quiebre + c_merma).
   - (Recommended) Tres grupos: perecederos (quiebre 1.0, merma 1.5 → τ = 0.40), no perecederos
     (1.0, 0.1 → τ ≈ 0.91) y default (1.0, 0.5 → τ ≈ 0.67). Perecederos: PRODUCE, DAIRY, MEATS,
     POULTRY, SEAFOOD, BREAD/BAKERY, DELI, EGGS, FROZEN FOODS, PREPARED FOODS.
   - Un solo grupo para todas las familias (más simple, menos realista).
   - Valores propios del usuario.
2. **Cobertura y lead time del pedido.**
   - (Recommended) Cobertura de 7 días con lead time 0: el pedido del corte T cubre T..T+6 (h = 1..7).
   - Lead time de 2 días: cubre T+2..T+8.
3. **Cómo se agrega la demanda de la semana para el pedido.**
   - (Recommended) Suma de los cuantiles diarios τ (supuesto de dependencia perfecta,
     conservador). Es simple y se documenta.
   - Cuantil τ de la demanda semanal entrenado directamente (más correcto, pero agrega modelos).
     Se puede evaluar en la fase 5.
4. **Ventana de entrenamiento.**
   - (Recommended) Orígenes semanales en las últimas 52 semanas antes del corte (~1.3 millones de
     filas). Cabe en memoria y cubre un año de estacionalidad.
   - Desde 2015-01-01 (~3 millones de filas; más lento y con más memoria).

## Configuración nueva

`config/model.yaml`:

```yaml
horizonte_dias: 14
dia_corte: 0                     # 0 = lunes
cuantiles_reporte: [0.1, 0.5, 0.9]
ventana_origenes_semanas: 52
semilla: 2017
backtest:
  n_origenes: 8                  # últimos 8 lunes cuyos 14 días ya se conocen
  paso_dias: 7
ventana_features_dias: 364       # cuánta historia usan las features (para cortes_afectados)
regla_ceros: {dias_sin_ventas: 56}   # serie sin ventas en 56 días → pronóstico 0
```

`config/business.yaml`:

```yaml
cobertura_dias: 7
lead_time_dias: 0
inventario_inicial: 0            # supuesto: no hay datos de inventario
redondeo: entero_arriba
grupos:
  perecederos:    {c_quiebre: 1.0, c_merma: 1.5, familias: [PRODUCE, DAIRY, ...]}
  no_perecederos: {c_quiebre: 1.0, c_merma: 0.1, familias: [AUTOMOTIVE, HARDWARE, ...]}
  default:        {c_quiebre: 1.0, c_merma: 0.5}      # todas las demás
```

Valida con pydantic que cada familia pertenezca a un solo grupo y que `default` exista.

## Módulos y contratos

### `src/reposicion/datos.py`

```python
def cargar_datos_asof(corte: date, dir_data: Path) -> dict[str, pd.DataFrame]
```

Llama a `asof` para cada fuente una sola vez. Todo lo demás trabaja sobre este diccionario.

### `src/reposicion/features.py`

```python
def construir_features(datos: dict[str, pd.DataFrame], origenes: list[date],
                       cfg_modelo, cfg_fuentes, con_objetivo: bool) -> pd.DataFrame
```

Devuelve una fila por (store_nbr, family, origen, fecha_objetivo), con
`fecha_objetivo = origen + h - 1` y h = 1..14. Columnas de identificación: `store_nbr`, `family`,
`origen`, `fecha_objetivo`, `h`. Si `con_objetivo`, agrega también `y` (sales real, NaN si no se
conoce).

**Regla anti-leakage (idéntica en entrenamiento e inferencia):** para el origen O, cada fuente solo
aporta filas que habrían estado disponibles en O según su lag de `sources.yaml`:

| Fuente | Se usa en el origen O | Comentario |
|---|---|---|
| ventas | `date <= O - 1` | |
| transacciones | `date <= O - lag_esperado` (3) | |
| petróleo | `date <= O - 1`, con forward-fill **solo hacia adelante** | |
| promociones | del día objetivo, solo si `fecha_objetivo <= O + anticipación` (10); si no, NaN | |
| feriados | todos (se conocen de antemano) | en inferencia, asof ya los filtra |

En inferencia, `datos` viene de `asof(T)`, que de por sí no contiene lo que no existía. La regla
anterior hace que el entrenamiento **imite** esa misma falta de información. Por ejemplo, la
promoción para h = 12..14 debe venir en NaN en ambos casos.

**Features** (en `float32`; las categóricas como `category` con categorías fijas tomadas del maestro
de tiendas y del catálogo de familias):

- Ventas ancladas en O: `lag_1` (O−1), `lag_7`, `lag_14`, `lag_28`, `lag_364`; medias móviles de
  7, 14, 28 y 56 días; mediana de 28; desviación estándar de 28; `media_dds_4` y `media_dds_8`
  (media de los últimos 4 u 8 días con el mismo día de semana que `fecha_objetivo`); proporción de
  días en 0 en 28; días desde la última venta > 0.
- Calendario del día objetivo: día de la semana, día del mes, mes, semana del año, `es_quincena`
  (día 15 o último día del mes, que son días de pago en Ecuador) y h.
- Feriados del día objetivo, según la tienda (nacional, regional por `state`, local por `city`):
  `es_feriado`, `es_puente`, `es_dia_laboral_extra`, `es_evento`, días al próximo feriado y desde
  el anterior. Un feriado `transferred=True` no cuenta en su fecha original; cuenta su `Transfer`.
- Promociones: `onpromotion` del día objetivo (NaN si no se conoce) y su media de 28 días hasta O−1.
- Petróleo: último valor conocido en O−1 y su cambio porcentual en 28 días.
- Transacciones: media de 28 días hasta el último dato permitido.
- Estáticas: store_nbr, family, city, state, type y cluster (categóricas).

Implementación sugerida: una matriz ancha de ventas (series × fechas) para calcular lags y
ventanas de forma vectorizada; evita el `groupby().apply` fila por fila. Mide el tiempo: la meta
es construir 52 orígenes en menos de ~2 minutos.

### `src/reposicion/modelos/base.py`

```python
class ModeloPronostico(Protocol):
    nombre: str
    def ajustar(self, X: pd.DataFrame, y: pd.Series) -> "ModeloPronostico": ...
    def predecir_cuantiles(self, X: pd.DataFrame, cuantiles: list[float]) -> pd.DataFrame: ...
        # columnas "q0.10", "q0.50", …; valores >= 0 y monótonos por fila
    def guardar(self, ruta: Path) -> None: ...
    @classmethod
    def cargar(cls, ruta: Path) -> "ModeloPronostico": ...

def nombre_cuantil(q: float) -> str   # 0.1 -> "q0.10", 0.4 -> "q0.40"; se usa en todo el proyecto
def cuantiles_requeridos(cfg_modelo, cfg_negocio) -> list[float]   # reporte ∪ τ de cada grupo, ordenados
def ordenar_cuantiles(df) -> df        # aplica np.sort por fila para que no se crucen
```

### `src/reposicion/modelos/baseline.py`

- Punto: `media_dds_4` (media de los últimos 4 días con el mismo día de semana).
- Cuantiles: en `ajustar`, calcula los residuos en espacio log
  `r = log1p(y) - log1p(punto)` y guarda sus cuantiles empíricos por (family, h). En la
  predicción: `expm1(log1p(punto) + r_q)`, recortado a ≥ 0.
- Aplica la regla de ceros: si una serie no tuvo ventas en 56 días, todos sus cuantiles son 0.
- Se guarda como JSON o parquet en `ruta/`, sin pickle.

### `src/reposicion/metricas.py`

```python
def wape(y, pred) -> float                      # sum|y-p| / sum y
def rmsle(y, pred) -> float
def pinball(y, pred_q, q) -> float
def cobertura(y, bajo, alto) -> float           # proporción de y dentro de [q0.10, q0.90]
def costo_newsvendor(y_cobertura, pedido, c_quiebre, c_merma) -> float
def resumen_metricas(predicciones, cfg_negocio, por: list[str] | None) -> pd.DataFrame
```

`costo_newsvendor` se calcula sobre la demanda agregada de la cobertura (la suma de `y` en los
días del pedido) comparada con el pedido. Reporta también el fill rate y el % de unidades en merma.

### `src/reposicion/pedido.py`

```python
def cuantil_critico(c_quiebre: float, c_merma: float) -> float
def grupo_de_familia(family: str, cfg_negocio) -> str
def calcular_pedido(pronostico: pd.DataFrame, cfg_negocio) -> pd.DataFrame
```

Columnas de salida: `corte`, `store_nbr`, `family`, `grupo`, `cuantil_critico`,
`cobertura_desde`, `cobertura_hasta`, `demanda_cuantil` (suma de q_τ en la cobertura),
`inventario_inicial`, `pedido` (entero, ≥ 0, redondeado hacia arriba).

Si τ no está entre las columnas del pronóstico, interpola linealmente entre los cuantiles vecinos
y registra un warning.

### `src/reposicion/backtest.py`

```python
def origenes_backtest(corte_final: date, cfg_modelo) -> list[date]
    # los últimos n lunes O con O + horizonte - 1 <= corte_final - 1 (el real ya se conoce)
def ejecutar_backtest(fabrica: Callable[[], ModeloPronostico], corte_final: date,
                      dir_data: Path, cfgs) -> pd.DataFrame
```

- Carga `cargar_datos_asof(corte_final)` una sola vez. Para cada origen de backtest O: entrena con
  los orígenes O' tales que `O' + horizonte - 1 <= O - 1` (ventana de 52 semanas), predice O con
  `cuantiles_requeridos` y guarda las predicciones junto con `y`.
- Usa los **mismos orígenes y la misma ventana para todos los modelos** (lo exige el enunciado).
- Documenta en DECISIONES que el backtest usa los datos revisados a `corte_final`, mientras que
  la operación usa as-of estricto.

### CLI

`python -m reposicion.cli backtest --modelo baseline --corte 2017-08-14` → escribe
`data/backtest/<modelo>/<corte>/predicciones.parquet` y `metricas.parquet`, e imprime el resumen.

## Pruebas requeridas

- `test_features_sin_leakage`: para O fijo, cambiar ventas con `date >= O` (o promociones con
  fecha > O+10, o transacciones posteriores a O−3) **no** cambia ninguna feature.
- `test_features_iguales_en_entrenamiento_e_inferencia`: las features de O construidas desde
  `asof(T_grande)` (entrenamiento) son iguales a las construidas desde `asof(O)` (inferencia),
  salvo `y`. Usa una bandeja sintética **sin correcciones**: con correcciones, la diferencia es
  esperada, porque son datos revisados.
- `test_lags_correctos` con una serie sintética conocida (por ejemplo ventas = número de día).
- `test_feriado_local_solo_en_su_ciudad`; `test_feriado_transferido`.
- `test_baseline_cuantiles_monotonos_y_no_negativos`; `test_regla_ceros`.
- Métricas: valores calculados a mano para casos pequeños.
- `test_cuantil_critico`; `test_pedido_cambia_si_cambian_costos` (mismo pronóstico y otro YAML →
  otro pedido, **sin tocar código**); `test_pedido_interpola_cuantil_faltante`.
- `test_origenes_backtest_no_usan_futuro`.

## Verificación con datos reales

```bash
python -m reposicion.cli backtest --modelo baseline --corte 2017-08-14
```

Revisa: 8 orígenes, ~1,782 × 14 × 8 ≈ 200 mil predicciones, WAPE del baseline en un rango razonable
(como referencia, entre 0.2 y 0.5 a nivel tienda-familia-día), cobertura P10–P90 cercana al 80% y
el tiempo total. Anota las métricas en el PR: son el piso que el modelo de la fase 5 debe superar.

## Documentación

- `DECISIONES.md` §8 (baseline, validación temporal y métricas) y §9 (pedido newsvendor, τ, suma
  de cuantiles, inventario 0, lead time).
- `README.md`: cómo correr el backtest.

## Criterios de terminado

- [ ] Las pruebas de no-leakage de features pasan.
- [ ] Hay métricas del baseline sobre datos reales y quedaron anotadas.
- [ ] Al cambiar `business.yaml` cambia el pedido (existe una prueba de ello).
- [ ] `plan/ESTADO.md` y DECISIONES actualizados.
