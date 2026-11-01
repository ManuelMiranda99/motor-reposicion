# Comparación de modelos — corte 2017-08-14

Backtest rolling-origin con 8 orígenes semanales (2017-06-12 a 2017-07-31), misma ventana de entrenamiento (52 semanas) y mismos datos para ambos modelos. Datos revisados a la fecha del corte (ver DECISIONES §8). 199,584 predicciones diarias por modelo.

## Métricas globales

| Métrica | Baseline | LightGBM | Cambio relativo |
|---|---|---|---|
| WAPE (mediana) | 0.1412 | 0.1197 | -15.2% |
| RMSLE (mediana) | 0.4513 | 0.3998 | -11.4% |
| Pinball q0.50 | 33.626 | 28.508 | -15.2% |
| Pinball q0.90 | 22.378 | 17.070 | -23.7% |
| Cobertura P10-P90 | 0.8412 | 0.8019 | -4.7% |
| Costo de negocio total | 2,949,032 | 2,363,349 | -19.9% |
| Fill rate | 0.9730 | 0.9722 | -0.1% |
| Merma (% de lo pedido) | 0.1018 | 0.0595 | -41.5% |

## Decisión de promoción (LightGBM como challenger del baseline)

**PROMOVER**

- cumple: el costo total baja 19.9% (se exige al menos 3%)
- cumple: el WAPE cambia -15.2% (se tolera hasta +1%)
- cumple: cobertura P10-P90 0.802 (rango [0.7, 0.9])
- cumple: ninguna familia grande empeora su costo de forma material
- cumple: checks técnicos sin problemas

## Por familia (ordenadas por volumen)

| Familia | % volumen | WAPE base | WAPE LGBM | Costo base | Costo LGBM | Δ costo |
|---|---|---|---|---|---|---|
| GROCERY I | 29.3% | 0.126 | 0.100 | 817,088 | 513,774 | -37.1% |
| BEVERAGES | 22.6% | 0.149 | 0.128 | 703,524 | 576,638 | -18.0% |
| PRODUCE | 15.1% | 0.087 | 0.078 | 353,443 | 333,804 | -5.6% |
| CLEANING | 8.3% | 0.227 | 0.193 | 228,267 | 201,126 | -11.9% |
| DAIRY | 5.6% | 0.105 | 0.090 | 154,184 | 131,991 | -14.4% |
| BREAD/BAKERY | 3.5% | 0.113 | 0.103 | 122,788 | 114,871 | -6.4% |
| POULTRY | 2.5% | 0.126 | 0.108 | 82,834 | 73,872 | -10.8% |
| MEATS | 2.4% | 0.130 | 0.120 | 82,767 | 78,678 | -4.9% |
| HOME CARE | 2.0% | 0.178 | 0.146 | 30,086 | 21,597 | -28.2% |
| DELI | 2.0% | 0.137 | 0.114 | 74,913 | 58,325 | -22.1% |
| PERSONAL CARE | 2.0% | 0.192 | 0.142 | 41,788 | 27,001 | -35.4% |
| EGGS | 1.3% | 0.179 | 0.171 | 59,630 | 64,835 | +8.7% |
| FROZEN FOODS | 0.8% | 0.181 | 0.166 | 44,228 | 44,910 | +1.5% |
| LIQUOR,WINE,BEER | 0.6% | 0.294 | 0.260 | 27,769 | 16,684 | -39.9% |
| PREPARED FOODS | 0.6% | 0.174 | 0.166 | 27,138 | 29,015 | +6.9% |
| GROCERY II | 0.2% | 0.365 | 0.347 | 15,545 | 14,030 | -9.7% |
| HOME AND KITCHEN I | 0.2% | 0.415 | 0.341 | 10,364 | 7,820 | -24.5% |
| HOME AND KITCHEN II | 0.2% | 0.391 | 0.325 | 8,657 | 6,866 | -20.7% |
| SEAFOOD | 0.1% | 0.256 | 0.226 | 11,308 | 9,309 | -17.7% |
| LAWN AND GARDEN | 0.1% | 0.309 | 0.283 | 4,739 | 2,697 | -43.1% |
| SCHOOL AND OFFICE SUPPLIES | 0.1% | 0.942 | 0.889 | 25,378 | 20,031 | -21.1% |
| CELEBRATION | 0.1% | 0.402 | 0.372 | 4,048 | 2,873 | -29.0% |
| LADIESWEAR | 0.1% | 0.364 | 0.325 | 2,702 | 2,104 | -22.1% |
| PLAYERS AND ELECTRONICS | 0.1% | 0.320 | 0.293 | 3,132 | 1,888 | -39.7% |
| PET SUPPLIES | 0.1% | 0.347 | 0.310 | 2,555 | 1,483 | -42.0% |
| AUTOMOTIVE | 0.0% | 0.412 | 0.373 | 2,167 | 1,494 | -31.1% |
| LINGERIE | 0.0% | 0.527 | 0.477 | 2,769 | 1,800 | -35.0% |
| MAGAZINES | 0.0% | 0.413 | 0.390 | 2,010 | 1,358 | -32.4% |
| BEAUTY | 0.0% | 0.418 | 0.354 | 1,862 | 1,178 | -36.7% |
| HARDWARE | 0.0% | 0.770 | 0.703 | 748 | 621 | -16.9% |
| HOME APPLIANCES | 0.0% | 1.410 | 1.001 | 384 | 392 | +2.0% |
| BABY CARE | 0.0% | 1.349 | 0.989 | 178 | 213 | +19.9% |
| BOOKS | 0.0% | 2.109 | 1.047 | 39 | 71 | +81.4% |

