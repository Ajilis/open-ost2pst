"""Read-only OST/PST inspection through libpff's Python bindings."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class PffUnavailableError(RuntimeError):
    """Raised when the pypff bindings are not available."""


@dataclass(slots=True)
class InspectionStats:
    path: str
    folders: int = 0
    messages: int = 0
    attachments: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_pypff() -> Any:
    try:
        import pypff  # type: ignore
    except ImportError as exc:
        raise PffUnavailableError(
            "pypff is required for OST/PST inspection. "
            "Install libpff and its Python bindings, then retry."
        ) from exc
    return pypff


def _int_attr(obj: Any, name: str) -> int:
    value = getattr(obj, name, 0)
    if callable(value):
        value = value()
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _walk_folder(folder: Any, stats: InspectionStats) -> None:
    stats.folders += 1

    message_count = _int_attr(folder, "number_of_sub_messages")
    stats.messages += message_count

    for index in range(message_count):
        try:
            message = folder.get_sub_message(index)
            stats.attachments += _int_attr(message, "number_of_attachments")
        except Exception:
            # Inspection is deliberately best-effort so one damaged item does
            # not make the whole OST unreadable.
            continue

    child_count = _int_attr(folder, "number_of_sub_folders")
    for index in range(child_count):
        try:
            child = folder.get_sub_folder(index)
        except Exception:
            continue
        _walk_folder(child, stats)


def inspect_store(path: str | Path) -> InspectionStats:
    """Inspect an OST/PST without modifying it.

    Returns aggregate folder/message/attachment counts. Damaged individual
    items are skipped where libpff can continue traversing the store.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    pypff = _load_pypff()
    store = pypff.file()

    stats = InspectionStats(path=str(source))

    try:
        store.open(str(source))
        root = store.get_root_folder()
        _walk_folder(root, stats)
    finally:
        try:
            store.close()
        except Exception:
            pass

    return stats
