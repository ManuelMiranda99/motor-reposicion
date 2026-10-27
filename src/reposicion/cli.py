"""Línea de comandos del proyecto: `python -m reposicion.cli <subcomando>`."""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from reposicion import rutas
from reposicion.backtest import ejecutar_backtest, guardar_backtest
from reposicion.fuentes import cargar_fuentes
from reposicion.ingesta import ingestar
from reposicion.modelos import fabrica
from reposicion.parametros import cargar_configs
from reposicion.validacion import cargar_validacion


def _cmd_ingestar(args: argparse.Namespace) -> None:
    config = rutas.RAIZ_REPO / "config"
    resumen = ingestar(
        date.fromisoformat(args.hasta),
        Path(args.data) if args.data else rutas.dir_data(),
        Path(args.bandeja) if args.bandeja else rutas.dir_bandeja(),
        cargar_fuentes(config / "sources.yaml"),
        cargar_validacion(config / "validation.yaml"),
    )
    print(resumen.texto())


def _cmd_backtest(args: argparse.Namespace) -> None:
    cfgs = cargar_configs(rutas.RAIZ_REPO / "config")
    dir_data = Path(args.data) if args.data else rutas.dir_data()
    corte = date.fromisoformat(args.corte)
    pred = ejecutar_backtest(fabrica(args.modelo, cfgs), corte, dir_data, cfgs)
    metricas = guardar_backtest(pred, args.modelo, corte, dir_data, cfgs)
    print(f"{len(pred)} predicciones, {pred['origen'].nunique()} orígenes")
    print(metricas.round(4).to_string(index=False))


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="reposicion")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("ingestar", help="ingiere la bandeja hasta una fecha de entrega")
    p.add_argument("--hasta", required=True, help="última fecha de entrega a ingerir (YYYY-MM-DD)")
    p.add_argument("--bandeja", help="ruta de la bandeja (por defecto REPOSICION_BANDEJA)")
    p.add_argument("--data", help="raíz de datos (por defecto REPOSICION_DATA)")
    p.set_defaults(func=_cmd_ingestar)
    p = sub.add_parser("backtest", help="backtest rolling-origin de un modelo")
    p.add_argument("--modelo", required=True, help="nombre del modelo (por ejemplo, baseline)")
    p.add_argument("--corte", required=True, help="corte final del backtest (YYYY-MM-DD)")
    p.add_argument("--data", help="raíz de datos (por defecto REPOSICION_DATA)")
    p.set_defaults(func=_cmd_backtest)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
