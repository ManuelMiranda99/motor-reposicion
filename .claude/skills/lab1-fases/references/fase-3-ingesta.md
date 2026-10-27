# Fase 3 — Ingesta, ledger, validación y as-of

**Rama:** `feat/ingesta` · **Estimado:** 2 días · **Prerequisitos:** fases 0–2.

Esta es la fase más importante del laboratorio: todo lo demás confía en que `asof(fuente, T)`
devuelva **exactamente** lo que se sabía en T, sin importar cuándo se ejecute ni cuántas veces.

## Objetivo

1. Leer la bandeja (sin modificarla), copiar cada archivo nuevo a `data/raw/` y registrarlo en un
   **ledger** con hash, versión y estado.
2. Validar cada archivo: los inválidos van a **cuarentena** (no entran al almacén limpio) y las
   situaciones esperadas solo generan advertencias.
3. Mantener un **almacén limpio** con todas las versiones válidas y su `fecha_disponible`.
4. Exponer `asof(fuente, corte)`.
5. Detectar correcciones y los cortes que afectan (función pura que se usará en la fase 7).

## Decisiones para el usuario (preguntar al inicio)

1. **Archivos sin columna requerida o con columnas extra.**
   - (Recommended) Columna faltante → cuarentena; columna extra → advertencia y se descarta.
   - Estricto: cualquier diferencia de columnas → cuarentena.
2. **Completitud de ventas** (un archivo de ventas con menos filas que tiendas activas × familias).
   - (Recommended) Advertencia y se acepta lo recibido: puede faltar una tienda cerrada.
   - Cuarentena si faltan más de X% de filas (pedir X, sugerir 20%).
3. **Disponibilidad de la carga histórica** (las filas del histórico no tienen fecha de entrega).
   - (Recommended) Aplicar la regla de cada fuente: ventas D+1, transacciones D+3 (el peor caso),
     petróleo D+1, promociones D−10, feriados un trimestre antes, tiendas siempre disponibles.
     Así los backtests de 2016 respetan el as-of.
   - Todo el histórico disponible en la fecha de carga (2017-01-01). Más simple, pero los
     backtests en 2016 tendrían leakage.
4. **Formato del almacén limpio.**
   - (Recommended) Un parquet por fuente con **todas** las versiones, reconstruido de forma
     determinista desde el histórico + el ledger + `data/raw` (idempotente por construcción).
   - Particionado por `fecha_dato` (más escalable, más complejo de mantener idempotente).

## Configuración nueva

`config/sources.yaml` (ajusta según las respuestas):

```yaml
fecha_carga_historica: 2017-01-01
bandeja:
  variable_entorno: REPOSICION_BANDEJA
  ruta_defecto: bandeja_sim
  patron_carpeta: '^\d{4}-\d{2}-\d{2}$'
  patron_archivo: '^(?P<fuente>[a-z]+)_(?P<fecha_dato>\d{4}-\d{2}-\d{2})\.csv$'
  prefijo_ignorado: "_"
fuentes:
  ventas:
    columnas: {date: fecha, store_nbr: entero, family: texto, sales: decimal}
    llave: [date, store_nbr, family]
    no_negativas: [sales]
    nulos_permitidos: []
    disponibilidad_historica: {tipo: dias, dias: 1}
    lag_esperado_dias: 1
    tolerancia_retraso_dias: 2
    imprescindible: true
  promociones:
    columnas: {date: fecha, store_nbr: entero, family: texto, onpromotion: entero}
    llave: [date, store_nbr, family]
    no_negativas: [onpromotion]
    disponibilidad_historica: {tipo: dias, dias: -10}
    lag_esperado_dias: -10
    imprescindible: false
  transacciones:
    columnas: {date: fecha, store_nbr: entero, transactions: entero}
    llave: [date, store_nbr]
    no_negativas: [transactions]
    disponibilidad_historica: {tipo: dias, dias: 3}
    lag_esperado_dias: 3
    imprescindible: false
  petroleo:
    columnas: {date: fecha, dcoilwtico: decimal}
    llave: [date]
    no_negativas: [dcoilwtico]
    nulos_permitidos: [dcoilwtico]
    disponibilidad_historica: {tipo: dias, dias: 1}
    lag_esperado_dias: 1
    imprescindible: false
  feriados:
    columnas: {date: fecha, type: texto, locale: texto, locale_name: texto, description: texto, transferred: booleano}
    llave: [date, locale_name, description]
    disponibilidad_historica: {tipo: trimestre_anticipado, trimestres: 1}
    imprescindible: false
  tiendas:
    columnas: {store_nbr: entero, city: texto, state: texto, type: texto, cluster: entero}
    llave: [store_nbr]
    snapshot: true             # cada archivo reemplaza el maestro completo
    disponibilidad_historica: {tipo: siempre}
    imprescindible: true
```

