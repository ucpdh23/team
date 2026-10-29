"""Árbol de documentos compartidos del repositorio (`./docs`).

La consola expone únicamente este directorio como `/api/docs`; las rutas se resuelven bajo su
raíz y no pueden escapar mediante `..` ni enlaces simbólicos.
"""

from pathlib import Path

from .workitems import Tree, WorkitemError


class Docs(Tree):
    """`docs/` del repositorio, compartido por los agentes y editable desde la consola."""

    def __init__(self, docs_dir: Path, max_upload_bytes: int):
        super().__init__(max_upload_bytes)
        self.docs_dir = docs_dir

    def _resolve(self, scope: str, parts: list[str], must_exist: bool = True) -> Path:
        if scope != "docs":
            raise WorkitemError(404, f"ámbito desconocido: {scope}")
        root = self.docs_dir.resolve()
        if not root.is_dir():
            raise WorkitemError(404, "la carpeta docs no está montada")
        return self._under(root, parts, must_exist, "/".join(parts))
