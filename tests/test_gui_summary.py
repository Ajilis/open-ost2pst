from types import SimpleNamespace

from datetime import date, time

from open_ost2pst.gui import (
    _conversion_summary_rows,
    _format_count,
    _format_duration_minutes,
    _parse_hhmm,
    _parse_optional_date,
    _report_kpi_lines,
)


def _result(
    *,
    before_folders=679,
    before_messages=29003,
    before_attachments=43423,
    after_folders=680,
    after_messages=29003,
    after_attachments=43423,
):
    return SimpleNamespace(
        inspection=SimpleNamespace(
            folders=before_folders,
            messages=before_messages,
            attachments=before_attachments,
        ),
        verification=SimpleNamespace(
            ok=True,
            destination_manifest=SimpleNamespace(
                folder_count=after_folders,
                message_count=after_messages,
                attachment_count=after_attachments,
            ),
        ),
    )


def test_conversion_summary_rows_use_source_and_reopened_pst_counts() -> None:
    rows = _conversion_summary_rows(_result())

    assert rows == (
        ("Dossiers", 679, 680),
        ("Messages", 29003, 29003),
        ("Pièces jointes", 43423, 43423),
    )


def test_conversion_summary_rows_surface_real_count_differences() -> None:
    rows = _conversion_summary_rows(
        _result(
            after_messages=28850,
            after_attachments=43000,
        )
    )

    assert rows[1] == ("Messages", 29003, 28850)
    assert rows[2] == ("Pièces jointes", 43423, 43000)


def test_format_count_groups_thousands_for_french_gui() -> None:
    assert _format_count(29003) == "29 003"
    assert _format_count(7) == "7"



def test_pst_report_parameter_parsers() -> None:
    assert _parse_hhmm("09:30") == time(9, 30)
    assert _parse_optional_date("") is None
    assert _parse_optional_date("2026-10-02") == date(2026, 10, 2)
    assert _format_duration_minutes(750) == "12 h 30"


def test_report_kpi_lines_contains_all_eight_metrics() -> None:
    report = SimpleNamespace(
        percent_workdays_out_of_hours=25.0,
        working_days_out_of_hours=5,
        scheduled_workdays=20,
        days_overtime_gt_1h=3,
        days_overtime_gt_2h=1,
        median_last_activity=time(18, 42),
        latest_last_activity=time(23, 17),
        max_consecutive_overtime_days=4,
        rest_days_with_activity=2,
        minimum_apparent_rest_minutes=432,
    )

    lines = _report_kpi_lines(report)

    assert len(lines) == 8
    assert "25.00 %" in lines[0]
    assert "18:42" in lines[3]
    assert "23:17" in lines[4]
    assert "7 h 12" in lines[7]
