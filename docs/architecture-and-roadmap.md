# Architecture and roadmap

## Current implementation

The current application is a Windows/PySide6 system-tray program. Device discovery and battery reads are performed by provider functions registered in `battery_tray.py`:

- `provider_bluetooth()` reads the Windows Bluetooth battery device property.
- `provider_xinput()` reads XInput battery information for compatible controllers.
- `provider_logitech()` delegates to the Logitech HID++ implementation in `hidpp.py`.

`collect_devices()` combines provider results, handles provider exceptions, and deduplicates devices by their display name. The UI and history layer consume normalized dictionaries.

## Proposed provider contract

New providers should be independent modules and should not contain UI code. A provider should expose a predictable entry point, such as `discover()`, returning zero or more device records.

The first compatibility layer can preserve the current dictionary contract:

| Field | Meaning |
|---|---|
| `id` | Stable provider-specific device identifier |
| `name` | Human-readable device name |
| `battery` | Integer battery percentage or the provider's documented coarse level mapping |
| `connected` | Whether the device is currently connected |
| `kind` | Normalized category such as `mouse`, `keyboard`, `headphones`, `gamepad`, or `device` |
| `source` | Provider identifier, for example `bluetooth`, `xinput`, or `ardor` |
| `charging` | Optional charging state; use `None`/absence when unknown |
| `metadata` | Optional diagnostic details, including VID, PID, HID usage page/usage, and transport |

Unknown values must remain unknown. A provider must not invent an exact percentage, charging state, temperature, battery health, or other telemetry when the device/protocol does not expose it.

## Diagnostics

A diagnostics mode should be added before broad vendor support. It should list detected HID interfaces and Bluetooth devices, report the metadata available from Windows, show which provider attempted to read each interface, and preserve error details. This will help distinguish:

1. the device is not visible to Windows;
2. Windows sees it but exposes no battery property;
3. the receiver exposes a HID interface but its protocol is unknown;
4. a provider recognizes the protocol but the read operation fails;
5. a battery value was read successfully.

Raw HID writes should be limited to documented or reverse-engineered commands validated against the exact receiver/model. Read-only operations should be preferred.

## ARDOR GAMING integration plan

ARDOR support is not implemented in this repository yet. The next step is to identify the exact device model and connection mode (Bluetooth, 2.4 GHz receiver, or USB cable), then inspect the receiver's HID descriptors and VID/PID. Protocol-specific code should live in an `ardor` provider and must be validated on the physical device before being marked supported.

## Long-term direction

The platform should remain manufacturer-independent. Vendor integrations belong in providers; the core owns discovery scheduling, normalized device state, history, notifications, settings, and UI. Adding a provider should not require rewriting the UI or the history subsystem.
