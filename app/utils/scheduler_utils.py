"""APScheduler cron utilities - fix day_of_week numbering mismatch.

APScheduler 3.x uses Python's weekday numbering (0=Monday, 6=Sunday),
while standard crontab uses (0=Sunday, 1=Monday, ..., 7=Sunday).

CronTrigger.from_crontab() passes the day_of_week field through as-is,
so crontab ``1-5`` (Mon-Fri) is interpreted by APScheduler as Tue-Sat,
skipping Monday entirely.

This module provides a safe replacement :func:`cron_trigger` that converts
the day_of_week field before creating the trigger.

See: APScheduler issue #286 and the ``from_crontab`` docstring warning.
"""

from __future__ import annotations

from typing import Union

from apscheduler.triggers.cron import CronTrigger


def _dow_to_apscheduler(n: int) -> int:
    """Convert a single day-of-week number from crontab to APScheduler internal.

    Crontab:     0=Sunday, 1=Monday, ..., 5=Friday, 6=Saturday, 7=Sunday
    APScheduler: 0=Monday, 1=Tuesday, ..., 4=Friday, 5=Saturday, 6=Sunday
    """
    if n in (0, 7):
        return 6
    return n - 1


def _convert_dow_token(token: str) -> str:
    """Convert a day_of_week token (number, range, step, or list item)."""
    if token == "*":
        return "*"

    # Handle step: */n or range/n
    if "/" in token:
        base, step = token.split("/", 1)
        if base == "*":
            return f"*/{step}"
        base_converted = _convert_dow_token(base)
        return f"{base_converted}/{step}"

    # Handle range: a-b
    if "-" in token:
        parts = token.split("-", 1)
        start = str(_dow_to_apscheduler(int(parts[0])))
        end = str(_dow_to_apscheduler(int(parts[1])))
        return f"{start}-{end}"

    # Single number
    return str(_dow_to_apscheduler(int(token)))


def _convert_dow_field(dow: str) -> str:
    """Convert a full day_of_week field from crontab to APScheduler format."""
    if dow == "*":
        return "*"

    # Comma-separated list: e.g. "1,3,5"
    if "," in dow:
        return ",".join(_convert_dow_token(t.strip()) for t in dow.split(","))

    return _convert_dow_token(dow.strip())


def cron_trigger(cron_expr: str, timezone: Union[str, object] = None) -> CronTrigger:
    """Create a :class:`CronTrigger` from a standard crontab expression.

    Unlike :meth:`CronTrigger.from_crontab`, this function correctly converts
    the ``day_of_week`` field so that ``1-5`` properly means Monday–Friday.

    :param cron_expr: crontab expression (min hour day month day_of_week)
    :param timezone: timezone for the trigger
    :return: a properly configured CronTrigger
    """
    values = cron_expr.split()
    if len(values) != 5:
        raise ValueError(
            f"Wrong number of fields in cron expression; got {len(values)}, expected 5"
        )

    dow_converted = _convert_dow_field(values[4])

    return CronTrigger(
        minute=values[0],
        hour=values[1],
        day=values[2],
        month=values[3],
        day_of_week=dow_converted,
        timezone=timezone,
    )
