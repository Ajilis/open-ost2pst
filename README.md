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

## Windows GUI

A standalone Windows x64 GUI is built in CI as the artifact `OpenOST2PST-Windows-x64`.
It lets users select the source OST/PST, choose a destination directory, set the
PST filename, follow a real 0-100% progress bar, and optionally write a JSON
conversion report. The generated PST is automatically reopened and verified.

Local Python launch:

```bash
open-ost2pst-gui
```

Local Windows executable build:

```powershell
python -m pip install -e ".[dev,windows,build-windows]"
.\scripts\windows\build_gui.ps1
```

The resulting executable is `dist\OpenOST2PST.exe`. See
`docs/windows-gui.md` for details.

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

Large variable properties, multi-block HN streams, large Row Matrices, zero-length binary values, and large attachments are supported through LTP subnodes plus XBLOCK/XXBLOCK data trees. Attachments larger than 1 MiB are extracted in 1 MiB chunks into auto-cleaned temporary payloads, then streamed through verification and the XBLOCK writer instead of being concatenated into a single large Python bytes object. XBLOCK/XXBLOCK covers the maximum two-level data-tree indirection defined by MS-PST. Subnode BTrees automatically use SIBLOCK roots when more than 340 local subnodes are present, supporting up to 173,400 subnodes per local tree. RTF bodies are preserved through PidTagRtfCompressed using a standards-compliant literal-only LZFu stream and are hash-verified after libpff reopen.

Production PST construction is disk-streamed: physical PST blocks are written to a temporary `.partial` file in the destination directory as they are produced, and the final HEADER/AMap/NBT/BBT structures are patched in before an atomic rename to the requested `.pst`. The normal conversion path therefore no longer retains the complete PST image (or a second full-size `bytes` copy) in RAM. Memory usage still includes the intermediate mailbox model and BTree metadata, so very large stores still require sensible free RAM/page-file capacity and sufficient destination disk space.

Generated PSTs now include the standard physical minimum hierarchy (Root Folder, IPM subtree, Deleted Items, Search Root, and Spam Search Folder) while the format-neutral mailbox model continues to expose the IPM subtree as its logical root. The writer also emits the Name-to-ID Map and supports real named properties in the 0x8000–0x8FFF range. Property ID 0x8000 is reserved internally as a compatibility sentinel so old libpff releases can parse non-empty NameID streams; user named properties are allocated from 0x8001.

Advanced mail metadata is preserved for message class, Internet Message-ID, transport headers, conversation topic/index, importance, sensitivity, and attachment MIME Content-ID/Content-Location. Embedded-message attachments are emitted as afEmbeddedMessage with a PtypObject reference to a nested message subnode. CI validates this path directly through the libpff C API: libpff_attachment_get_item() resolves the nested message and reads its subject successfully. The pypff Python bindings do not wrap libpff_attachment_get_item(), so source-side extraction of nested embedded-message content through pypff remains a non-fatal reader limitation.

Named properties are now read from the source Name-to-ID map by their portable identity (GUID plus string name or LID), normalized into the mailbox model, and remapped into the destination PST instead of copying store-local 0x8000-0x8FFF IDs. This preserves common Outlook calendar, contact, and task metadata. CI round-trips IPM.Appointment, IPM.Contact, and IPM.Task objects including Unicode strings, PtypTime values, 32-bit integers, booleans, and binary blobs. Examples include appointment location/start time/duration/all-day state/time-zone data, contact address data, and task assignment data. Multi-valued MAPI named-property types remain future work.

Outlook item fidelity now includes native Calendar, Contact, and Task objects:

- Calendar folders use `IPF.Appointment`; Contacts use `IPF.Contact`; Tasks use `IPF.Task`.
- Appointments/meetings use `IPM.Appointment` with PSETID_Appointment start/end, location, duration, all-day, busy status, meeting state, response status, organizer alias, and optional reminders.
- Contacts use `IPM.Contact`, standard name/company/phone properties, and PSETID_Address FileUnder/Email1 properties.
- Tasks use `IPM.Task` with PSETID_Task status, percent complete, start/due/completed dates, complete flag and owner, plus common start/end/reminder properties.
- Folder container classes, selected standard contact properties, and all named properties survive the pypff -> Mailbox -> PST bridge.

Recurring Outlook items are now supported for common Gregorian daily, weekly, monthly/monthly-nth, and yearly patterns, with count-based, date-bounded, or non-ending ranges. Calendar recurrence is emitted as PidLidAppointmentRecur/AppointmentRecurrencePattern with RecurrenceType, Recurring, IsRecurring, ClipStart/ClipEnd and optional deleted occurrences; Task recurrence uses PidLidTaskRecurrence and PidLidTaskFRecurring. Modified appointment exceptions (ExceptionInfo/ExtendedException) remain a future extension.

The meeting transport workflow is also implemented: IPM.Schedule.Meeting.Request, accepted/tentative/declined responses, and IPM.Schedule.Meeting.Canceled share a spec-shaped GlobalObjectId/CleanGlobalObjectId and preserve sequence, start/end, owner appointment ID, meeting type, response status, location and recurrence metadata. The libpff system suite round-trips the recurrence blobs and these meeting objects through the format-neutral mailbox model.

Windows interoperability tooling is included under scripts/windows/ plus a manual Windows Outlook Interop workflow. The normal CI validates the Windows fixture generator and PowerShell syntax on windows-latest. Real SCANPST/classic-Outlook validation requires a dedicated self-hosted Windows runner with classic Outlook installed and a configured Outlook profile. See docs/windows-interop.md.

## Project layout

```text
src/open_ost2pst/
  cli.py
  conversion.py
  gui.py
  binary_payload.py
  model.py
  verification.py
  reader/
    pff_reader.py
  pst/
    bridge.py
    messaging.py
    nameid.py
    outlook_items.py
    recurrence.py
    writer.py
    large_data.py
    rtf.py
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
    build_gui.ps1
docs/
  windows-interop.md
  windows-gui.md
```

## References

- Microsoft MS-PST specification: https://learn.microsoft.com/openspecs/office_file_formats/ms-pst/
- libpff: https://github.com/libyal/libpff

## License

MIT
