# Open OST2PST v0.1.1

Pre-alpha Windows binary release focused on bounded-memory handling for large attachments.

## Downloads

- **open-ost2pst.exe** — Windows graphical interface.
- **open-ost2pst-cli.exe** — command-line interface.
- **SHA256SUMS.txt** — SHA-256 checksums for both executables.

The executables are self-contained PyInstaller bundles and include the Windows pypff/libpff runtime required by the converter.

## What changed since v0.1.0

- Large source attachments are no longer concatenated into one giant Python `bytes` object during extraction.
- Attachments larger than 1 MiB are streamed in 1 MiB chunks into auto-cleaned temporary files.
- Temporary payload size is bounded by the attachment size reported by libpff.
- Streamed attachment payloads flow through the mailbox model, Messaging/LTP layer and XBLOCK/XXBLOCK writer without rematerializing the full attachment.
- Attachment verification computes SHA-256 directly from the streamed payload.
- Conversion and verification paths explicitly close/delete temporary attachment storage.
- Extraction reports now include:
  - `attachments_streamed`
  - `attachment_temp_bytes`

## Included capabilities

- Read-only OST/PST extraction through libpff/pypff.
- Unicode PST writing without Outlook.
- Folders, messages, recipients and attachments.
- Large values and attachments through XBLOCK/XXBLOCK.
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
- bounded temporary-payload tests;
- streamed XBLOCK test;
- Windows harness;
- frozen CLI version check;
- bundled pypff import;
- generated PST inspect/convert/verify;
- frozen GUI self-test.

## Status

This remains a **pre-alpha** release. Real classic Outlook/SCANPST interoperability validation remains a separate optional gate and is not claimed by this release.

The executables are **not Authenticode-signed**, so Windows SmartScreen may display a warning on first launch.
