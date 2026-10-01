# Windows GUI executable

Open OST2PST includes a native-looking Windows desktop GUI built with Tkinter
and packaged as a standalone x64 executable with PyInstaller.

## Features

The GUI provides:

- OST/PST source file selection;
- destination directory selection;
- configurable PST output filename;
- optional JSON conversion report;
- determinate progress bar from 0 to 100 percent;
- live conversion stage and log;
- persistent end-of-conversion recap with OST/PST folder, message, and attachment counts;
- crash-resilient conversion-state checkpoint beside the destination;
- interrupted-run detection and state-file archiving before restart;
- automatic reopening and verification of the generated PST;
- source-file overwrite protection.

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

The source OST/PST is opened read-only through pypff. The GUI writes only to
the selected destination path and refuses to use the source file itself as the
destination.

Conversion runs on a worker thread so the Windows UI remains responsive.
While a conversion is active, closing the application is blocked to avoid
interrupting a PST write.

## Windows libpff binding

The automated x64 build currently uses the libpff-python-windows 20231205
wheel for CPython 3.13. The resulting pypff extension is bundled into the
frozen executable. See THIRD_PARTY_NOTICES.md for licensing information.
