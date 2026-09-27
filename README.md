# open-ost2pst

Open-source toolkit for inspecting, recovering, and converting Microsoft Outlook OST data into PST.

> **Status:** early but functional end-to-end prototype. The project can read an OST/PST through libpff, normalize it into the mailbox model, and write a Unicode PST that is reopened successfully by libpff in CI.

## Goals

- Read OST files without Microsoft Outlook.
- Preserve folder hierarchy, messages, recipients, dates, bodies, and attachments.
- Support damaged/orphaned OST recovery where `libpff` can expose recoverable items.
- Write Unicode PST files.
- Validate output by reopening the generated PST and comparing source/destination counts and hashes.
- Validate generated PSTs with SCANPST and classic Outlook on a dedicated Windows runner.
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
open-ost2pst verify mailbox.pst --source mailbox.ost
open-ost2pst verify mailbox.pst --source mailbox.ost --report verify.json
```

`inspect`, `convert`, and `verify` are implemented. `convert` performs the read-only libpff extraction → mailbox model → Unicode PST pipeline, then automatically reopens and verifies the generated PST. With `--report`, the JSON report includes extraction, writing, and automatic verification results.

`verify` can validate a PST on its own or compare it against a source OST/PST. Source/destination comparison checks folder hierarchy and counts, message order/subjects/dates/read state, attachment counts/sizes, and SHA-256 hashes of attachment bytes. Verification exits non-zero when libpff extraction fails or mismatches are detected.

Large variable properties, multi-block HN streams, large Row Matrices, zero-length binary values, and large attachments are supported through LTP subnodes plus XBLOCK/XXBLOCK data trees. Subnode BTrees automatically use SIBLOCK roots when more than 340 local subnodes are present, supporting up to 173,400 subnodes per local tree. RTF is extracted but not yet emitted. Data trees deeper than XXBLOCK remain future work.

Windows interoperability tooling is included under scripts/windows/ plus a manual Windows Outlook Interop workflow. The normal CI validates the Windows fixture generator and PowerShell syntax on windows-latest. Real SCANPST/classic-Outlook validation requires a dedicated self-hosted Windows runner with classic Outlook installed and a configured Outlook profile. See docs/windows-interop.md.

## Project layout

```text
src/open_ost2pst/
  cli.py
  model.py
  verification.py
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
scripts/
  generate_windows_interop_fixture.py
  windows/
    validate_scanpst.ps1
    validate_outlook.ps1
docs/
  windows-interop.md
```

## References

- Microsoft MS-PST specification: https://learn.microsoft.com/openspecs/office_file_formats/ms-pst/
- libpff: https://github.com/libyal/libpff

## License

MIT
