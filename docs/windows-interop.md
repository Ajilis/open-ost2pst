# Windows Outlook / SCANPST interoperability validation

This repository includes a dedicated Windows validation harness for the generated PST writer.

## Why this needs a self-hosted runner

The regular GitHub-hosted Windows images are useful for syntax and fixture-generation checks, but the interoperability test requires **classic Outlook for Windows** and its SCANPST.EXE installation.

The workflow therefore uses a self-hosted runner with these labels:

~~~text
self-hosted
Windows
X64
outlook
~~~

Use a dedicated Windows VM or machine for this runner.

## Runner prerequisites

Install and configure:

1. Windows x64.
2. Classic Outlook for Windows (Microsoft 365 Apps / Outlook 2016 or later).
3. SCANPST.EXE from the Outlook installation.
4. Python 3.13, or allow actions/setup-python to install it.
5. A default Outlook profile for the Windows user that runs the runner.
6. The GitHub Actions self-hosted runner registered with the outlook label.

### Important: do not run the runner as a Windows service

The Outlook Object Model is COM-based, requires an STA thread, and is not supported from Windows service applications.

Run the GitHub runner **interactively inside the logged-in desktop session** of the dedicated test user.

The workflow explicitly launches the Outlook validator through:

~~~powershell
powershell.exe -STA
~~~

The **new Outlook for Windows is not sufficient** for this validation. The harness uses classic Outlook COM automation (Outlook.Application).

## What the workflow validates

Trigger:

~~~text
Actions -> Windows Outlook Interop -> Run workflow
~~~

The workflow first generates a deterministic Unicode PST containing:

- Unicode folder and message names;
- nested folders;
- recipients;
- a large message body;
- a 150 KB attachment;
- a message with 341 attachments, forcing SIBLOCK use.

It then runs two independent validators.

### SCANPST

scripts/windows/validate_scanpst.ps1:

- finds SCANPST.EXE;
- copies the generated PST to a temporary directory;
- runs SCANPST silently and automatically;
- records the process exit code and SCANPST log;
- compares SHA-256 before/after;
- fails if SCANPST changed the copy or created a repair backup.

The repository artifact is never modified.

### Classic Outlook

scripts/windows/validate_outlook.ps1:

- copies the generated PST;
- starts Outlook.Application;
- mounts the existing PST with NameSpace.AddStoreEx(..., olStoreUnicode);
- locates the corresponding Store;
- calls Store.GetRootFolder();
- recursively enumerates folders and items;
- counts attachments;
- checks expected Unicode subjects and folder names;
- removes the PST from the current profile with NameSpace.RemoveStore;
- writes a JSON report.

The validation copy is isolated in a temporary directory.

## Reports

The workflow uploads the windows-outlook-interop artifact containing:

~~~text
windows-interop.pst
windows-interop.expected.json
scanpst.report.json
outlook.report.json
~~~

A successful run is the project gate for claiming real classic-Outlook interoperability.

## Local execution

Generate the fixture:

~~~powershell
python scripts/generate_windows_interop_fixture.py --output artifacts/windows-interop.pst --manifest artifacts/windows-interop.expected.json
~~~

Run SCANPST validation:

~~~powershell
./scripts/windows/validate_scanpst.ps1 -PstPath artifacts/windows-interop.pst -ReportPath artifacts/scanpst.report.json
~~~

Run classic Outlook validation from an STA process:

~~~powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File scripts/windows/validate_outlook.ps1 -PstPath artifacts/windows-interop.pst -ExpectedManifest artifacts/windows-interop.expected.json -ReportPath artifacts/outlook.report.json
~~~
