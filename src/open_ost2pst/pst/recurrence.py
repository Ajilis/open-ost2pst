"""MS-OXOCAL recurrence pattern serialization helpers."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import struct
from typing import Literal


RECURRENCE_EPOCH = date(1601, 1, 1)
NEVER_END_DATE = 0x5AE980DF

RECUR_FREQUENCY_DAILY = 0x200A
RECUR_FREQUENCY_WEEKLY = 0x200B
RECUR_FREQUENCY_MONTHLY = 0x200C
RECUR_FREQUENCY_YEARLY = 0x200D

PATTERN_DAY = 0x0000
PATTERN_WEEK = 0x0001
PATTERN_MONTH = 0x0002
PATTERN_MONTH_NTH = 0x0003

END_AFTER_DATE = 0x00002021
END_AFTER_COUNT = 0x00002022
END_NEVER = 0x00002023

DAY_SUNDAY = 0x01
DAY_MONDAY = 0x02
DAY_TUESDAY = 0x04
DAY_WEDNESDAY = 0x08
DAY_THURSDAY = 0x10
DAY_FRIDAY = 0x20
DAY_SATURDAY = 0x40

WEEKDAY_BITS = (
    DAY_MONDAY,
    DAY_TUESDAY,
    DAY_WEDNESDAY,
    DAY_THURSDAY,
    DAY_FRIDAY,
    DAY_SATURDAY,
    DAY_SUNDAY,
)

RECURRENCE_TYPE_NONE = 0
RECURRENCE_TYPE_DAILY = 1
RECURRENCE_TYPE_WEEKLY = 2
RECURRENCE_TYPE_MONTHLY = 3
RECURRENCE_TYPE_YEARLY = 4


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """High-level recurrence rule for Gregorian Outlook items.

    weekdays uses Python weekday numbers: Monday=0 through Sunday=6.
    week_of_month is 1..5, where 5 means the last matching weekday.
    Exactly one of count and until may be supplied. If neither is supplied,
    the recurrence never ends.
    """

    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = 1
    weekdays: tuple[int, ...] = ()
    day_of_month: int | None = None
    week_of_month: int | None = None
    count: int | None = None
    until: date | datetime | None = None
    first_day_of_week: int = 6

    def __post_init__(self) -> None:
        if self.interval < 1:
            raise ValueError("recurrence interval must be at least 1")
        if self.count is not None and self.count < 1:
            raise ValueError("recurrence count must be at least 1")
        if self.count is not None and self.until is not None:
            raise ValueError("recurrence count and until are mutually exclusive")
        if not 0 <= self.first_day_of_week <= 6:
            raise ValueError("first_day_of_week must be between 0 and 6")
        if any(not 0 <= day <= 6 for day in self.weekdays):
            raise ValueError("weekdays must contain Python weekday values 0..6")
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 31:
            raise ValueError("day_of_month must be between 1 and 31")
        if self.week_of_month is not None and not 1 <= self.week_of_month <= 5:
            raise ValueError("week_of_month must be between 1 and 5")
        if self.frequency == "daily":
            if self.weekdays or self.day_of_month or self.week_of_month:
                raise ValueError(
                    "daily recurrence does not use monthly/weekly selectors"
                )
        elif self.frequency == "weekly":
            if self.day_of_month is not None or self.week_of_month is not None:
                raise ValueError(
                    "weekly recurrence does not use monthly selectors"
                )
        elif self.frequency in ("monthly", "yearly"):
            if self.day_of_month is not None and self.week_of_month is not None:
                raise ValueError(
                    "choose day_of_month or week_of_month, not both"
                )
            if self.week_of_month is not None and not self.weekdays:
                raise ValueError(
                    "week_of_month requires at least one weekday"
                )


def build_recurrence_pattern(
    rule: RecurrenceRule,
    *,
    start: date | datetime,
    deleted_dates: tuple[date | datetime, ...] = (),
    task: bool = False,
) -> bytes:
    """Serialize an MS-OXOCAL RecurrencePattern without modified exceptions."""

    start_date = _as_date(start)
    if task and deleted_dates:
        raise ValueError("task recurrence cannot contain deleted instances")

    frequency, pattern_type, period, pattern_specific = _pattern_fields(
        rule,
        start_date,
    )
    start_minutes = _date_minutes(start_date)
    first_date_time = _first_date_time(
        rule,
        start_date,
        period,
    )

    if rule.count is not None:
        end_type = END_AFTER_COUNT
        occurrence_count = rule.count
        end_date = _nth_occurrence(rule, start_date, rule.count)
    elif rule.until is not None:
        end_type = END_AFTER_DATE
        until_date = _as_date(rule.until)
        if until_date < start_date:
            raise ValueError("recurrence until date precedes start date")
        occurrences = _occurrences_through(rule, start_date, until_date)
        if not occurrences:
            raise ValueError(
                "recurrence has no occurrences before until date"
            )
        occurrence_count = len(occurrences)
        end_date = occurrences[-1]
    else:
        end_type = END_NEVER
        occurrence_count = 10
        end_date = None

    deleted = tuple(
        sorted({_date_minutes(_as_date(value)) for value in deleted_dates})
    )
    end_minutes = (
        _date_minutes(end_date)
        if end_date is not None
        else NEVER_END_DATE
    )

    payload = bytearray(
        struct.pack(
            "<HHHHHIII",
            0x3004,
            0x3004,
            frequency,
            pattern_type,
            0,
            first_date_time,
            period,
            0,
        )
    )
    payload.extend(pattern_specific)
    payload.extend(
        struct.pack(
            "<III",
            end_type,
            occurrence_count,
            _mapi_first_dow(rule.first_day_of_week),
        )
    )
    payload.extend(struct.pack("<I", len(deleted)))
    for value in deleted:
        payload.extend(struct.pack("<I", value))

    payload.extend(struct.pack("<I", 0))
    payload.extend(struct.pack("<II", start_minutes, end_minutes))
    return bytes(payload)


def build_appointment_recurrence(
    rule: RecurrenceRule,
    *,
    start: datetime,
    end: datetime,
    deleted_dates: tuple[date | datetime, ...] = (),
) -> bytes:
    """Serialize AppointmentRecurrencePattern without modified exceptions."""

    if end < start:
        raise ValueError("appointment end must not precede start")

    recurrence = build_recurrence_pattern(
        rule,
        start=start,
        deleted_dates=deleted_dates,
    )
    midnight = datetime.combine(
        start.date(),
        time.min,
        tzinfo=start.tzinfo,
    )
    start_offset = int((start - midnight).total_seconds() // 60)
    end_offset = int((end - midnight).total_seconds() // 60)
    if start_offset < 0 or end_offset < start_offset:
        raise ValueError("invalid appointment recurrence time offsets")

    return b"".join(
        (
            recurrence,
            struct.pack(
                "<IIIIHII",
                0x00003006,
                0x00003009,
                start_offset,
                end_offset,
                0,
                0,
                0,
            ),
        )
    )


def recurrence_type(rule: RecurrenceRule) -> int:
    if rule.frequency == "daily":
        return RECURRENCE_TYPE_DAILY
    if rule.frequency == "weekly":
        return RECURRENCE_TYPE_WEEKLY
    if rule.frequency == "monthly":
        return RECURRENCE_TYPE_MONTHLY
    return RECURRENCE_TYPE_YEARLY


def recurrence_clip_end(
    rule: RecurrenceRule,
    *,
    start: datetime,
) -> datetime:
    """Return the UTC clip-end value used by recurring Calendar objects."""

    if rule.count is not None:
        last = _nth_occurrence(rule, start.date(), rule.count)
        return datetime.combine(last, time.min, tzinfo=timezone.utc)
    if rule.until is not None:
        occurrences = _occurrences_through(
            rule,
            start.date(),
            _as_date(rule.until),
        )
        if not occurrences:
            raise ValueError(
                "recurrence has no occurrences before until date"
            )
        return datetime.combine(
            occurrences[-1],
            time.min,
            tzinfo=timezone.utc,
        )
    return datetime(4500, 8, 31, 23, 59, tzinfo=timezone.utc)


def recurrence_description(rule: RecurrenceRule) -> str:
    if rule.count is not None:
        suffix = f"; count={rule.count}"
    elif rule.until is not None:
        suffix = f"; until={_as_date(rule.until).isoformat()}"
    else:
        suffix = "; never"

    if rule.frequency == "daily":
        return f"daily every {rule.interval} day(s){suffix}"
    if rule.frequency == "weekly":
        days = rule.weekdays or ()
        return (
            f"weekly every {rule.interval} week(s) on {days}{suffix}"
        )
    if rule.week_of_month is not None:
        return (
            f"{rule.frequency} every {rule.interval} interval(s), "
            f"week {rule.week_of_month}, days {rule.weekdays}{suffix}"
        )
    day = rule.day_of_month
    return (
        f"{rule.frequency} every {rule.interval} interval(s), "
        f"day {day}{suffix}"
    )


def _pattern_fields(
    rule: RecurrenceRule,
    start: date,
) -> tuple[int, int, int, bytes]:
    if rule.frequency == "daily":
        return (
            RECUR_FREQUENCY_DAILY,
            PATTERN_DAY,
            rule.interval * 1440,
            b"",
        )

    if rule.frequency == "weekly":
        weekdays = rule.weekdays or (start.weekday(),)
        return (
            RECUR_FREQUENCY_WEEKLY,
            PATTERN_WEEK,
            rule.interval,
            struct.pack("<I", _weekday_mask(weekdays)),
        )

    interval_months = rule.interval
    frequency = RECUR_FREQUENCY_MONTHLY
    if rule.frequency == "yearly":
        interval_months *= 12
        frequency = RECUR_FREQUENCY_YEARLY

    if rule.week_of_month is not None:
        weekdays = rule.weekdays or (start.weekday(),)
        return (
            frequency,
            PATTERN_MONTH_NTH,
            interval_months,
            struct.pack(
                "<II",
                _weekday_mask(weekdays),
                rule.week_of_month,
            ),
        )

    day = rule.day_of_month or start.day
    return (
        frequency,
        PATTERN_MONTH,
        interval_months,
        struct.pack("<I", day),
    )


def _first_date_time(
    rule: RecurrenceRule,
    start: date,
    period: int,
) -> int:
    if rule.frequency == "daily":
        return _date_minutes(start) % period

    if rule.frequency == "weekly":
        days_since_week_start = (
            start.weekday() - rule.first_day_of_week
        ) % 7
        week_start = start - timedelta(days=days_since_week_start)
        return _date_minutes(week_start) % (period * 10080)

    months = (start.year - 1601) * 12 + (start.month - 1)
    residue = months % period
    year = 1601 + residue // 12
    month = residue % 12 + 1
    return _date_minutes(date(year, month, 1))


def _occurrences_through(
    rule: RecurrenceRule,
    start: date,
    end: date,
) -> list[date]:
    result: list[date] = []
    current = start
    guard = 0
    while current <= end:
        if _matches(rule, start, current):
            result.append(current)
        current += timedelta(days=1)
        guard += 1
        if guard > 5_000_000:
            raise ValueError("recurrence expansion exceeded safety limit")
    return result


def _nth_occurrence(
    rule: RecurrenceRule,
    start: date,
    count: int,
) -> date:
    found = 0
    current = start
    guard = 0
    while True:
        if _matches(rule, start, current):
            found += 1
            if found == count:
                return current
        current += timedelta(days=1)
        guard += 1
        if guard > 5_000_000:
            raise ValueError("recurrence expansion exceeded safety limit")


def _matches(
    rule: RecurrenceRule,
    start: date,
    candidate: date,
) -> bool:
    if candidate < start:
        return False

    if rule.frequency == "daily":
        delta = (candidate - start).days
        return delta % rule.interval == 0

    if rule.frequency == "weekly":
        days_since_start_week = (
            candidate - _week_start(start, rule.first_day_of_week)
        ).days
        week_index = days_since_start_week // 7
        if week_index % rule.interval:
            return False
        weekdays = rule.weekdays or (start.weekday(),)
        return candidate.weekday() in weekdays

    months = (
        (candidate.year - start.year) * 12
        + candidate.month
        - start.month
    )
    interval_months = rule.interval * (
        12 if rule.frequency == "yearly" else 1
    )
    if months < 0 or months % interval_months:
        return False

    if rule.week_of_month is None:
        target_day = rule.day_of_month or start.day
        return candidate.day == min(
            target_day,
            monthrange(candidate.year, candidate.month)[1],
        )

    weekdays = rule.weekdays or (start.weekday(),)
    if candidate.weekday() not in weekdays:
        return False
    return candidate == _nth_matching_weekday(
        candidate.year,
        candidate.month,
        weekdays,
        rule.week_of_month,
    )


def _nth_matching_weekday(
    year: int,
    month: int,
    weekdays: tuple[int, ...],
    occurrence: int,
) -> date:
    matches = [
        date(year, month, day)
        for day in range(1, monthrange(year, month)[1] + 1)
        if date(year, month, day).weekday() in weekdays
    ]
    if occurrence == 5:
        return matches[-1]
    index = occurrence - 1
    if index >= len(matches):
        return matches[-1]
    return matches[index]


def _week_start(value: date, first_day: int) -> date:
    delta = (value.weekday() - first_day) % 7
    return value - timedelta(days=delta)


def _weekday_mask(days: tuple[int, ...]) -> int:
    mask = 0
    for day in days:
        mask |= WEEKDAY_BITS[day]
    return mask


def _mapi_first_dow(python_weekday: int) -> int:
    return (python_weekday + 1) % 7


def _date_minutes(value: date) -> int:
    delta = value - RECURRENCE_EPOCH
    minutes = delta.days * 1440
    if not 0 <= minutes <= 0xFFFFFFFF:
        raise ValueError(
            "recurrence date is outside 32-bit minute range"
        )
    return minutes


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value