Reglas de llenado de `sources.yaml`:
- Toda fuente con `lag_esperado_dias` lleva también `tolerancia_retraso_dias`. Si no se indica,
  vale 0.
  - Valores: ventas 2, promociones 0, transacciones 0 (3 ya es el peor caso del lag variable),
    petróleo 2.
  - `feriados` y `tiendas` no tienen lag esperado y nunca se marcan como tardíos.
- `imprescindible` no lo consume la fase 3. Lo usa `verificar_datos` en la fase 5/6, para decidir
  qué fuentes pueden fallar el corte.

`config/validation.yaml`:

```yaml
modo_degradado:
  max_dias_sin_ventas: 3          # en el corte T: si la última venta disponible < T-1-3 → fallar
  ventana_huecos_dias: 28         # contar fechas faltantes de ventas en los últimos 28 días → advertencia
# completitud_min_ventas: 0.8     # solo si el usuario elige la opción "cuarentena si falta > X%"
```

No implementes una regla de variación de volumen en esta fase: necesita historia dentro de la
validación y complica la idempotencia. Queda como mejora futura en DECISIONES.

**Validación con pandas puro.** El plan inicial (P3) proponía pandera, pero las reglas de este
proyecto (fecha del nombre, maestro vigente, llave, tipos desde texto) son más claras como
funciones de pandas, y así se evita una dependencia. Si el usuario prefiere pandera, pregúntalo
como una quinta decisión. Si no, anota en DECISIONES que se descartó y por qué.

## Rutas y variables de entorno

Crea `src/reposicion/rutas.py` con `dir_data() -> Path` (variable `REPOSICION_DATA`, por defecto
`<repo>/data`) y `dir_bandeja() -> Path` (variable `REPOSICION_BANDEJA`, por defecto
`<repo>/bandeja_sim`). **Solo la CLI y los DAGs** llaman a estas funciones; los módulos de lógica
siempre reciben las rutas por parámetro (así las pruebas usan `tmp_path`).

## Escritura determinista de parquet

Crea `src/reposicion/io.py` con `escribir_parquet(df, ruta)`:
1. Convierte con `pa.Table.from_pandas(df, preserve_index=False)` y un esquema explícito (fechas
   como `date32`, enteros `int64`, texto `string`).
2. Elimina los metadatos de pandas con `table.replace_schema_metadata(None)`.
3. Escribe con `pq.write_table(..., compression="zstd")` a `ruta.tmp` y luego `os.replace`.

Úsalo para **todo** parquet del proyecto. Para "siempre disponible" usa la fecha centinela
`date(1900, 1, 1)`, no `date.min`. Prueba: escribir dos veces el mismo DataFrame da bytes
idénticos.

## Módulos y contratos

### `src/reposicion/fuentes.py`
- Modelos pydantic para `sources.yaml` y `cargar_fuentes(ruta) -> ConfigFuentes`.
- `fecha_disponible_historica(fuente_cfg, fecha_dato: date) -> date`.

### `src/reposicion/validacion.py`

```python
@dataclass
class ResultadoValidacion:
    valido: bool
    errores: list[str]        # reglas duras → cuarentena
    advertencias: list[str]   # reglas blandas → solo registro
    datos: pd.DataFrame | None  # tipado, solo si valido

def validar_archivo(texto: pd.DataFrame, fuente: str, fecha_dato: date,
                    cfg: ConfigFuentes, tiendas_validas: set[int],
                    familias_validas: set[str]) -> ResultadoValidacion
```

`texto` se lee con `pd.read_csv(ruta, dtype=str, keep_default_na=False)`.

**Reglas duras (errores):** archivo vacío o ilegible; columna requerida faltante; valor no
convertible al tipo (incluye `N/A` y vacío donde no se permiten nulos); `date` distinta de
`fecha_dato` (en feriados: fuera del trimestre; tiendas no tiene `date`); llave duplicada;
negativos en `no_negativas`; `store_nbr` fuera de `tiendas_validas`; `family` fuera de
`familias_validas`.

