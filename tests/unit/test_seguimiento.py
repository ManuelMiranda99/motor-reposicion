"""Seguimiento con publicaciones y ventas hechas a mano (valores conocidos)."""

import json
import math
from datetime import date, timedelta

import pandas as pd
import pytest

from reposicion import seguimiento
from reposicion.almacen import leer_parquet
from reposicion.io import escribir_parquet
from reposicion.parametros import Configs
from reposicion.pedido import calcular_pedido
from reposicion.seguimiento import evaluar_publicados, listar_publicaciones
from tests.sinteticos import hashes_dir
from tests.unit.test_backtest import NEGOCIO, cfg_modelo

FAMILIAS = ["A", "B"]
TIENDAS = [1, 2]


@pytest.fixture
def cfgs(cfg_fuentes, cfg_validacion) -> Configs:
    return Configs(cfg_modelo(), NEGOCIO, cfg_fuentes, cfg_validacion)


def publicar(dir_data, corte: date, revision: int = 1, emitido_en: date | None = None, q50=12.0):
    """Publicación sintética: q10=8, q50=`q50`, q67=13, q90=14 en todas las series y días."""
    fechas = pd.date_range(corte, periods=14)
    pron = pd.DataFrame(
        [(pd.Timestamp(corte), s, f, d, h + 1) for s in TIENDAS for f in FAMILIAS
         for h, d in enumerate(fechas)],
        columns=["corte", "store_nbr", "family", "fecha_objetivo", "h"],
    )  # fmt: skip
    for q, v in (("q0.10", 8.0), ("q0.50", q50), ("q0.67", 13.0), ("q0.90", 14.0)):
        pron[q] = v
    ped = calcular_pedido(pron, NEGOCIO)
    pron["modelo_id"] = ped["modelo_id"] = "baseline-x"
    destino = dir_data / "published" / f"corte={corte}" / f"rev={revision}"
    escribir_parquet(pron, destino / "pronostico.parquet")
    escribir_parquet(ped, destino / "pedido.parquet")
    manifiesto = {"corte": corte.isoformat(), "revision": revision, "modelo_id": "baseline-x",
                  "calidad": "ok"}  # fmt: skip
    if emitido_en:
        manifiesto["emitido_en"] = emitido_en.isoformat()
    (destino / "manifest.json").write_text(json.dumps(manifiesto))


def ventas(dir_data, desde: date, hasta: date, valor=10.0, sin=(), extra=()):
    """Almacén `limpio/ventas`: `valor` por día, disponible al día siguiente (versión 1).

    `extra`: filas (fecha_dato, fecha_disponible, version, valor) adicionales (correcciones).
    """
    filas = []
    for d in pd.date_range(desde, hasta):
        if d.date().isoformat() in sin:
            continue
        for s in TIENDAS:
            for f in FAMILIAS:
                filas.append((d, s, f, valor, d + pd.Timedelta(days=1), 1, "bandeja"))
    for fecha, disp, version, v in extra:
        for s in TIENDAS:
            for f in FAMILIAS:
                filas.append((pd.Timestamp(fecha), s, f, v, pd.Timestamp(disp), version, "bandeja"))
    df = pd.DataFrame(
        filas,
        columns=["fecha_dato", "store_nbr", "family", "sales", "fecha_disponible", "version",
                 "origen"],
    )  # fmt: skip
    escribir_parquet(df, dir_data / "limpio" / "ventas.parquet")


def fila(por_corte, corte: date, revision: int = 1):
    return por_corte[
        (por_corte["corte"] == pd.Timestamp(corte)) & (por_corte["revision"] == revision)
    ].iloc[0]


def test_metricas_con_valores_conocidos(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 6))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))
    r = fila(evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs), date(2017, 3, 6))
    assert r["estado"] == "completo" and r["dias_con_real"] == 14
    assert r["wape"] == pytest.approx(0.2)  # |12 - 10| / 10
    assert r["sesgo"] == pytest.approx(0.2)
    assert r["cobertura_p10_p90"] == 1.0  # 8 <= 10 <= 14
    assert r["costo_estado"] == "completo"
    # pedido = 7 × 13 = 91 por serie contra 70 reales: sobran 21 × c_merma 0.5 × 4 series
    assert r["costo_total"] == pytest.approx(21 * 0.5 * 4)
    assert r["fill_rate"] == pytest.approx(1.0)
    assert r["rmsle"] == pytest.approx(abs(math.log1p(12.0) - math.log1p(10.0)))


