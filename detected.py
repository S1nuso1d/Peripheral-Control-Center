"""Devices that Windows can see but whose battery we could not read — and why.

Qt-free and pure: the app passes in what the providers observed, and gets back a short list
for the popup ("found, but no battery data"). This exists so an empty list never looks like
"nothing is connected"; it shows what *is* connected and what is missing.
"""
from __future__ import annotations

from typing import Iterable, Mapping

MAX_ITEMS = 6
_GENERIC_NAMES = ("unknown hid device", "hid-compliant", "usb input device", "unknown manufacturer")


def _kind(name: str) -> str:
    value = name.casefold()
    if any(t in value for t in ("head", "ear", "buds", "науш", "audio")):
        return "headphones"
    if any(t in value for t in ("mouse", "мыш", "gaming mouse")):
        return "mouse"
    if any(t in value for t in ("keyboard", "клав")):
        return "keyboard"
    if any(t in value for t in ("controller", "gamepad", "джойст")):
        return "gamepad"
    return "device"


def build_unsupported(bluetooth_nodes: Iterable[Mapping], hid_interfaces: Iterable[Mapping],
                      reading_names: Iterable[str]) -> list[dict]:
    """Return [{name, kind, reason, detail}] for connected devices without battery data.

    reason is "bluetooth" (Windows publishes no battery for this paired device) or "vendor"
    (a USB/2.4 GHz device with a vendor-defined HID interface: a manufacturer protocol is
    needed). Devices that already have a reading are excluded.
    """
    reading = [n.casefold() for n in reading_names if n]

    def already_read(name: str) -> bool:
        n = name.casefold()
        return any(n in r or r in n for r in reading)

    out: list[dict] = []
    seen: set[str] = set()

    for node in bluetooth_nodes:
        name = str(node.get("name") or "").strip()
        key = name.casefold()
        if not name or not node.get("connected") or key in seen or already_read(name):
            continue
        seen.add(key)
        out.append({"name": name, "kind": node.get("kind") or _kind(name),
                    "reason": "bluetooth", "detail": ""})

    groups: dict[tuple, dict] = {}
    for iface in hid_interfaces:
        if not iface.get("vendor_defined") or iface.get("transport") in ("Bluetooth", "I2C", "SPI"):
            continue
        key = (iface.get("vendor_id"), iface.get("product_id"))
        group = groups.setdefault(key, {"product": "", "manufacturer": ""})
        product = str(iface.get("product") or "")
        manufacturer = str(iface.get("manufacturer") or "")
        if product and product.casefold() not in _GENERIC_NAMES:
            group["product"] = group["product"] or product
        if manufacturer and manufacturer.casefold() not in _GENERIC_NAMES:
            group["manufacturer"] = group["manufacturer"] or manufacturer

    for (vid, pid), group in sorted(groups.items(), key=lambda kv: str(kv[0])):
        name = group["product"] or group["manufacturer"]
        if not name or name.casefold() in seen or already_read(name):
            continue
        seen.add(name.casefold())
        out.append({"name": name, "kind": _kind(f"{name} {group['manufacturer']}"),
                    "reason": "vendor", "detail": f"{int(vid):04X}:{int(pid):04X}"})

    return out[:MAX_ITEMS]
