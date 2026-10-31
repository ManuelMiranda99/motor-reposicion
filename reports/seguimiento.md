# Seguimiento del desempeño — corte de evaluación 2017-08-14

Compara cada pronóstico publicado con las ventas reales visibles en la fecha de evaluación (la última versión de cada día, así que las correcciones ya están incluidas). Un día sin real es *real pendiente*, no un error.

## Alerta de degradación

WAPE móvil 0.1370 vs backtest 0.1742 (-21.4%): dentro del umbral de 20%

- WAPE móvil (4 cortes: 2017-07-17, 2017-07-24, 2017-07-31, 2017-08-07): **0.1370**
- WAPE del backtest del champion (lgbm-2017-01-02-496d76f4): 0.1742
- Umbral: +20% (solo advertencia, sin reentrenamiento automático)

## Desempeño por corte (última revisión de cada corte)

| Corte | Rev | Estado | Días con real | WAPE | RMSLE | Sesgo | Cobertura P10–P90 | Costo | Costo total | Fill rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 2017-01-02 | 1 | completo | 14 | 0.5631 | 0.6847 | -0.559 | 0.526 | completo | 4,022,376 | 0.4579 |
| 2017-01-09 | 1 | completo | 14 | 0.1586 | 0.4144 | -0.048 | 0.693 | completo | 447,316 | 0.9388 |
| 2017-01-16 | 1 | completo | 14 | 0.1503 | 0.4053 | -0.031 | 0.706 | completo | 385,471 | 0.9480 |
| 2017-01-23 | 1 | completo | 14 | 0.1505 | 0.4555 | -0.058 | 0.721 | completo | 294,318 | 0.9632 |
| 2017-01-30 | 1 | completo | 14 | 0.1395 | 0.4399 | -0.055 | 0.737 | completo | 529,833 | 0.9235 |
| 2017-02-06 | 2 | completo | 14 | 0.1169 | 0.5090 | -0.007 | 0.753 | completo | 351,549 | 0.9528 |
| 2017-02-13 | 1 | completo | 14 | 0.1399 | 0.5304 | -0.005 | 0.742 | completo | 308,336 | 0.9659 |
| 2017-02-20 | 1 | completo | 14 | 0.1959 | 0.5039 | -0.127 | 0.698 | completo | 433,621 | 0.9424 |
| 2017-02-27 | 1 | completo | 14 | 0.1871 | 0.4681 | -0.149 | 0.691 | completo | 1,110,891 | 0.8378 |
| 2017-03-06 | 1 | completo | 14 | 0.1321 | 0.3988 | -0.089 | 0.739 | completo | 489,623 | 0.9210 |
| 2017-03-13 | 2 | completo | 14 | 0.1315 | 0.4122 | -0.088 | 0.761 | completo | 511,793 | 0.9199 |
| 2017-03-20 | 1 | completo | 14 | 0.1512 | 0.5585 | -0.088 | 0.743 | completo | 489,987 | 0.9231 |
| 2017-03-27 | 1 | completo | 14 | 0.1501 | 0.5385 | -0.056 | 0.750 | completo | 559,827 | 0.9215 |
| 2017-04-03 | 1 | completo | 14 | 0.1400 | 0.4418 | -0.040 | 0.754 | completo | 381,792 | 0.9539 |
| 2017-04-10 | 1 | completo | 14 | 0.1326 | 0.4222 | -0.027 | 0.760 | completo | 386,571 | 0.9469 |
| 2017-04-17 | 1 | completo | 14 | 0.1441 | 0.7361 | -0.041 | 0.764 | completo | 464,654 | 0.9493 |
| 2017-04-24 | 1 | completo | 14 | 0.1676 | 0.4513 | -0.081 | 0.736 | completo | 467,434 | 0.9365 |
| 2017-05-01 | 1 | completo | 14 | 0.1575 | 0.4411 | -0.069 | 0.742 | completo | 677,130 | 0.9099 |
| 2017-05-08 | 2 | completo | 14 | 0.1308 | 0.4368 | -0.027 | 0.770 | completo | 397,868 | 0.9680 |
| 2017-05-15 | 1 | completo | 14 | 0.1335 | 0.4248 | -0.075 | 0.777 | completo | 423,496 | 0.9400 |
| 2017-05-22 | 1 | completo | 14 | 0.1319 | 0.3999 | -0.055 | 0.793 | completo | 312,089 | 0.9580 |
| 2017-05-29 | 1 | completo | 14 | 0.1362 | 0.3986 | -0.072 | 0.783 | completo | 403,707 | 0.9484 |
| 2017-06-05 | 1 | completo | 14 | 0.1295 | 0.4003 | -0.049 | 0.767 | completo | 419,039 | 0.9415 |
| 2017-06-12 | 1 | completo | 14 | 0.1183 | 0.3900 | -0.021 | 0.781 | completo | 277,677 | 0.9681 |
| 2017-06-19 | 1 | completo | 14 | 0.1094 | 0.3900 | -0.024 | 0.803 | completo | 255,864 | 0.9708 |
| 2017-06-26 | 1 | parcial | 13 | 0.1071 | 0.3771 | -0.010 | 0.817 | completo | 281,626 | 0.9762 |
| 2017-07-03 | 1 | parcial | 13 | 0.1086 | 0.3792 | -0.009 | 0.808 | pendiente | — | — |
| 2017-07-10 | 1 | completo | 14 | 0.1172 | 0.3890 | -0.008 | 0.798 | completo | 309,744 | 0.9729 |
| 2017-07-17 | 1 | completo | 14 | 0.1272 | 0.4065 | -0.043 | 0.779 | completo | 311,756 | 0.9688 |
| 2017-07-24 | 1 | completo | 14 | 0.1362 | 0.4292 | -0.042 | 0.776 | completo | 436,220 | 0.9389 |
| 2017-07-31 | 1 | completo | 14 | 0.1423 | 0.4360 | +0.002 | 0.780 | completo | 355,876 | 0.9661 |
| 2017-08-07 | 1 | parcial | 7 | 0.1485 | 0.4093 | +0.034 | 0.781 | completo | 429,266 | 0.9695 |
| 2017-08-14 | 1 | sin_datos | 0 | — | — | — | — | pendiente | — | — |