def test_estado_parcial_y_costo_pendiente(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 13))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))
    # el 2017-03-18 se conocen las ventas hasta el 03-17: 5 de 14 días y la cobertura (7) no está
    r = fila(evaluar_publicados(date(2017, 3, 18), tmp_path, cfgs), date(2017, 3, 13))
    assert r["estado"] == "parcial" and r["dias_con_real"] == 5 and r["dias_futuros"] == 9
    assert r["costo_estado"] == "pendiente" and pd.isna(r["costo_total"])
    assert r["wape"] == pytest.approx(0.2) and r["dias_sin_real"] == ""
    # el 03-20 ya se conocen los 7 días de la cobertura: hay costo aunque el corte sea parcial
    r = fila(evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs), date(2017, 3, 13))
    assert r["estado"] == "parcial" and r["dias_con_real"] == 7
    assert r["costo_estado"] == "completo"


def test_sin_datos_si_el_corte_es_el_de_la_evaluacion(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 13))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))
    r = fila(evaluar_publicados(date(2017, 3, 13), tmp_path, cfgs), date(2017, 3, 13))
    assert r["estado"] == "sin_datos" and r["dias_con_real"] == 0
    assert pd.isna(r["wape"]) and r["filas_con_real"] == 0


def test_dia_faltante_es_real_pendiente_y_no_falla(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 13))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31), sin=("2017-03-16",))
    por_corte = evaluar_publicados(date(2017, 3, 27), tmp_path, cfgs)
    r = fila(por_corte, date(2017, 3, 13))
    assert r["estado"] == "parcial" and r["dias_con_real"] == 13
    assert r["dias_sin_real"] == "2017-03-16" and r["dias_futuros"] == 0
    assert r["costo_estado"] == "pendiente"  # el 03-16 está en la cobertura
    md = (tmp_path / "monitoring" / "reportes" / "2017-03-27.md").read_text()
    assert "sin real el 2017-03-16" in md


def test_usa_la_version_corregida_de_las_ventas(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 6))
    # el 03-08 se corrige a 20 (entrega el 03-12): antes de eso no se ve
    ventas(
        tmp_path, date(2017, 2, 1), date(2017, 3, 31), extra=[("2017-03-08", "2017-03-12", 2, 20.0)]
    )
    antes = fila(evaluar_publicados(date(2017, 3, 11), tmp_path, cfgs), date(2017, 3, 6))
    despues = fila(evaluar_publicados(date(2017, 3, 14), tmp_path, cfgs), date(2017, 3, 6))
    assert antes["wape"] == pytest.approx(0.2)  # solo versión 1
    assert (
        despues["abs_err"] > antes["abs_err"] / antes["filas_con_real"] * despues["filas_con_real"]
    )
    por_h = leer_parquet(tmp_path / "monitoring" / "corte=2017-03-14" / "metricas_por_h.parquet")
    h3 = por_h[por_h["h"] == 3].iloc[0]  # el 03-08 es h=3 del corte 03-06
    assert h3["wape"] == pytest.approx(8 / 20)  # |12 - 20| / 20
    assert por_h[por_h["h"] == 2].iloc[0]["wape"] == pytest.approx(0.2)


def test_revisiones_se_evaluan_aparte_y_solo_si_ya_fueron_emitidas(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 6))
    publicar(tmp_path, date(2017, 3, 6), revision=2, emitido_en=date(2017, 3, 13), q50=10.0)
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))
    antes = evaluar_publicados(date(2017, 3, 10), tmp_path, cfgs)
    assert list(antes["revision"]) == [1]
    despues = evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    assert list(despues["revision"]) == [1, 2]
    assert fila(despues, date(2017, 3, 6), 2)["wape"] == pytest.approx(0.0)
    assert [p["revision"] for p in listar_publicaciones(tmp_path, date(2017, 3, 12))] == [1]


