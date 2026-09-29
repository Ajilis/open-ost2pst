"""Low-overhead, crash-resilient conversion checkpoint journal."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import traceback as traceback_module
from typing import Any

from open_ost2pst import __version__


DEFAULT_CHECKPOINT_INTERVAL_SECONDS = 60.0
CHECKPOINT_SCHEMA_VERSION = 1


def default_checkpoint_path(destination: str | Path) -> Path:
    """Return the persistent checkpoint path for a destination PST."""

    return Path(destination).with_suffix(".conversion-state.json")


def atomic_write_json(
    path: str | Path,
    payload: dict[str, Any],
    *,
    durable: bool = False,
) -> None:
    """Atomically replace one small JSON file.

    Periodic checkpoints deliberately avoid fsync to keep disk overhead low.
    Important stage transitions and terminal states request durable=True.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        if durable:
            os.fsync(handle.fileno())

    os.replace(temporary, target)


class ConversionJournal:
    """Keep conversion state in RAM and checkpoint it at a low frequency."""

    def __init__(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        state_path: str | Path | None = None,
        report_path: str | Path | None = None,
        interval_seconds: float = DEFAULT_CHECKPOINT_INTERVAL_SECONDS,
    ) -> None:
        self.source = Path(source)
        self.destination = Path(destination)
        self.state_path = (
            Path(state_path)
            if state_path is not None
            else default_checkpoint_path(self.destination)
        )
        self.report_path = Path(report_path) if report_path is not None else None
        self.interval_seconds = float(interval_seconds)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_monotonic = time.monotonic()
        self._partial_path: Path | None = None
        self._reports: dict[str, Any] = {}
        self._last_stage: str | None = None
        self._last_write_error: str | None = None

        started_at = _now_iso()
        self._state: dict[str, Any] = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "app_version": __version__,
            "status": "running",
            "source": str(self.source),
            "destination": str(self.destination),
            "state_file": str(self.state_path),
            "report_file": (
                str(self.report_path) if self.report_path is not None else None
            ),
            "started_at": started_at,
            "last_checkpoint": started_at,
            "elapsed_seconds": 0,
            "percent": 0,
            "stage": "Initialisation",
            "detail": "",
            "inspection": None,
            "extraction": None,
            "writing": None,
            "verification": None,
            "output": {},
            "error": None,
        }

    @property
    def last_write_error(self) -> str | None:
        return self._last_write_error

    def start(self) -> None:
        """Write the initial state and start the periodic checkpoint worker."""

        self.write_checkpoint(durable=True)
        if self.interval_seconds <= 0:
            return
        self._thread = threading.Thread(
            target=self._periodic_loop,
            daemon=True,
            name="ost2pst-checkpoint",
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, min(5.0, self.interval_seconds + 0.5)))
            self._thread = None

    def update_progress(
        self,
        percent: int,
        stage: str,
        detail: str = "",
    ) -> None:
        """Update RAM state; persist only when the logical stage changes."""

        bounded = max(0, min(100, int(percent)))
        with self._lock:
            stage_changed = stage != self._last_stage
            self._state["percent"] = bounded
            self._state["stage"] = stage
            self._state["detail"] = detail
            self._last_stage = stage

        if stage_changed:
            self.write_checkpoint(durable=True)

    def set_inspection(self, report: Any) -> None:
        self._set_report("inspection", report)

    def set_extraction(self, report: Any) -> None:
        self._set_report("extraction", report)

    def set_writing(self, report: Any) -> None:
        self._set_report("writing", report)

    def set_verification(self, report: Any) -> None:
        self._set_report("verification", report)

    def set_partial_path(self, path: str | Path) -> None:
        with self._lock:
            self._partial_path = Path(path)
        # This is an important boundary: construction has created its
        # destination-side partial file. Record it immediately.
        self.write_checkpoint(durable=True)

    def mark_success(self) -> None:
        with self._lock:
            self._state["status"] = "success"
            self._state["percent"] = 100
            self._state["stage"] = "Terminé"
            self._state["detail"] = self.destination.name
            self._state["finished_at"] = _now_iso()
            self._partial_path = None
        self.write_checkpoint(durable=True)

    def mark_verification_failed(self, mismatch_count: int) -> None:
        with self._lock:
            self._state["status"] = "verification_failed"
            self._state["percent"] = 100
            self._state["stage"] = "Vérification échouée"
            self._state["detail"] = f"{mismatch_count} écart(s)"
            self._state["finished_at"] = _now_iso()
            self._partial_path = None
        self.write_checkpoint(durable=True)

    def mark_failed(
        self,
        exc: BaseException,
        *,
        traceback_text: str | None = None,
    ) -> None:
        if traceback_text is None:
            traceback_text = "".join(
                traceback_module.format_exception(
                    type(exc),
                    exc,
                    exc.__traceback__,
                )
            )

        with self._lock:
            self._state["status"] = "failed"
            self._state["finished_at"] = _now_iso()
            self._state["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback_text,
            }
        self.write_checkpoint(durable=True)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-ready snapshot, including current output sizes."""

        with self._lock:
            snapshot = deepcopy(self._state)
            partial_path = self._partial_path
            reports = dict(self._reports)

        for key, report in reports.items():
            value = report.to_dict() if hasattr(report, "to_dict") else report
            snapshot[key] = deepcopy(value)

        snapshot["elapsed_seconds"] = round(
            max(0.0, time.monotonic() - self._started_monotonic),
            3,
        )
        snapshot["last_checkpoint"] = _now_iso()
        snapshot["output"] = self._output_snapshot(partial_path)
        if self._last_write_error is not None:
            snapshot["checkpoint_write_warning"] = self._last_write_error
        return snapshot

    def write_checkpoint(self, *, durable: bool = False) -> None:
        """Best-effort checkpoint write that never aborts the conversion."""

        payload = self.snapshot()
        try:
            atomic_write_json(self.state_path, payload, durable=durable)
        except OSError as exc:
            self._last_write_error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                # Keep in-memory timestamps aligned with what reached disk.
                self._state["last_checkpoint"] = payload["last_checkpoint"]
                self._state["elapsed_seconds"] = payload["elapsed_seconds"]

    def write_final_report(
        self,
        payload: dict[str, Any] | None = None,
        *,
        durable: bool = True,
    ) -> None:
        """Write the requested final report atomically, if one was requested."""

        if self.report_path is None:
            return
        report = self.snapshot() if payload is None else payload
        atomic_write_json(self.report_path, report, durable=durable)

    def _set_report(self, key: str, report: Any) -> None:
        # Keep the live report object in RAM and serialize it only when a
        # checkpoint is actually written. Extraction/writing callbacks can run
        # tens of thousands of times, so this avoids repeated dataclass copies.
        with self._lock:
            self._reports[key] = report

    def _output_snapshot(self, partial_path: Path | None) -> dict[str, Any]:
        output: dict[str, Any] = {
            "partial_path": str(partial_path) if partial_path is not None else None,
            "partial_exists": False,
            "partial_bytes": 0,
            "destination_exists": False,
            "destination_bytes": 0,
        }

        if partial_path is not None:
            try:
                output["partial_bytes"] = partial_path.stat().st_size
                output["partial_exists"] = True
            except OSError:
                pass

        try:
            output["destination_bytes"] = self.destination.stat().st_size
            output["destination_exists"] = True
        except OSError:
            pass

        return output

    def _periodic_loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.write_checkpoint(durable=False)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
