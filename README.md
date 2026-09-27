# open-ost2pst

Open-source toolkit for inspecting, recovering, and converting Microsoft Outlook OST data into PST.

> **Status:** early development. The reader/model layer is being built first; the PST Unicode writer will follow the Microsoft MS-PST specification.

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
open-ost2pst verify mailbox.pst
```

At the current stage, `inspect` is the first implemented path. `convert` and `verify` are intentionally staged as the PST writer and validator are developed.

## Project layout

```text
src/open_ost2pst/
  cli.py
  model.py
  reader/
    pff_reader.py
  pst/
    writer.py

tests/
```

## References

- Microsoft MS-PST specification: https://learn.microsoft.com/openspecs/office_file_formats/ms-pst/
- libpff: https://github.com/libyal/libpff

## License

MIT
