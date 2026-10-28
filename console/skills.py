"""Skills y AGENTS.md de cada agente, navegables y editables por API y por web.

Es la configuración de equipo que vive en el repositorio (`agents/`), la misma que el
docker-compose monta en los agentes. Cada ámbito tiene una raíz virtual:

    <rol>/     AGENTS.md   → agents/<rol>/AGENTS.md       (backend y frontend: el de su stack,
                             AGENTS.<stack>.md, igual que hace el compose con BACKEND_STACK y
                             FRONTEND_STACK)
               skills/     → agents/<rol>/pi/skills/       (los skills propios de ese rol)
    shared/    skills/     → agents/_shared/pi/skills/     (los genéricos, de todo el equipo)

De `agents/` solo se llega a esas rutas: las extensiones, los scripts de arranque y todo lo
demás quedan fuera aunque el directorio entero esté montado.

Aquí sustituir es lo normal (`overwrite` por defecto): el fin es revisar y mejorar estos
ficheros, y están en git, así que `git diff`/`git checkout` lo deshacen. Y se escribe sobre el
mismo fichero, sin renombrar: los AGENTS.md están montados como fichero suelto en los
agentes, y un rename los dejaría viendo el inodo viejo.
"""

from __future__ import annotations

import os
from pathlib import Path

from .costs import ROLES
from .workitems import Tree, WorkitemError, _entry

SHARED = "shared"
AGENTS_FILE = "AGENTS.md"
SKILLS_DIR = "skills"
#: Los skills y AGENTS.md son texto: un tope bajo basta y frena una subida equivocada.
MAX_BYTES = 2 << 20


class Skills(Tree):
    overwrite_default = True
    in_place = True

    def __init__(self, agents_dir: Path, backend_stack: str = "java",
                 frontend_stack: str = "angular"):
        super().__init__(MAX_BYTES)
        self.agents_dir = agents_dir
        self.stacks = {"backend": backend_stack or "java", "frontend": frontend_stack or "angular"}

    # --------------------------------------------------------------------- mapa

    def _mapping(self, scope: str) -> dict[str, Path]:
        """Nombre virtual → ruta real, para un ámbito."""
        if scope == SHARED:
            return {SKILLS_DIR: self.agents_dir / "_shared" / "pi" / "skills"}
        if scope not in ROLES:
            raise WorkitemError(404, f"ámbito desconocido: {scope}")
        stack = self.stacks.get(scope)
        agents_md = f"AGENTS.{stack}.md" if stack else AGENTS_FILE
        return {AGENTS_FILE: self.agents_dir / scope / agents_md,
                SKILLS_DIR: self.agents_dir / scope / "pi" / "skills"}

    def _resolve(self, scope: str, parts: list[str], must_exist: bool = True) -> Path:
        mapping = self._mapping(scope)
        if not parts or parts[0] not in mapping:
            raise WorkitemError(404, "no existe: /" + "/".join(parts)
                                + f" (en este ámbito solo hay: {', '.join(mapping)})")
        real = mapping[parts[0]]
        if parts[0] == AGENTS_FILE:
            if len(parts) > 1:
                raise WorkitemError(400, f"{AGENTS_FILE} es un fichero")
            if must_exist and not real.is_file():
                raise WorkitemError(404, f"no existe: {real.name}")
            return real
        if not real.is_dir():
            if must_exist:
                raise WorkitemError(404, "no existe: /" + "/".join(parts))
            if len(parts) == 1:
                raise WorkitemError(409, f"{SKILLS_DIR} es un directorio")
            if not real.parent.is_dir():
                raise WorkitemError(404, "el directorio de agentes no está montado")
            return real.joinpath(*parts[1:])   # escribir aquí crea la carpeta
        return self._under(real.resolve(), parts[1:], must_exist, "/".join(parts))

    def _virtual(self, scope: str, parts: list[str], recursive: bool):
        if parts:
            return None
        entries: list = []
        truncated = False
        for name, real in self._mapping(scope).items():
            if real.is_file():
                entries.append({**_entry(real, name), "name": name})
            elif real.is_dir():
                if recursive:
                    truncated = self._walk(real, name, True, entries) or truncated
                else:
                    entries.append({**_entry(real, name), "name": name})
        return entries, truncated

    # -------------------------------------------------------------------- índice

    def index(self) -> dict:
        out = []
        for scope in (SHARED, *ROLES):
            mapping = self._mapping(scope)
            skills_dir = mapping[SKILLS_DIR]
            skills = 0
            if skills_dir.is_dir():
                try:
                    skills = sum(1 for e in os.scandir(skills_dir)
                                 if e.is_dir() and not e.name.startswith("."))
                except OSError:
                    pass
            agents_md = mapping.get(AGENTS_FILE)
            out.append({"scope": scope, "exists": skills_dir.is_dir() or bool(
                            agents_md and agents_md.is_file()),
                        "items": skills,
                        "agents_md": agents_md.name if agents_md else None,
                        "agents_md_exists": bool(agents_md and agents_md.is_file())})
        return {"scopes": out}
