"""Tkinter Windows GUI for Open OST2PST."""

from __future__ import annotations

from datetime import date, datetime, time
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import traceback
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from open_ost2pst import __version__
from open_ost2pst.checkpoint import default_checkpoint_path
from open_ost2pst.conversion import (
    ConversionProgress,
    ConversionVerificationError,
    convert_file,
)
from open_ost2pst.reports.rh_activity import (
    REPORT_TEMPLATE_NAME,
    RhActivityConfig,
    generate_rh_activity_report,
    scan_pst_sent_activity,
    write_rh_activity_report,
)


APP_NAME = "Open OST2PST"


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _default_output_name(source: str) -> str:
    path = Path(source)
    if not path.name:
        return "converted.pst"
    return f"{path.stem}.pst"


def _normalized_output_name(value: str) -> str:
    name = value.strip()
    if not name:
        return "converted.pst"
    if not name.lower().endswith(".pst"):
        name += ".pst"
    return Path(name).name


def _format_count(value: int) -> str:
    """Format an integer with French-style thin grouping."""

    return f"{int(value):,}".replace(",", " ")


def _conversion_summary_rows(result: Any) -> tuple[tuple[str, int, int], ...]:
    """Return source/destination counts shown after conversion."""

    destination_manifest = result.verification.destination_manifest
    return (
        (
            "Dossiers",
            int(result.inspection.folders),
            int(destination_manifest.folder_count),
        ),
        (
            "Messages",
            int(result.inspection.messages),
            int(destination_manifest.message_count),
        ),
        (
            "Pièces jointes",
            int(result.inspection.attachments),
            int(destination_manifest.attachment_count),
        ),
    )


WEEKDAY_LABELS = (
    "Lun",
    "Mar",
    "Mer",
    "Jeu",
    "Ven",
    "Sam",
    "Dim",
)


def _parse_hhmm(value: str) -> time:
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(
            f"heure invalide {value!r} ; format attendu HH:MM"
        ) from exc


def _parse_optional_date(value: str) -> date | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"date invalide {value!r} ; format attendu AAAA-MM-JJ"
        ) from exc


def _format_duration_minutes(value: int | None) -> str:
    if value is None:
        return "—"
    hours, minutes = divmod(max(0, int(value)), 60)
    return f"{hours} h {minutes:02d}"


def _report_kpi_lines(report: Any) -> tuple[str, ...]:
    return (
        (
            "1. Jours avec activité hors horaires : "
            f"{report.percent_workdays_out_of_hours:.2f} % "
            f"({report.working_days_out_of_hours}/"
            f"{report.scheduled_workdays})"
        ),
        f"2. Dépassement > 1 h : {report.days_overtime_gt_1h} jour(s)",
        f"3. Dépassement > 2 h : {report.days_overtime_gt_2h} jour(s)",
        (
            "4. Heure médiane de dernière activité : "
            f"{report.median_last_activity.strftime('%H:%M') if report.median_last_activity else '—'}"
        ),
        (
            "5. Heure maximale de dernière activité : "
            f"{report.latest_last_activity.strftime('%H:%M') if report.latest_last_activity else '—'}"
        ),
        (
            "6. Série maximale de jours avec dépassement : "
            f"{report.max_consecutive_overtime_days}"
        ),
        (
            "7. Jours de repos / week-end avec activité : "
            f"{report.rest_days_with_activity}"
        ),
        (
            "8. Repos apparent minimal : "
            f"{_format_duration_minutes(report.minimum_apparent_rest_minutes)}"
        ),
    )