**Reglas blandas (advertencias):** columnas extra (se descartan); filas incompletas respecto a
tiendas × familias; total del día de una tienda en 0 (tienda cerrada); petróleo vacío; volumen
fuera de rango (esta regla necesita historia, así que es opcional en `validar_archivo` y puede
hacerse en la ingesta).

- `tiendas_validas` = el maestro de tiendas **vigente en `fecha_entrega`**. Durante la ingesta
  **no** se obtiene con `asof` (el almacén limpio se reconstruye al final y puede estar
  desactualizado). En cambio, `ingestar` mantiene el maestro en memoria:
  1. Parte de `data/historico/tiendas.csv`.
  2. Lo reemplaza por el último snapshot `tiendas` **válido** del ledger con
     `fecha_entrega <= hasta` que ya se haya procesado, leído de `data/raw`.
  3. Al validar un archivo nuevo de `tiendas`, actualiza el maestro antes de seguir.

  Como los archivos se procesan en orden (por `fecha_entrega`, con `tiendas` primero), ingerir de
  forma incremental o completa da el mismo resultado. Una fila de la tienda 52 entregada antes del
  2017-04-13 sería `tienda desconocida`, es decir, cuarentena (el simulador nunca la genera; está
  bien que sea así).
- `familias_validas` = familias del histórico de ventas.
- Completitud de ventas: "tiendas activas" = las tiendas del maestro vigente.

### `src/reposicion/ingesta.py`

```python
@dataclass(frozen=True)
class ArchivoBandeja:
    fuente: str
    fecha_dato: date
    fecha_entrega: date
    ruta: Path          # absoluta, dentro de la bandeja
    relativa: str       # "<fecha_entrega>/<archivo>"
    sha256: str

def escanear_bandeja(bandeja: Path, hasta: date, cfg) -> list[ArchivoBandeja]
def ingestar(hasta: date, dir_data: Path, bandeja: Path, cfg_fuentes, cfg_validacion) -> ResumenIngesta
```

- `escanear_bandeja` solo devuelve archivos con `fecha_entrega <= hasta` (**clave para el
  backfill**), ignora los que empiezan con `_`, y registra con un warning los nombres que no
  coinciden con el patrón (no se lanza error). El orden es estable: por `fecha_entrega`, con
  `tiendas` primero y luego por nombre.
- `ingestar` es **idempotente**: la llave de idempotencia es `(relativa, sha256)`; si ya está en el
  ledger, no se hace nada. Para cada archivo nuevo: copia byte a byte a
  `data/raw/<relativa>` (con `shutil.copyfile`, nunca mueve ni borra la bandeja), valida y
  agrega una fila al ledger. Al final reconstruye el almacén limpio si hubo cambios.
- **Estado y versión de un archivo nuevo** (el mismo `fuente` + `fecha_dato` puede llegar varias
  veces, en carpetas distintas):

  | Caso | estado | version | es_correccion |
  |---|---|---|---|
  | falla la validación | `cuarentena` | 0 | False |
  | válido y es el primero válido de esa fecha | `valido` | 1 | False |
  | válido, mismo sha256 que la **última versión válida** | `duplicado` | la de esa versión | False |
  | válido, contenido distinto de la última versión válida (aunque sea igual a una versión más vieja) | `valido` | última + 1 | True |

  Un archivo idéntico a uno en cuarentena se vuelve a validar y da el mismo resultado: otra fila
  `cuarentena`. Así, "igual a una versión vieja" cuenta como una versión nueva: la fuente volvió a
  enviar ese contenido como el vigente.
- Devuelve un resumen: nuevos, válidos, en cuarentena, duplicados, advertencias y correcciones
  detectadas.

**Ledger** `data/ledger/ingesta.parquet` (columnas exactas):

| Columna | Tipo | Nota |
|---|---|---|
| fuente | str | |
| fecha_dato | date | |
| fecha_entrega | date | = `fecha_disponible` |
| archivo | str | ruta relativa a la bandeja |
| sha256 | str | |
| estado | str | `valido` \| `cuarentena` \| `duplicado` |
| version | int | por (fuente, fecha_dato): 1, 2, … solo entre archivos **válidos** con contenido distinto; `duplicado` repite la versión del original; `cuarentena` = 0 |
| es_correccion | bool | válido con versión > 1 (ya había una versión válida antes) |
| es_tardio | bool | primera versión válida con `fecha_entrega > fecha_dato + lag_esperado + tolerancia` |
| errores | str | separados por `; ` |
| advertencias | str | |
| filas | int | |

