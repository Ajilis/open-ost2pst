"""Read-only HR activity report for PST files.

The report describes observed messaging activity. It does not infer working
time, performance, productivity, intent, or compliance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from html import escape
import json
import os
from pathlib import Path
from statistics import median
import unicodedata
from typing import Callable, Iterable

from open_ost2pst.reader import pff_reader


REPORT_TEMPLATE_ID = "rh-out-of-hours"
REPORT_TEMPLATE_NAME = "RH — Activité hors horaires"

# Common Outlook/localized names for the default Sent Items folder.
_SENT_FOLDER_NAMES = {
    "sent",
    "sent items",
    "sent mail",
    "elements envoyes",
    "element envoye",
    "elements expedies",
    "gesendete elemente",
    "elementos enviados",
    "itens enviados",
    "posta inviata",
    "verzonden items",
}


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    timestamp: datetime
    folder_path: str
    subject: str | None
    timestamp_source: str


@dataclass(slots=True)
class ActivityScan:
    source: Path
    folders_seen: int = 0
    messages_seen: int = 0
    sent_folders_seen: int = 0
    sent_messages_seen: int = 0
    events: list[ActivityEvent] = field(default_factory=list)
    undated_sent_messages: int = 0
    timestamp_fallbacks: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "folders_seen": self.folders_seen,
            "messages_seen": self.messages_seen,
            "sent_folders_seen": self.sent_folders_seen,
            "sent_messages_seen": self.sent_messages_seen,
            "dated_events": len(self.events),
            "undated_sent_messages": self.undated_sent_messages,
            "timestamp_fallbacks": self.timestamp_fallbacks,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class RhActivityConfig:
    workday_start: time = time(9, 0)
    workday_end: time = time(18, 0)
    working_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    period_start: date | None = None
    period_end: date | None = None

    def __post_init__(self) -> None:
        if self.workday_end <= self.workday_start:
            raise ValueError("l'heure de fin doit être après l'heure de début")
        if not self.working_weekdays:
            raise ValueError("au moins un jour travaillé doit être sélectionné")
        if any(day < 0 or day > 6 for day in self.working_weekdays):
            raise ValueError("jour de semaine invalide")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("la date de fin précède la date de début")


@dataclass(frozen=True, slots=True)
class DailyActivity:
    day: date
    is_working_day: bool
    event_count: int
    first_activity: datetime
    last_activity: datetime
    before_start: bool
    after_end: bool
    out_of_hours: bool
    overtime_minutes: int
    apparent_rest_minutes: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.day.isoformat(),
            "is_working_day": self.is_working_day,
            "event_count": self.event_count,
            "first_activity": self.first_activity.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "before_start": self.before_start,
            "after_end": self.after_end,
            "out_of_hours": self.out_of_hours,
            "overtime_minutes": self.overtime_minutes,
            "apparent_rest_minutes": self.apparent_rest_minutes,
        }


@dataclass(frozen=True, slots=True)
class RhActivityReport:
    source: Path
    generated_at: datetime
    config: RhActivityConfig
    scan: ActivityScan
    period_start: date | None
    period_end: date | None
    scheduled_workdays: int
    working_days_with_activity: int
    working_days_out_of_hours: int
    percent_workdays_out_of_hours: float
    days_overtime_gt_1h: int
    days_overtime_gt_2h: int
    median_last_activity: time | None
    latest_last_activity: time | None
    max_consecutive_overtime_days: int
    rest_days_with_activity: int
    minimum_apparent_rest_minutes: int | None
    median_apparent_rest_minutes: int | None
    daily: tuple[DailyActivity, ...]
    timezone_note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "template": {
                "id": REPORT_TEMPLATE_ID,
                "name": REPORT_TEMPLATE_NAME,
            },
            "source": str(self.source),
            "generated_at": self.generated_at.isoformat(),
            "definitions": {
                "activity": (
                    "messages présents dans un dossier d'éléments envoyés ; "
                    "horodatage client_submit_time, puis delivery_time, puis "
                    "creation_time en repli"
                ),
                "out_of_hours": (
                    "activité observée avant l'heure de début ou après "
                    "l'heure de fin sur un jour travaillé"
                ),
                "overtime": (
                    "écart entre la dernière activité observée et l'heure "
                    "théorique de fin, si positif"
                ),
                "apparent_rest": (
                    "intervalle entre la dernière activité d'un jour actif "
                    "et la première activité du jour actif suivant"
                ),
            },
            "config": {
                "workday_start": self.config.workday_start.strftime("%H:%M"),
                "workday_end": self.config.workday_end.strftime("%H:%M"),
                "working_weekdays": sorted(self.config.working_weekdays),
                "period_start": (
                    self.config.period_start.isoformat()
                    if self.config.period_start
                    else None
                ),
                "period_end": (
                    self.config.period_end.isoformat()
                    if self.config.period_end
                    else None
                ),
            },
            "observed_period": {
                "start": self.period_start.isoformat() if self.period_start else None,
                "end": self.period_end.isoformat() if self.period_end else None,
            },
            "scan": self.scan.to_dict(),
            "kpi": {
                "scheduled_workdays": self.scheduled_workdays,
                "working_days_with_activity": self.working_days_with_activity,
                "working_days_out_of_hours": self.working_days_out_of_hours,
                "percent_workdays_out_of_hours": round(
                    self.percent_workdays_out_of_hours,
                    2,
                ),
                "days_overtime_gt_1h": self.days_overtime_gt_1h,
                "days_overtime_gt_2h": self.days_overtime_gt_2h,
                "median_last_activity": _format_clock(self.median_last_activity),
                "latest_last_activity": _format_clock(self.latest_last_activity),
                "max_consecutive_overtime_days": self.max_consecutive_overtime_days,
                "rest_days_with_activity": self.rest_days_with_activity,
                "minimum_apparent_rest_minutes": self.minimum_apparent_rest_minutes,
                "median_apparent_rest_minutes": self.median_apparent_rest_minutes,
            },
            "timezone_note": self.timezone_note,
            "daily": [row.to_dict() for row in self.daily],
            "caution": (
                "Ces indicateurs décrivent des traces de messagerie observées "
                "dans le PST. Ils ne mesurent pas le temps de travail effectif "
                "et ne doivent pas être interprétés seuls comme une évaluation "
                "individuelle."
            ),
        }


ScanProgressCallback = Callable[[int, str], None]


def scan_pst_sent_activity(
    path: str | Path,
    *,
    progress_callback: ScanProgressCallback | None = None,
) -> ActivityScan:
    """Read sent-message timestamps from a PST without extracting bodies/files."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() != ".pst":
        raise ValueError("le rapport RH accepte uniquement un fichier PST")

    pypff = pff_reader._load_pypff()
    store = pypff.file()
    scan = ActivityScan(source=source)

    try:
        store.open(str(source))
        root = pff_reader._select_logical_root(store.get_root_folder())
        _scan_folder(
            root,
            scan,
            parent_path="",
            inside_sent_tree=False,
            progress_callback=progress_callback,
        )
    finally:
        try:
            store.close()
        except Exception:
            pass

    if scan.sent_folders_seen == 0:
        scan.warnings.append(
            "Aucun dossier d'éléments envoyés reconnu dans le PST. "
            "Le rapport ne contient donc aucune activité envoyée."
        )
    elif scan.sent_messages_seen > 0 and not scan.events:
        scan.warnings.append(
            "Des messages envoyés ont été trouvés, mais aucun horodatage "
            "exploitable n'a pu être lu."
        )

    if progress_callback is not None:
        progress_callback(100, "Analyse PST terminée")
    return scan


