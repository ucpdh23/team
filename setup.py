#!/usr/bin/env python3
"""Herramientas de configuración del proyecto team-pi.

Solo usa la librería estándar para poder ejecutarse igual en Windows y Linux con
`python setup.py <flag>` (o `python3 setup.py <flag>`), sin instalar nada más.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"
ENV_BACKUP = ROOT / ".env.bak"

TRUTHY_ANSWERS = {"s", "si", "sí", "y", "yes"}
ROLES = ("manager", "backend", "frontend", "devops", "cypress")


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


def read_env_file() -> dict[str, str]:
    """Lee .env (no .env.example) y devuelve un dict clave->valor, ya sin comillas
    envolventes si las hubiera (las que añade `quote_if_needed` en --init)."""
    if not ENV_FILE.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def run_docker(*args) -> int:
    cmd = ["docker", *args]
    print(f"[setup] ejecutando: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=ROOT)
    except FileNotFoundError:
        print(
            "No se encuentra el comando 'docker' en el PATH. Instala Docker Desktop "
            "(Windows/macOS) o Docker Engine + Compose plugin (Linux).",
            file=sys.stderr,
        )
        return 1
    return result.returncode


def run_compose(*compose_args) -> int:
    return run_docker("compose", *compose_args)


def cmd_start(args) -> int:
    return run_compose("up", "-d", "--build")


def cmd_stop(args) -> int:
    return run_compose("down")


def resolve_container(role: str) -> str | None:
    """Devuelve el ID del contenedor en marcha para ese rol (vía `docker compose ps -q
    <role>`), que resuelve el nombre real sin tener que reimplementar aquí la lógica de
    interpolación de CONTAINER_PREFIX de docker-compose.yml."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", role],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(
            "No se encuentra el comando 'docker' en el PATH. Instala Docker Desktop "
            "(Windows/macOS) o Docker Engine + Compose plugin (Linux).",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return None

    container_id = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not container_id:
        print(
            f"No hay ningún contenedor en marcha para el rol '{role}' "
            "(¿lanzaste 'python setup.py --start'?).",
            file=sys.stderr,
        )
        return None
    return container_id


def cmd_tmux(args) -> int:
    container = resolve_container(args.tmux)
    if container is None:
        return 1
    return run_docker("exec", "-it", container, "tmux", "attach", "-t", "pi")


def cmd_logs(args) -> int:
    container = resolve_container(args.logs)
    if container is None:
        return 1
    return run_docker("logs", "--tail", "100", "-f", container)


def cmd_bash(args) -> int:
    container = resolve_container(args.bash)
    if container is None:
        return 1
    return run_docker("exec", "-it", container, "bash")


def workspace_has_content(container: str) -> bool | None:
    """True/False si se pudo comprobar si /workspace tiene algo dentro; None si docker
    no está disponible o el exec falló (contenedor no arrancado del todo, etc.)."""
    try:
        result = subprocess.run(
            ["docker", "exec", container, "sh", "-c", "[ -z \"$(ls -A /workspace 2>/dev/null)\" ]"],
            capture_output=True,
        )
    except FileNotFoundError:
        print(
            "No se encuentra el comando 'docker' en el PATH. Instala Docker Desktop "
            "(Windows/macOS) o Docker Engine + Compose plugin (Linux).",
            file=sys.stderr,
        )
        return None
    if result.returncode not in (0, 1):
        print(result.stderr.decode(errors="replace").strip(), file=sys.stderr)
        return None
    return result.returncode == 1  # el "[ -z ... ]" devuelve 1 cuando SÍ hay contenido


def cmd_git_clone(args) -> int:
    if not ENV_FILE.exists():
        print(
            f"No existe {ENV_FILE.name}. Ejecuta antes 'python setup.py --init'.",
            file=sys.stderr,
        )
        return 1

    env_values = read_env_file()
    exit_code = 0
    any_role = False

    for role in ROLES:
        repo_url = env_values.get(f"{role.upper()}_REPO_URL", "").strip()
        if not repo_url:
            continue
        any_role = True

        container = resolve_container(role)
        if container is None:
            exit_code = 1
            continue

        has_content = workspace_has_content(container)
        if has_content is None:
            exit_code = 1
            continue
        if has_content:
            print(f"[setup] {role}: /workspace ya tiene contenido, se omite (¿ya clonado?).")
            continue

        print(f"[setup] {role}: git clone {repo_url} . (en /workspace)")
        rc = run_docker("exec", "-w", "/workspace", container, "git", "clone", repo_url, ".")
        if rc != 0:
            exit_code = rc

    if not any_role:
        print("Ningún rol tiene <ROL>_REPO_URL definido en .env; nada que clonar.")
    return exit_code


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
    parser.add_argument(
        "--start",
        action="store_true",
        help="Equivalente a 'docker compose up -d --build': construye (si hace falta) y "
        "levanta los 5 contenedores en segundo plano.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Equivalente a 'docker compose down': para y elimina los 5 contenedores sin "
        "tocar los volúmenes (logins/estado de cada agente se conservan).",
    )
    parser.add_argument(
        "--tmux",
        metavar="ROLE",
        choices=ROLES,
        help="Conecta a la sesión tmux persistente del contenedor de ese rol "
        "(docker exec -it ... tmux attach -t pi). Ctrl-b d para desconectar sin matarla.",
    )
    parser.add_argument(
        "--logs",
        metavar="ROLE",
        choices=ROLES,
        help="Sigue los logs del contenedor de ese rol (docker logs --tail 100 -f).",
    )
    parser.add_argument(
        "--bash",
        metavar="ROLE",
        choices=ROLES,
        help="Abre una shell bash interactiva dentro del contenedor de ese rol.",
    )
    parser.add_argument(
        "--git-clone",
        action="store_true",
        help="Para cada rol con <ROL>_REPO_URL definido en .env, hace 'git clone $REPO_URL .' "
        "dentro de /workspace en su contenedor (requiere que esté arrancado). Si /workspace "
        "ya tiene contenido para ese rol, lo omite en vez de fallar.",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init:
        return cmd_init(args)
    if args.start:
        return cmd_start(args)
    if args.stop:
        return cmd_stop(args)
    if args.tmux:
        return cmd_tmux(args)
    if args.logs:
        return cmd_logs(args)
    if args.bash:
        return cmd_bash(args)
    if args.git_clone:
        return cmd_git_clone(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
