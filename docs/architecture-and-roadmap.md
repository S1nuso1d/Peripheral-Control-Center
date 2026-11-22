# Architecture and roadmap

## Current implementation

The current application is a Windows/PySide6 system-tray program. Device discovery and battery reads are performed by provider functions registered in `battery_tray.py`:

- `provider_bluetooth()` reads Windows Bluetooth battery properties.
- `provider_ble_battery()` delegates to `ble_battery.py`, which reads the standard BLE Battery Service (0x180F) / Battery Level (0x2A19) with Bleak.
- `provider_hid_battery()` delegates to `hid_battery.py`, which parses standard HID Battery Strength and Battery System input/feature reports using Windows HidP APIs.
- `provider_xinput()` reads XInput battery information for compatible controllers.
- `provider_logitech()` delegates to the Logitech HID++ implementation in `hidpp.py`.

The BLE provider intentionally scans only for advertisements containing the Battery Service UUID before connecting. The generic HID provider only reads report usages explicitly declared by the descriptor; it does not send output reports or SET_FEATURE commands.

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


## Implemented: HID inventory (0.2.0 foundation)

The tray menu now exposes a read-only HID inventory window. It lists every interface returned by hid.enumerate(0, 0), including vendor-defined interfaces that are not yet supported by a battery provider. The inventory reports VID/PID, manufacturer, product, interface number, usage page, usage, and transport when hidapi can identify it.

The discovery layer deliberately does not expose raw HID paths or serial numbers. It derives a short SHA-256 fingerprint from the path for stable per-interface identifiers. A vendor-defined usage page is only a protocol-research hint; it is not evidence that the device exposes battery telemetry.

The full diagnostic report is also available from the tray menu. It combines Windows PnP, Bluetooth battery-property, HID interface, and XInput observations. This makes it possible to tell whether Windows sees a device even when no supported battery provider can read it.

### Provider diagnostics

Windows PnP inventory checks the generic `System.Devices.BatteryLife` property when available, then falls back to `DEVPKEY_Bluetooth_Battery`. The provider diagnostics distinguish missing dependencies, no advertised BLE Battery Service, failed GATT reads, missing standard HID usages, and successful readings.

The BLE provider cannot discover a Battery Service that a peripheral does not advertise. The HID provider can only decode standard usages exposed in readable input/feature reports. Proprietary 2.4 GHz receivers, and devices exposing custom vendor pages, still require an exact VID/PID/model-specific provider. Vendor report writes and undocumented commands remain disabled until validated against the exact physical model and receiver.


## Implemented: Windows PnP inventory

The inventory window now has two views:

- HID interfaces — interfaces returned by hidapi, including vendor-defined usage pages.
- Windows devices — relevant present PnP nodes returned by the Windows PnP cmdlets, including USB, HID, Bluetooth and audio endpoint classes.

The Windows PnP normalizer exposes friendly name, manufacturer, device class, status, transport, VID/PID when present, and the battery value and source when Windows reports `System.Devices.BatteryLife` or `DEVPKEY_Bluetooth_Battery`. Raw PnP instance IDs and complete hardware-ID strings are never returned from the normalizer; a short SHA-256 fingerprint is used for stable identifiers.

A single physical device can create several PnP nodes (for example a parent, receiver and HID child). The inventory is intentionally a diagnostic view, not yet a deduplicated user-facing device list. The next step is correlating parent/child nodes and linking them to battery-provider results without merging distinct devices that happen to share a VID/PID.


## Implemented: conservative HID ↔ PnP correlation

The inventory now displays a candidate count for each HID interface. Candidates require an exact VID/PID match and a compatible or unknown transport. Multiple PnP nodes are preserved and listed individually in the copied report.

This is intentionally not physical-device deduplication: VID/PID can be shared by parent, receiver and child nodes, and no candidate is automatically merged into a single device. The relationship is a diagnostic hint only.