Escribe el ledger de forma atómica y ordenado por (fecha_entrega, fuente, fecha_dato, archivo),
para que dos ejecuciones produzcan bytes idénticos.

### `src/reposicion/almacen.py`

```python
def reconstruir_limpio(dir_data: Path, cfg_fuentes) -> None
def leer_limpio(dir_data: Path, fuente: str) -> pd.DataFrame
```

- Fuente de la verdad = `data/historico/*.csv` (versión 0, `origen="historico"`,
  `fecha_disponible` según la regla de la fuente) + los archivos `valido` del ledger leídos de
  `data/raw` (`origen="bandeja"`, con su versión).
- Columnas: las tipadas de la fuente + `fecha_dato` (date; en feriados es el inicio del trimestre),
  `fecha_disponible` (date), `version` (int), `origen` (str).
- En el histórico de `tiendas`, `fecha_dato = fecha_disponible = date(1900, 1, 1)` (siempre
  disponible).
- La salida es determinista: orden estable y escritura atómica.

### `src/reposicion/asof.py`

```python
def asof(fuente: str, corte: date, dir_data: Path) -> pd.DataFrame
```

1. Filtra `fecha_disponible <= corte`.
2. Para cada `fecha_dato`, conserva solo las filas de la **versión máxima** disponible.
3. En `tiendas` (snapshot), devuelve únicamente el snapshot con mayor `fecha_dato`.
4. Quita las columnas técnicas (`version`, `origen`); conserva `fecha_dato` y `fecha_disponible`.
5. Puede cachear `leer_limpio` (lru_cache con la ruta y el mtime), pero el resultado no debe
   depender de la caché.

Agrega también dos funciones que usará el modo degradado de la fase 5:
- `ultima_fecha_disponible(fuente, corte, dir_data) -> date | None`: detecta una fuente detenida.
  Si la última venta < T−1−`max_dias_sin_ventas`, se falla.
- `fechas_faltantes(fuente, corte, ventana_dias, dir_data) -> list[date]`: detecta **huecos
  intermedios**, por ejemplo la venta del 2017-07-04 que nunca llega. Hay hueco si una fecha de
  `[T−ventana, T−1]` no tiene datos en `asof`. Excluye las fechas sin datos en ningún año, como el
  25 de diciembre, y los días no hábiles en petróleo. Un hueco solo genera una advertencia y
  `calidad = "degradada"`; no falla.

### `src/reposicion/correcciones.py`

```python
def correcciones_entre(ledger: pd.DataFrame, desde: date, hasta: date) -> pd.DataFrame
    # filas con es_correccion o es_tardio y desde < fecha_entrega <= hasta
def cortes_afectados(correcciones: pd.DataFrame, cortes: list[date],
                     horizonte_dias: int, ventana_features_dias: int) -> list[date]
    # un corte P está afectado si P < fecha_entrega (se calculó antes de la corrección) y
    # P - ventana_features_dias <= fecha_dato <= P + horizonte_dias - 1
```

### `src/reposicion/cli.py`
Una CLI con argparse y subcomandos, que crecerá en las demás fases. En esta fase:
`python -m reposicion.cli ingestar --hasta 2017-09-01 [--bandeja ruta] [--data ruta]`,
que imprime el resumen.

## Pruebas requeridas (`tests/unit/`)

**Datos sintéticos.** En `tests/unit/test_simulador.py` no hay fixtures compartidos, sino las
funciones `_escribir_kaggle(d)` y `_config(**cambios)` y las constantes `TIENDAS` y `FAMILIAS`.
Refactoriza (sin cambiar lo que prueban las pruebas del simulador):
1. Mueve esas funciones a `tests/sinteticos.py` (un módulo normal; agrega `tests/__init__.py`, que
   ya existe, para que se pueda importar como `tests.sinteticos`). Agrega a `_escribir_kaggle` un
   parámetro `inicio="2016-12-01"` y `fin="2017-02-28"`.
2. En `tests/conftest.py`, define fixtures de sesión: `kaggle_sintetico`, `config_sintetica`
   (el `_config()` actual, con escenarios de enero a febrero de 2017 y la tienda 3 nueva el
   2017-01-20) y `bandeja_sintetica` (corre `simulador.generar` y devuelve `(historico, bandeja)`).
