import json

from open_ost2pst.checkpoint import ConversionJournal


def test_progress_only_writes_on_stage_changes(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_write(path, payload, *, durable=False):
        calls.append((path, payload["stage"], durable))

    monkeypatch.setattr(
        "open_ost2pst.checkpoint.atomic_write_json",
        fake_write,
    )

    journal = ConversionJournal(
        tmp_path / "source.ost",
        tmp_path / "output.pst",
        interval_seconds=0,
    )
    journal.start()

    journal.update_progress(5, "Extraction OST", "1/100")
    journal.update_progress(6, "Extraction OST", "2/100")
    journal.update_progress(7, "Extraction OST", "3/100")
    journal.update_progress(55, "Extraction terminée", "100 messages")
    journal.close()

    assert [stage for _path, stage, _durable in calls] == [
        "Initialisation",
        "Extraction OST",
        "Extraction terminée",
    ]
    assert all(durable for _path, _stage, durable in calls)


def test_checkpoint_tracks_partial_and_destination_sizes(tmp_path) -> None:
    source = tmp_path / "source.ost"
    destination = tmp_path / "output.pst"
    partial = tmp_path / ".output.pst.test.partial"
    partial.write_bytes(b"x" * 1234)

    journal = ConversionJournal(
        source,
        destination,
        interval_seconds=0,
    )
    journal.start()
    journal.set_partial_path(partial)

    snapshot = journal.snapshot()
    assert snapshot["output"]["partial_exists"] is True
    assert snapshot["output"]["partial_bytes"] == 1234
    assert snapshot["output"]["destination_exists"] is False

    destination.write_bytes(b"y" * 4321)
    journal.mark_success()
    snapshot = journal.snapshot()
    journal.close()

    assert snapshot["status"] == "success"
    assert snapshot["output"]["partial_path"] is None
    assert snapshot["output"]["destination_exists"] is True
    assert snapshot["output"]["destination_bytes"] == 4321


def test_atomic_checkpoint_file_contains_failure_details(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    journal = ConversionJournal(
        tmp_path / "source.ost",
        tmp_path / "output.pst",
        state_path=state_path,
        interval_seconds=0,
    )
    journal.start()

    try:
        raise ValueError("broken item")
    except ValueError as exc:
        journal.mark_failed(exc)

    journal.close()

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error"]["type"] == "ValueError"
    assert payload["error"]["message"] == "broken item"
    assert "broken item" in payload["error"]["traceback"]
    assert not state_path.with_name(state_path.name + ".tmp").exists()
