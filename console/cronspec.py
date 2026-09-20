"""Expresiones cron de 5 campos, con lo justo y bien definido.

Se implementa aquí en vez de traer `croniter` porque el servidor de la consola es solo
librería estándar, y esto son sesenta líneas bien acotadas: `*`, un número, `a-b`, `*/n`,
`a-b/n` y listas separadas por comas, en los cinco campos clásicos.

    ┌───────────── minuto (0-59)
    │ ┌─────────── hora (0-23)
    │ │ ┌───────── día del mes (1-31)
    │ │ │ ┌─────── mes (1-12)
    │ │ │ │ ┌───── día de la semana (0-6, domingo = 0; 7 también vale como domingo)
    0 20 * * 1-5

No se soportan `@daily`, segundos, ni `L`/`#`: si hicieran falta, son azúcar encima de esto.

Regla heredada del cron de siempre, y que sorprende si no se conoce: cuando **día del mes** y
**día de la semana** están los dos restringidos, se cumple con que coincida **uno de los dos**,
no los dos a la vez.
"""

from __future__ import annotations

from datetime import datetime, timedelta

FIELDS = (
    ("minuto", 0, 59),
    ("hora", 0, 23),
    ("día del mes", 1, 31),
    ("mes", 1, 12),
    ("día de la semana", 0, 7),
)
# Tope de la búsqueda del próximo disparo: cuatro años cubren el 29 de febrero, y una
# expresión imposible (30 de febrero) termina en vez de buscar para siempre.
MAX_SEARCH_DAYS = 366 * 4


class CronError(ValueError):
    pass


def _parse_field(raw: str, low: int, high: int, label: str) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"campo '{label}' vacío en la expresión")
        step = 1
        if "/" in part:
            part, _, step_raw = part.partition("/")
            if not step_raw.isdigit() or int(step_raw) < 1:
                raise CronError(f"paso inválido en '{label}': /{step_raw}")
            step = int(step_raw)
        if part == "*":
            start, end = low, high
        elif "-" in part.lstrip("-"):
            start_raw, _, end_raw = part.partition("-")
            start, end = _number(start_raw, low, high, label), _number(end_raw, low, high, label)
            if start > end:
                raise CronError(f"rango invertido en '{label}': {part}")
        else:
            start = end = _number(part, low, high, label)
        values.update(range(start, end + 1, step))
    return values


def _number(raw: str, low: int, high: int, label: str) -> int:
    raw = raw.strip()
    if not raw.isdigit():
        raise CronError(f"'{raw}' no es un número válido en '{label}'")
    value = int(raw)
    if not (low <= value <= high):
        raise CronError(f"{value} fuera de rango en '{label}' ({low}-{high})")
    return value


class CronSpec:
    def __init__(self, expression: str):
        parts = (expression or "").split()
        if len(parts) != 5:
            raise CronError(
                "la expresión debe tener 5 campos (minuto hora día-del-mes mes día-de-semana), "
                f"y tiene {len(parts)}"
            )
        self.expression = " ".join(parts)
        self.minutes = _parse_field(parts[0], *FIELDS[0][1:], FIELDS[0][0])
        self.hours = _parse_field(parts[1], *FIELDS[1][1:], FIELDS[1][0])
        self.days = _parse_field(parts[2], *FIELDS[2][1:], FIELDS[2][0])
        self.months = _parse_field(parts[3], *FIELDS[3][1:], FIELDS[3][0])
        weekdays = _parse_field(parts[4], *FIELDS[4][1:], FIELDS[4][0])
        # 7 y 0 son el mismo domingo.
        self.weekdays = {0 if d == 7 else d for d in weekdays}
        self.dom_restricted = parts[2].strip() != "*"
        self.dow_restricted = parts[4].strip() != "*"

    def matches(self, when: datetime) -> bool:
        if when.minute not in self.minutes or when.hour not in self.hours:
            return False
        if when.month not in self.months:
            return False
        return self._day_matches(when)

    def _day_matches(self, when: datetime) -> bool:
        # datetime.weekday(): lunes=0..domingo=6. En cron, domingo=0.
        dow = (when.weekday() + 1) % 7
        in_dom = when.day in self.days
        in_dow = dow in self.weekdays
        if self.dom_restricted and self.dow_restricted:
            return in_dom or in_dow   # la regla clásica: basta con uno de los dos
        if self.dom_restricted:
            return in_dom
        if self.dow_restricted:
            return in_dow
        return True

    def next_after(self, after: datetime) -> datetime | None:
        """Primer disparo estrictamente posterior a `after` (con precisión de minuto).

        Avanza día a día y solo entra a mirar horas y minutos cuando el día encaja: una
        expresión como `0 20 1 1 *` no puede costar medio millón de comprobaciones.
        """
        cursor = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
        limit = after + timedelta(days=MAX_SEARCH_DAYS)
        while cursor <= limit:
            if cursor.month not in self.months or not self._day_matches(cursor):
                cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            for hour in sorted(self.hours):
                if hour < cursor.hour:
                    continue
                for minute in sorted(self.minutes):
                    if hour == cursor.hour and minute < cursor.minute:
                        continue
                    return cursor.replace(hour=hour, minute=minute)
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
        return None


def describe(expression: str) -> str:
    """Validación con mensaje legible; devuelve la expresión normalizada."""
    return CronSpec(expression).expression
