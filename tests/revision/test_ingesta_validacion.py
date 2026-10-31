"""Revisión independiente — ingesta, validación y almacén limpio.

Cada prueba afirma el comportamiento CORRECTO esperado; si falla, demuestra el hallazgo descrito en
`tests/revision/INFORME.md`.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import reposicion.ingesta as ingesta_mod
from reposicion.almacen import leer_ledger
from reposicion.asof import asof, ultima_fecha_disponible
from reposicion.ingesta import ingestar
from reposicion.publicacion import DatosInsuficientes, calidad_datos
from tests.revision.comun import (
    configs,
    copiar_bandeja,
    escribir_ventas,
    fila_ledger,
    nuevo_dir_data,
)


# ------------------------------------------------------------- H-ING-1 atomicidad de la ingesta
def test_fallo_al_reconstruir_limpio_no_deja_el_almacen_obsoleto(
    bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path, monkeypatch
):
    """`ingestar` escribe el ledger y DESPUÉS reconstruye `limpio/`. Si la reconstrucción falla
    (disco lleno, OOM, kill del worker), el reintento no ve archivos nuevos (ya están en el ledger)
    y, como `limpio/` existe, no lo reconstruye: el almacén queda obsoleto para siempre."""
    historico, bandeja = bandeja_sintetica
    datos = nuevo_dir_data(historico, tmp_path / "data")
    ingestar(date(2017, 1, 5), datos, bandeja, cfg_fuentes, cfg_validacion)

    real = ingesta_mod.reconstruir_limpio

    def falla(*_a, **_k):
        raise OSError("simulación: el worker muere al reconstruir limpio/")

    monkeypatch.setattr(ingesta_mod, "reconstruir_limpio", falla)
    with pytest.raises(OSError):
        ingestar(date(2017, 1, 10), datos, bandeja, cfg_fuentes, cfg_validacion)
    monkeypatch.setattr(ingesta_mod, "reconstruir_limpio", real)

    ingestar(date(2017, 1, 10), datos, bandeja, cfg_fuentes, cfg_validacion)  # reintento
    # Las ventas del 01-09 se entregaron el 01-10 y están en el ledger como válidas...
    ledger = leer_ledger(datos)
    assert fila_ledger(ledger, "2017-01-10/ventas_2017-01-09.csv")["estado"] == "valido"
    # ...pero el as-of no las ve: limpio/ quedó con lo ingerido hasta el 01-05.
    assert ultima_fecha_disponible("ventas", date(2017, 1, 10), datos) == date(2017, 1, 9)


# ------------------------------------------------------------- H-VAL-1 archivos "del futuro"
@pytest.fixture
def bandeja_con_futuro(bandeja_sintetica, tmp_path):
    """Bandeja con un archivo de ventas cuyo `fecha_dato` es posterior a su entrega."""
    historico, bandeja = bandeja_sintetica
    b = copiar_bandeja(bandeja, tmp_path / "bandeja")
    escribir_ventas(b, date(2017, 1, 10), date(2017, 3, 15), tiendas=[1, 2])
    return historico, b


def test_ventas_con_fecha_dato_posterior_a_la_entrega_van_a_cuarentena(
    bandeja_con_futuro, cfg_fuentes, cfg_validacion, tmp_path
):
    """Ventas del 2017-03-15 entregadas el 2017-01-10 son imposibles (lag de ventas = +1 día), pero
    la validación solo compara el contenido con el nombre del archivo y las acepta."""
    historico, bandeja = bandeja_con_futuro
    datos = nuevo_dir_data(historico, tmp_path / "data")
    ingestar(date(2017, 1, 10), datos, bandeja, cfg_fuentes, cfg_validacion)
    fila = fila_ledger(leer_ledger(datos), "2017-01-10/ventas_2017-03-15.csv")
    assert fila["estado"] == "cuarentena", "un dato del futuro entró al almacén como válido"


def test_dato_del_futuro_no_desactiva_el_modo_degradado(
    bandeja_con_futuro, cfg_fuentes, cfg_validacion, tmp_path
):
    """Consecuencia: `calidad_datos` usa la MÁXIMA `fecha_dato` visible. Con el archivo del futuro,
    un corte sin ventas recientes (las reales se detuvieron el 01-09) no lanza
    `DatosInsuficientes` y se publica un pronóstico con datos viejos."""
    historico, bandeja = bandeja_con_futuro
    datos = nuevo_dir_data(historico, tmp_path / "data")
    ingestar(date(2017, 1, 10), datos, bandeja, cfg_fuentes, cfg_validacion)  # nada después
    reales = asof("ventas", date(2017, 1, 20), datos)
    assert reales.loc[reales["fecha_dato"] < "2017-03-01", "fecha_dato"].max() == pd.Timestamp(
        "2017-01-09"
    )
    with pytest.raises(DatosInsuficientes):
        calidad_datos(date(2017, 1, 20), datos, configs(cfg_fuentes, cfg_validacion))


# --------------------------------------------- H-VAL-2 maestro de tiendas parcial (no snapshot)
def test_maestro_de_tiendas_parcial_no_contamina_las_ventas_posteriores(
    bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path
):
    """Un `tiendas_*.csv` que solo trae una tienda (el origen manda un alta incremental en vez del
    snapshot completo) se acepta como válido y REEMPLAZA el maestro: desde ese día todas las ventas
    válidas de las tiendas 1 y 2 van a cuarentena ("store_nbr desconocido") y el corte siguiente
    termina en `DatosInsuficientes`. La validación no exige que el snapshot conserve las tiendas
    con ventas recientes ni avisa del cambio."""
    historico, bandeja = bandeja_sintetica
    b = copiar_bandeja(bandeja, tmp_path / "bandeja")
    parcial = b / "2017-01-25" / "tiendas_2017-01-25.csv"
    pd.DataFrame(
        [{"store_nbr": 3, "city": "Quito", "state": "Pichincha", "type": "C", "cluster": 3}]
    ).to_csv(parcial, index=False)
    datos = nuevo_dir_data(historico, tmp_path / "data")
    ingestar(date(2017, 2, 5), datos, b, cfg_fuentes, cfg_validacion)
    ledger = leer_ledger(datos)
    ventas_despues = ledger[
        (ledger["fuente"] == "ventas") & (ledger["fecha_entrega"] > pd.Timestamp("2017-01-25"))
    ]
    assert (ventas_despues["estado"] == "valido").all(), (
        f"{(ventas_despues['estado'] == 'cuarentena').sum()} archivos de ventas válidos quedaron "
        "en cuarentena por un maestro parcial aceptado"
    )


# ------------------------------------------- H-ING-2 archivo que aparece en una carpeta antigua
def test_version_vigente_es_la_ultima_entregada_aunque_se_ingiera_despues(
    bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path
):
    """La versión se asigna por orden de INGESTA, pero `asof` elige la versión máxima. Si un
    archivo aparece tarde en una carpeta de entrega antigua (la bandeja no es append-only), recibe
    una versión mayor que una corrección entregada después y `asof` la prefiere: en el 01-10 se
    vería la versión entregada el 01-07 en lugar de la corrección del 01-09. Además cambia
    retroactivamente lo que "se sabía" en el 01-07 (huella de cortes ya publicados)."""
    historico, bandeja = bandeja_sintetica
    b = copiar_bandeja(bandeja, tmp_path / "bandeja")
    datos = nuevo_dir_data(historico, tmp_path / "data")
    ingestar(date(2017, 1, 10), datos, b, cfg_fuentes, cfg_validacion)
    antes = asof("ventas", date(2017, 1, 10), datos)
    antes = antes[antes["fecha_dato"] == "2017-01-05"].sort_values(["store_nbr", "family"])

    escribir_ventas(b, date(2017, 1, 7), date(2017, 1, 5), tiendas=[1, 2])  # aparece "tarde"
    ingestar(date(2017, 1, 10), datos, b, cfg_fuentes, cfg_validacion)
    despues = asof("ventas", date(2017, 1, 10), datos)
    despues = despues[despues["fecha_dato"] == "2017-01-05"].sort_values(["store_nbr", "family"])
    # La corrección entregada el 01-09 debe seguir siendo la vigente en el 01-10.
    assert despues["sales"].tolist() == antes["sales"].tolist()