3. Los escenarios de `config/simulador.yaml` (de marzo a julio) **no** se usan en las pruebas
   unitarias: las pruebas usan los de `config_sintetica`. Para un escenario extra, crea una
   config propia en la prueba con `_config(escenarios={...})`.

Pruebas mínimas:

- `test_escanear_respeta_hasta`: ningún archivo con `fecha_entrega > hasta`.
- `test_escanear_ignora_prefijo_y_nombres_raros`.
- `test_ingesta_no_modifica_bandeja`: hashes de la bandeja antes y después iguales.
- `test_ingesta_idempotente`: correr dos veces → ledger y almacén limpio idénticos (bytes).
- `test_ingesta_incremental_igual_a_completa`: ingerir día por día = ingerir todo de una vez.
- Validación: una prueba por cada regla dura (incluye `N/A` y columna faltante) y por cada regla
  blanda (tienda en 0 → advertencia, no error).
- `test_duplicado_identico_no_crea_version`.
- `test_correccion_crea_version_2_y_asof_la_ve_solo_despues`.
- `test_reentrega_valida_tras_cuarentena_es_version_1`.
- `test_tienda_nueva_valida_solo_desde_su_alta`.
- `test_tardio_marcado_y_no_visible_antes_de_su_entrega`.
- `test_historico_respeta_disponibilidad` (dentro del rango sintético): `asof("ventas", 2016-12-12)`
  no contiene fechas ≥ 2016-12-12, y en `asof("promociones", 2016-12-12)` la fecha máxima es el
  2016-12-22.
- `test_ventas_de_ayer_visibles_en_el_corte`: `asof("ventas", T)` contiene T−1 (entregada en T) y
  no contiene T.
- `test_fechas_faltantes_detecta_hueco` (con un escenario de ventas faltante) y
  `test_ultima_fecha_disponible`.
- `test_duplicado_de_version_vieja_es_version_nueva`.
- `test_escribir_parquet_determinista`.
- **`test_asof_sin_leakage`** (la más importante): genera la bandeja completa y una copia
  truncada con solo las carpetas ≤ T. Ingiere cada una en un `dir_data` distinto y comprueba
  que `asof(f, T)` sea idéntico para todas las fuentes y para varios T, incluido uno justo
  antes de una corrección.
- `test_cortes_afectados`.

## Verificación con datos reales

```bash
python -m reposicion.cli ingestar --hasta 2017-09-01
python - <<'EOF'
import pandas as pd
l = pd.read_parquet("data/ledger/ingesta.parquet")
print(l.estado.value_counts())          # 853 archivos: 847 válidos, 5 en cuarentena, 1 duplicado
print(l[l.estado != "valido"][["fuente", "fecha_dato", "fecha_entrega", "estado", "errores"]])
print(l[l.es_correccion | l.es_tardio][["fuente", "fecha_dato", "fecha_entrega"]])
EOF
```

Compara los resultados con `bandeja_sim/_escenarios.csv`: **cada escenario debe reflejarse**. Haz
una segunda corrida y verifica que nada cambie (`shasum` del ledger antes y después). Mide el tiempo
total; la reconstrucción del almacén limpio debería tardar menos de ~1 minuto.

Luego `dvc add data/raw data/ledger data/limpio`, `dvc push` y commitea los `.dvc`. DVC agrega
`/raw`, `/ledger` y `/limpio` al `data/.gitignore` existente, que es un archivo trackeado: commitea
también ese cambio.

## Documentación

- `DECISIONES.md` §5 (as-of: `fecha_disponible`, regla del histórico, entregas del mismo día T),
  §6 (reglas duras/blandas, cuarentena, modo degradado) y §7 (correcciones: versiones, ledger,
  publicados inmutables). Incluye las alternativas descartadas: mtime y fecha de ingesta.
- `README.md`: comando `ingestar` y qué es el ledger.

## Criterios de terminado

- [ ] Todos los escenarios de `_escenarios.csv` aparecen correctamente en el ledger.
- [ ] La prueba de no-leakage y la de idempotencia pasan.
- [ ] La bandeja nunca se escribe (existe una prueba de ello).
- [ ] Datos nuevos en DVC y subidos al remoto.
- [ ] DECISIONES §5–7 y `plan/ESTADO.md` actualizados.
