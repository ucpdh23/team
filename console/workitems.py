"""Árboles de ficheros que la consola expone por API y por web: base común (`Tree`) y la
implementación de `/workspace/workitems` de cada agente (`Workitems`). Los skills y los
AGENTS.md viven en skills.py y reutilizan esta misma base.

La consola monta los cinco volúmenes de workspace en `<workspaces_dir>/<rol>` (ver
docker-compose.yml) y de ellos solo se ve la subcarpeta `workitems`: es la raíz de todo lo que
se expone, de modo que el resto del workspace (repositorios, credenciales de git…) queda fuera
de alcance aunque alguien pida `..` o un enlace simbólico apunte fuera.

Sin dependencias y sin estado: cada llamada mira el disco.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from .costs import ROLES

WORKITEMS_DIR = "workitems"
#: Tope de ficheros en un listado recursivo (`?recursive=1`).
MAX_RECURSIVE = 5000

# Tipos que un navegador ejecutaría o renderizaría con scripts si se sirvieran tal cual:
# se entregan como texto plano para que ver un documento nunca ejecute nada.
_AS_TEXT = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml",
            "application/xml", "application/javascript", "text/javascript"}
_TEXT_EXTRA = {".md", ".markdown", ".yml", ".yaml", ".toml", ".ini", ".log", ".csv", ".sh",
               ".java", ".kt", ".py", ".ts", ".tsx", ".js", ".json", ".sql", ".feature",
               ".properties", ".gradle", ".env", ".txt", ".xml", ".html", ".css", ".svg"}


class WorkitemError(Exception):
    """Error con código HTTP para devolver tal cual al cliente."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _entry(path: Path, rel: str) -> dict:
    st = path.stat()
    is_dir = path.is_dir()
    return {"name": path.name, "path": rel, "type": "dir" if is_dir else "file",
            "size": None if is_dir else st.st_size, "modified": int(st.st_mtime * 1000)}


def _join(base: str, name: str) -> str:
    return f"{base}/{name}" if base else name


