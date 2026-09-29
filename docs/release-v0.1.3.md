# Open OST2PST v0.1.3

Pre-alpha Windows release focused on crash-resilient conversion tracing with minimal disk I/O.

## Downloads

- **open-ost2pst.exe** — Windows graphical interface.
- **open-ost2pst-cli.exe** — command-line interface.
- **SHA256SUMS.txt** — SHA-256 checksums for both executables.

## What changed since v0.1.2

- Every conversion now maintains a small `*.conversion-state.json` file beside the destination PST.
- Progress counters are updated in RAM and persisted only on stage transitions plus a periodic checkpoint (60 seconds by default).
- Periodic checkpoints avoid forced `fsync`; important stage changes and terminal states use durable atomic replacement.
- The checkpoint records source/destination paths, timestamps, stage, percentage, inspection/extraction/writing/verification state, and current `.partial` PST size.
- Caught Python exceptions are persisted immediately with exception type, message, and traceback.
- The optional final JSON report is written atomically from the same state model and includes `success`, `failed`, or `verification_failed` status.
- The GUI detects an earlier checkpoint still marked `running`, shows its last known stage/time, and archives it before a new run when the user confirms.
- The partial PST path is exposed by the streaming writer so long 80% construction stages can be diagnosed from checkpoint data without per-block logging.

## Disk-I/O design

The checkpoint mechanism deliberately avoids per-message writes. On large stores, tens of thousands of message/attachment progress updates remain memory-only. The journal normally performs only a handful of stage-boundary writes plus about one tiny JSON replacement per minute during long stages.

This keeps journal overhead negligible compared with reading a multi-gigabyte OST and streaming a PST to disk, while still leaving a recent trace if Windows, the process, or a native dependency terminates unexpectedly.

## Validation

- Python 3.10–3.13 unit suite;
- libpff system suite;
- low-I/O checkpoint write-frequency tests;
- persistent success/failure report tests;
- Windows harness and frozen executable smoke tests;
- existing large-data and streamed-PST regression tests.

## Status

This remains a **pre-alpha** release. A checkpoint is diagnostic state, not a resumable conversion snapshot: after an unexpected termination the conversion currently restarts from the beginning. The previous state remains useful for identifying the last completed stage, counters, partial PST growth, warnings, and caught errors.

The executables are **not Authenticode-signed**, so Windows SmartScreen may display a warning on first launch.