## Real pendiente (días que ya debieron llegar y faltan)

- Corte 2017-06-26 rev=1: sin real el 2017-07-04
- Corte 2017-07-03 rev=1: sin real el 2017-07-04

## Revisiones emitidas por correcciones

| Corte | Rev | Emitida en | Estado | WAPE |
|---|---|---|---|---|
| 2017-02-06 | 2 | 2017-02-13 | completo | 0.1169 |
| 2017-03-13 | 2 | 2017-03-20 | completo | 0.1315 |
| 2017-05-08 | 2 | 2017-05-15 | completo | 0.1308 |

## Desempeño por familia (ventana móvil)

| Familia | WAPE | Costo |
|---|---|---|
| BOOKS | 1.3165 | 42 |
| HOME APPLIANCES | 1.1794 | 164 |
| BABY CARE | 1.0001 | 107 |
| SCHOOL AND OFFICE SUPPLIES | 0.8698 | 28,772 |
| HARDWARE | 0.7090 | 315 |
| LINGERIE | 0.4996 | 962 |
| CELEBRATION | 0.3886 | 1,547 |
| MAGAZINES | 0.3831 | 675 |
| AUTOMOTIVE | 0.3808 | 738 |
| GROCERY II | 0.3784 | 9,219 |
| BEAUTY | 0.3614 | 602 |
| LADIESWEAR | 0.3513 | 1,048 |
| HOME AND KITCHEN II | 0.3357 | 3,481 |
| HOME AND KITCHEN I | 0.3334 | 3,564 |
| PET SUPPLIES | 0.3119 | 740 |
| PLAYERS AND ELECTRONICS | 0.2991 | 909 |
| LAWN AND GARDEN | 0.2841 | 1,138 |
| LIQUOR,WINE,BEER | 0.2664 | 9,596 |
| CLEANING | 0.2273 | 135,316 |
| SEAFOOD | 0.2107 | 4,095 |
| EGGS | 0.1776 | 35,164 |
| HOME CARE | 0.1763 | 15,889 |
| PREPARED FOODS | 0.1743 | 15,741 |
| FROZEN FOODS | 0.1710 | 24,196 |
| PERSONAL CARE | 0.1542 | 13,943 |
| BEVERAGES | 0.1483 | 363,030 |
| MEATS | 0.1277 | 46,380 |
| DELI | 0.1194 | 31,560 |
| POULTRY | 0.1183 | 44,091 |
| GROCERY I | 0.1137 | 366,931 |
| BREAD/BAKERY | 0.1088 | 64,453 |
| DAIRY | 0.1062 | 96,866 |
| PRODUCE | 0.0891 | 211,844 |

## Gráficos

![WAPE y costo por corte](seguimiento_wape_costo.png)

![Cobertura vs 80%](seguimiento_cobertura.png)

![WAPE por familia](seguimiento_familias.png)
