# Peripheral Control Center

**A Windows desktop application for discovering and monitoring connected PC peripherals.**

Peripheral Control Center brings battery information from supported wireless devices into one place: the Windows system tray, a compact taskbar widget, and a popup with battery history.

> **Project status:** early development. The current codebase is the starting point for a broader, manufacturer-independent peripheral platform. Not every device exposes battery data to Windows, and manufacturer-specific receivers may require dedicated protocol providers.

## Current capabilities

- Windows 10/11 system-tray application with a compact taskbar widget.
- Popup device list with battery history (24 hours, 3 days, and 7 days).
- Low-battery and fully-charged notifications.
- Per-device display names, device categories, visibility, refresh interval, and language settings.
- Russian and English interface strings.
- Battery history and an approximate remaining-time estimate based on collected history.
- Separate data providers for the currently implemented sources:
  - **Bluetooth / Windows device properties** — devices for which Windows exposes the `DEVPKEY_Bluetooth_Battery` property.
  - **XInput** — compatible wireless Xbox controllers; the API reports coarse battery levels rather than an exact percentage.
  - **Logitech HID++** — supported Logitech devices using compatible USB receivers; requires `hidapi`.

### Important compatibility note

A device being paired or visible in Windows does **not** guarantee that Windows exposes its battery percentage. The current version does not yet include a dedicated ARDOR GAMING provider, nor generic Razer, SteelSeries, Corsair, or other vendor-receiver support. These integrations require device-specific protocol research and testing.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer (Python 3.12 is used by the build workflow).
- `PySide6` for the desktop interface.
- `hidapi` for the existing Logitech HID++ provider. It is optional if Logitech receiver support is not needed.

## Run from source

Open PowerShell in the repository directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python battery_tray.py
```

To launch without a console window:

```powershell
.\.venv\Scripts\pythonw.exe .\battery_tray.py
```

The application runs in the background. Look for its icon in the notification area near the clock; Windows may place it under the `^` hidden-icons menu.

## Build a standalone executable

Run on Windows from the repository directory:

```powershell
.\build_exe.bat
```

The executable is written to:

```text
dist\PeripheralControlCenter.exe
```

To create an installer, install **Inno Setup 6** and run:

```powershell
iscc installer.iss
```

The installer is written to `installer_out\PeripheralControlCenter-Setup.exe`.

## Run tests

```powershell
python -m unittest discover -s tests -t . -v
```

The GitHub Actions workflow in `.github/workflows/ci.yml` runs the tests on Windows and builds a standalone executable.

## Project layout

```text
app files (current implementation)
├── battery_tray.py       # Windows tray app, UI, device collection, providers
├── hidpp.py              # Logitech HID++ communication
├── history.py            # Battery history and estimates
├── taskbar.py            # Windows taskbar geometry and mini-widget
├── settings_dialog.py    # Device settings dialog
└── i18n.py               # Russian and English strings

tests/
└── test_app_logic.py     # Logic and UI smoke tests

.github/workflows/
└── ci.yml                # Windows CI and executable build

docs/
└── architecture-and-roadmap.md
```

The current data directory remains `%LOCALAPPDATA%\BatteryTray` for compatibility with settings and history created by the original application. A later migration can move this to a Peripheral Control Center-specific directory without silently losing existing user data.

## Roadmap

1. Stabilize the current Windows application and its test/build workflow.
2. Introduce a documented provider interface and normalized device model.
3. Add diagnostics for detected Bluetooth and HID interfaces (VID/PID, usage page, usage, manufacturer, product, and provider result).
4. Implement and physically validate an ARDOR GAMING provider for the user's device models.
5. Add providers for more manufacturers and connection types.
6. Expand monitoring beyond battery level where hardware and public protocols allow it.

See [docs/architecture-and-roadmap.md](docs/architecture-and-roadmap.md) for the proposed provider architecture.

## License

No license has been selected yet. Until a license is added, the repository should be treated as all rights reserved; do not assume others have permission to redistribute or modify the code.
