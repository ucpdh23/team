#!/usr/bin/env python3
"""Herramientas de configuración del proyecto team-pi.

Solo usa la librería estándar para poder ejecutarse igual en Windows y Linux con
`python setup.py <flag>` (o `python3 setup.py <flag>`), sin instalar nada más.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"
ENV_BACKUP = ROOT / ".env.bak"

TRUTHY_ANSWERS = {"s", "si", "sí", "y", "yes"}


def parse_env_example(path: Path):
    """Lee .env.example y devuelve (lineas, entradas).

    `lineas` conserva el fichero tal cual (comentarios y espaciado incluidos) para poder
    reconstruirlo después sin perder nada. `entradas` es la lista de asignaciones
    VAR=valor que hay que preguntar, como (indice_de_linea, clave, valor_por_defecto).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        entries.append((i, key.strip(), value.strip()))
    return lines, entries


def quote_if_needed(value: str) -> str:
    needs_quotes = value and any(c in value for c in " \t") and not (
        value.startswith('"') and value.endswith('"')
    )
    return f'"{value}"' if needs_quotes else value


def cmd_init(args) -> int:
    if not ENV_EXAMPLE.exists():
        print(f"No se encuentra {ENV_EXAMPLE.name} en {ROOT}", file=sys.stderr)
        return 1

    lines, entries = parse_env_example(ENV_EXAMPLE)
    if not entries:
        print(f"{ENV_EXAMPLE.name} no define ninguna variable.", file=sys.stderr)
        return 1

    if ENV_FILE.exists() and not args.yes:
        answer = input(
            f"{ENV_FILE.name} ya existe y se sobreescribirá (se guarda copia en "
            f"{ENV_BACKUP.name}). ¿Continuar? [s/N]: "
        ).strip().lower()
        if answer not in TRUTHY_ANSWERS:
            print("Cancelado.")
            return 1

    print(f"Configurando {ENV_FILE.name} a partir de {ENV_EXAMPLE.name}.")
    print("Pulsa Enter para aceptar el valor por defecto que se muestra entre corchetes.\n")

    answers = {}
    for _, key, default in entries:
        prompt = f"{key} [{default}]: " if default else f"{key} []: "
        try:
            raw = input(prompt)
        except EOFError:
            raw = ""
        answers[key] = raw.strip() if raw.strip() != "" else default

    output_lines = list(lines)
    for line_index, key, _ in entries:
        output_lines[line_index] = f"{key}={quote_if_needed(answers[key])}"

    if ENV_FILE.exists():
        shutil.copy2(ENV_FILE, ENV_BACKUP)
        print(f"\nCopia de seguridad del .env anterior guardada en {ENV_BACKUP.name}")

    ENV_FILE.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    print(f"{ENV_FILE.name} generado correctamente.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setup.py",
        description="Herramientas de configuración del proyecto team-pi.",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Genera .env a partir de .env.example, preguntando valor por valor "
        "(Enter para aceptar el valor por defecto).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="No pedir confirmación antes de sobreescribir un .env existente.",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init:
        return cmd_init(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
