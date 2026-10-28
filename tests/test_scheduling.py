from __future__ import annotations

from datetime import timedelta

import pytest

from paper_status_monitor import scheduling


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12h", timedelta(hours=12)),
        ("1d", timedelta(days=1)),
        ("90m", timedelta(minutes=90)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        (" 1D 12H ", timedelta(days=1, hours=12)),
        ("1.5h", timedelta(hours=1, minutes=30)),
    ],
)
def test_parse_interval(text: str, expected: timedelta) -> None:
    assert scheduling.parse_interval(text) == expected


@pytest.mark.parametrize("text", ["", "12", "h", "12 hours", "-1h", "1w", "1h-30m"])
def test_parse_interval_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValueError, match="Invalid interval"):
        scheduling.parse_interval(text)


def test_parse_interval_has_a_minimum() -> None:
    with pytest.raises(ValueError, match="too short: the minimum is 1h"):
        scheduling.parse_interval("59m")
    assert scheduling.parse_interval("5m", minimum=timedelta(0)) == timedelta(minutes=5)


@pytest.mark.parametrize(
    ("interval", "text"),
    [
        (timedelta(hours=12), "12h"),
        (timedelta(days=1, hours=12), "1d12h"),
        (timedelta(minutes=90), "1h30m"),
        (timedelta(days=2), "2d"),
        (timedelta(0), "0m"),
    ],
)
def test_format_interval(interval: timedelta, text: str) -> None:
    assert scheduling.format_interval(interval) == text
    if interval:
        assert scheduling.parse_interval(text, minimum=timedelta(0)) == interval


class FakeTime:
    """A wall clock that only moves when the code sleeps (or when told to jump)."""

    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.sleeps: list[float] = []
        self.jumps: dict[int, float] = {}  # sleep number -> extra seconds (suspend, clock change)

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds + self.jumps.get(len(self.sleeps), 0.0)


def test_run_every_repeats_at_the_interval() -> None:
    time = FakeTime()
    starts: list[float] = []
    runs = scheduling.run_every(
        lambda: starts.append(time.now),
        timedelta(hours=1),
        clock=time.clock,
        sleep=time.sleep,
        max_runs=3,
    )
    assert runs == 3
    assert [start - starts[0] for start in starts] == [0, 3600, 7200]
    assert max(time.sleeps) <= scheduling.POLL_SECONDS


def test_run_every_catches_up_once_after_the_computer_slept() -> None:
    time = FakeTime()
    time.jumps[2] = 10 * 3600  # the computer is suspended for 10 hours during the 2nd sleep
    starts: list[float] = []
    scheduling.run_every(
        lambda: starts.append(time.now),
        timedelta(hours=1),
        clock=time.clock,
        sleep=time.sleep,
        max_runs=3,
    )
    first, second, third = (start - starts[0] for start in starts)
    assert first == 0
    assert 10 * 3600 < second <= 10 * 3600 + 2 * scheduling.POLL_SECONDS  # one check on waking
    assert third == second + 3600  # then back to the normal rhythm


def test_run_every_does_not_wait_longer_when_the_clock_goes_back() -> None:
    time = FakeTime()
    time.jumps[1] = -5 * 3600  # the system clock is set back by five hours
    starts: list[float] = []
    scheduling.run_every(
        lambda: starts.append(time.now),
        timedelta(hours=1),
        clock=time.clock,
        sleep=time.sleep,
        max_runs=2,
    )
    assert sum(time.sleeps) <= 3600 + scheduling.POLL_SECONDS


def test_run_every_survives_failing_checks() -> None:
    time = FakeTime()
    calls: list[int] = []

    def check() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    scheduling.run_every(check, timedelta(hours=1), clock=time.clock, sleep=time.sleep, max_runs=2)
    assert len(calls) == 2


def test_run_every_rejects_a_zero_interval() -> None:
    with pytest.raises(ValueError, match="positive"):
        scheduling.run_every(lambda: None, timedelta(0), max_runs=1)
