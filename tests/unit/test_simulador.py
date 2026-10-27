import hashlib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from reposicion.simulador import (
    ARCHIVO_ESCENARIOS,
    TIENDA_DESCONOCIDA,
    ConfigSimulador,
    cargar_config,
    generar,
)

RAIZ = Path(__file__).resolve().parents[2]
TIENDAS = [1, 2, 3]
FAMILIAS = ["A", "B"]


def _escribir_kaggle(d: Path) -> Path:
    """Mini dataset con la misma forma que el de Kaggle (2016-12-01 a 2017-02-28)."""
    d.mkdir(parents=True)
    fechas = pd.date_range("2016-12-01", "2017-02-28")
    filas = [
        {
            "id": i,
            "date": f.date().isoformat(),
            "store_nbr": s,
            "family": fam,
            "sales": round(10 + 5 * s + 3 * j + 1.25 * (f.day_of_week), 3),
            "onpromotion": (f.day + s + j) % 3,
        }
        for i, (f, s, (j, fam)) in enumerate(
            (f, s, jf) for f in fechas for s in TIENDAS for jf in enumerate(FAMILIAS)
        )
    ]
    pd.DataFrame(filas).to_csv(d / "train.csv", index=False)
    pd.DataFrame(
        [
            {"date": f.date().isoformat(), "store_nbr": s, "transactions": 1000 + 10 * s + f.day}
            for f in fechas
            for s in TIENDAS
        ]
    ).to_csv(d / "transactions.csv", index=False)
    habiles = [f for f in fechas if f.day_of_week < 5]
    oil = pd.DataFrame(
        {"date": [f.date().isoformat() for f in habiles], "dcoilwtico": 50.0 + 0.1 * len(habiles)}
    )
    oil.loc[3, "dcoilwtico"] = None
    oil.to_csv(d / "oil.csv", index=False)
    pd.DataFrame(
        {
            "date": ["2016-12-25", "2017-02-27", "2017-05-01", "2017-08-10"],
            "type": ["Holiday", "Holiday", "Holiday", "Holiday"],
            "locale": ["National"] * 4,
            "locale_name": ["Ecuador"] * 4,
            "description": ["Navidad", "Carnaval", "Dia del Trabajo", "Primer Grito"],
            "transferred": [False] * 4,
        }
    ).to_csv(d / "holidays_events.csv", index=False)
    pd.DataFrame(
        {
            "store_nbr": TIENDAS,
            "city": ["Quito"] * 3,
            "state": ["Pichincha"] * 3,
            "type": ["A", "B", "C"],
            "cluster": [1, 2, 3],
        }
    ).to_csv(d / "stores.csv", index=False)
    return d


def _config(**cambios) -> ConfigSimulador:
    base = {
        "semilla": 7,
        "fecha_carga_historica": "2017-01-01",
        "tiendas_nuevas": {3: "2017-01-20"},
        "escenarios": {
            "faltantes": [{"fuente": "transacciones", "fecha_dato": "2017-01-10"}],
            "tardios": [
                {"fuente": "ventas", "fecha_dato": "2017-01-12", "fecha_entrega": "2017-01-18"}
            ],
            "correcciones": [
                {
                    "fuente": "ventas",
                    "fecha_dato": "2017-01-05",
                    "fecha_entrega": "2017-01-09",
                    "fraccion_filas": 0.5,
                    "factor": 1.3,
                }
            ],
            "duplicados": [
                {"fuente": "ventas", "fecha_dato": "2017-01-06", "fecha_entrega": "2017-01-08"}
            ],
            "invalidos": [
                {
                    "fuente": "ventas",
                    "fecha_dato": "2017-01-14",
                    "defecto": "ventas_negativas",
                    "correccion_entrega": "2017-01-16",
                },
                {
                    "fuente": "transacciones",
                    "fecha_dato": "2017-01-20",
                    "defecto": "columna_faltante",
                },
                {"fuente": "ventas", "fecha_dato": "2017-01-22", "defecto": "filas_duplicadas"},
                {
                    "fuente": "promociones",
                    "fecha_dato": "2017-02-20",
                    "defecto": "tienda_desconocida",
                },
                {"fuente": "ventas", "fecha_dato": "2017-01-24", "defecto": "tipo_invalido"},
            ],
        },
    }
    base.update(cambios)
    return ConfigSimulador.model_validate(base)