class OpenOst2PstApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.geometry("860x790")
        self.root.minsize(740, 650)

        self.source_var = tk.StringVar()
        self.destination_dir_var = tk.StringVar()
        self.output_name_var = tk.StringVar(value="converted.pst")
        self.report_var = tk.BooleanVar(value=True)
        self.progress_var = tk.DoubleVar(value=0)
        self.percent_var = tk.StringVar(value="0 %")
        self.status_var = tk.StringVar(value="Prêt")
        self.subtitle_var = tk.StringVar(
            value="Conversion locale OST → PST Unicode, sans Outlook"
        )

        self.report_template_var = tk.StringVar(value=REPORT_TEMPLATE_NAME)
        self.rh_start_var = tk.StringVar(value="09:00")
        self.rh_end_var = tk.StringVar(value="18:00")
        self.rh_period_start_var = tk.StringVar(value="")
        self.rh_period_end_var = tk.StringVar(value="")
        self.rh_weekday_vars = [
            tk.BooleanVar(value=index < 5)
            for index in range(7)
        ]

        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False
        self._mode = "conversion"
        self._last_report_path: Path | None = None

        self._build_ui()
        self.source_var.trace_add(
            "write",
            lambda *_args: self._refresh_source_mode(),
        )
        self._refresh_source_mode()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._pump_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(9, weight=1)

        title = ttk.Label(
            outer,
            text=APP_NAME,
            font=("Segoe UI", 18, "bold"),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(
            outer,
            textvariable=self.subtitle_var,
        ).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(0, 18),
        )

        self.source_label = ttk.Label(
            outer,
            text="Fichier source OST/PST :",
        )
        self.source_label.grid(
            row=2,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=5,
        )
        self.source_entry = ttk.Entry(
            outer,
            textvariable=self.source_var,
        )
        self.source_entry.grid(
            row=2,
            column=1,
            sticky="ew",
            pady=5,
        )
        self.source_button = ttk.Button(
            outer,
            text="Parcourir…",
            command=self._choose_source,
        )
        self.source_button.grid(
            row=2,
            column=2,
            padx=(10, 0),
            pady=5,
        )

        self.destination_label = ttk.Label(
            outer,
            text="Répertoire destination :",
        )
        self.destination_label.grid(
            row=3,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=5,
        )
        self.destination_entry = ttk.Entry(
            outer,
            textvariable=self.destination_dir_var,
        )
        self.destination_entry.grid(
            row=3,
            column=1,
            sticky="ew",
            pady=5,
        )
        self.destination_button = ttk.Button(
            outer,
            text="Parcourir…",
            command=self._choose_destination,
        )
        self.destination_button.grid(
            row=3,
            column=2,
            padx=(10, 0),
            pady=5,
        )

        self.output_label = ttk.Label(outer, text="Nom du PST :")
        self.output_label.grid(
            row=4,
            column=0,
            sticky="w",
            padx=(0, 10),
            pady=5,
        )
        self.output_entry = ttk.Entry(
            outer,
            textvariable=self.output_name_var,
        )
        self.output_entry.grid(
            row=4,
            column=1,
            sticky="ew",
            pady=5,
        )

        self.report_check = ttk.Checkbutton(
            outer,
            text="Créer un rapport JSON de conversion",
            variable=self.report_var,
        )
        self.report_check.grid(
            row=5,
            column=1,
            sticky="w",
            pady=(5, 12),
        )

        self.analysis_frame = ttk.LabelFrame(
            outer,
            text="Analyse PST — modèles de rapport",
            padding=10,
        )
        self.analysis_frame.grid(
            row=4,
            column=0,
            columnspan=3,
            rowspan=2,
            sticky="ew",
            pady=(4, 10),
        )
        self.analysis_frame.columnconfigure(1, weight=1)

        ttk.Label(self.analysis_frame, text="Modèle :").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=3,
        )
        self.report_template_combo = ttk.Combobox(
            self.analysis_frame,
            textvariable=self.report_template_var,
            values=(REPORT_TEMPLATE_NAME,),
            state="readonly",
        )
        self.report_template_combo.grid(
            row=0,
            column=1,
            columnspan=5,
            sticky="ew",
            pady=3,
        )

        ttk.Label(self.analysis_frame, text="Activité :").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=3,
        )
        ttk.Label(
            self.analysis_frame,
            text=(
                "Messages envoyés uniquement "
                "(lecture seule du PST, aucune conversion)"
            ),
        ).grid(
            row=1,
            column=1,
            columnspan=5,
            sticky="w",
            pady=3,
        )

        ttk.Label(self.analysis_frame, text="Horaires :").grid(
            row=2,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=3,
        )
        ttk.Label(self.analysis_frame, text="Début").grid(
            row=2,
            column=1,
            sticky="e",
            padx=(0, 4),
        )
        self.rh_start_entry = ttk.Entry(
            self.analysis_frame,
            textvariable=self.rh_start_var,
            width=8,
        )
        self.rh_start_entry.grid(row=2, column=2, sticky="w")
        ttk.Label(self.analysis_frame, text="Fin").grid(
            row=2,
            column=3,
            sticky="e",
            padx=(16, 4),
        )
        self.rh_end_entry = ttk.Entry(
            self.analysis_frame,
            textvariable=self.rh_end_var,
            width=8,
        )
        self.rh_end_entry.grid(row=2, column=4, sticky="w")
        ttk.Label(
            self.analysis_frame,
            text="(HH:MM)",
        ).grid(row=2, column=5, sticky="w", padx=(6, 0))

        ttk.Label(self.analysis_frame, text="Jours travaillés :").grid(
            row=3,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=3,
        )
        days_frame = ttk.Frame(self.analysis_frame)
        days_frame.grid(
            row=3,
            column=1,
            columnspan=5,
            sticky="w",
            pady=3,
        )
        self.rh_day_checks: list[ttk.Checkbutton] = []
        for index, label in enumerate(WEEKDAY_LABELS):
            check = ttk.Checkbutton(
                days_frame,
                text=label,
                variable=self.rh_weekday_vars[index],
            )
            check.pack(side="left", padx=(0, 8))
            self.rh_day_checks.append(check)

        ttk.Label(self.analysis_frame, text="Période :").grid(
            row=4,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=3,
        )
        ttk.Label(self.analysis_frame, text="Du").grid(
            row=4,
            column=1,
            sticky="e",
            padx=(0, 4),
        )
        self.rh_period_start_entry = ttk.Entry(
            self.analysis_frame,
            textvariable=self.rh_period_start_var,
            width=12,
        )
        self.rh_period_start_entry.grid(row=4, column=2, sticky="w")
        ttk.Label(self.analysis_frame, text="Au").grid(
            row=4,
            column=3,
            sticky="e",
            padx=(16, 4),
        )
        self.rh_period_end_entry = ttk.Entry(
            self.analysis_frame,
            textvariable=self.rh_period_end_var,
            width=12,
        )
        self.rh_period_end_entry.grid(row=4, column=4, sticky="w")
        ttk.Label(
            self.analysis_frame,
            text="(AAAA-MM-JJ, vide = toute la période)",
        ).grid(row=4, column=5, sticky="w", padx=(6, 0))

        ttk.Label(
            self.analysis_frame,
            text=(
                "Les KPI décrivent des traces de messagerie ; ils ne mesurent "
                "pas le temps de travail effectif."
            ),
            wraplength=760,
        ).grid(
            row=5,
            column=0,
            columnspan=6,
            sticky="w",
            pady=(7, 0),
        )

        self._analysis_widgets: list[Any] = [
            self.report_template_combo,
            self.rh_start_entry,
            self.rh_end_entry,
            self.rh_period_start_entry,
            self.rh_period_end_entry,
            *self.rh_day_checks,
        ]
        self.analysis_frame.grid_remove()

        progress_frame = ttk.Frame(outer)
        progress_frame.grid(
            row=6,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(6, 4),
        )
        progress_frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress.grid(row=0, column=0, sticky="ew")

        ttk.Label(
            progress_frame,
            textvariable=self.percent_var,
            width=7,
            anchor="e",
        ).grid(row=0, column=1, padx=(10, 0))

        ttk.Label(
            outer,
            textvariable=self.status_var,
        ).grid(
            row=7,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(2, 8),
        )

        self.summary_frame = ttk.LabelFrame(
            outer,
            text="Récapitulatif final",
            padding=8,
        )
        self.summary_frame.grid(
            row=8,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(2, 10),
        )
        self.summary_frame.columnconfigure(0, weight=1)

        headers = ("Élément", "Avant (OST)", "Après (PST)", "Écart")
        for column, label in enumerate(headers):
            ttk.Label(
                self.summary_frame,
                text=label,
                font=("Segoe UI", 9, "bold"),
                anchor="e" if column else "w",
            ).grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0, 16) if column < 3 else 0,
            )

        self._summary_vars: dict[
            str,
            tuple[tk.StringVar, tk.StringVar, tk.StringVar],
        ] = {}
        for row, label in enumerate(
            ("Dossiers", "Messages", "Pièces jointes"),
            start=1,
        ):
            before_var = tk.StringVar(value="—")
            after_var = tk.StringVar(value="—")
            delta_var = tk.StringVar(value="—")
            self._summary_vars[label] = (
                before_var,
                after_var,
                delta_var,
            )

            ttk.Label(
                self.summary_frame,
                text=label,
                anchor="w",
            ).grid(row=row, column=0, sticky="ew")

            for column, variable in enumerate(
                (before_var, after_var, delta_var),
                start=1,
            ):
                ttk.Label(
                    self.summary_frame,
                    textvariable=variable,
                    anchor="e",
                    width=14,
                ).grid(
                    row=row,
                    column=column,
                    sticky="e",
                    padx=(0, 16) if column < 3 else 0,
                )

        self.summary_note_var = tk.StringVar(value="")
        ttk.Label(
            self.summary_frame,
            textvariable=self.summary_note_var,
            wraplength=760,
        ).grid(
            row=4,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(6, 0),
        )
        self.summary_frame.grid_remove()

        self.report_result_frame = ttk.LabelFrame(
            outer,
            text="Résultat du rapport",
            padding=8,
        )
        self.report_result_frame.grid(
            row=8,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(2, 10),
        )
        self.report_result_var = tk.StringVar(value="")
        ttk.Label(
            self.report_result_frame,
            textvariable=self.report_result_var,
            justify="left",
            wraplength=720,
        ).pack(side="left", fill="x", expand=True)
        self.open_report_button = ttk.Button(
            self.report_result_frame,
            text="Ouvrir le rapport HTML",
            command=self._open_last_report,
        )
        self.open_report_button.pack(side="right", padx=(12, 0))
        self.report_result_frame.grid_remove()

        log_frame = ttk.LabelFrame(outer, text="Journal", padding=6)
        log_frame.grid(
            row=9,
            column=0,
            columnspan=3,
            sticky="nsew",
        )
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log = tk.Text(
            log_frame,
            height=9,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        buttons = ttk.Frame(outer)
        buttons.grid(
            row=10,
            column=0,
            columnspan=3,
            sticky="e",
            pady=(14, 0),
        )

        self.convert_button = ttk.Button(
            buttons,
            text="Convertir",
            command=self._start_primary_action,
        )
        self.convert_button.pack(side="left", padx=(0, 8))

        self.quit_button = ttk.Button(
            buttons,
            text="Quitter",
            command=self._on_close,
        )
        self.quit_button.pack(side="left")

    def _refresh_source_mode(self) -> None:
        source = Path(self.source_var.get().strip())
        is_pst = source.suffix.lower() == ".pst"
        self._mode = "report" if is_pst else "conversion"

        if is_pst:
            self.subtitle_var.set(
                "Analyse locale PST en lecture seule — aucun fichier PST généré"
            )
            self.destination_label.configure(text="Répertoire des rapports :")
            self.output_label.grid_remove()
            self.output_entry.grid_remove()
            self.report_check.grid_remove()
            self.analysis_frame.grid()
            self.convert_button.configure(text="Générer le rapport")
            self._hide_summary()
        else:
            self.subtitle_var.set(
                "Conversion locale OST → PST Unicode, sans Outlook"
            )
            self.destination_label.configure(text="Répertoire destination :")
            self.output_label.grid()
            self.output_entry.grid()
            self.report_check.grid()
            self.analysis_frame.grid_remove()
            self.convert_button.configure(text="Convertir")
            self._hide_report_result()

        if self._running:
            return

        self.source_entry.configure(state="normal")
        self.destination_entry.configure(state="normal")
        self.source_button.configure(state="normal")
        self.destination_button.configure(state="normal")
        self.convert_button.configure(state="normal")

        if is_pst:
            self.output_entry.configure(state="disabled")
            self.report_check.configure(state="disabled")
            self.report_template_combo.configure(state="readonly")
            for widget in self._analysis_widgets:
                if widget is not self.report_template_combo:
                    widget.configure(state="normal")
        else:
            self.output_entry.configure(state="normal")
            self.report_check.configure(state="normal")
            self.report_template_combo.configure(state="disabled")
            for widget in self._analysis_widgets:
                if widget is not self.report_template_combo:
                    widget.configure(state="disabled")

    def _choose_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="Sélectionner un fichier OST ou PST",
            filetypes=[
                ("Fichiers Outlook", "*.ost *.pst"),
                ("Fichiers OST", "*.ost"),
                ("Fichiers PST", "*.pst"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not selected:
            return

        self.source_var.set(selected)
        if Path(selected).suffix.lower() == ".ost":
            self.output_name_var.set(_default_output_name(selected))

        if not self.destination_dir_var.get():
            self.destination_dir_var.set(str(Path(selected).parent))

    def _choose_destination(self) -> None:
        initial = self.destination_dir_var.get() or str(Path.home())
        title = (
            "Sélectionner le répertoire des rapports"
            if self._mode == "report"
            else "Sélectionner le répertoire de destination"
        )
        selected = filedialog.askdirectory(
            title=title,
            initialdir=initial,
        )
        if selected:
            self.destination_dir_var.set(selected)

    def _start_primary_action(self) -> None:
        if self._running:
            return
        source = Path(self.source_var.get().strip())
        if source.suffix.lower() == ".pst":
            self._start_pst_report()
        else:
            self._start_conversion()

    def _start_conversion(self) -> None:
        source_text = self.source_var.get().strip()
        destination_text = self.destination_dir_var.get().strip()
        source = Path(source_text)
        output_name = _normalized_output_name(self.output_name_var.get())

        if not source.is_file():
            messagebox.showerror(
                APP_NAME,
                "Sélectionnez un fichier OST source valide.",
            )
            return

        if source.suffix.lower() != ".ost":
            messagebox.showerror(
                APP_NAME,
                "La conversion de l'interface accepte uniquement une source "
                "OST. Pour un PST, utilisez le mode Rapports.",
            )
            return

        if not destination_text:
            messagebox.showerror(
                APP_NAME,
                "Sélectionnez un répertoire de destination.",
            )
            return

        destination_dir = Path(destination_text)

        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                APP_NAME,
                f"Impossible de créer le répertoire de destination :\n{exc}",
            )
            return

        destination = destination_dir / output_name
        if source.resolve() == destination.resolve():
            messagebox.showerror(
                APP_NAME,
                "Le fichier PST de destination doit être différent du fichier source.",
            )
            return

        report_path = (
            destination.with_suffix(".report.json")
            if self.report_var.get()
            else None
        )

        if destination.exists():
            overwrite = messagebox.askyesno(
                APP_NAME,
                f"Le fichier existe déjà :\n{destination}\n\nLe remplacer ?",
            )
            if not overwrite:
                return

        checkpoint_path = default_checkpoint_path(destination)
        if checkpoint_path.is_file():
            try:
                previous_state = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                previous_state = None

            if (
                isinstance(previous_state, dict)
                and previous_state.get("status") == "running"
            ):
                stage = previous_state.get("stage") or "inconnue"
                percent = previous_state.get("percent")
                checkpoint_time = (
                    previous_state.get("last_checkpoint") or "inconnu"
                )
                answer = messagebox.askyesno(
                    APP_NAME,
                    "Une conversion précédente semble avoir été interrompue "
                    "ou est peut-être encore active.\n\n"
                    f"Étape : {stage}\n"
                    f"Progression : {percent} %\n"
                    f"Dernier checkpoint : {checkpoint_time}\n\n"
                    "Démarrer une nouvelle conversion ? "
                    "L'ancien état sera archivé.",
                )
                if not answer:
                    return

                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                archived = checkpoint_path.with_name(
                    f"{checkpoint_path.stem}.interrupted-{timestamp}"
                    f"{checkpoint_path.suffix}"
                )
                try:
                    checkpoint_path.replace(archived)
                except OSError as exc:
                    messagebox.showerror(
                        APP_NAME,
                        "Impossible d'archiver l'état de la conversion "
                        f"précédente :\n{exc}",
                    )
                    return

        self._set_running(True)
        self.progress_var.set(0)
        self.percent_var.set("0 %")
        self.status_var.set("Démarrage…")
        self._clear_log()
        self._hide_summary()
        self._hide_report_result()
        self._append_log(f"Source      : {source}")
        self._append_log(f"Destination : {destination}")
        self._append_log(
            f"État        : {default_checkpoint_path(destination)}"
        )
        if report_path is not None:
            self._append_log(f"Rapport     : {report_path}")

        self._worker = threading.Thread(
            target=self._conversion_worker,
            args=(source, destination, report_path),
            daemon=True,
            name="ost2pst-converter",
        )
        self._worker.start()

    def _conversion_worker(
        self,
        source: Path,
        destination: Path,
        report_path: Path | None,
    ) -> None:
        def progress(update: ConversionProgress) -> None:
            self._events.put(("progress", update))

        try:
            result = convert_file(
                source,
                destination,
                report_path=report_path,
                overwrite=True,
                progress_callback=progress,
            )
            self._events.put(("success", result))
        except ConversionVerificationError as exc:
            self._events.put(("verification_error", exc))
        except Exception as exc:
            self._events.put(
                (
                    "error",
                    (
                        exc,
                        traceback.format_exc(),
                    ),
                )
            )

    def _start_pst_report(self) -> None:
        source = Path(self.source_var.get().strip())
        destination_text = self.destination_dir_var.get().strip()

        if not source.is_file() or source.suffix.lower() != ".pst":
            messagebox.showerror(
                APP_NAME,
                "Sélectionnez un fichier PST valide.",
            )
            return
        if not destination_text:
            messagebox.showerror(
                APP_NAME,
                "Sélectionnez un répertoire pour les rapports.",
            )
            return
        if self.report_template_var.get() != REPORT_TEMPLATE_NAME:
            messagebox.showerror(APP_NAME, "Modèle de rapport non pris en charge.")
            return

        try:
            config = RhActivityConfig(
                workday_start=_parse_hhmm(self.rh_start_var.get()),
                workday_end=_parse_hhmm(self.rh_end_var.get()),
                working_weekdays=frozenset(
                    index
                    for index, variable in enumerate(self.rh_weekday_vars)
                    if variable.get()
                ),
                period_start=_parse_optional_date(
                    self.rh_period_start_var.get()
                ),
                period_end=_parse_optional_date(
                    self.rh_period_end_var.get()
                ),
            )
        except ValueError as exc:
            messagebox.showerror(APP_NAME, f"Paramètres invalides :\n{exc}")
            return

        output_dir = Path(destination_text)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                APP_NAME,
                f"Impossible de créer le répertoire des rapports :\n{exc}",
            )
            return

        html_path = (
            output_dir
            / f"{source.stem}.rh-activite-hors-horaires.html"
        )
        json_path = html_path.with_suffix(".json")
        if html_path.exists() or json_path.exists():
            overwrite = messagebox.askyesno(
                APP_NAME,
                "Le rapport existe déjà.\n\n"
                f"{html_path}\n\nLe remplacer ?",
            )
            if not overwrite:
                return

        self._set_running(True)
        self.progress_var.set(0)
        self.percent_var.set("0 %")
        self.status_var.set("Analyse PST — démarrage")
        self._clear_log()
        self._hide_summary()
        self._hide_report_result()
        self._append_log(f"PST source   : {source}")
        self._append_log(f"Modèle       : {REPORT_TEMPLATE_NAME}")
        self._append_log(
            "Horaires     : "
            f"{config.workday_start.strftime('%H:%M')}–"
            f"{config.workday_end.strftime('%H:%M')}"
        )
        self._append_log(f"Rapport HTML : {html_path}")
        self._append_log(f"Rapport JSON : {json_path}")

        self._worker = threading.Thread(
            target=self._pst_report_worker,
            args=(source, html_path, json_path, config),
            daemon=True,
            name="pst-report-analyzer",
        )
        self._worker.start()

    def _pst_report_worker(
        self,
        source: Path,
        html_path: Path,
        json_path: Path,
        config: RhActivityConfig,
    ) -> None:
        def scan_progress(percent: int, detail: str) -> None:
            self._events.put(
                (
                    "progress",
                    ConversionProgress(
                        percent=max(0, min(95, int(percent))),
                        stage="Analyse PST",
                        detail=detail,
                    ),
                )
            )

        try:
            self._events.put(
                (
                    "progress",
                    ConversionProgress(
                        percent=2,
                        stage="Analyse PST",
                        detail="Lecture des dossiers d'éléments envoyés",
                    ),
                )
            )
            scan = scan_pst_sent_activity(
                source,
                progress_callback=scan_progress,
            )
            self._events.put(
                (
                    "progress",
                    ConversionProgress(
                        percent=96,
                        stage="Calcul des KPI",
                        detail=f"{len(scan.events)} activités horodatées",
                    ),
                )
            )
            report = generate_rh_activity_report(scan, config)
            self._events.put(
                (
                    "progress",
                    ConversionProgress(
                        percent=98,
                        stage="Écriture du rapport",
                        detail=html_path.name,
                    ),
                )
            )
            written_html, written_json = write_rh_activity_report(
                report,
                html_path,
                json_path=json_path,
            )
            self._events.put(
                (
                    "report_success",
                    (report, written_html, written_json),
                )
            )
        except Exception as exc:
            self._events.put(
                (
                    "report_error",
                    (
                        exc,
                        traceback.format_exc(),
                    ),
                )
            )

    def _pump_events(self) -> None:
        try:
            while True:
                event, payload = self._events.get_nowait()

                if event == "progress":
                    update: ConversionProgress = payload
                    self.progress_var.set(update.percent)
                    self.percent_var.set(f"{update.percent} %")
                    status = update.stage
                    if update.detail:
                        status += f" — {update.detail}"
                    self.status_var.set(status)
                    self._append_log(status)

                elif event == "success":
                    self._set_running(False)
                    result = payload
                    destination = result.destination
                    self.status_var.set("Conversion terminée et vérifiée")
                    self._append_log("Conversion terminée avec succès.")
                    summary_text = self._show_summary(result)
                    messagebox.showinfo(
                        APP_NAME,
                        "Conversion terminée et vérifiée.\n\n"
                        f"{summary_text}\n\n"
                        f"PST : {destination}",
                    )

                elif event == "verification_error":
                    self._set_running(False)
                    exc: ConversionVerificationError = payload
                    self.status_var.set("PST créé, mais vérification échouée")
                    self._append_log(str(exc))
                    summary_text = self._show_summary(exc.result)
                    messagebox.showwarning(
                        APP_NAME,
                        "Le PST a été créé, mais la vérification automatique "
                        f"a détecté {exc.result.verification.mismatch_count} "
                        "écart(s).\n\n"
                        f"{summary_text}\n\n"
                        "Consultez le rapport JSON.",
                    )

                elif event == "report_success":
                    self._set_running(False)
                    report, html_path, json_path = payload
                    self.progress_var.set(100)
                    self.percent_var.set("100 %")
                    self.status_var.set("Rapport PST généré")
                    self._show_report_result(
                        report,
                        html_path,
                        json_path,
                    )
                    messagebox.showinfo(
                        APP_NAME,
                        "Rapport généré sans modification du PST.\n\n"
                        f"HTML : {html_path}\n"
                        f"JSON : {json_path}",
                    )

                elif event == "report_error":
                    self._set_running(False)
                    exc, trace = payload
                    self.status_var.set("Échec de l'analyse PST")
                    self._append_log(f"ERREUR : {exc}")
                    self._append_log(trace)
                    messagebox.showerror(
                        APP_NAME,
                        f"L'analyse du PST a échoué :\n\n{exc}",
                    )

                elif event == "error":
                    self._set_running(False)
                    exc, trace = payload
                    self.status_var.set("Échec de la conversion")
                    self._append_log(f"ERREUR : {exc}")
                    self._append_log(trace)
                    messagebox.showerror(
                        APP_NAME,
                        f"La conversion a échoué :\n\n{exc}",
                    )

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._pump_events)

    def _show_summary(self, result: Any) -> str:
        self._hide_report_result()
        rows = _conversion_summary_rows(result)
        log_lines = ["Récapitulatif final :"]
        dialog_lines = []

        for label, before, after in rows:
            delta = after - before
            before_text = _format_count(before)
            after_text = _format_count(after)
            delta_text = (
                "0"
                if delta == 0
                else f"{delta:+,}".replace(",", " ")
            )

            before_var, after_var, delta_var = self._summary_vars[label]
            before_var.set(before_text)
            after_var.set(after_text)
            delta_var.set(delta_text)

            log_lines.append(
                f"  {label:<16} {before_text:>10} -> {after_text:>10} "
                f"(écart {delta_text})"
            )
            dialog_lines.append(
                f"{label} : {before_text} → {after_text} "
                f"(écart {delta_text})"
            )

        folder_before = rows[0][1]
        folder_after = rows[0][2]
        if (
            result.verification.ok
            and folder_after == folder_before + 1
        ):
            note = (
                "Note : le PST contient un dossier système supplémentaire "
                "créé par le format PST (Deleted Items)."
            )
        elif result.verification.ok:
            note = "Les données vérifiées correspondent à la source."
        else:
            note = (
                "La vérification a détecté des écarts ; consultez le rapport "
                "JSON pour le détail."
            )

        self.summary_note_var.set(note)
        self.summary_frame.grid()

        for line in log_lines:
            self._append_log(line)
        self._append_log(note)

        return "\n".join(dialog_lines)

    def _show_report_result(
        self,
        report: Any,
        html_path: Path,
        json_path: Path,
    ) -> None:
        self._hide_summary()
        self._last_report_path = html_path
        lines = _report_kpi_lines(report)
        self.report_result_var.set(
            "\n".join(lines)
            + "\n\n"
            + f"HTML : {html_path}\nJSON : {json_path}"
        )
        self.report_result_frame.grid()
        self._append_log("Rapport PST terminé :")
        for line in lines:
            self._append_log(f"  {line}")
        self._append_log(f"HTML : {html_path}")
        self._append_log(f"JSON : {json_path}")

    def _hide_summary(self) -> None:
        self.summary_frame.grid_remove()
        self.summary_note_var.set("")
        for variables in self._summary_vars.values():
            for variable in variables:
                variable.set("—")

    def _hide_report_result(self) -> None:
        self.report_result_frame.grid_remove()
        self.report_result_var.set("")
        self._last_report_path = None

    def _open_last_report(self) -> None:
        path = self._last_report_path
        if path is None or not path.is_file():
            messagebox.showerror(APP_NAME, "Le rapport HTML est introuvable.")
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))
            else:
                import webbrowser

                webbrowser.open(path.resolve().as_uri())
        except Exception as exc:
            messagebox.showerror(
                APP_NAME,
                f"Impossible d'ouvrir le rapport :\n{exc}",
            )

    def _set_running(self, running: bool) -> None:
        self._running = running
        common_state = "disabled" if running else "normal"

        for widget in (
            self.source_entry,
            self.destination_entry,
            self.source_button,
            self.destination_button,
        ):
            widget.configure(state=common_state)

        if running:
            self.output_entry.configure(state="disabled")
            self.report_check.configure(state="disabled")
            self.report_template_combo.configure(state="disabled")
            for widget in self._analysis_widgets:
                if widget is not self.report_template_combo:
                    widget.configure(state="disabled")
            self.convert_button.configure(state="disabled")
        else:
            self._refresh_source_mode()

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + os.linesep)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        if self._running:
            messagebox.showinfo(
                APP_NAME,
                "Une opération est en cours. "
                "Attendez sa fin avant de fermer l'application.",
            )
            return
        self.root.destroy()


def self_test() -> int:
    """Validate the frozen executable and bundled pypff extension."""

    try:
        import pypff  # type: ignore

        from open_ost2pst.pst.messaging import MessagingBuilder

        builder = MessagingBuilder()
        inbox = builder.add_folder(builder.root, "Inbox")
        builder.add_message(
            inbox,
            subject="Windows executable self-test",
            body="pypff bundle test",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "self-test.pst"
            path.write_bytes(builder.build().data)

            store = pypff.file()
            try:
                store.open(str(path))
                root = store.get_root_folder()
                if root is None:
                    return 3
            finally:
                try:
                    store.close()
                except Exception:
                    pass
        return 0
    except Exception:
        return 2


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()

    _enable_windows_dpi_awareness()
    root = tk.Tk()
    OpenOst2PstApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
