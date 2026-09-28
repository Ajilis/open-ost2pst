# Third-party notices

Open OST2PST can be distributed as a Windows executable containing third-party
components.

## libpff / pypff

The Windows build installs the libpff-python-windows package, which provides
the pypff Python extension used for read-only OST/PST access.

- Upstream project: libyal/libpff
- License: GNU Lesser General Public License v3 or later (LGPL-3.0-or-later)
- Source: https://github.com/libyal/libpff
- Windows wheel used by the build: libpff-python-windows 20231205

The Open OST2PST source code does not copy libpff source code into this
repository. The Windows build downloads the binary wheel as a build dependency.

## PyInstaller

PyInstaller is used only to produce the frozen executable.

- License: GPL-2.0-or-later with the PyInstaller bootloader exception
- Project: https://pyinstaller.org/

See each upstream project for its complete license text and corresponding
source code.
