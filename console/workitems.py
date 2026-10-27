"""Navegación (y subida) de `/workspace/workitems` de cada agente.

La consola monta los cinco volúmenes de workspace en `<workspaces_dir>/<rol>` (ver
docker-compose.yml) y aquí solo se ve la subcarpeta `workitems`: es la raíz de todo lo que
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


class Workitems:
    def __init__(self, workspaces_dir: Path, max_upload_bytes: int):
        self.workspaces_dir = workspaces_dir
        self.max_upload_bytes = max_upload_bytes

    # ------------------------------------------------------------------ resolución

    def _root(self, agent: str) -> Path:
        if agent not in ROLES:
            raise WorkitemError(404, f"agente desconocido: {agent}")
        return self.workspaces_dir / agent / WORKITEMS_DIR

    def _resolve(self, agent: str, parts: list[str], must_exist: bool = True) -> Path:
        """Ruta real dentro de workitems/ del agente, o error. Nunca sale de esa raíz."""
        root = self._root(agent)
        if any(p in (".", "..") or "/" in p or "\\" in p or "\x00" in p for p in parts):
            raise WorkitemError(400, "ruta no válida")
        if not root.is_dir():
            raise WorkitemError(404, f"{agent} no tiene carpeta {WORKITEMS_DIR}")
        real_root = root.resolve()
        target = (real_root.joinpath(*parts)).resolve()
        if target != real_root and real_root not in target.parents:
            raise WorkitemError(403, "ruta fuera de workitems")
        if must_exist and not target.exists():
            raise WorkitemError(404, "no existe: /" + "/".join(parts))
        return target

    # ---------------------------------------------------------------------- lectura

    def agents(self) -> dict:
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

    @staticmethod
    def _entry(path: Path, rel: str) -> dict:
        st = path.stat()
        is_dir = path.is_dir()
        return {"name": path.name, "path": rel, "type": "dir" if is_dir else "file",
                "size": None if is_dir else st.st_size, "modified": int(st.st_mtime * 1000)}

    def list(self, agent: str, parts: list[str], recursive: bool = False) -> dict:
        target = self._resolve(agent, parts)
        if not target.is_dir():
            raise WorkitemError(400, "no es un directorio")
        base = "/".join(parts)
        rel_of = lambda name: (f"{base}/{name}" if base else name)  # noqa: E731
        entries, truncated = [], False
        if recursive:
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames.sort()
                for fname in sorted(filenames):
                    full = Path(dirpath) / fname
                    if len(entries) >= MAX_RECURSIVE:
                        truncated = True
                        break
                    try:
                        entries.append(self._entry(
                            full, rel_of(str(full.relative_to(target)).replace(os.sep, "/"))))
                    except OSError:
                        continue
                if truncated:
                    break
        else:
            for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    entries.append(self._entry(child, rel_of(child.name)))
                except OSError:
                    continue  # enlace roto o fichero que desaparece mientras se lista
        return {"agent": agent, "path": base, "entries": entries, "truncated": truncated}

    def open_file(self, agent: str, parts: list[str]) -> tuple[Path, str, int]:
        """(ruta, content-type seguro, tamaño) de un fichero a servir."""
        target = self._resolve(agent, parts)
        if not target.is_file():
            raise WorkitemError(400, "no es un fichero")
        return target, content_type(target), target.stat().st_size

    # --------------------------------------------------------------------- escritura

    def save(self, agent: str, parts: list[str], stream, length: int,
             overwrite: bool) -> dict:
        if not parts:
            raise WorkitemError(400, "falta el nombre del fichero en la ruta")
        if length > self.max_upload_bytes:
            raise WorkitemError(413, f"máximo {self.max_upload_bytes // (1 << 20)} MiB")
        target = self._resolve(agent, parts, must_exist=False)
        if target.is_dir():
            raise WorkitemError(409, "ya existe un directorio con ese nombre")
        if target.exists() and not overwrite:
            raise WorkitemError(409, "ya existe; usa ?overwrite=1 para sustituirlo")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Se escribe a un temporal y se renombra: un agente leyendo no ve un fichero a medias.
        tmp = target.with_name(f".{target.name}.upload-{os.getpid()}")
        remaining = length
        try:
            with open(tmp, "wb") as out:
                while remaining > 0:
                    chunk = stream.read(min(1 << 16, remaining))
                    if not chunk:
                        raise WorkitemError(400, "cuerpo incompleto")
                    out.write(chunk)
                    remaining -= len(chunk)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        return {"saved": "/".join(parts), "size": length}


def content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0] or ""
    if guessed in _AS_TEXT or path.suffix.lower() in _TEXT_EXTRA and not guessed.startswith(
            ("image/", "application/pdf")):
        return "text/plain; charset=utf-8"
    if guessed.startswith("text/"):
        return guessed + "; charset=utf-8"
    return guessed or "application/octet-stream"
