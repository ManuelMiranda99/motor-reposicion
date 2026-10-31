# Comparación de modelos — corte 2017-08-14

Backtest rolling-origin con 8 orígenes semanales (2017-06-12 a 2017-07-31), misma ventana de entrenamiento (52 semanas) y mismos datos para ambos modelos. Datos revisados a la fecha del corte (ver DECISIONES §8). 199,584 predicciones diarias por modelo.

## Métricas globales

| Métrica | Baseline | LightGBM | Cambio relativo |
|---|---|---|---|
| WAPE (mediana) | 0.1425 | 0.1207 | -15.3% |
| RMSLE (mediana) | 0.4516 | 0.4000 | -11.4% |
| Pinball q0.50 | 33.941 | 28.741 | -15.3% |
| Pinball q0.90 | 23.003 | 17.111 | -25.6% |
| Cobertura P10-P90 | 0.8431 | 0.7991 | -5.2% |
| Costo de negocio total | 2,991,009 | 2,379,594 | -20.4% |
| Fill rate | 0.9741 | 0.9724 | -0.2% |
| Merma (% de lo pedido) | 0.1062 | 0.0601 | -43.4% |

## Decisión de promoción (LightGBM como challenger del baseline)

**PROMOVER**

- cumple: el costo total baja 20.4% (se exige al menos 3%)
- cumple: el WAPE cambia -15.3% (se tolera hasta +1%)
- cumple: cobertura P10-P90 0.799 (rango [0.7, 0.9])
- cumple: ninguna familia grande empeora su costo de forma material
- cumple: checks técnicos sin problemas

## Por familia (ordenadas por volumen)

| Familia | % volumen | WAPE base | WAPE LGBM | Costo base | Costo LGBM | Δ costo |
|---|---|---|---|---|---|---|
| GROCERY I | 29.3% | 0.128 | 0.101 | 845,189 | 520,147 | -38.5% |
| BEVERAGES | 22.6% | 0.150 | 0.130 | 718,379 | 574,598 | -20.0% |
| PRODUCE | 15.1% | 0.088 | 0.079 | 350,526 | 342,161 | -2.4% |
| CLEANING | 8.3% | 0.228 | 0.194 | 230,335 | 199,657 | -13.3% |
| DAIRY | 5.6% | 0.106 | 0.091 | 154,105 | 133,760 | -13.2% |
| BREAD/BAKERY | 3.5% | 0.114 | 0.104 | 122,296 | 114,789 | -6.1% |
| POULTRY | 2.5% | 0.127 | 0.108 | 82,084 | 76,813 | -6.4% |
| MEATS | 2.4% | 0.131 | 0.121 | 82,046 | 78,644 | -4.1% |
| HOME CARE | 2.0% | 0.178 | 0.146 | 31,654 | 22,086 | -30.2% |
| DELI | 2.0% | 0.139 | 0.114 | 74,413 | 57,465 | -22.8% |
| PERSONAL CARE | 2.0% | 0.193 | 0.141 | 43,237 | 26,874 | -37.8% |
| EGGS | 1.3% | 0.180 | 0.170 | 59,042 | 65,288 | +10.6% |
| FROZEN FOODS | 0.8% | 0.182 | 0.166 | 43,735 | 44,319 | +1.3% |
| LIQUOR,WINE,BEER | 0.6% | 0.295 | 0.260 | 27,896 | 16,516 | -40.8% |
| PREPARED FOODS | 0.6% | 0.174 | 0.168 | 26,831 | 29,722 | +10.8% |
| GROCERY II | 0.2% | 0.366 | 0.346 | 15,699 | 14,310 | -8.9% |
| HOME AND KITCHEN I | 0.2% | 0.416 | 0.340 | 10,471 | 7,893 | -24.6% |
| HOME AND KITCHEN II | 0.2% | 0.393 | 0.323 | 8,767 | 6,869 | -21.7% |
| SEAFOOD | 0.1% | 0.257 | 0.228 | 11,227 | 9,628 | -14.2% |
| LAWN AND GARDEN | 0.1% | 0.309 | 0.285 | 4,794 | 2,659 | -44.5% |
| SCHOOL AND OFFICE SUPPLIES | 0.1% | 0.942 | 0.887 | 25,363 | 19,911 | -21.5% |
| CELEBRATION | 0.1% | 0.402 | 0.371 | 4,088 | 2,864 | -29.9% |
| LADIESWEAR | 0.1% | 0.364 | 0.327 | 2,765 | 2,104 | -23.9% |
| PLAYERS AND ELECTRONICS | 0.1% | 0.321 | 0.293 | 3,164 | 1,884 | -40.5% |
| PET SUPPLIES | 0.1% | 0.348 | 0.313 | 2,603 | 1,477 | -43.3% |
| AUTOMOTIVE | 0.0% | 0.412 | 0.372 | 2,180 | 1,501 | -31.1% |
| LINGERIE | 0.0% | 0.527 | 0.478 | 2,799 | 1,797 | -35.8% |
| MAGAZINES | 0.0% | 0.413 | 0.390 | 2,045 | 1,364 | -33.3% |
| BEAUTY | 0.0% | 0.418 | 0.354 | 1,927 | 1,199 | -37.8% |
| HARDWARE | 0.0% | 0.771 | 0.703 | 748 | 622 | -16.8% |
| HOME APPLIANCES | 0.0% | 1.410 | 1.006 | 386 | 391 | +1.4% |
| BABY CARE | 0.0% | 1.349 | 0.993 | 178 | 210 | +17.6% |
| BOOKS | 0.0% | 2.109 | 1.031 | 39 | 72 | +84.2% |