def test_desglose_por_familia(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 6))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))
    evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    fam = leer_parquet(
        tmp_path / "monitoring" / "corte=2017-03-20" / "metricas_por_familia.parquet"
    )
    assert sorted(fam["family"]) == FAMILIAS
    assert fam["wape"].tolist() == pytest.approx([0.2, 0.2])
    assert fam["costo_total"].tolist() == pytest.approx([21.0, 21.0])


def _cuatro_cortes(tmp_path):
    for k in range(4):
        publicar(tmp_path, date(2017, 2, 20) + timedelta(days=7 * k))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))


@pytest.mark.parametrize(
    ("wape_backtest", "alerta"), [(0.10, True), (0.19, False)]
)  # móvil = 0.2: +100% o +5.3% sobre la referencia, con umbral de 20%
def test_alerta_de_degradacion(tmp_path, cfgs, monkeypatch, caplog, wape_backtest, alerta):
    _cuatro_cortes(tmp_path)
    monkeypatch.setattr(seguimiento, "champion_vigente", lambda corte, d: "lgbm-1")
    monkeypatch.setattr(
        seguimiento,
        "leer_registro",
        lambda d: pd.DataFrame({"modelo_id": ["lgbm-1"], "wape": [wape_backtest]}),
    )
    with caplog.at_level("WARNING"):
        evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    resumen = json.loads(
        (tmp_path / "monitoring" / "corte=2017-03-20" / "resumen.json").read_text()
    )
    a = resumen["alerta"]
    assert a["alerta"] is alerta and a["wape_movil"] == pytest.approx(0.2)
    assert a["cortes_en_ventana"] == ["2017-02-20", "2017-02-27", "2017-03-06", "2017-03-13"]
    assert ("ADVERTENCIA" in caplog.text) is alerta
    assert (
        "ADVERTENCIA" in (tmp_path / "monitoring" / "reportes" / "2017-03-20.md").read_text()
    ) is alerta


def test_sin_ventana_suficiente_no_hay_alerta(tmp_path, cfgs):
    publicar(tmp_path, date(2017, 3, 6))
    ventas(tmp_path, date(2017, 2, 1), date(2017, 3, 31))
    evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    a = seguimiento.leer_resumen(tmp_path, date(2017, 3, 20))["alerta"]
    assert a["estado"] == "insuficiente" and a["alerta"] is False


def test_idempotente_y_reporte_con_graficos(tmp_path, cfgs):
    _cuatro_cortes(tmp_path)
    evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    primero = hashes_dir(tmp_path / "monitoring")
    evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    assert hashes_dir(tmp_path / "monitoring") == primero
    reportes = tmp_path / "monitoring" / "reportes"
    assert (reportes / "2017-03-20.md").exists()
    assert {p.name for p in reportes.glob("*.png")} == {
        "2017-03-20_wape_costo.png", "2017-03-20_cobertura.png", "2017-03-20_familias.png",
    }  # fmt: skip
    assert not list((tmp_path / "monitoring").rglob("*.tmp"))
    assert not {"timestamp"} & set(
        json.loads((tmp_path / "monitoring" / "corte=2017-03-20" / "resumen.json").read_text())
    )


def test_publicar_reporte_reciente_copia_y_reescribe_enlaces(tmp_path, cfgs):
    _cuatro_cortes(tmp_path)
    evaluar_publicados(date(2017, 3, 13), tmp_path, cfgs)
    evaluar_publicados(date(2017, 3, 20), tmp_path, cfgs)
    salida = seguimiento.publicar_reporte_reciente(tmp_path, tmp_path / "reports")
    texto = salida.read_text()
    assert "2017-03-20" in texto.splitlines()[0]
    assert "](seguimiento_wape_costo.png)" in texto
    assert (tmp_path / "reports" / "seguimiento_wape_costo.png").exists()
    assert seguimiento.publicar_reporte_reciente(tmp_path / "vacio", tmp_path / "x") is None
