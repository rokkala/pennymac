"""Five-field cron expressions evaluated in the vendor's timezone, with business-day calendars.

    minute hour day-of-month month day-of-week        e.g.  "0 6 * * MON-FRI"   business days 06:00
                                                             "0 */4 * * *"       every 4 hours
                                                             "30 7 1 * *"        1st of the month 07:30

Supports *, lists, ranges, steps and names (JAN-DEC, SUN-SAT; 0 and 7 are Sunday). When both
day-of-month and day-of-week are restricted, a day matches either (standard cron semantics).

Times are wall-clock in the schedule's IANA timezone, so "06:00 America/New_York" stays 06:00
across daylight-saving changes. A time that does not exist on the spring-forward day resolves to
the instant one hour later; an ambiguous fall-back time resolves to its first occurrence.

Calendars
    none          every matching day
    us_federal    skips US Federal Reserve holidays (observed dates), the settlement calendar mortgage
                  servicing runs on. holiday_rule: skip (no delivery that day) | next_business_day
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
DAYS = {d: i for i, d in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])}
CALENDARS = ("none", "us_federal")


class CronError(ValueError):
    pass


def _field(spec: str, lo: int, hi: int, names: dict[str, int] | None = None) -> frozenset[int]:
    out: set[int] = set()
    for part in spec.upper().split(","):
        if not part:
            raise CronError(f"empty list item in '{spec}'")
        step = 1
        if "/" in part:
            part, st = part.split("/", 1)
            if not st.isdigit() or int(st) < 1:
                raise CronError(f"bad step '{st}'")
            step = int(st)

        def val(x: str) -> int:
            if names and x in names:
                return names[x]
            if not x.isdigit():
                raise CronError(f"'{x}' is not a number or name")
            return int(x)

        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            x, y = part.split("-", 1)
            a, b = val(x), val(y)
        else:
            a = val(part)
            b = hi if step > 1 else a
        if a < lo or b > hi or a > b:
            raise CronError(f"'{part}' is outside {lo}-{hi}")
        out.update(range(a, b + 1, step))
    return frozenset(out)


@cache
def parse(expr: str) -> tuple:
    parts = (expr or "").split()
    if len(parts) != 5:
        raise CronError("cron needs 5 fields: minute hour day-of-month month day-of-week")
    mi = _field(parts[0], 0, 59)
    hr = _field(parts[1], 0, 23)
    dom = _field(parts[2], 1, 31)
    mon = _field(parts[3], 1, 12, MONTHS)
    dow = frozenset(d % 7 for d in _field(parts[4], 0, 7, DAYS))
    return mi, hr, dom, mon, dow, parts[2] != "*", parts[4] != "*"


def tz_of(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise CronError(f"unknown timezone '{name}'") from e


def _day_matches(d: date, p) -> bool:
    _, _, dom, mon, dow, dom_r, dow_r = p
    if d.month not in mon:
        return False
    cron_dow = (d.weekday() + 1) % 7  # Python Mon=0 -> cron Sun=0
    if dom_r and dow_r:
        return d.day in dom or cron_dow in dow
    return d.day in dom and cron_dow in dow


# ------------------------------------------------------------------ holidays
def _nth_weekday(y, m, weekday, n):
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y, m, weekday):
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


@cache
def us_federal_holidays(year: int) -> frozenset[date]:
    """Federal Reserve holidays. Saturday holidays are not moved (the Fed is open the Friday before);
    Sunday holidays are observed on Monday."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    out = {d + timedelta(days=1) if d.weekday() == 6 else d for d in fixed if d.weekday() != 5}
    out |= {
        _nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        _last_weekday(year, 5, 0),     # Memorial Day
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
    }
    return frozenset(out)


def is_business_day(d: date, calendar: str = "us_federal") -> bool:
    if calendar == "none":
        return True
    return d.weekday() < 5 and d not in us_federal_holidays(d.year)


def next_business_day(d: date, calendar: str) -> date:
    d += timedelta(days=1)
    while not is_business_day(d, calendar):
        d += timedelta(days=1)
    return d


# ------------------------------------------------------------------ evaluation
def _to_utc(local: datetime) -> datetime:
    return local.astimezone(UTC).replace(tzinfo=None)


def occurrences(expr: str, tz: str, start_utc: datetime, end_utc: datetime, calendar: str = "none",
                holiday_rule: str = "skip") -> list[datetime]:
    """Due instants (naive UTC) with start_utc < t <= end_utc."""
    p = parse(expr)
    zone = tz_of(tz)
    if calendar not in CALENDARS:
        raise CronError(f"calendar must be one of {CALENDARS}")
    mi, hr = sorted(p[0]), sorted(p[1])
    d = start_utc.replace(tzinfo=UTC).astimezone(zone).date() - timedelta(days=1)
    last = end_utc.replace(tzinfo=UTC).astimezone(zone).date() + timedelta(days=1)
    out: set[datetime] = set()
    while d <= last:
        if _day_matches(d, p):
            day = d
            if not is_business_day(d, calendar):
                day = next_business_day(d, calendar) if holiday_rule == "next_business_day" else None
            if day is not None:
                for h in hr:
                    for m in mi:
                        t = _to_utc(datetime.combine(day, time(h, m), tzinfo=zone))
                        if start_utc < t <= end_utc:
                            out.add(t)
        d += timedelta(days=1)
    return sorted(out)


def next_after(expr: str, tz: str, after_utc: datetime, n: int = 1, calendar: str = "none", holiday_rule: str = "skip") -> list[datetime]:
    out: list[datetime] = []
    start, span = after_utc, timedelta(days=8)
    for _ in range(60):  # up to ~16 months ahead (monthly / yearly schedules, holiday shifts)
        out += occurrences(expr, tz, start, start + span, calendar, holiday_rule)
        if len(out) >= n:
            return out[:n]
        start += span
    return out[:n]


def local_label(t_utc: datetime, tz: str) -> str:
    loc = t_utc.replace(tzinfo=UTC).astimezone(tz_of(tz))
    return f"{loc:%Y-%m-%d %H:%M} {loc.tzname()}"


def describe(expr: str) -> str:
    """Short human description for common shapes; falls back to the expression."""
    try:
        p = parse(expr)
    except CronError:
        return expr
    mi, hr, dom, mon, dow, dom_r, dow_r = p
    if len(mi) == 1 and len(hr) == 1:
        at = f"{min(hr):02d}:{min(mi):02d}"
        if not dom_r and dow == frozenset({1, 2, 3, 4, 5}) and len(mon) == 12:
            return f"Business days at {at}"
        if not dom_r and not dow_r and len(mon) == 12:
            return f"Daily at {at}"
        if dom_r and not dow_r and len(dom) == 1 and len(mon) == 12:
            return f"Monthly on day {min(dom)} at {at}"
        if not dom_r and len(dow) == 1 and len(mon) == 12:
            return f"Weekly on {[k for k, v in DAYS.items() if v == min(dow)][0].title()} at {at}"
    parts = expr.split()
    if len(mi) == 1 and parts[1].startswith("*/") and not dom_r and not dow_r:
        return f"Every {parts[1][2:]} hours at :{min(mi):02d}"
    return expr