## Por horizonte (h = días desde el corte)

| h | WAPE base | WAPE LGBM | Cobertura base | Cobertura LGBM |
|---|---|---|---|---|
| 1.0 | 0.1249 | 0.1107 | 0.8630 | 0.8067 |
| 2.0 | 0.1555 | 0.1157 | 0.8240 | 0.8067 |
| 3.0 | 0.1319 | 0.1047 | 0.8375 | 0.8095 |
| 4.0 | 0.1406 | 0.1197 | 0.8430 | 0.7952 |
| 5.0 | 0.1308 | 0.1216 | 0.8450 | 0.7986 |
| 6.0 | 0.1322 | 0.1125 | 0.8409 | 0.8023 |
| 7.0 | 0.1434 | 0.1245 | 0.8380 | 0.8053 |
| 8.0 | 0.1288 | 0.1155 | 0.8586 | 0.8013 |
| 9.0 | 0.1595 | 0.1199 | 0.8204 | 0.8005 |
| 10.0 | 0.1366 | 0.1087 | 0.8395 | 0.8060 |
| 11.0 | 0.1435 | 0.1264 | 0.8479 | 0.7948 |
| 12.0 | 0.1472 | 0.1316 | 0.8368 | 0.8072 |
| 13.0 | 0.1530 | 0.1299 | 0.8319 | 0.7936 |
| 14.0 | 0.1505 | 0.1294 | 0.8452 | 0.7997 |

## Variante: cuantil de la demanda semanal para el pedido

Un modelo LightGBM con objetivo = suma de los 7 días de la cobertura (una fila por serie y origen; un cuantil por grupo de costos), contra el pedido por suma de cuantiles diarios. Mismos orígenes, mismas series y misma demanda real; solo cuentan los pedidos cuyos 7 días reales se conocen (por eso el costo total difiere del de la tabla global, que descarta los días sin dato real). Un costo menor es mejor.

| Pedido | Costo total | Fill rate | Merma | Costo perecederos | Costo no_perecederos | Costo default | Δ costo vs LGBM diario |
|---|---|---|---|---|---|---|---|
| Baseline, suma de cuantiles diarios | 2,647,613 | 0.9739 | 0.1051 | 884,349 | 350,838 | 1,412,426 | +25.5% |
| LightGBM, suma de cuantiles diarios (actual) | 2,109,878 | 0.9713 | 0.0586 | 844,218 | 279,543 | 986,117 | +0.0% |
| LightGBM, cuantil de la demanda semanal | 2,357,522 | 0.9673 | 0.0498 | 957,180 | 311,698 | 1,088,644 | +11.7% |
