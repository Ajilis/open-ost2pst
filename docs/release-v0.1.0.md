# Open OST2PST v0.1.0

First pre-alpha Windows binary release of Open OST2PST.

## Downloads

- **open-ost2pst.exe** — Windows graphical interface.
- **open-ost2pst-cli.exe** — command-line interface.
- **SHA256SUMS.txt** — SHA-256 checksums for both executables.

The executables are self-contained PyInstaller bundles and include the Windows pypff/libpff runtime required by the converter.

## Included capabilities

- Read-only OST/PST extraction through libpff/pypff.
- Unicode PST writing without Outlook.
- Folders, messages, recipients and attachments.
- Large values and attachments through XBLOCK/XXBLOCK.
- SLBLOCK/SIBLOCK subnode trees.
- Plain text, HTML and RTF bodies.
- Source/destination verification and SHA-256 attachment checks.
- Standard PST hierarchy and Name-to-ID named-property support.
- Advanced message metadata.
- Calendar, contacts and tasks.
- Calendar/task recurrence and meeting request/response/cancellation workflow.
- Windows graphical interface with conversion progress and JSON reporting.

## Validation

The release workflow must pass before assets are published:

- frozen CLI version check;
- bundled pypff import;
- generation of a deterministic PST fixture;
- frozen EXE inspect;
- frozen EXE PST-to-PST conversion;
- frozen EXE source/destination verification;
- frozen GUI self-test opening a generated PST through bundled pypff.

## Status

This is a **pre-alpha** release. Real classic Outlook/SCANPST interoperability validation remains a separate optional gate and is not claimed by this release.

The executables are **not Authenticode-signed**, so Windows SmartScreen may display a warning on first launch.
