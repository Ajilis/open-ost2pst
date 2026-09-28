from datetime import date, datetime, timezone
import struct

from open_ost2pst.pst.outlook_items import create_meeting_identity
from open_ost2pst.pst.recurrence import (
    END_AFTER_COUNT,
    END_AFTER_DATE,
    PATTERN_DAY,
    PATTERN_MONTH,
    PATTERN_MONTH_NTH,
    PATTERN_WEEK,
    RECUR_FREQUENCY_DAILY,
    RECUR_FREQUENCY_MONTHLY,
    RECUR_FREQUENCY_WEEKLY,
    RECUR_FREQUENCY_YEARLY,
    RecurrenceRule,
    build_appointment_recurrence,
    build_recurrence_pattern,
)


def _core(blob: bytes):
    return struct.unpack_from("<HHHHHIII", blob, 0)


def test_daily_recurrence_matches_ms_oxocal_core_fields() -> None:
    rule = RecurrenceRule(
        "daily",
        interval=3,
        until=date(2011, 5, 4),
    )
    blob = build_appointment_recurrence(
        rule,
        start=datetime(2011, 4, 7, 8, 0, tzinfo=timezone.utc),
        end=datetime(2011, 4, 7, 8, 30, tzinfo=timezone.utc),
    )

    (
        reader,
        writer,
        frequency,
        pattern,
        calendar,
        first_date_time,
        period,
        sliding,
    ) = _core(blob)

    assert reader == writer == 0x3004
    assert frequency == RECUR_FREQUENCY_DAILY
    assert pattern == PATTERN_DAY
    assert calendar == 0
    assert first_date_time == 1440
    assert period == 4320
    assert sliding == 0

    offset = 22
    end_type, occurrence_count, first_dow = struct.unpack_from(
        "<III", blob, offset
    )
    assert end_type == END_AFTER_DATE
    assert occurrence_count == 10
    assert first_dow == 0

    # No deleted or modified instances.
    assert struct.unpack_from("<I", blob, 34)[0] == 0
    assert struct.unpack_from("<I", blob, 38)[0] == 0

    start_date, end_date = struct.unpack_from("<II", blob, 42)
    assert start_date == 215_776_800
    assert end_date == 215_815_680

    reader2, writer2, start_offset, end_offset, exceptions = (
        struct.unpack_from("<IIIIH", blob, 50)
    )
    assert reader2 == 0x3006
    assert writer2 == 0x3009
    assert start_offset == 480
    assert end_offset == 510
    assert exceptions == 0
    assert struct.unpack_from("<II", blob, 68) == (0, 0)


def test_weekly_recurrence_matches_published_weekly_example() -> None:
    rule = RecurrenceRule(
        "weekly",
        weekdays=(0, 3, 4),
        count=12,
    )
    blob = build_appointment_recurrence(
        rule,
        start=datetime(2007, 3, 26, 10, 0, tzinfo=timezone.utc),
        end=datetime(2007, 3, 26, 10, 30, tzinfo=timezone.utc),
    )

    core = _core(blob)
    assert core[2] == RECUR_FREQUENCY_WEEKLY
    assert core[3] == PATTERN_WEEK
    assert core[5] == 8640
    assert core[6] == 1
    assert struct.unpack_from("<I", blob, 22)[0] == 0x32

    end_type, occurrence_count, first_dow = struct.unpack_from(
        "<III", blob, 26
    )
    assert end_type == END_AFTER_COUNT
    assert occurrence_count == 12
    assert first_dow == 0

    # 12th occurrence is Friday 20 April 2007.
    start_date, end_date = struct.unpack_from("<II", blob, 46)
    epoch = date(1601, 1, 1)
    assert start_date == (date(2007, 3, 26) - epoch).days * 1440
    assert end_date == (date(2007, 4, 20) - epoch).days * 1440

    assert struct.unpack_from("<IIIIH", blob, 54) == (
        0x3006,
        0x3009,
        600,
        630,
        0,
    )


def test_monthly_and_yearly_pattern_specific_fields() -> None:
    monthly = build_recurrence_pattern(
        RecurrenceRule(
            "monthly",
            interval=2,
            day_of_month=15,
            count=3,
        ),
        start=date(2026, 1, 15),
    )
    assert _core(monthly)[2:4] == (
        RECUR_FREQUENCY_MONTHLY,
        PATTERN_MONTH,
    )
    assert struct.unpack_from("<I", monthly, 22)[0] == 15

    yearly = build_recurrence_pattern(
        RecurrenceRule(
            "yearly",
            weekdays=(0,),
            week_of_month=2,
            count=2,
        ),
        start=date(2026, 3, 9),
    )
    assert _core(yearly)[2:4] == (
        RECUR_FREQUENCY_YEARLY,
        PATTERN_MONTH_NTH,
    )
    day_mask, nth = struct.unpack_from("<II", yearly, 22)
    assert day_mask == 0x02
    assert nth == 2


def test_task_recurrence_is_plain_recurrence_pattern() -> None:
    blob = build_recurrence_pattern(
        RecurrenceRule("weekly", weekdays=(1,), count=4),
        start=date(2026, 9, 29),
        task=True,
    )

    assert len(blob) == 54
    assert _core(blob)[3] == PATTERN_WEEK
    assert struct.unpack_from("<I", blob, 22)[0] == 0x04


def test_meeting_global_object_id_layout_is_stable() -> None:
    creation = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    identity = create_meeting_identity(
        creation_time=creation,
        data=bytes.fromhex("00112233445566778899aabbccddeeff"),
        owner_appointment_id=12345,
    )

    value = identity.global_object_id
    assert value[:16] == bytes.fromhex(
        "040000008200e00074c5b7101a82e008"
    )
    assert value[16:20] == b"\x00" * 4
    assert value[28:36] == b"\x00" * 8
    assert struct.unpack_from("<I", value, 36)[0] == 16
    assert value[40:] == bytes.fromhex(
        "00112233445566778899aabbccddeeff"
    )
    assert identity.clean_global_object_id == value
    assert identity.owner_appointment_id == 12345