def _hashes(d: Path) -> dict[str, str]:
    return {
        str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob("*.csv"))
    }


@pytest.fixture(scope="module")
def kaggle(tmp_path_factory) -> Path:
    return _escribir_kaggle(tmp_path_factory.mktemp("kaggle") / "kaggle")


@pytest.fixture(scope="module")
def salida(kaggle, tmp_path_factory) -> tuple[Path, Path]:
    raiz = tmp_path_factory.mktemp("salida")
    generar(kaggle, _config(), raiz / "historico", raiz / "bandeja")
    return raiz / "historico", raiz / "bandeja"


def _leer(bandeja: Path, entrega: str, archivo: str) -> pd.DataFrame:
    return pd.read_csv(bandeja / entrega / archivo, dtype={"date": str})


# --------------------------------------------------------------------------- carga histórica


def test_historico_contiene_solo_lo_entregado_hasta_la_carga(salida):
    historico, _ = salida
    ventas = pd.read_csv(historico / "ventas.csv", dtype={"date": str})
    promos = pd.read_csv(historico / "promociones.csv", dtype={"date": str})
    assert ventas["date"].max() == "2016-12-31"  # lag de 1 día
    assert promos["date"].max() == "2017-01-11"  # anticipación de 10 días
    assert "onpromotion" not in ventas.columns
    assert "sales" not in promos.columns


def test_historico_excluye_tienda_nueva(salida):
    historico, _ = salida
    assert 3 not in set(pd.read_csv(historico / "tiendas.csv")["store_nbr"])
    assert 3 not in set(pd.read_csv(historico / "ventas.csv")["store_nbr"])


def test_feriados_llegan_un_trimestre_antes(salida):
    historico, bandeja = salida
    feriados = set(pd.read_csv(historico / "feriados.csv")["date"])
    assert "2017-05-01" in feriados  # Q2-2017 se entrega el 2017-01-01 (dentro de la carga)
    assert "2017-08-10" not in feriados
    assert (bandeja / "2017-04-01" / "feriados_2017-07-01.csv").exists()


# --------------------------------------------------------------------------- bandeja normal


def test_layout_por_fecha_de_entrega(salida):
    _, bandeja = salida
    assert (bandeja / "2017-01-06" / "ventas_2017-01-05.csv").exists()
    assert (bandeja / "2017-01-10" / "promociones_2017-01-20.csv").exists()
    assert (bandeja / "2017-01-03" / "petroleo_2017-01-02.csv").exists()


def test_transacciones_con_lag_en_rango(salida):
    _, bandeja = salida
    archivos = list(bandeja.glob("*/transacciones_*.csv"))
    assert archivos
    for p in archivos:
        lag = (date.fromisoformat(p.parent.name) - date.fromisoformat(p.stem.split("_")[1])).days
        assert 1 <= lag <= 3


def test_alta_de_tienda_nueva(salida):
    _, bandeja = salida
    tiendas = pd.read_csv(bandeja / "2017-01-20" / "tiendas_2017-01-20.csv")
    assert 3 in set(tiendas["store_nbr"])
    assert 3 not in set(_leer(bandeja, "2017-01-19", "ventas_2017-01-18.csv")["store_nbr"])
    assert 3 in set(_leer(bandeja, "2017-01-21", "ventas_2017-01-20.csv")["store_nbr"])


# --------------------------------------------------------------------------- escenarios


def test_faltante_nunca_se_entrega(salida):
    _, bandeja = salida
    assert not list(bandeja.glob("*/transacciones_2017-01-10.csv"))


def test_tardio_solo_en_su_fecha_tardia(salida):
    _, bandeja = salida
    encontrados = [p.parent.name for p in bandeja.glob("*/ventas_2017-01-12.csv")]
    assert encontrados == ["2017-01-18"]


def test_correccion_cambia_una_fraccion_de_filas(salida):
    _, bandeja = salida
    original = _leer(bandeja, "2017-01-06", "ventas_2017-01-05.csv")
    corregido = _leer(bandeja, "2017-01-09", "ventas_2017-01-05.csv")
    assert original[["date", "store_nbr", "family"]].equals(
        corregido[["date", "store_nbr", "family"]]
    )
    cambia = original["sales"] != corregido["sales"]
    assert cambia.sum() == round(0.5 * len(original))
    assert (corregido.loc[cambia, "sales"] / original.loc[cambia, "sales"]).round(2).eq(1.3).all()


