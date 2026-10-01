"""Tkinter Windows GUI for Open OST2PST."""

from __future__ import annotations

from datetime import datetime
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


class OpenOst2PstApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.geometry("800x650")
        self.root.minsize(700, 560)

        self.source_var = tk.StringVar()
        self.destination_dir_var = tk.StringVar()
        self.output_name_var = tk.StringVar(value="converted.pst")
        self.report_var = tk.BooleanVar(value=True)
        self.progress_var = tk.DoubleVar(value=0)
        self.percent_var = tk.StringVar(value="0 %")
        self.status_var = tk.StringVar(value="Prêt")

        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False

        self._build_ui()
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

        subtitle = ttk.Label(
            outer,
            text="Conversion locale OST → PST Unicode, sans Outlook",
        )
        subtitle.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(0, 18),
        )

        ttk.Label(outer, text="Fichier source OST :").grid(
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

        ttk.Label(outer, text="Répertoire destination :").grid(
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

        ttk.Label(outer, text="Nom du PST :").grid(
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

        self._summary_vars: dict[str, tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = {}
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
            wraplength=720,
        ).grid(
            row=4,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(6, 0),
        )
        self.summary_frame.grid_remove()

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
            height=10,
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
            command=self._start_conversion,
        )
        self.convert_button.pack(side="left", padx=(0, 8))

        self.quit_button = ttk.Button(
            buttons,
            text="Quitter",
            command=self._on_close,
        )
        self.quit_button.pack(side="left")

    def _choose_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="Sélectionner un fichier OST",
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
        self.output_name_var.set(_default_output_name(selected))

        if not self.destination_dir_var.get():
            self.destination_dir_var.set(str(Path(selected).parent))

    def _choose_destination(self) -> None:
        initial = self.destination_dir_var.get() or str(Path.home())
        selected = filedialog.askdirectory(
            title="Sélectionner le répertoire de destination",
            initialdir=initial,
        )
        if selected:
            self.destination_dir_var.set(selected)

    def _start_conversion(self) -> None:
        if self._running:
            return

        source_text = self.source_var.get().strip()
        destination_text = self.destination_dir_var.get().strip()
        source = Path(source_text)
        output_name = _normalized_output_name(self.output_name_var.get())

        if not source.is_file():
            messagebox.showerror(
                APP_NAME,
                "Sélectionnez un fichier OST/PST source valide.",
            )
            return

        if source.suffix.lower() not in (".ost", ".pst"):
            messagebox.showerror(
                APP_NAME,
                "Le fichier source doit avoir l'extension .ost ou .pst.",
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

    def _hide_summary(self) -> None:
        self.summary_frame.grid_remove()
        self.summary_note_var.set("")
        for variables in self._summary_vars.values():
            for variable in variables:
                variable.set("—")

    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "normal"

        for widget in (
            self.source_entry,
            self.destination_entry,
            self.output_entry,
            self.source_button,
            self.destination_button,
            self.report_check,
        ):
            widget.configure(state=state)

        self.convert_button.configure(
            state="disabled" if running else "normal"
        )

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
                "Une conversion est en cours. "
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
