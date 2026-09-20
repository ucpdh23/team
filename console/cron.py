"""Programación y ejecución de los scripts del equipo dentro del contenedor de la consola.

El reparto de responsabilidades es el que define esta pieza:

- **Qué se ejecuta** es del equipo de desarrollo: los scripts viven fuera de este repositorio,
  en el directorio montado en `/data/scripts` (por defecto `tmp/scripts/`, no versionado), y
  se montan en **solo lectura**. La consola los ejecuta; no los escribe, no los edita y no
  acepta comandos libres desde la web. Programar es elegir uno del catálogo, no inventarse una
  línea de shell — que es lo que permite tener una consola sin autenticación sin que eso
  signifique ejecución arbitraria para quien alcance el puerto.
- **Cuándo** es de aquí: un planificador en el propio proceso del servidor, con una sola
  fuente de verdad (la base de datos) en vez de un crontab paralelo.
- **Con qué hablar con el equipo** lo pone `console_sdk` (ver console/sdk/): `notify()` deja un
  aviso en la cola para un agente, y `state` recuerda cosas entre ejecuciones.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .cronspec import CronError, CronSpec

# Lo que se guarda en la base de datos de cada ejecución; la salida completa va a un fichero.
MAX_OUTPUT_CHARS = 32_000
DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 3600
RUNS_KEPT_PER_JOB = 50


def now_ms() -> int:
    return int(time.time() * 1000)


def _to_ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


class CronManager:
    def __init__(self, db, events, inbox, config):
        self.db = db
        self.events = events
        self.inbox = inbox
        self.config = config
        self.scripts_dir = Path(config.scripts_dir)
        self.logs_dir = Path(config.data_dir) / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ------------------------------------------------------------------ catálogo

    def scripts(self) -> list[dict]:
        """Lo que hay publicado en el directorio montado, con su descripción.

        Un `.py` describe lo que hace en su docstring y un ejecutable en su primer comentario;
        se lee sin importar ni ejecutar nada (`ast.parse`), porque listar el catálogo no puede
        tener efectos.
        """
        if not self.scripts_dir.is_dir():
            return []
        out = []
        for path in sorted(self.scripts_dir.iterdir()):
            if not path.is_file() or path.name.startswith(".") or path.name == "requirements.txt":
                continue
            runnable = path.suffix == ".py" or os.access(path, os.X_OK)
            if not runnable:
                continue
            out.append({
                "name": path.name,
                "description": self._describe(path),
                "kind": "python" if path.suffix == ".py" else "ejecutable",
                "size": path.stat().st_size,
                "modified_ts": int(path.stat().st_mtime * 1000),
            })
        return out

    @staticmethod
    def _describe(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if path.suffix == ".py":
            try:
                doc = ast.get_docstring(ast.parse(text))
            except SyntaxError:
                doc = None
            if doc:
                return doc.strip().splitlines()[0][:200]
        for line in text.splitlines()[:5]:
            line = line.strip()
            if line.startswith("#") and not line.startswith("#!"):
                return line.lstrip("#").strip()[:200]
        return ""

    def resolve_script(self, name: str) -> Path:
        """Ruta real de un script del catálogo, o error.

        Se valida en CADA ejecución y no solo al crear el job: un job que apunta a un script
        que ya no existe tiene que fallar diciéndolo, nunca ejecutar otra cosa. El `resolve()`
        contra el directorio es lo que impide que un `../` salga del catálogo.
        """
        candidate = (self.scripts_dir / name).resolve()
        root = self.scripts_dir.resolve()
        if not str(candidate).startswith(str(root) + os.sep):
            raise ValueError(f"'{name}' está fuera del catálogo de scripts")
        if not candidate.is_file():
            raise ValueError(f"el script '{name}' no existe en {self.scripts_dir}")
        if candidate.suffix != ".py" and not os.access(candidate, os.X_OK):
            raise ValueError(f"'{name}' no es un .py ni un ejecutable")
        return candidate

    # ---------------------------------------------------------------------- jobs

    def jobs(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM cron_jobs ORDER BY name")
        last = {
            r["job_id"]: r
            for r in self.db.query(
                "SELECT job_id, status, started_ts, finished_ts, exit_code FROM cron_runs "
                "WHERE id IN (SELECT id FROM cron_runs GROUP BY job_id HAVING MAX(started_ts))"
            )
        }
        out = []
        for row in rows:
            job = self._job_dict(row)
            previous = last.get(row["id"])
            job["last_run"] = dict(previous) if previous else None
            out.append(job)
        return out

    @staticmethod
    def _job_dict(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "schedule": row["schedule"],
            "script": row["script"],
            "args": json.loads(row["args"] or "[]"),
            "enabled": bool(row["enabled"]),
            "timeout_s": row["timeout_s"],
            "created_ts": row["created_ts"],
            "last_run_ts": row["last_run_ts"],
            "next_run_ts": row["next_run_ts"],
        }

    def create_job(self, data: dict) -> dict:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("el job necesita un nombre")
        if self.db.query("SELECT 1 FROM cron_jobs WHERE name = ?", (name,)):
            raise ValueError(f"ya existe un job llamado '{name}'")
        schedule, script, args, timeout = self._validate(data)
        job_id = str(uuid.uuid4())
        created = now_ms()
        self.db.execute(
            "INSERT INTO cron_jobs (id, name, schedule, script, args, enabled, timeout_s, "
            "created_ts, next_run_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, name, schedule, script, json.dumps(args),
             1 if data.get("enabled", True) else 0, timeout, created,
             self._next_run(schedule)),
        )
        return self.job(job_id)

    def update_job(self, job_id: str, data: dict) -> dict:
        row = self._row(job_id)
        schedule, script, args, timeout = self._validate({**self._job_dict(row), **data})
        enabled = 1 if data.get("enabled", bool(row["enabled"])) else 0
        self.db.execute(
            "UPDATE cron_jobs SET schedule = ?, script = ?, args = ?, enabled = ?, "
            "timeout_s = ?, next_run_ts = ? WHERE id = ?",
            (schedule, script, json.dumps(args), enabled, timeout,
             self._next_run(schedule) if enabled else None, job_id),
        )
        return self.job(job_id)

    def delete_job(self, job_id: str) -> bool:
        self._row(job_id)
        self.db.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        return True

    def job(self, job_id: str) -> dict:
        return self._job_dict(self._row(job_id))

    def _row(self, job_id: str):
        rows = self.db.query("SELECT * FROM cron_jobs WHERE id = ?", (job_id,))
        if not rows:
            raise KeyError(f"no existe el job {job_id}")
        return rows[0]

    def _validate(self, data: dict):
        try:
            schedule = CronSpec(str(data.get("schedule") or "")).expression
        except CronError as exc:
            raise ValueError(str(exc)) from exc
        script = str(data.get("script") or "").strip()
        self.resolve_script(script)  # existe y es ejecutable AHORA
        args = data.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError("los argumentos deben ser una lista de cadenas")
        timeout = int(data.get("timeout_s") or DEFAULT_TIMEOUT_S)
        if not (1 <= timeout <= MAX_TIMEOUT_S):
            raise ValueError(f"el timeout debe estar entre 1 y {MAX_TIMEOUT_S} segundos")
        return schedule, script, args, timeout

    @staticmethod
    def _next_run(schedule: str) -> int | None:
        nxt = CronSpec(schedule).next_after(datetime.now())
        return _to_ms(nxt) if nxt else None

    # --------------------------------------------------------------- ejecuciones

    def runs(self, job_id: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT id, job_id, job_name, started_ts, finished_ts, exit_code, status, " \
              "substr(output, 1, 400) AS preview FROM cron_runs"
        params: tuple = ()
        if job_id:
            sql += " WHERE job_id = ?"
            params = (job_id,)
        sql += " ORDER BY started_ts DESC LIMIT ?"
        return [dict(r) for r in self.db.query(sql, (*params, max(1, min(limit, 200))))]

    def run_detail(self, run_id: str) -> dict:
        rows = self.db.query("SELECT * FROM cron_runs WHERE id = ?", (run_id,))
        if not rows:
            raise KeyError(f"no existe la ejecución {run_id}")
        run = dict(rows[0])
        log = self.logs_dir / f"{run_id}.log"
        run["log_available"] = log.is_file()
        if log.is_file():
            run["output"] = log.read_text(encoding="utf-8", errors="replace")
        return run

    def run_now(self, job_id: str) -> dict:
        job = self.job(job_id)
        threading.Thread(target=self._execute, args=(job, "manual"), daemon=True).start()
        return {"started": True, "job": job["name"]}

    def _execute(self, job: dict, trigger: str) -> None:
        # Sin solapes: si la ejecución anterior del mismo job sigue viva, se deja constancia y
        # se sale, en vez de acumular procesos sobre el mismo script.
        with self._lock:
            if job["id"] in self._running:
                self._record_skipped(job)
                return
            self._running.add(job["id"])

        run_id = str(uuid.uuid4())
        started = now_ms()
        self.db.execute(
            "INSERT INTO cron_runs (id, job_id, job_name, started_ts, status) "
            "VALUES (?, ?, ?, ?, 'running')",
            (run_id, job["id"], job["name"], started),
        )
        self.db.execute("UPDATE cron_jobs SET last_run_ts = ? WHERE id = ?", (started, job["id"]))

        status, exit_code, output = "error", None, ""
        try:
            script = self.resolve_script(job["script"])
            command = self._command(script, job["args"])
            result = subprocess.run(
                command,
                cwd=str(self.scripts_dir),
                env=self._env(job, run_id),
                capture_output=True,
                text=True,
                timeout=job["timeout_s"],
            )
            exit_code = result.returncode
            output = (result.stdout or "") + (result.stderr or "")
            status = "ok" if exit_code == 0 else "error"
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            output += f"\n[console] cortado por timeout ({job['timeout_s']}s)"
        except (ValueError, OSError) as exc:
            output = f"[console] no se pudo ejecutar: {exc}"

        finished = now_ms()
        (self.logs_dir / f"{run_id}.log").write_text(output, encoding="utf-8", errors="replace")
        self.db.execute(
            "UPDATE cron_runs SET finished_ts = ?, exit_code = ?, status = ?, output = ? "
            "WHERE id = ?",
            (finished, exit_code, status, output[:MAX_OUTPUT_CHARS], run_id),
        )
        self._trim_runs(job["id"])
        # La ejecución aparece en la pestaña Actividad junto a los mensajes del equipo: es una
        # cosa más que ha pasado en el sistema, y se lee mejor en la misma línea de tiempo.
        self.events.ingest([{
            "ts": finished, "type": "cron.run", "agent": "console", "peer": None,
            "payload": {"job": job["name"], "status": status, "exit_code": exit_code,
                        "duration_ms": finished - started, "trigger": trigger},
        }])

        with self._lock:
            self._running.discard(job["id"])

    def _record_skipped(self, job: dict) -> None:
        self.db.execute(
            "INSERT INTO cron_runs (id, job_id, job_name, started_ts, finished_ts, status, "
            "output) VALUES (?, ?, ?, ?, ?, 'skipped', ?)",
            (str(uuid.uuid4()), job["id"], job["name"], now_ms(), now_ms(),
             "[console] saltado: la ejecución anterior seguía en curso"),
        )

    def _trim_runs(self, job_id: str) -> None:
        self.db.execute(
            "DELETE FROM cron_runs WHERE job_id = ? AND id NOT IN "
            "(SELECT id FROM cron_runs WHERE job_id = ? ORDER BY started_ts DESC LIMIT ?)",
            (job_id, job_id, RUNS_KEPT_PER_JOB),
        )

    def _command(self, script: Path, args: list[str]) -> list[str]:
        if script.suffix == ".py":
            return [self._python(), str(script), *args]
        return [str(script), *args]

    def _env(self, job: dict, run_id: str) -> dict:
        env = dict(os.environ)
        env.update({
            # Dentro del propio contenedor: el script habla con la consola por loopback.
            "CONSOLE_URL": f"http://127.0.0.1:{self.config.port}",
            "CONSOLE_JOB_NAME": job["name"],
            "CONSOLE_RUN_ID": run_id,
            "PYTHONPATH": os.pathsep.join(
                p for p in ["/opt/console-sdk", env.get("PYTHONPATH", "")] if p
            ),
            "PYTHONUNBUFFERED": "1",
        })
        # Mismo criterio que el entrypoint de los agentes: az lee el PAT de esta variable y así
        # `az boards` funciona sin login interactivo.
        if env.get("ADO_PAT"):
            env["AZURE_DEVOPS_EXT_PAT"] = env["ADO_PAT"]
        return env

    # ------------------------------------------------- dependencias de los scripts

    def _python(self) -> str:
        """Intérprete para los scripts: el del venv si hay `requirements.txt`, si no el del sistema.

        La regla es stdlib por defecto —`urllib` y `json` bastan para hablar con la consola y
        con la API de ADO—, y si algún script necesita más, basta con dejar un
        `requirements.txt` en el directorio de scripts. El venv se crea en el volumen de datos
        (el de scripts está montado en solo lectura) y solo se rehace cuando el fichero cambia.
        """
        requirements = self.scripts_dir / "requirements.txt"
        if not requirements.is_file():
            return sys.executable
        venv = Path(self.config.data_dir) / "venv"
        python = venv / "bin" / "python"
        digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
        stamp = venv / ".requirements.sha256"
        if python.is_file() and stamp.is_file() and stamp.read_text().strip() == digest:
            return str(python)
        try:
            if not python.is_file():
                subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True,
                               capture_output=True, timeout=120)
            subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(requirements)],
                           check=True, capture_output=True, timeout=600)
            stamp.write_text(digest, encoding="utf-8")
            print(f"[console] venv de scripts actualizado desde {requirements}")
            return str(python)
        except (subprocess.SubprocessError, OSError) as exc:
            # Que falle instalar no puede dejar sin ejecutar a los scripts que no necesitan nada.
            print(f"[console] aviso: no se pudo preparar el venv de scripts ({exc}); "
                  "se usará el intérprete del sistema")
            return sys.executable

    # -------------------------------------------------------- estado de los scripts

    def state(self, job: str) -> dict:
        return {
            r["key"]: json.loads(r["value"])
            for r in self.db.query("SELECT key, value FROM cron_state WHERE job = ?", (job,))
        }

    def set_state(self, job: str, key: str, value) -> None:
        if value is None:
            self.db.execute("DELETE FROM cron_state WHERE job = ? AND key = ?", (job, key))
            return
        self.db.execute(
            "INSERT INTO cron_state (job, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(job, key) DO UPDATE SET value = excluded.value",
            (job, key, json.dumps(value)),
        )

    # ------------------------------------------------------------ planificador

    def start(self) -> None:
        self._reschedule_all()
        threading.Thread(target=self._loop, daemon=True, name="cron").start()

    def stop(self) -> None:
        self._stop.set()

    def _reschedule_all(self) -> None:
        for row in self.db.query("SELECT id, schedule FROM cron_jobs WHERE enabled = 1"):
            try:
                self.db.execute("UPDATE cron_jobs SET next_run_ts = ? WHERE id = ?",
                                (self._next_run(row["schedule"]), row["id"]))
            except CronError:
                continue

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Duerme hasta el comienzo del siguiente minuto en vez de 60 s a secas: así el job
            # de las 20:00 se dispara a las 20:00 y no a las 20:00:37 del primer arranque.
            time.sleep(max(1.0, 60 - (time.time() % 60)))
            if self._stop.is_set():
                break
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 — el planificador no puede morirse
                print(f"[console] aviso: fallo en el ciclo del cron: {exc}")

    def _tick(self) -> None:
        now = now_ms()
        for row in self.db.query(
            "SELECT * FROM cron_jobs WHERE enabled = 1 AND next_run_ts IS NOT NULL "
            "AND next_run_ts <= ?", (now,)
        ):
            job = self._job_dict(row)
            self.db.execute("UPDATE cron_jobs SET next_run_ts = ? WHERE id = ?",
                            (self._next_run(job["schedule"]), job["id"]))
            threading.Thread(target=self._execute, args=(job, "cron"), daemon=True).start()

    def stats(self) -> dict:
        jobs = self.db.query("SELECT COUNT(*) AS n, SUM(enabled) AS activos FROM cron_jobs")[0]
        failing = self.db.query(
            "SELECT COUNT(*) AS n FROM cron_runs WHERE status IN ('error', 'timeout') "
            "AND started_ts > ?", (now_ms() - 86_400_000,)
        )[0]["n"]
        return {
            "jobs": jobs["n"],
            "enabled": jobs["activos"] or 0,
            "scripts": len(self.scripts()),
            "failed_last_day": failing,
            # Las horas se evalúan aquí dentro: si el contenedor va en UTC, "0 20 * * *" son
            # las 22:00 en Madrid, y eso hay que poder verlo sin investigarlo.
            "timezone": os.environ.get("TZ") or time.tzname[0],
            "now": datetime.now().strftime("%H:%M"),
        }
