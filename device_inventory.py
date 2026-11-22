"""Read-only HID interface discovery for Peripheral Control Center.

Only non-sensitive hardware metadata is returned. HID paths and serial numbers
are deliberately excluded; a short SHA-256 fingerprint is used for stable IDs.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

try:
    import hid
except Exception:  # hidapi is optional
    hid = None


USAGE_PAGE_NAMES = {
    0x01: "Generic Desktop",
    0x02: "Simulation Controls",
    0x05: "Game Controls",
    0x06: "Generic Device Controls",
    0x07: "Keyboard / Keypad",
    0x08: "LED",
    0x09: "Button",
    0x0C: "Consumer",
    0x0D: "Digitizers",
    0x0F: "Physical Interface Device",
    0x10: "Unicode",
    0x14: "Alphanumeric Display",
    0x40: "Medical Instruments",
    0x84: "Power Device",
    0x85: "Battery System",
}


def hid_available() -> bool:
    """Return whether hidapi could be imported."""
    return hid is not None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value).strip()


def _path_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    return str(value).encode("utf-8", errors="replace")


def _transport(info: Mapping[str, Any], path: bytes) -> str:
    """Use an explicit hidapi bus type when available; never guess from VID/PID."""
    bus = info.get("bus_type")
    if bus is not None:
        if isinstance(bus, str):
            value = bus.strip().lower()
            if "bluetooth" in value or value == "bt":
                return "Bluetooth"
            if "usb" in value:
                return "USB"
            if value:
                return value.upper()
        else:
            # hidapi bus type values: unknown=0, USB=1, Bluetooth=2, I2C=3, SPI=4.
            bus_name = {1: "USB", 2: "Bluetooth", 3: "I2C", 4: "SPI"}.get(_as_int(bus))
            if bus_name:
                return bus_name

    upper = path.decode("utf-8", errors="ignore").upper()
    if "BTHENUM" in upper or "BTHLE" in upper or "BLUETOOTH" in upper:
        return "Bluetooth"
    if "USB" in upper:
        return "USB"
    return "HID (transport unknown)"


def usage_page_name(page: int) -> str:
    page = _as_int(page)
    if page in USAGE_PAGE_NAMES:
        return USAGE_PAGE_NAMES[page]
    if 0xFF00 <= page <= 0xFFFF:
        return "Vendor-defined"
    return "Other / unknown"


def _protocol_hint(page: int) -> str:
    if page == 0x85:
        return "Battery System HID page; device-specific parsing required"
    if page == 0x84:
        return "Power Device HID page; device-specific parsing required"
    if 0xFF00 <= page <= 0xFFFF:
        return "Vendor-defined interface; manufacturer protocol required"
    return "HID interface found; battery telemetry not confirmed"


def discover_hid_interfaces(hid_module=None) -> list[dict]:
    """Enumerate present HID interfaces and return safe, normalized metadata.

    hid_module is injectable to make discovery independently testable.
    Raises RuntimeError when hidapi is unavailable and propagates enumeration
    errors so the UI/report can explain the failure instead of showing zero devices.
    """
    module = hid if hid_module is None else hid_module
    if module is None:
        raise RuntimeError("hidapi is not installed; install it with: pip install hidapi")

    raw_items = module.enumerate(0, 0) or []
    devices = []
    for info in raw_items:
        if not isinstance(info, Mapping):
            continue

        vendor_id = _as_int(info.get("vendor_id"))
        product_id = _as_int(info.get("product_id"))
        usage_page = _as_int(info.get("usage_page"))
        usage = _as_int(info.get("usage"))
        interface_number = _as_int(info.get("interface_number"), -1)
        raw_path = _path_bytes(info.get("path"))

        identity = raw_path or (
            f"{vendor_id:04X}:{product_id:04X}:{interface_number}:"
            f"{usage_page:04X}:{usage:04X}"
        ).encode("ascii")
        fingerprint = hashlib.sha256(identity).hexdigest()[:12]

        manufacturer = _as_text(info.get("manufacturer_string"))
        product = _as_text(info.get("product_string"))
        if not manufacturer:
            manufacturer = "Unknown manufacturer"
        if not product:
            product = "Unknown HID device"

        devices.append({
            "id": f"hid:{vendor_id:04X}:{product_id:04X}:{interface_number}:{fingerprint}",
            "vendor_id": vendor_id,
            "product_id": product_id,
            "interface_number": interface_number,
            "usage_page": usage_page,
            "usage": usage,
            "usage_page_name": usage_page_name(usage_page),
            "manufacturer": manufacturer,
            "product": product,
            "transport": _transport(info, raw_path),
            "path_fingerprint": fingerprint,
            "vendor_defined": 0xFF00 <= usage_page <= 0xFFFF,
            "battery_related_page": usage_page in (0x84, 0x85),
            "protocol_hint": _protocol_hint(usage_page),
        })

    devices.sort(key=lambda item: (
        item["manufacturer"].casefold(),
        item["product"].casefold(),
        item["vendor_id"],
        item["product_id"],
        item["interface_number"],
        item["usage_page"],
        item["usage"],
        item["path_fingerprint"],
    ))
    return devices
