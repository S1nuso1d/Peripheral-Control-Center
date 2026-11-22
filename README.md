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
- Device inventory with separate HID-interface and Windows PnP views, including devices without battery telemetry.
- Copyable HID inventory report without raw HID paths or serial numbers.
- Full Windows / Bluetooth / HID diagnostics report accessible from the tray menu, including provider outcomes and read errors.
- Windows PnP battery properties, including `System.Devices.BatteryLife` when Windows publishes it.
- Bluetooth LE Battery Service (0x180F) reads of Battery Level (0x2A19), through Bleak; scans only devices advertising that service.
- Standard HID battery readings: Generic Device Controls / Battery Strength (0x06/0x20), Battery System state-of-charge fields (0x85/0x64–0x65), and remaining/full capacity ratio (0x85/0x66–0x67).
- Battery history and an approximate remaining-time estimate based on collected history.
- Separate data providers for the currently implemented sources:
  - **Bluetooth / Windows device properties** — devices for which Windows exposes `DEVPKEY_Bluetooth_Battery` or `System.Devices.BatteryLife`.
  - **Bluetooth LE GATT** — devices that advertise the standard Battery Service and permit a read of Battery Level; requires `bleak`.
  - **Generic HID** — interfaces exposing standard battery usages in input or feature reports; requires `hidapi` and Windows HID parser support.
  - **XInput** — compatible wireless Xbox controllers; the API reports coarse battery levels rather than an exact percentage.
  - **Logitech HID++** — supported Logitech devices using compatible USB receivers; requires `hidapi`.

### Important compatibility note

A device being paired or visible in Windows does **not** guarantee that Windows exposes its battery percentage. The current version does not yet include dedicated ARDOR GAMING, Razer, SteelSeries, Corsair, or other proprietary receiver providers. A 2.4 GHz receiver is not a standard battery interface: each vendor/model may require a documented or reverse-engineered protocol and physical validation. BLE devices that do not advertise Battery Service 0x180F may also need a paired-device GATT lookup or a manufacturer-specific provider.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer (Python 3.12 is used by the build workflow).
- `PySide6` for the desktop interface.
- `hidapi` for Logitech HID++ and standard HID battery report discovery.
- `bleak` for Bluetooth LE GATT Battery Service reads.

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
├── battery_tray.py       # Windows tray app, UI, battery providers
├── device_inventory.py   # Read-only HID enumeration and metadata normalization
├── windows_device_inventory.py # Read-only Windows PnP discovery and normalization
├── device_inventory_dialog.py # HID and Windows PnP inventory UI
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
3. Expand inventory discovery from HID interfaces to relevant Windows PnP and Bluetooth device nodes.
4. Add provider-result diagnostics that connect each discovered interface to the telemetry source that attempted to read it.
5. Implement and physically validate an ARDOR GAMING provider for the user's device models.
6. Add providers for more manufacturers and connection types.
7. Expand monitoring beyond battery level where hardware and public protocols allow it.

See [docs/architecture-and-roadmap.md](docs/architecture-and-roadmap.md) for the proposed provider architecture.

## License

No license has been selected yet. Until a license is added, the repository should be treated as all rights reserved; do not assume others have permission to redistribute or modify the code.