def generate_rh_activity_report(
    scan: ActivityScan,
    config: RhActivityConfig,
) -> RhActivityReport:
    """Compute the eight MVP HR KPIs from sent-message activity."""

    localized: list[ActivityEvent] = []
    saw_aware = False
    saw_naive = False

    for event in scan.events:
        timestamp = event.timestamp
        if timestamp.tzinfo is None:
            saw_naive = True
            local_timestamp = timestamp
        else:
            saw_aware = True
            local_timestamp = timestamp.astimezone()

        local_event = ActivityEvent(
            timestamp=local_timestamp,
            folder_path=event.folder_path,
            subject=event.subject,
            timestamp_source=event.timestamp_source,
        )
        if (
            config.period_start is not None
            and local_timestamp.date() < config.period_start
        ):
            continue
        if (
            config.period_end is not None
            and local_timestamp.date() > config.period_end
        ):
            continue
        localized.append(local_event)

    localized.sort(key=lambda item: item.timestamp)

    if config.period_start is not None:
        period_start = config.period_start
    elif localized:
        period_start = localized[0].timestamp.date()
    else:
        period_start = None

    if config.period_end is not None:
        period_end = config.period_end
    elif localized:
        period_end = localized[-1].timestamp.date()
    else:
        period_end = None

    grouped: dict[date, list[ActivityEvent]] = {}
    for event in localized:
        grouped.setdefault(event.timestamp.date(), []).append(event)

    daily_rows: list[DailyActivity] = []
    active_dates = sorted(grouped)
    next_first_by_day: dict[date, datetime] = {}
    for index, day in enumerate(active_dates[:-1]):
        next_day = active_dates[index + 1]
        next_first_by_day[day] = grouped[next_day][0].timestamp

    for day in active_dates:
        events = grouped[day]
        first_activity = events[0].timestamp
        last_activity = events[-1].timestamp
        is_working_day = day.weekday() in config.working_weekdays
        before_start = is_working_day and first_activity.time() < config.workday_start
        after_end = is_working_day and last_activity.time() > config.workday_end

        end_boundary = datetime.combine(
            day,
            config.workday_end,
            tzinfo=last_activity.tzinfo,
        )
        overtime_minutes = 0
        if is_working_day and last_activity > end_boundary:
            overtime_minutes = max(
                0,
                int((last_activity - end_boundary).total_seconds() // 60),
            )

        apparent_rest_minutes = None
        next_first = next_first_by_day.get(day)
        if next_first is not None:
            apparent_rest_minutes = max(
                0,
                int((next_first - last_activity).total_seconds() // 60),
            )

        daily_rows.append(
            DailyActivity(
                day=day,
                is_working_day=is_working_day,
                event_count=len(events),
                first_activity=first_activity,
                last_activity=last_activity,
                before_start=before_start,
                after_end=after_end,
                out_of_hours=before_start or after_end,
                overtime_minutes=overtime_minutes,
                apparent_rest_minutes=apparent_rest_minutes,
            )
        )

    scheduled_workdays = _count_scheduled_workdays(
        period_start,
        period_end,
        config.working_weekdays,
    )
    working_rows = [row for row in daily_rows if row.is_working_day]
    out_rows = [row for row in working_rows if row.out_of_hours]
    last_times = [row.last_activity.time().replace(tzinfo=None) for row in working_rows]

    percent_out = (
        (len(out_rows) * 100.0 / scheduled_workdays)
        if scheduled_workdays
        else 0.0
    )

    rest_values = [
        row.apparent_rest_minutes
        for row in daily_rows
        if row.apparent_rest_minutes is not None
    ]

    timezone_note = _timezone_note(saw_aware, saw_naive)

    return RhActivityReport(
        source=scan.source,
        generated_at=datetime.now().astimezone(),
        config=config,
        scan=scan,
        period_start=period_start,
        period_end=period_end,
        scheduled_workdays=scheduled_workdays,
        working_days_with_activity=len(working_rows),
        working_days_out_of_hours=len(out_rows),
        percent_workdays_out_of_hours=percent_out,
        days_overtime_gt_1h=sum(row.overtime_minutes > 60 for row in working_rows),
        days_overtime_gt_2h=sum(row.overtime_minutes > 120 for row in working_rows),
        median_last_activity=_median_clock(last_times),
        latest_last_activity=max(last_times) if last_times else None,
        max_consecutive_overtime_days=_max_consecutive_overtime(
            daily_rows,
            period_start,
            period_end,
        ),
        rest_days_with_activity=sum(
            1 for row in daily_rows if not row.is_working_day
        ),
        minimum_apparent_rest_minutes=(
            min(rest_values) if rest_values else None
        ),
        median_apparent_rest_minutes=(
            int(median(rest_values)) if rest_values else None
        ),
        daily=tuple(daily_rows),
        timezone_note=timezone_note,
    )


def write_rh_activity_report(
    report: RhActivityReport,
    html_path: str | Path,
    *,
    json_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write an HTML report plus an auditable JSON sidecar atomically."""

    html_target = Path(html_path)
    json_target = (
        Path(json_path)
        if json_path is not None
        else html_target.with_suffix(".json")
    )

    _atomic_write_text(html_target, _render_html(report))
    _atomic_write_text(
        json_target,
        json.dumps(
            report.to_dict(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    return html_target, json_target


def _scan_folder(
    folder,
    scan: ActivityScan,
    *,
    parent_path: str,
    inside_sent_tree: bool,
    progress_callback: ScanProgressCallback | None,
) -> None:
    scan.folders_seen += 1
    name = str(pff_reader._safe_attr(folder, "name") or "(sans nom)")
    path = f"{parent_path}/{name}" if parent_path else f"/{name}"

    is_sent_folder = _is_sent_folder_name(name)
    sent_tree = inside_sent_tree or is_sent_folder
    if is_sent_folder:
        scan.sent_folders_seen += 1

    message_count = pff_reader._int_attr(folder, "number_of_sub_messages")
    scan.messages_seen += message_count
    if sent_tree:
        scan.sent_messages_seen += message_count

    for index in range(message_count):
        if not sent_tree:
            continue
        try:
            message = folder.get_sub_message(index)
            timestamp, source_name = _message_activity_timestamp(message)
            if timestamp is None:
                scan.undated_sent_messages += 1
                continue
            if source_name != "client_submit_time":
                scan.timestamp_fallbacks += 1
            scan.events.append(
                ActivityEvent(
                    timestamp=timestamp,
                    folder_path=path,
                    subject=pff_reader._safe_attr(message, "subject"),
                    timestamp_source=source_name,
                )
            )
        except Exception as exc:
            if len(scan.warnings) < 100:
                scan.warnings.append(
                    f"message {index} illisible dans {path}: {exc}"
                )

    if progress_callback is not None and scan.folders_seen % 20 == 0:
        progress_callback(
            min(95, 5 + scan.folders_seen // 2),
            (
                f"{scan.folders_seen} dossiers, "
                f"{scan.sent_messages_seen} messages envoyés examinés"
            ),
        )

    child_count = pff_reader._int_attr(folder, "number_of_sub_folders")
    for index in range(child_count):
        try:
            child = folder.get_sub_folder(index)
        except Exception as exc:
            if len(scan.warnings) < 100:
                scan.warnings.append(
                    f"sous-dossier {index} illisible dans {path}: {exc}"
                )
            continue
        _scan_folder(
            child,
            scan,
            parent_path=path,
            inside_sent_tree=sent_tree,
            progress_callback=progress_callback,
        )


def _message_activity_timestamp(message) -> tuple[datetime | None, str]:
    for attr in (
        "client_submit_time",
        "delivery_time",
        "creation_time",
    ):
        value = pff_reader._datetime_attr(message, attr)
        if value is not None:
            return value, attr
    return None, "none"


def _is_sent_folder_name(value: str) -> bool:
    normalized = _normalize_folder_name(value)
    return normalized in _SENT_FOLDER_NAMES


def _normalize_folder_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    asciiish = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(asciiish.casefold().replace("-", " ").split())


def _count_scheduled_workdays(
    start: date | None,
    end: date | None,
    working_weekdays: frozenset[int],
) -> int:
    if start is None or end is None or end < start:
        return 0
    count = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() in working_weekdays:
            count += 1
        cursor += timedelta(days=1)
    return count


def _max_consecutive_overtime(
    rows: Iterable[DailyActivity],
    start: date | None,
    end: date | None,
) -> int:
    if start is None or end is None:
        return 0
    overtime_days = {
        row.day
        for row in rows
        if row.is_working_day and row.overtime_minutes > 0
    }
    longest = 0
    current = 0
    cursor = start
    while cursor <= end:
        if cursor in overtime_days:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
        cursor += timedelta(days=1)
    return longest


def _median_clock(values: list[time]) -> time | None:
    if not values:
        return None
    minutes = sorted(value.hour * 60 + value.minute for value in values)
    middle = median(minutes)
    total = int(round(middle))
    return time((total // 60) % 24, total % 60)


def _format_clock(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "—"
    hours, mins = divmod(max(0, int(minutes)), 60)
    return f"{hours} h {mins:02d}"


def _timezone_note(saw_aware: bool, saw_naive: bool) -> str:
    if saw_aware and saw_naive:
        return (
            "Les horodatages avec fuseau ont été convertis dans le fuseau "
            "local de Windows ; les horodatages sans fuseau ont été conservés "
            "tels quels."
        )
    if saw_aware:
        return (
            "Les horodatages ont été convertis dans le fuseau local de Windows."
        )
    if saw_naive:
        return (
            "Les horodatages du PST ne comportaient pas de fuseau explicite ; "
            "ils ont été interprétés comme des heures locales."
        )
    return "Aucun horodatage d'activité exploitable."


def _render_html(report: RhActivityReport) -> str:
    data = report.to_dict()
    kpi = data["kpi"]
    period = data["observed_period"]

    rows = [
        (
            "% de jours avec activité hors horaires",
            (
                f"{kpi['percent_workdays_out_of_hours']:.2f} % "
                f"({kpi['working_days_out_of_hours']} / "
                f"{kpi['scheduled_workdays']})"
            ),
        ),
        (
            "Jours avec dépassement > 1 h",
            str(kpi["days_overtime_gt_1h"]),
        ),
        (
            "Jours avec dépassement > 2 h",
            str(kpi["days_overtime_gt_2h"]),
        ),
        (
            "Heure médiane de dernière activité",
            kpi["median_last_activity"] or "—",
        ),
        (
            "Heure maximale de dernière activité",
            kpi["latest_last_activity"] or "—",
        ),
        (
            "Maximum de jours consécutifs avec dépassement",
            str(kpi["max_consecutive_overtime_days"]),
        ),
        (
            "Jours de repos / week-end avec activité",
            str(kpi["rest_days_with_activity"]),
        ),
        (
            "Repos apparent minimal",
            _format_duration(kpi["minimum_apparent_rest_minutes"]),
        ),
    ]

    kpi_html = "\n".join(
        f"<tr><td>{escape(label)}</td><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )

    daily_html = "\n".join(
        "<tr>"
        f"<td>{escape(row.day.strftime('%d/%m/%Y'))}</td>"
        f"<td>{'Oui' if row.is_working_day else 'Non'}</td>"
        f"<td>{row.event_count}</td>"
        f"<td>{escape(row.first_activity.strftime('%H:%M'))}</td>"
        f"<td>{escape(row.last_activity.strftime('%H:%M'))}</td>"
        f"<td>{escape(_format_duration(row.overtime_minutes))}</td>"
        f"<td>{escape(_format_duration(row.apparent_rest_minutes))}</td>"
        "</tr>"
        for row in report.daily
    )

    source = escape(str(report.source))
    period_text = (
        f"{period['start'] or '—'} → {period['end'] or '—'}"
    )
    warning = (
        "Ce rapport décrit des traces de messagerie observées dans le PST. "
        "Il ne mesure pas le temps de travail effectif et ne constitue pas, "
        "à lui seul, une évaluation individuelle."
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{escape(REPORT_TEMPLATE_NAME)}</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #222; }}
h1 {{ margin-bottom: 4px; }}
.meta, .note {{ color: #555; }}
.note {{ border-left: 4px solid #888; padding: 10px 14px; background: #f5f5f5; }}
table {{ border-collapse: collapse; width: 100%; margin: 18px 0 28px; }}
th, td {{ border: 1px solid #ccc; padding: 8px 10px; text-align: left; }}
th {{ background: #f0f0f0; }}
td:last-child {{ white-space: nowrap; }}
</style>
</head>
<body>
<h1>{escape(REPORT_TEMPLATE_NAME)}</h1>
<p class="meta">Source : {source}<br>
Période observée : {escape(period_text)}<br>
Horaires théoriques : {report.config.workday_start.strftime('%H:%M')}–{report.config.workday_end.strftime('%H:%M')}<br>
Activité de référence : messages envoyés<br>
{escape(report.timezone_note)}</p>

<p class="note">{escape(warning)}</p>

<h2>8 KPI</h2>
<table>
<thead><tr><th>Indicateur</th><th>Valeur</th></tr></thead>
<tbody>
{kpi_html}
</tbody>
</table>

<h2>Détail journalier des jours avec activité</h2>
<table>
<thead>
<tr>
<th>Date</th><th>Jour travaillé</th><th>Messages envoyés</th>
<th>1re activité</th><th>Dernière activité</th>
<th>Dépassement</th><th>Repos apparent suivant</th>
</tr>
</thead>
<tbody>
{daily_html}
</tbody>
</table>

<h2>Traçabilité</h2>
<p>Dossiers parcourus : {report.scan.folders_seen}<br>
Messages parcourus : {report.scan.messages_seen}<br>
Messages présents dans les dossiers envoyés : {report.scan.sent_messages_seen}<br>
Événements horodatés retenus : {len(report.scan.events)}<br>
Messages envoyés sans date exploitable : {report.scan.undated_sent_messages}<br>
Horodatages de repli utilisés : {report.scan.timestamp_fallbacks}</p>
{_render_warnings(report.scan.warnings)}
</body>
</html>
"""


def _render_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "".join(
        f"<li>{escape(warning)}</li>"
        for warning in warnings
    )
    return f"<h3>Avertissements</h3><ul>{items}</ul>"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