class Tree:
    """Árbol de ficheros navegable y subible, con un «ámbito» (agente, compartido…) como raíz.

    Las subclases dicen cómo se resuelve una ruta a una ruta real (`_resolve`) y, si el ámbito
    tiene una raíz virtual que junta varios sitios (`_virtual`), cuál es. Todo lo demás —
    listar, leer, escribir con las mismas garantías— vive aquí, una sola vez.
    """

    #: ¿`save` sustituye por defecto un fichero que ya existe?
    overwrite_default = False
    #: Escribir sobre el mismo fichero en vez de renombrar uno temporal. Hace falta cuando el
    #: fichero está montado como fichero suelto en otro contenedor: un bind mount de un fichero
    #: se queda con el inodo viejo si alguien lo sustituye por un rename.
    in_place = False

    def __init__(self, max_upload_bytes: int):
        self.max_upload_bytes = max_upload_bytes

    # ------------------------------------------------------------- a implementar

    def _resolve(self, scope: str, parts: list[str], must_exist: bool = True) -> Path:
        raise NotImplementedError

    def _virtual(self, scope: str, parts: list[str], recursive: bool):
        """(entradas, truncado) de la raíz virtual del ámbito, o None si `parts` no es esa raíz."""
        return None

    # ------------------------------------------------------------------- lectura

    @staticmethod
    def _check_parts(parts: list[str]) -> None:
        if any(p in (".", "..") or "/" in p or "\\" in p or "\x00" in p for p in parts):
            raise WorkitemError(400, "ruta no válida")

    @staticmethod
    def _under(real_root: Path, parts: list[str], must_exist: bool, shown: str) -> Path:
        target = real_root.joinpath(*parts).resolve()
        if target != real_root and real_root not in target.parents:
            raise WorkitemError(403, "ruta fuera de la raíz permitida")
        if must_exist and not target.exists():
            raise WorkitemError(404, f"no existe: /{shown}")
        return target

    @staticmethod
    def _walk(directory: Path, prefix: str, recursive: bool, out: list) -> bool:
        """Añade las entradas de `directory` a `out`. Devuelve True si se truncó."""
        if recursive:
            for dirpath, dirnames, filenames in os.walk(directory):
                dirnames.sort()
                for fname in sorted(filenames):
                    if len(out) >= MAX_RECURSIVE:
                        return True
                    full = Path(dirpath) / fname
                    try:
                        rel = str(full.relative_to(directory)).replace(os.sep, "/")
                        out.append(_entry(full, _join(prefix, rel)))
                    except OSError:
                        continue
            return False
        for child in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                out.append(_entry(child, _join(prefix, child.name)))
            except OSError:
                continue  # enlace roto o fichero que desaparece mientras se lista
        return False

    def read(self, scope: str, parts: list[str], recursive: bool = False):
        """("json", listado) para un directorio o ("file", ruta, tipo, tamaño) para un fichero."""
        self._check_parts(parts)
        base = "/".join(parts)
        virtual = self._virtual(scope, parts, recursive)
        if virtual is not None:
            entries, truncated = virtual
        else:
            target = self._resolve(scope, parts)
            if not target.is_dir():
                return ("file", target, content_type(target), target.stat().st_size)
            entries = []
            truncated = self._walk(target, base, recursive, entries)
        return ("json", {"scope": scope, "agent": scope, "path": base, "entries": entries,
                         "truncated": truncated})

    # ----------------------------------------------------------------- escritura

    def save(self, scope: str, parts: list[str], stream, length: int,
             overwrite: bool | None = None) -> dict:
        if not parts:
            raise WorkitemError(400, "falta el nombre del fichero en la ruta")
        if overwrite is None:
            overwrite = self.overwrite_default
        if length > self.max_upload_bytes:
            raise WorkitemError(413, f"máximo {self.max_upload_bytes // (1 << 20)} MiB")
        self._check_parts(parts)
        target = self._resolve(scope, parts, must_exist=False)
        if target.is_dir():
            raise WorkitemError(409, "ya existe un directorio con ese nombre")
        exists = target.exists()
        if exists and not overwrite:
            raise WorkitemError(409, "ya existe; usa ?overwrite=1 para sustituirlo")
        target.parent.mkdir(parents=True, exist_ok=True)
        if exists and self.in_place:
            # Se lee todo antes de tocar nada: un cuerpo cortado no deja el fichero a medias.
            data = self._read_exact(stream, length)
            with open(target, "r+b") as out:
                out.truncate(0)
                out.write(data)
            return {"saved": "/".join(parts), "size": length, "replaced": True}
        # Se escribe a un temporal y se renombra: un agente leyendo no ve un fichero a medias.
        tmp = target.with_name(f".{target.name}.upload-{os.getpid()}")
        try:
            with open(tmp, "wb") as out:
                out.write(self._read_exact(stream, length))
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        return {"saved": "/".join(parts), "size": length, "replaced": exists}

    @staticmethod
    def _read_exact(stream, length: int) -> bytes:
        chunks, remaining = [], length
        while remaining > 0:
            chunk = stream.read(min(1 << 16, remaining))
            if not chunk:
                raise WorkitemError(400, "cuerpo incompleto")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class Workitems(Tree):
    """`<workspaces>/<rol>/workitems`: lo que el equipo ha ido produciendo."""

    def __init__(self, workspaces_dir: Path, max_upload_bytes: int):
        super().__init__(max_upload_bytes)
        self.workspaces_dir = workspaces_dir

    def _root(self, agent: str) -> Path:
        if agent not in ROLES:
            raise WorkitemError(404, f"agente desconocido: {agent}")
        return self.workspaces_dir / agent / WORKITEMS_DIR

    def _resolve(self, agent: str, parts: list[str], must_exist: bool = True) -> Path:
        """Ruta real dentro de workitems/ del agente, o error. Nunca sale de esa raíz."""
        root = self._root(agent)
        if not root.is_dir():
            if must_exist:
                raise WorkitemError(404, f"{agent} no tiene carpeta {WORKITEMS_DIR}")
            if not root.parent.is_dir():
                raise WorkitemError(404, f"el workspace de {agent} no está montado")
            return root.joinpath(*parts)   # subir a un agente sin workitems/ la crea
        return self._under(root.resolve(), parts, must_exist, "/".join(parts))

    def index(self) -> dict:
        out = []
        for role in ROLES:
            root = self._root(role)
            exists = root.is_dir()
            items = 0
            if exists:
                try:
                    items = sum(1 for e in os.scandir(root) if e.is_dir())
                except OSError:
                    pass
            out.append({"agent": role, "exists": exists, "items": items})
        return {"agents": out}


def content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0] or ""
    if guessed in _AS_TEXT or path.suffix.lower() in _TEXT_EXTRA and not guessed.startswith(
            ("image/", "application/pdf")):
        return "text/plain; charset=utf-8"
    if guessed.startswith("text/"):
        return guessed + "; charset=utf-8"
    return guessed or "application/octet-stream"
