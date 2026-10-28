"""Repeat the checks at a fixed interval while the computer stays on.

``paper-status-monitor run --every 12h`` checks the submissions once and then again
every 12 hours, until the process is stopped (for instance, when you log out). The
Windows autostart can start it that way (``autostart enable --every 12h``), so a
computer that stays on for days keeps being checked.

The waiting is done in short steps against the wall clock: a computer that was
asleep or hibernated catches up with **one** check (not several) shortly after it
wakes up, and changes of the system time do not stretch the wait.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

#: Shortest interval accepted: review statuses change over days, and checking more
#: often only loads the tracker.
MIN_INTERVAL = timedelta(hours=1)

#: Longest pause, in seconds, between two looks at the clock while waiting.
POLL_SECONDS = 60.0

_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60}
_INTERVAL = re.compile(r"(?:\d+(?:\.\d+)?[dhm])+")
_PART = re.compile(r"(\d+(?:\.\d+)?)([dhm])")


def parse_interval(text: str, *, minimum: timedelta = MIN_INTERVAL) -> timedelta:
    """Parse an interval such as ``"12h"``, ``"1d"``, ``"90m"`` or ``"1d12h"``.

    Units are ``d`` (days), ``h`` (hours) and ``m`` (minutes); spaces and case are
    ignored.

    Args:
        text: The interval, as written by the user.
        minimum: Shortest interval accepted.

    Raises:
        ValueError: If *text* is not an interval or is shorter than *minimum*.
    """
    compact = "".join(str(text).split()).lower()
    if not _INTERVAL.fullmatch(compact):
        raise ValueError(
            f"Invalid interval {text!r}: write a number followed by d (days), h (hours) or "
            "m (minutes), for example 12h, 1d or 1h30m."
        )
    seconds = sum(float(number) * _UNIT_SECONDS[unit] for number, unit in _PART.findall(compact))
    interval = timedelta(seconds=round(seconds))
    if interval < minimum:
        raise ValueError(
            f"The interval {text!r} is too short: the minimum is {format_interval(minimum)}. "
            "Review statuses change over days, and frequent checks only load the tracker."
        )
    return interval


def format_interval(interval: timedelta) -> str:
    """Write *interval* in the compact form read by :func:`parse_interval` (``"1d12h"``).

    The interval is rounded to whole minutes.
    """
    minutes = max(0, round(interval.total_seconds() / 60))
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    units = ((days, "d"), (hours, "h"), (minutes, "m"))
    return "".join(f"{value}{unit}" for value, unit in units if value) or "0m"


def run_every(
    task: Callable[[], object],
    interval: timedelta,
    *,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], object] = time.sleep,
    poll: float = POLL_SECONDS,
    max_runs: int | None = None,
) -> int:
    """Call *task* now and then once every *interval*, until interrupted.

    The interval is counted from the start of each call. Exceptions raised by *task*
    are logged and do not stop the loop (``KeyboardInterrupt`` does).

    Args:
        task: The work to repeat (one complete check).
        interval: Time between the starts of two calls.
        clock: Wall clock in seconds since the epoch (injectable for tests).
        sleep: Function used to wait (injectable for tests).
        poll: Longest single wait, in seconds, so that the end of a sleep or
            hibernation of the computer is noticed quickly.
        max_runs: Stop after this many calls; ``None`` repeats forever.

    Returns:
        The number of calls made, when *max_runs* is reached.

    Raises:
        ValueError: If *interval* or *poll* is not positive.
    """
    period = interval.total_seconds()
    if period <= 0 or poll <= 0:
        raise ValueError("The interval and the polling period must be positive.")
    runs = 0
    while True:
        started = clock()
        try:
            task()
        except Exception:
            log.exception("A periodic check failed; the next one will run as planned.")
        runs += 1
        if max_runs is not None and runs >= max_runs:
            return runs
        due = started + period
        log.info("Next check at about %s", _local_time(due))
        while True:
            now = clock()
            due = min(due, now + period)  # the system clock went back: do not wait longer
            if now >= due:
                break
            sleep(min(poll, due - now))


def _local_time(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).isoformat(sep=" ", timespec="minutes")
    except (OverflowError, OSError, ValueError):
        return "an unknown time"
