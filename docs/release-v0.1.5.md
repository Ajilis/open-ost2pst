# Open OST2PST v0.1.5

Pre-alpha Windows release adding a persistent end-of-conversion recap in the GUI.

## GUI conversion recap

At the end of a conversion, the main window now displays a summary table with source and reopened-PST counts for:

- folders;
- messages;
- attachments.

Each row shows **Avant (OST)**, **Après (PST)** and the numeric difference. The same recap is also included in the completion/warning dialog and appended to the GUI journal.

The recap is shown both after a successful verification and after a verification failure, so count discrepancies are immediately visible without opening the JSON report.

When verification succeeds and the PST contains exactly one additional folder, the GUI explains that the PST writer creates the mandatory empty top-level `Deleted Items` system folder.

## Existing reliability fixes

- large folder Contents Tables keep complete rows inside NDB blocks;
- large PST construction is streamed to disk;
- low-I/O crash-resilient conversion checkpoints remain enabled;
- verification matches folders by path and messages by stable identity.

## Validation

- Python 3.10–3.13 unit suite;
- GUI recap helper tests;
- libpff interoperability suite;
- Windows harness;
- frozen Windows GUI/CLI build and smoke tests.

## Status

This remains a **pre-alpha** release.

The executables are **not Authenticode-signed**, so Windows SmartScreen may display a warning on first launch.
