# Open OST2PST v0.1.2

Pre-alpha Windows binary release focused on disk-streamed PST construction for large mailboxes.

## Downloads

- **open-ost2pst.exe** — Windows graphical interface.
- **open-ost2pst-cli.exe** — command-line interface.
- **SHA256SUMS.txt** — SHA-256 checksums for both executables.

The executables are self-contained PyInstaller bundles and include the Windows pypff/libpff runtime required by the converter.

## What changed since v0.1.1

- PST physical data blocks can now be written directly to a file sink instead of being retained for the entire build.
- The final PST is no longer assembled as one full-size `bytearray` followed by a second `bytes` copy during normal conversion.
- Large-data XBLOCK/XXBLOCK construction keeps only one XBLOCK-sized BID window in memory on the streamed path.
- BBT metadata is retained for final indexing, while physical block payload bytes are released after they are written.
- Normal conversion and `PstWriter` now use the disk-streaming writer.
- The destination is built as a temporary `.partial` file in the destination directory and atomically renamed when PST construction completes.
- Conversion status now explicitly reports that NDB/LTP/Messaging construction is streaming to disk.

This changes peak-memory behavior substantially for large OST files: memory usage now scales primarily with the mailbox model, metadata/index structures and the largest active per-item structures rather than with the complete generated PST size.

## Included capabilities

- Read-only OST/PST extraction through libpff/pypff.
- Unicode PST writing without Outlook.
- Folders, messages, recipients and attachments.
- Large attachments through temporary payloads plus XBLOCK/XXBLOCK.
- Disk-streamed PST construction for production conversion.
- SLBLOCK/SIBLOCK subnode trees.
- Plain text, HTML and RTF bodies.
- Source/destination verification and SHA-256 attachment checks.
- Standard PST hierarchy and Name-to-ID named-property support.
- Advanced message metadata and embedded-message writing.
- Calendar, contacts and tasks.
- Calendar/task recurrence and meeting request/response/cancellation workflow.
- Windows graphical interface with conversion progress and JSON reporting.

## Validation

The release workflow must pass before assets are published:

- Python 3.10–3.13 CI;
- libpff system tests;
- streamed NDB writer tests;
- bounded large-data streaming tests;
- Windows harness;
- frozen CLI version check;
- bundled pypff import;
- generated PST inspect/convert/verify;
- frozen GUI self-test.

## Status

This remains a **pre-alpha** release. Disk streaming removes the previous requirement to hold the complete PST image in RAM, but it does not make memory usage independent of mailbox metadata or the intermediate mailbox model. Very large or highly fragmented stores should still be tested with adequate free disk space and Windows page-file capacity.

Real classic Outlook/SCANPST interoperability validation remains a separate optional gate and is not claimed by this release.

The executables are **not Authenticode-signed**, so Windows SmartScreen may display a warning on first launch.