## Por horizonte (h = días desde el corte)

| h | WAPE base | WAPE LGBM | Cobertura base | Cobertura LGBM |
|---|---|---|---|---|
| 1.0 | 0.1249 | 0.1129 | 0.8627 | 0.8086 |
| 2.0 | 0.1555 | 0.1163 | 0.8239 | 0.8044 |
| 3.0 | 0.1319 | 0.1051 | 0.8373 | 0.8063 |
| 4.0 | 0.1406 | 0.1204 | 0.8429 | 0.7941 |
| 5.0 | 0.1308 | 0.1215 | 0.8460 | 0.7995 |
| 6.0 | 0.1322 | 0.1153 | 0.8414 | 0.7996 |
| 7.0 | 0.1496 | 0.1263 | 0.8511 | 0.8023 |
| 8.0 | 0.1288 | 0.1157 | 0.8591 | 0.7992 |
| 9.0 | 0.1595 | 0.1208 | 0.8204 | 0.7965 |
| 10.0 | 0.1366 | 0.1097 | 0.8394 | 0.8037 |
| 11.0 | 0.1435 | 0.1278 | 0.8483 | 0.7886 |
| 12.0 | 0.1472 | 0.1303 | 0.8371 | 0.8047 |
| 13.0 | 0.1530 | 0.1291 | 0.8331 | 0.7915 |
| 14.0 | 0.1585 | 0.1322 | 0.8561 | 0.7884 |

## Variante: cuantil de la demanda semanal para el pedido

Un modelo LightGBM con objetivo = suma de los 7 días de la cobertura (una fila por serie y origen; un cuantil por grupo de costos), contra el pedido por suma de cuantiles diarios. Mismos orígenes, mismas series y misma demanda real; solo cuentan los pedidos cuyos 7 días reales se conocen (por eso el costo total difiere del de la tabla global, que descarta los días sin dato real). Un costo menor es mejor.

| Pedido | Costo total | Fill rate | Merma | Costo perecederos | Costo no_perecederos | Costo default | Δ costo vs LGBM diario |
|---|---|---|---|---|---|---|---|
| Baseline, suma de cuantiles diarios | 2,687,808 | 0.9750 | 0.1094 | 880,208 | 356,042 | 1,451,558 | +26.7% |
| LightGBM, suma de cuantiles diarios (actual) | 2,121,607 | 0.9715 | 0.0589 | 855,079 | 278,964 | 987,564 | +0.0% |
| LightGBM, cuantil de la demanda semanal | 2,314,601 | 0.9674 | 0.0484 | 923,177 | 310,970 | 1,080,454 | +9.1% |
