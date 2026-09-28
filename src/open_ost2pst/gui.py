"""Tkinter Windows GUI for Open OST2PST."""

from __future__ import annotations

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


class OpenOst2PstApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.geometry("760x520")
        self.root.minsize(680, 470)

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
        outer.rowconfigure(8, weight=1)

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

        log_frame = ttk.LabelFrame(outer, text="Journal", padding=6)
        log_frame.grid(
            row=8,
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
            row=9,
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

        source = Path(self.source_var.get().strip())
        destination_dir = Path(self.destination_dir_var.get().strip())
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

        if not str(destination_dir):
            messagebox.showerror(
                APP_NAME,
                "Sélectionnez un répertoire de destination.",
            )
            return

        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                APP_NAME,
                f"Impossible de créer le répertoire de destination :\n{exc}",
            )
            return

        destination = destination_dir / output_name
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

        self._set_running(True)
        self.progress_var.set(0)
        self.percent_var.set("0 %")
        self.status_var.set("Démarrage…")
        self._clear_log()
        self._append_log(f"Source      : {source}")
        self._append_log(f"Destination : {destination}")
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
                    destination = payload.destination
                    self.status_var.set("Conversion terminée et vérifiée")
                    self._append_log("Conversion terminée avec succès.")
                    messagebox.showinfo(
                        APP_NAME,
                        "Conversion terminée.\n\n"
                        f"PST : {destination}",
                    )

                elif event == "verification_error":
                    self._set_running(False)
                    exc: ConversionVerificationError = payload
                    self.status_var.set("PST créé, mais vérification échouée")
                    self._append_log(str(exc))
                    messagebox.showwarning(
                        APP_NAME,
                        "Le PST a été créé, mais la vérification automatique "
                        f"a détecté {exc.result.verification.mismatch_count} "
                        "écart(s). Consultez le rapport JSON.",
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
