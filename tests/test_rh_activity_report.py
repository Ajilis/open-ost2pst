from datetime import date, datetime, time
from pathlib import Path

from open_ost2pst.reader import pff_reader
from open_ost2pst.reports.rh_activity import (
    ActivityEvent,
    ActivityScan,
    RhActivityConfig,
    generate_rh_activity_report,
    scan_pst_sent_activity,
    write_rh_activity_report,
)


def test_rh_activity_report_computes_eight_mvp_kpis(tmp_path) -> None:
    source = tmp_path / "mailbox.pst"
    source.write_bytes(b"fake")
    events = [
        # Monday
        ActivityEvent(datetime(2026, 9, 7, 8, 45), "/Sent Items", "a", "client_submit_time"),
        ActivityEvent(datetime(2026, 9, 7, 18, 30), "/Sent Items", "b", "client_submit_time"),
        # Tuesday
        ActivityEvent(datetime(2026, 9, 8, 9, 10), "/Sent Items", "c", "client_submit_time"),
        ActivityEvent(datetime(2026, 9, 8, 19, 30), "/Sent Items", "d", "client_submit_time"),
        # Wednesday
        ActivityEvent(datetime(2026, 9, 9, 9, 0), "/Sent Items", "e", "client_submit_time"),
        ActivityEvent(datetime(2026, 9, 9, 20, 30), "/Sent Items", "f", "client_submit_time"),
        # Thursday
        ActivityEvent(datetime(2026, 9, 10, 9, 0), "/Sent Items", "g", "client_submit_time"),
        ActivityEvent(datetime(2026, 9, 10, 18, 10), "/Sent Items", "h", "client_submit_time"),
        # Friday
        ActivityEvent(datetime(2026, 9, 11, 9, 0), "/Sent Items", "i", "client_submit_time"),
        ActivityEvent(datetime(2026, 9, 11, 17, 30), "/Sent Items", "j", "client_submit_time"),
        # Saturday / rest day
        ActivityEvent(datetime(2026, 9, 12, 11, 0), "/Sent Items", "k", "client_submit_time"),
    ]
    scan = ActivityScan(source=source, events=events)
    config = RhActivityConfig(
        workday_start=time(9, 0),
        workday_end=time(18, 0),
        working_weekdays=frozenset({0, 1, 2, 3, 4}),
        period_start=date(2026, 9, 7),
        period_end=date(2026, 9, 12),
    )

    report = generate_rh_activity_report(scan, config)

    assert report.scheduled_workdays == 5
    assert report.working_days_out_of_hours == 4
    assert report.percent_workdays_out_of_hours == 80.0
    assert report.days_overtime_gt_1h == 2
    assert report.days_overtime_gt_2h == 1
    assert report.median_last_activity == time(18, 30)
    assert report.latest_last_activity == time(20, 30)
    assert report.max_consecutive_overtime_days == 4
    assert report.rest_days_with_activity == 1
    assert report.minimum_apparent_rest_minutes == 750


def test_report_writer_creates_html_and_json_sidecar(tmp_path) -> None:
    source = tmp_path / "mailbox.pst"
    source.write_bytes(b"fake")
    scan = ActivityScan(
        source=source,
        events=[
            ActivityEvent(
                datetime(2026, 9, 7, 19, 15),
                "/Éléments envoyés",
                "Bonsoir",
                "client_submit_time",
            )
        ],
    )
    report = generate_rh_activity_report(
        scan,
        RhActivityConfig(
            period_start=date(2026, 9, 7),
            period_end=date(2026, 9, 7),
        ),
    )

    html_path, json_path = write_rh_activity_report(
        report,
        tmp_path / "rh-report.html",
    )

    html = html_path.read_text(encoding="utf-8")
    data = __import__("json").loads(json_path.read_text(encoding="utf-8"))

    assert "RH — Activité hors horaires" in html
    assert "8 KPI" in html
    assert "Il ne mesure pas le temps de travail effectif" in html
    assert data["template"]["id"] == "rh-out-of-hours"
    assert data["kpi"]["days_overtime_gt_1h"] == 1


class _FakeMessage:
    def __init__(
        self,
        subject,
        *,
        client_submit_time=None,
        delivery_time=None,
        creation_time=None,
    ):
        self.subject = subject
        self.client_submit_time = client_submit_time
        self.delivery_time = delivery_time
        self.creation_time = creation_time


class _FakeFolder:
    def __init__(self, name, *, messages=None, folders=None):
        self.name = name
        self._messages = messages or []
        self._folders = folders or []
        self.number_of_sub_messages = len(self._messages)
        self.number_of_sub_folders = len(self._folders)

    def get_sub_message(self, index):
        return self._messages[index]

    def get_sub_folder(self, index):
        return self._folders[index]


class _FakeStore:
    def __init__(self, root):
        self.root = root
        self.closed = False

    def open(self, path):
        self.path = path

    def get_root_folder(self):
        return self.root

    def close(self):
        self.closed = True


class _FakePypff:
    def __init__(self, store):
        self.store = store

    def file(self):
        return self.store


def test_scan_pst_uses_only_sent_folder_tree_and_submit_time(
    tmp_path,
    monkeypatch,
) -> None:
    sent = _FakeFolder(
        "Éléments envoyés",
        messages=[
            _FakeMessage(
                "sent",
                client_submit_time=datetime(2026, 9, 7, 19, 30),
                delivery_time=datetime(2026, 9, 7, 19, 31),
            ),
            _FakeMessage(
                "fallback",
                delivery_time=datetime(2026, 9, 8, 18, 45),
            ),
        ],
        folders=[
            _FakeFolder(
                "2025",
                messages=[
                    _FakeMessage(
                        "nested",
                        client_submit_time=datetime(2025, 12, 1, 10, 0),
                    )
                ],
            )
        ],
    )
    inbox = _FakeFolder(
        "Inbox",
        messages=[
            _FakeMessage(
                "incoming",
                client_submit_time=datetime(2026, 9, 7, 23, 59),
            )
        ],
    )
    root = _FakeFolder("Root", folders=[inbox, sent])
    store = _FakeStore(root)
    monkeypatch.setattr(
        pff_reader,
        "_load_pypff",
        lambda: _FakePypff(store),
    )
    monkeypatch.setattr(
        pff_reader,
        "_select_logical_root",
        lambda value: value,
    )

    source = tmp_path / "mailbox.pst"
    source.write_bytes(b"fake")
    scan = scan_pst_sent_activity(source)

    assert store.closed is True
    assert scan.messages_seen == 4
    assert scan.sent_messages_seen == 3
    assert len(scan.events) == 3
    assert scan.events[0].subject == "sent"
    assert scan.events[0].timestamp_source == "client_submit_time"
    assert scan.timestamp_fallbacks == 1
    assert all(event.subject != "incoming" for event in scan.events)


def test_scan_rejects_non_pst_source(tmp_path) -> None:
    source = tmp_path / "mailbox.ost"
    source.write_bytes(b"fake")

    import pytest

    with pytest.raises(ValueError, match="uniquement un fichier PST"):
        scan_pst_sent_activity(source)
