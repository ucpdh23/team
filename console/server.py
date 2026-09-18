"""Servidor del dashboard de consumo (solo librería estándar).

Lee los `.jsonl` de `pi-cost-counter` bajo una carpeta `cost-tracking/` con la forma
`cost-tracking/<rol>/<AAAA>/<MM>/<DD>.jsonl`, donde cada línea es un registro como:

    {"ts": 1789717967858, "provider": "...", "model": "...",
     "tokens": {"input": 10026, "output": 308, "cacheRead": 0, "cacheWrite": 0},
     "cost":   {"input": 0.025, "output": 0.004, "cacheRead": 0, "cacheWrite": 0,
                "total": 0.0296}}

Expone una API JSON y sirve los estáticos de `console/static/`. El grueso del dibujado
(gráficas) ocurre en el navegador con Chart.js; aquí solo agregamos.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Mismo orden y nombres que el resto del proyecto (ver setup.py: ROLES).
ROLES = ("manager", "backend", "frontend", "devops", "cypress")

STATIC_DIR = Path(__file__).resolve().parent / "static"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


# --------------------------------------------------------------------------- datos

def _iter_records(cost_dir: Path):
    """Recorre todos los .jsonl bajo cost_dir/<rol>/** y produce (rol, registro dict).

    Ignora líneas vacías o no parseables en vez de abortar: los ficheros se escriben en vivo
    desde los contenedores y una última línea a medio escribir no debe tirar el dashboard.
    """
    for role in ROLES:
        role_dir = cost_dir / role
        if not role_dir.is_dir():
            continue
        for jsonl in sorted(role_dir.rglob("*.jsonl")):
            try:
                text = jsonl.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("ts"), (int, float)):
                    yield role, rec


def _load(cost_dir: Path):
    """Aplana todos los registros a tuplas ligeras y ordenables por tiempo.

    Cada tupla es (rol, ts_ms, coste_total, tokens_totales, modelo). El modelo lleva el
    proveedor por delante (p.ej. 'github-copilot/gpt-5.4') porque dos proveedores pueden servir
    modelos con el mismo nombre y no queremos que se sumen como si fueran uno.
    """
    out = []
    for role, rec in _iter_records(cost_dir):
        cost = rec.get("cost") or {}
        tokens = rec.get("tokens") or {}
        total_cost = cost.get("total")
        if not isinstance(total_cost, (int, float)):
            total_cost = sum(
                v for k, v in cost.items()
                if k != "total" and isinstance(v, (int, float))
            )
        total_tokens = sum(v for v in tokens.values() if isinstance(v, (int, float)))
        provider = str(rec.get("provider") or "").strip()
        model = str(rec.get("model") or "desconocido").strip() or "desconocido"
        label = f"{provider}/{model}" if provider else model
        out.append((role, float(rec["ts"]), float(total_cost), float(total_tokens), label))
    return out


def _bucket_key(dt: datetime, unit: str) -> str:
    if unit == "hour":
        return dt.strftime("%Y-%m-%d %H")
    return dt.strftime("%Y-%m-%d")


def _labels_and_keys(unit: str, starts: list[datetime]):
    """Etiquetas legibles y claves internas para una lista de inicios de bucket.

    Con buckets por hora que abarcan más de un día natural, la etiqueta incluye el día para no
    ser ambigua ('18 09h' vs '09:00'); en un solo día basta la hora.
    """
    if unit == "hour":
        multiday = len({d.date() for d in starts}) > 1
        label = (lambda d: d.strftime("%d %Hh")) if multiday else (lambda d: d.strftime("%H:%M"))
    else:
        label = lambda d: d.strftime("%d %b")
    keys = [_bucket_key(d, unit) for d in starts]
    labels = [label(d) for d in starts]
    return keys, labels


def _preset_starts(anchor: datetime, range_: str):
    """Buckets para los presets, terminando en el ancla (el registro más reciente).

    El ancla es el registro MÁS RECIENTE de los datos, no la hora del reloj: así un export
    histórico siempre pinta algo útil aunque se abra semanas después. 'day' = 24 buckets por
    hora; 'week' = 7 buckets por día.
    """
    if range_ == "day":
        unit, count, step = "hour", 24, timedelta(hours=1)
        end = anchor.replace(minute=0, second=0, microsecond=0)
    else:
        unit, count, step = "day", 7, timedelta(days=1)
        end = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    return unit, [end - step * (count - 1 - i) for i in range(count)]


def _date_range_starts(start: date, end: date):
    """Buckets para un rango de fechas [start, end] elegido en el calendario.

    Granularidad automática: hasta 2 días naturales se muestra por hora (detalle intradía);
    a partir de ahí, por día, para que un rango largo no genere cientos de barras.
    """
    if start > end:
        start, end = end, start
    span_days = (end - start).days + 1
    if span_days <= 2:
        unit, step = "hour", timedelta(hours=1)
        cur = datetime(start.year, start.month, start.day)
        last = datetime(end.year, end.month, end.day, 23)
    else:
        unit, step = "day", timedelta(days=1)
        cur = datetime(start.year, start.month, start.day)
        last = datetime(end.year, end.month, end.day)
    starts = []
    while cur <= last:
        starts.append(cur)
        cur += step
    return unit, starts


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def data_bounds(cost_dir: Path) -> dict:
    """Primera y última fecha con datos, para inicializar el calendario del frontend."""
    records = _load(cost_dir)
    if not records:
        return {"empty": True, "min": None, "max": None, "cost_dir": str(cost_dir)}
    lo = datetime.fromtimestamp(min(r[1] for r in records) / 1000.0).date()
    hi = datetime.fromtimestamp(max(r[1] for r in records) / 1000.0).date()
    return {
        "empty": False,
        "min": lo.isoformat(),
        "max": hi.isoformat(),
        "cost_dir": str(cost_dir),
    }


def build_payload(cost_dir: Path, range_: str = "day",
                  start: str | None = None, end: str | None = None) -> dict:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    use_dates = start_date is not None and end_date is not None
    if not use_dates:
        range_ = "week" if range_ == "week" else "day"

    records = _load(cost_dir)

    if not records:
        return {
            "range": range_, "empty": True, "labels": [], "series": {},
            "total_series": [], "cost_by_role": {}, "tokens_by_role": {},
            "calls_by_role": {}, "models": [],
            "cost_by_role_model": {}, "calls_by_role_model": {},
            "grand_total": 0.0, "grand_tokens": 0.0, "grand_calls": 0,
            "anchor": None, "records": 0, "cost_dir": str(cost_dir),
        }

    anchor_ms = max(r[1] for r in records)
    anchor_dt = datetime.fromtimestamp(anchor_ms / 1000.0)
    if use_dates:
        unit, starts = _date_range_starts(start_date, end_date)
        window_label = f"{min(start_date, end_date)} → {max(start_date, end_date)}"
    else:
        unit, starts = _preset_starts(anchor_dt, range_)
        window_label = anchor_dt.strftime("%Y-%m-%d %H:%M")
    keys, labels = _labels_and_keys(unit, starts)
    key_index = {k: i for i, k in enumerate(keys)}

    n = len(keys)
    series = {role: [0.0] * n for role in ROLES}
    cost_by_role = {role: 0.0 for role in ROLES}
    tokens_by_role = {role: 0.0 for role in ROLES}
    calls_by_role = {role: 0 for role in ROLES}
    cost_by_role_model = {role: {} for role in ROLES}
    calls_by_role_model = {role: {} for role in ROLES}
    cost_by_model = {}

    for role, ts, cost, tokens, model in records:
        idx = key_index.get(_bucket_key(datetime.fromtimestamp(ts / 1000.0), unit))
        if idx is None:
            continue
        series[role][idx] += cost
        cost_by_role[role] += cost
        tokens_by_role[role] += tokens
        calls_by_role[role] += 1
        cost_by_role_model[role][model] = cost_by_role_model[role].get(model, 0.0) + cost
        calls_by_role_model[role][model] = calls_by_role_model[role].get(model, 0) + 1
        cost_by_model[model] = cost_by_model.get(model, 0.0) + cost

    # Solo los roles con algún gasto en la ventana: evita líneas planas a cero (frontend,
    # cypress...) que solo añaden ruido a la leyenda.
    active = [role for role in ROLES if cost_by_role[role] > 0]
    total_series = [sum(series[role][i] for role in active) for i in range(n)]
    # Modelos ordenados por coste descendente: fija un orden estable para colores y leyendas.
    models = sorted(cost_by_model, key=lambda m: cost_by_model[m], reverse=True)

    return {
        "range": range_,
        "mode": "dates" if use_dates else "preset",
        "window": window_label,
        "empty": False,
        "unit": unit,
        "labels": labels,
        "series": {role: series[role] for role in active},
        "total_series": total_series,
        "cost_by_role": {role: cost_by_role[role] for role in active},
        "tokens_by_role": {role: tokens_by_role[role] for role in active},
        "calls_by_role": {role: calls_by_role[role] for role in active},
        "models": models,
        "cost_by_role_model": {role: cost_by_role_model[role] for role in active},
        "calls_by_role_model": {role: calls_by_role_model[role] for role in active},
        "grand_total": sum(cost_by_role[role] for role in active),
        "grand_tokens": sum(tokens_by_role[role] for role in active),
        "grand_calls": sum(calls_by_role[role] for role in active),
        "anchor": anchor_dt.strftime("%Y-%m-%d %H:%M"),
        "records": len(records),
        "cost_dir": str(cost_dir),
    }


# --------------------------------------------------------------------------- http

def _make_handler(cost_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        # Silencia el log por defecto (una línea por request) para no ensuciar la consola.
        def log_message(self, *args):
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel: str):
            if rel in ("", "/"):
                rel = "index.html"
            target = (STATIC_DIR / rel.lstrip("/")).resolve()
            # Cortafuegos de path traversal: nada fuera de STATIC_DIR.
            if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
                self.send_error(404, "Not found")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                _CONTENT_TYPES.get(target.suffix, "application/octet-stream"),
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/consumption":
                qs = parse_qs(parsed.query)
                range_ = (qs.get("range") or ["day"])[0]
                start = (qs.get("from") or [None])[0]
                end = (qs.get("to") or [None])[0]
                try:
                    self._send_json(build_payload(cost_dir, range_, start, end))
                except Exception as exc:  # noqa: BLE001 — el dashboard no debe caerse por un dato raro
                    self._send_json({"error": str(exc)}, status=500)
                return
            if parsed.path == "/api/bounds":
                try:
                    self._send_json(data_bounds(cost_dir))
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": str(exc)}, status=500)
                return
            self._send_static(parsed.path)

    return Handler


def serve(port: int = 4080, cost_dir: Path | None = None) -> int:
    cost_dir = (cost_dir or Path.cwd() / "cost-tracking").resolve()
    handler = _make_handler(cost_dir)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    except OSError as exc:
        print(f"[console] no se pudo abrir el puerto {port}: {exc}")
        return 1

    print(f"[console] datos de coste:  {cost_dir}")
    if not cost_dir.is_dir():
        print(f"[console] aviso: {cost_dir} no existe todavía (dashboard vacío).")
    print(f"[console] dashboard en:    http://localhost:{port}/  (Ctrl-C para parar)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[console] parado.")
    finally:
        httpd.server_close()
    return 0
