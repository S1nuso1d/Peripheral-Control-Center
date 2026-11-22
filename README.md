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
- "Found, but battery data unavailable" footer in the popup (connected Bluetooth devices without a Windows battery property, USB/2.4 GHz devices with a vendor-defined HID interface).
- Read-only HID probe (`hid_probe.py`) and profile-driven vendor provider (`vendor_hid.py`, `vendor_profiles.json`) for 2.4 GHz devices.
- Windows PnP battery properties, including `System.Devices.BatteryLife` and `System.Devices.BatteryPlusCharging` when published. Windows' categorical values are shown as approximate bands, not exact percentages.
- Bluetooth LE Battery Service (0x180F) reads of Battery Level (0x2A19) and Battery Level Status (0x2BED), including charging state; can also consume Battery Level Status broadcast in service data without connecting. Scans only devices advertising that service.
- Standard HID battery readings: Generic Device Controls / Battery Strength (0x06/0x20), Battery System state-of-charge fields (0x85/0x64–0x65), and remaining/full capacity ratio (0x85/0x66–0x67).
- Battery history and an approximate remaining-time estimate based on collected history.
- Separate data providers for the currently implemented sources:
  - **Bluetooth / Windows device properties** — devices for which Windows exposes `DEVPKEY_Bluetooth_Battery`, `System.Devices.BatteryLife`, or the categorical `System.Devices.BatteryPlusCharging` property.
  - **Bluetooth LE GATT** — devices that advertise the standard Battery Service and permit a read of Battery Level; requires `bleak`.
  - **Generic HID** — interfaces exposing standard battery usages in input or feature reports; requires `hidapi` and Windows HID parser support.
  - **XInput** — compatible wireless Xbox controllers; the API reports coarse battery levels rather than an exact percentage.
  - **Logitech HID++** — supported Logitech devices using compatible USB receivers; requires `hidapi`.

### 2.4 GHz receivers and other vendor-protocol devices

A 2.4 GHz receiver is not a standard battery interface, so these devices need data, not guesses:

1. **See what is connected.** The popup now lists devices that Windows sees but whose battery could not be read, with the reason ("Windows does not report a battery for this Bluetooth device" or "2.4 GHz/USB: vendor protocol needed (VID:PID)"). An empty battery list no longer looks like "nothing is connected".
2. **Capture the receiver.** Tray menu → *Probe 2.4 GHz device…* (or `python hid_probe.py 25A7:FA7C --battery 87`). The probe is read-only: it requests only feature reports that the device's own HID descriptor declares and listens passively for input reports. It never writes to the device. Enter the battery % shown by the manufacturer's app; bytes matching it are marked. Run it twice at different charge levels.
3. **Describe the device in a profile.** Copy `vendor_profiles.example.json` to `%LOCALAPPDATA%\BatteryTray\vendor_profiles.json` and fill in VID/PID, interface, report ID and the battery byte. Methods: `feature` (GET_FEATURE) and `input` are read-only; `request` sends a command and only runs with `"allow_write": true` — use it only for a documented command. No code change is needed for a new model once its profile is known.

Shipped vendor profiles: none yet — a profile is added only after it has been validated on the physical device.

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
├── ble_battery.py        # Standard Bluetooth LE Battery Service
├── hid_battery.py        # Standard Windows HID battery report parser
├── detected.py           # Connected devices without battery data, and why
├── hid_probe.py          # Read-only HID capture for vendor protocols
├── vendor_hid.py         # Profile-driven provider (vendor_profiles.json)
├── vendor_profiles.example.json
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

1. Validate BLE and standard HID providers against physical devices on Windows 10 and 11.
2. Add paired-device BLE GATT lookup for peripherals that do not advertise the Battery Service UUID.
3. Correlate discovered PnP/HID/BLE interfaces to a single physical-device record without merging unrelated devices.
4. Implement and physically validate vendor providers for the exact models and receivers identified in diagnostics (starting with ARDOR GAMING where present).
5. Add further Logitech, Razer, SteelSeries, Corsair and other protocol adapters when the device protocol is documented or safely verified.
6. Expand telemetry to charging state, battery health, temperature and cycle count only where the device actually exposes those measurements.

See [docs/architecture-and-roadmap.md](docs/architecture-and-roadmap.md) for the proposed provider architecture.

## License

No license has been selected yet. Until a license is added, the repository should be treated as all rights reserved; do not assume others have permission to redistribute or modify the code.
