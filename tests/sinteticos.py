"""Datos sintéticos tipo Kaggle y configuración del simulador para las pruebas."""

import hashlib
import shutil
from pathlib import Path

import pandas as pd

from reposicion.simulador import ConfigSimulador

TIENDAS = [1, 2, 3]
FAMILIAS = ["A", "B"]


def escribir_kaggle(d: Path, inicio: str = "2016-12-01", fin: str = "2017-02-28") -> Path:
    """Mini dataset con la misma forma que el de Kaggle (por defecto 2016-12-01 a 2017-02-28)."""
    d.mkdir(parents=True)
    fechas = pd.date_range(inicio, fin)
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


def crear_config(**cambios) -> ConfigSimulador:
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


def hashes_dir(d: Path, patron: str = "*") -> dict[str, str]:
    """sha256 de todos los archivos bajo `d` (para comprobar que algo no cambió)."""
    return {
        str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob(patron))
        if p.is_file()
    }


def preparar_data(destino: Path, historico: Path) -> Path:
    """Crea un `dir_data` nuevo cuyo histórico es una copia del sintético."""
    shutil.copytree(historico, destino / "historico")
    return destino