def test_duplicado_es_identico(salida):
    _, bandeja = salida
    a = (bandeja / "2017-01-07" / "ventas_2017-01-06.csv").read_bytes()
    b = (bandeja / "2017-01-08" / "ventas_2017-01-06.csv").read_bytes()
    assert a == b


def test_invalido_con_reentrega_valida(salida):
    _, bandeja = salida
    invalido = _leer(bandeja, "2017-01-15", "ventas_2017-01-14.csv")
    valido = _leer(bandeja, "2017-01-16", "ventas_2017-01-14.csv")
    assert (invalido["sales"] < 0).any()
    assert (valido["sales"] >= 0).all()


def test_defectos_de_archivos_invalidos(salida):
    _, bandeja = salida
    tx = list(bandeja.glob("*/transacciones_2017-01-20.csv"))
    assert len(tx) == 1 and "transactions" not in pd.read_csv(tx[0]).columns
    dup = _leer(bandeja, "2017-01-23", "ventas_2017-01-22.csv")
    assert dup.duplicated().any()
    promo = _leer(bandeja, "2017-02-10", "promociones_2017-02-20.csv")
    assert TIENDA_DESCONOCIDA in set(promo["store_nbr"])
    tipo = pd.read_csv(
        bandeja / "2017-01-25" / "ventas_2017-01-24.csv", dtype=str, keep_default_na=False
    )
    assert (tipo["sales"] == "N/A").any()


def test_manifiesto_de_escenarios(salida):
    _, bandeja = salida
    m = pd.read_csv(bandeja / ARCHIVO_ESCENARIOS)
    assert m["escenario"].value_counts().to_dict() == {
        "invalido": 5,
        "faltante": 1,
        "tardio": 1,
        "correccion": 1,
        "duplicado_identico": 1,
        "reentrega_valida": 1,
    }


# --------------------------------------------------------------------------- determinismo


def test_determinista(kaggle, salida, tmp_path):
    historico, bandeja = salida
    generar(kaggle, _config(), tmp_path / "h", tmp_path / "b")
    assert _hashes(tmp_path / "h") == _hashes(historico)
    assert _hashes(tmp_path / "b") == _hashes(bandeja)


def test_ampliar_hasta_no_altera_lo_ya_generado(kaggle, salida, tmp_path):
    _, bandeja = salida
    generar(kaggle, _config(hasta="2017-01-15"), tmp_path / "h", tmp_path / "b")
    parcial = _hashes(tmp_path / "b")
    assert max(Path(k).parent.name for k in parcial if "/" in k) == "2017-01-15"
    completo = _hashes(bandeja)
    assert all(completo[k] == v for k, v in parcial.items() if k != ARCHIVO_ESCENARIOS)

    generar(kaggle, _config(), tmp_path / "h", tmp_path / "b")
    assert _hashes(tmp_path / "b") == completo


# --------------------------------------------------------------------------- configuración


def test_escenario_dentro_de_la_carga_historica_falla(kaggle, tmp_path):
    cfg = _config(escenarios={"faltantes": [{"fuente": "ventas", "fecha_dato": "2016-12-20"}]})
    with pytest.raises(ValueError, match="carga histórica"):
        generar(kaggle, cfg, tmp_path / "h", tmp_path / "b")


def test_escenario_sobre_fecha_inexistente_falla(kaggle, tmp_path):
    cfg = _config(escenarios={"faltantes": [{"fuente": "ventas", "fecha_dato": "2018-01-01"}]})
    with pytest.raises(ValueError, match="inexistente"):
        generar(kaggle, cfg, tmp_path / "h", tmp_path / "b")


def test_tienda_desconocida_no_aplica_a_petroleo():
    with pytest.raises(ValidationError):
        _config(
            escenarios={
                "invalidos": [
                    {
                        "fuente": "petroleo",
                        "fecha_dato": "2017-01-10",
                        "defecto": "tienda_desconocida",
                    }
                ]
            }
        )


def test_config_del_repo_es_valida():
    cfg = cargar_config(RAIZ / "config" / "simulador.yaml")
    assert cfg.fecha_carga_historica == date(2017, 1, 1)
    assert 52 in cfg.tiendas_nuevas
