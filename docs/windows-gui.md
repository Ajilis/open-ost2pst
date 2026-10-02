# Windows GUI executable

Open OST2PST includes a native-looking Windows desktop GUI built with Tkinter
and packaged as a standalone x64 executable with PyInstaller.

## Features

The GUI provides two source-driven workflows:

- **OST selected**: conversion to a new PST, optional JSON conversion report,
  crash-resilient checkpoints, progress, automatic reopen verification, and a
  final before/after item-count recap.
- **PST selected**: read-only report mode. The GUI does not convert, rewrite,
  or replace the selected PST.

The first PST template is **RH — Activité hors horaires**. Its interactive
parameters are:

- theoretical start/end time (default 09:00–18:00);
- working weekdays (default Monday–Friday);
- optional analysis period (`YYYY-MM-DD`);
- activity source fixed to messages in Sent Items / localized sent folders.

The report is produced as HTML plus a JSON sidecar. It contains eight MVP KPI:
percentage of scheduled workdays with out-of-hours sent activity, days with
more than one/two hours after the theoretical end, median/latest last activity,
maximum consecutive overtime days, rest-day/weekend activity, and minimum
apparent rest between the last activity of one active day and the first of the
next.

The PST report scanner is intentionally lightweight: it traverses folders and
message timestamps only and does not extract message bodies or attachment
payloads. It prefers `client_submit_time`, then falls back to `delivery_time`
and `creation_time` when required.

The report is descriptive. Messaging traces are not a measurement of actual
working time and should not be used alone as an employment evaluation.

Microsoft Outlook is not required.

## Progress calculation

The percentage is based on real conversion work:

- 0-5%: source preflight and item counting;
- 5-55%: OST/PST extraction with libpff;
- 55-80%: mapping folders, messages and attachments into the PST model;
- 80-90%: NDB/LTP/Messaging PST construction and file write;
- 90-100%: libpff reopen verification and optional JSON report.

The extraction and mapping ranges advance from processed
folders/messages/attachments, rather than using a cosmetic timer.

## Crash-resilient conversion state

Every conversion maintains a small file beside the requested PST:

    <name>.conversion-state.json

Counters and progress are updated in memory. The state file is written only
when the logical stage changes and approximately once every 60 seconds during
long stages. Periodic checkpoints do not force an fsync; stage boundaries and
terminal states do. This avoids per-message journal writes while still leaving
a recent trace after a power loss, forced process termination, or native crash.

The state records the source and destination, timestamps, current stage and
percentage, extraction/writing/verification counters, caught exception details,
and the current size/path of the destination-side `.partial` PST while it is
being constructed.

Caught Python exceptions are checkpointed immediately with their traceback.
When the GUI sees a prior checkpoint still marked `running`, it displays the
last known stage and timestamp. If the user elects to start over, the previous
state file is archived with an `interrupted-YYYYMMDD-HHMMSS` suffix before the
new run starts.

The optional `*.report.json` remains the final report. It is now written
atomically from the same state model and can contain `success`, `failed`, or
`verification_failed` status information.

## CI artifact

The CI job named windows-exe builds and self-tests the executable on
windows-latest with CPython 3.13.

The uploaded artifact is named:

    OpenOST2PST-Windows-x64

It contains:

    OpenOST2PST.exe
    THIRD_PARTY_NOTICES.md
    SHA256.txt

The self-test runs the frozen EXE itself, imports the bundled pypff extension,
generates a small PST and reopens it with pypff.

## Local build

From PowerShell on 64-bit Windows:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".[dev,windows,build-windows]"
    .\scripts\windows\build_gui.ps1

The executable is created at:

    dist\OpenOST2PST.exe

## Running from Python

For development, the GUI can also be launched without freezing it:

    python -m open_ost2pst.gui

or after installation:

    open-ost2pst-gui

## Runtime behavior

The source OST/PST is opened read-only through pypff.

For OST sources, the GUI writes a new PST to the selected destination and
refuses to use the source file itself as the destination. For PST sources, the
GUI writes only report files (`.html` and `.json`) and never invokes the PST
writer.

Conversion and PST analysis run on worker threads so the Windows UI remains
responsive. While an operation is active, closing the application is blocked
to avoid interrupting a write.

## Windows libpff binding

The automated x64 build currently uses the libpff-python-windows 20231205
wheel for CPython 3.13. The resulting pypff extension is bundled into the
frozen executable. See THIRD_PARTY_NOTICES.md for licensing information.
