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

`config/validation.yaml`:

```yaml
variacion_volumen_max: 3.0        # advertir si el total del día > 3× o < 1/3 de la mediana de 28 días
modo_degradado:
  max_dias_sin_ventas: 3          # en el corte T: si la última venta disponible < T-1-3 → fallar
```

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

- `tiendas_validas` = maestro `asof("tiendas", fecha_entrega)`. Por eso, dentro de una misma
  `fecha_entrega`, se procesa **primero** el archivo de tiendas.
- `familias_validas` = familias del histórico de ventas.

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
- En el histórico de `tiendas`, `fecha_dato = fecha_disponible = date.min` (siempre disponible).
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

Agrega también `ultima_fecha_disponible(fuente, corte, dir_data) -> date | None`, que se usará en
el modo degradado.

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

Usa el simulador con los datos sintéticos de `tests/unit/test_simulador.py`: mueve el fixture de
datos tipo Kaggle a `tests/conftest.py` para reutilizarlo y genera con él una bandeja pequeña con
los escenarios. Pruebas mínimas:

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
- `test_historico_respeta_disponibilidad`: `asof("ventas", 2016-06-06)` no contiene fechas ≥
  2016-06-06; las promociones llegan hasta 2016-06-16.
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

Luego `dvc add data/raw data/ledger data/limpio`, `dvc push` y commitea los `.dvc`.

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
