# open-ost2pst

Open-source toolkit for inspecting, recovering, and converting Microsoft Outlook OST data into PST.

> **Status:** early but functional end-to-end prototype. The project can read an OST/PST through libpff, normalize it into the mailbox model, and write a Unicode PST that is reopened successfully by libpff in CI.

## Goals

- Read OST files without Microsoft Outlook.
- Preserve folder hierarchy, messages, recipients, dates, bodies, and attachments.
- Support damaged/orphaned OST recovery where `libpff` can expose recoverable items.
- Write Unicode PST files.
- Validate output by reopening the generated PST and comparing source/destination counts and hashes.
- Never modify the source OST.

## Architecture

```text
OST
 |
 v
libpff / pypff (read-only)
 |
 v
Intermediate mailbox model
 |
 v
Unicode PST writer (MS-PST)
 |
 v
output.pst
 |
 +--> structural verification
 +--> libpff reopen test
 +--> Outlook / SCANPST compatibility tests
```

## Development setup

```bash
git clone https://github.com/Ajilis/open-ost2pst.git
cd open-ost2pst

python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
# .venv\Scripts\activate

pip install -e .[dev]
pytest
```

The OST reader expects the Python bindings for libpff to be installed separately and importable as `pypff`.

## CLI

```bash
open-ost2pst inspect mailbox.ost
open-ost2pst convert mailbox.ost mailbox.pst
open-ost2pst convert mailbox.ost mailbox.pst --report mailbox.report.json
open-ost2pst verify mailbox.pst
```

`inspect` and `convert` are implemented. `convert` performs the current read-only libpff extraction → mailbox model → Unicode PST pipeline and can emit a JSON extraction/write report. `verify` is still staged for the dedicated validation milestone.

Large variable properties, multi-block HN streams, large Row Matrices, zero-length binary values, and large attachments are supported through LTP subnodes plus XBLOCK/XXBLOCK data trees. RTF is extracted but not yet emitted. Very large subnode sets that require SIBLOCK and data trees deeper than XXBLOCK remain future work.

## Project layout

```text
src/open_ost2pst/
  cli.py
  model.py
  reader/
    pff_reader.py
  pst/
    bridge.py
    messaging.py
    writer.py
    large_data.py
    ltp/
      heap.py
      bth.py
      pc.py
      tc.py

tests/
```

## References

- Microsoft MS-PST specification: https://learn.microsoft.com/openspecs/office_file_formats/ms-pst/
- libpff: https://github.com/libyal/libpff

## License

MIT
