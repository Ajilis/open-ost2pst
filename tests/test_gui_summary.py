from types import SimpleNamespace

from open_ost2pst.gui import _conversion_summary_rows, _format_count


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
