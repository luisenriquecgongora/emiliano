"""
Cron Expression Parser & Next Run Calculator.
Provides a zero-dependency 5-part cron evaluator with fallback to `croniter` if installed.
Supports standard 5 fields: (minute, hour, day of month, month, day of week)
and convenience macros: @hourly, @daily, @midnight, @weekly, @monthly, @yearly.
"""

from __future__ import annotations

import datetime
from typing import Optional, Set

try:
    import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False


CRON_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


def parse_field(field_str: str, min_val: int, max_val: int) -> Set[int]:
    """Parses a single cron field expression into a set of allowed integer values."""
    field_str = field_str.strip()
    result: Set[int] = set()

    for part in field_str.split(","):
        part = part.strip()
        if not part:
            continue

        step = 1
        if "/" in part:
            subparts = part.split("/")
            if len(subparts) != 2:
                raise ValueError(f"Invalid cron step syntax: {part}")
            part = subparts[0]
            step = int(subparts[1])
            if step <= 0:
                raise ValueError(f"Cron step must be > 0: {step}")

        if part == "*":
            start, end = min_val, max_val
        elif "-" in part:
            range_parts = part.split("-")
            if len(range_parts) != 2:
                raise ValueError(f"Invalid cron range syntax: {part}")
            start = int(range_parts[0])
            end = int(range_parts[1])
        else:
            start = end = int(part)

        if start < min_val or end > max_val or start > end:
            raise ValueError(f"Cron value {part} out of bounds [{min_val}-{max_val}]")

        for val in range(start, end + 1, step):
            result.add(val)

    return result


def get_next_cron_run(cron_expr: str, after_timestamp: Optional[float] = None) -> float:
    """
    Calculates the next unix timestamp matching the cron expression strictly after after_timestamp.
    """
    expr = cron_expr.strip()
    if expr in CRON_MACROS:
        expr = CRON_MACROS[expr]

    now_ts = after_timestamp if after_timestamp is not None else datetime.datetime.now().timestamp()

    if HAS_CRONITER:
        try:
            itr = croniter.croniter(expr, now_ts)
            return float(itr.get_next())
        except Exception:
            pass  # Fallback to pure python implementation

    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields, got {len(parts)}): {cron_expr}")

    # Standard fields: minute, hour, dom, month, dow
    allowed_minutes = parse_field(parts[0], 0, 59)
    allowed_hours = parse_field(parts[1], 0, 23)
    allowed_dom = parse_field(parts[2], 1, 31)
    allowed_months = parse_field(parts[3], 1, 12)

    # In cron, DOW is 0-7 where 0 and 7 are Sunday
    raw_dow = parse_field(parts[4], 0, 7)
    allowed_dow = {0 if d == 7 else d for d in raw_dow}

    # Start search from the next whole minute
    current_dt = datetime.datetime.fromtimestamp(now_ts).replace(second=0, microsecond=0)
    current_dt += datetime.timedelta(minutes=1)

    # Search up to 5 years into the future minute-by-minute with smart stepping
    max_search_dt = current_dt + datetime.timedelta(days=365 * 5)

    while current_dt < max_search_dt:
        # Check month
        if current_dt.month not in allowed_months:
            # Advance to first day of next month
            if current_dt.month == 12:
                current_dt = current_dt.replace(year=current_dt.year + 1, month=1, day=1, hour=0, minute=0)
            else:
                current_dt = current_dt.replace(month=current_dt.month + 1, day=1, hour=0, minute=0)
            continue

        # Check day of month and day of week
        # Python weekday: Mon=0, ..., Sun=6 -> Cron weekday: Sun=0, Mon=1, ..., Sat=6
        py_weekday = current_dt.weekday()
        cron_dow = (py_weekday + 1) % 7

        dom_match = current_dt.day in allowed_dom
        dow_match = cron_dow in allowed_dow

        # In standard cron, if both DOM and DOW are specified (neither is *), match either.
        # If either is *, both must match.
        dom_is_star = parts[2] == "*"
        dow_is_star = parts[4] == "*"

        day_matches = False
        if dom_is_star and dow_is_star:
            day_matches = True
        elif not dom_is_star and not dow_is_star:
            day_matches = dom_match or dow_match
        else:
            day_matches = dom_match if dow_is_star else dow_match

        if not day_matches:
            current_dt += datetime.timedelta(days=1)
            current_dt = current_dt.replace(hour=0, minute=0)
            continue

        # Check hour
        if current_dt.hour not in allowed_hours:
            current_dt += datetime.timedelta(hours=1)
            current_dt = current_dt.replace(minute=0)
            continue

        # Check minute
        if current_dt.minute not in allowed_minutes:
            current_dt += datetime.timedelta(minutes=1)
            continue

        return current_dt.timestamp()

    raise RuntimeError(f"Could not find matching next cron run for expression: {cron_expr}")
