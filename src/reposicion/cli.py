"""Línea de comandos del proyecto: `python -m reposicion.cli <subcomando>`."""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from reposicion import rutas
from reposicion.fuentes import cargar_fuentes
from reposicion.ingesta import ingestar
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


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="reposicion")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("ingestar", help="ingiere la bandeja hasta una fecha de entrega")
    p.add_argument("--hasta", required=True, help="última fecha de entrega a ingerir (YYYY-MM-DD)")
    p.add_argument("--bandeja", help="ruta de la bandeja (por defecto REPOSICION_BANDEJA)")
    p.add_argument("--data", help="raíz de datos (por defecto REPOSICION_DATA)")
    p.set_defaults(func=_cmd_ingestar)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
