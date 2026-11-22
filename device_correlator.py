"""Conservative correlation between HID interfaces and Windows PnP nodes.

A VID/PID match is only a candidate relationship: composite devices and receivers
can expose several PnP nodes. This module never merges records or claims identity.
"""
from __future__ import annotations


def _hex_id(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int):
            number = value
        else:
            number = int(str(value).strip().removeprefix("0x").removeprefix("0X"), 16)
        return f"{number:04X}" if 0 <= number <= 0xFFFF else None
    except (TypeError, ValueError, OverflowError):
        return None


def _transport_compatible(hid_transport, pnp_transport):
    hid_value = str(hid_transport or "").casefold()
    pnp_value = str(pnp_transport or "").casefold()
    if not hid_value or "unknown" in hid_value:
        return True
    if hid_value == "usb":
        return pnp_value in {"usb", "hid"}
    if hid_value == "bluetooth":
        return pnp_value in {"bluetooth", "hid"}
    return hid_value == pnp_value


def correlate_hid_to_pnp(hid_devices, pnp_devices):
    """Return HID-id -> candidate PnP rows using VID/PID and transport only.

    Multiple candidates are retained. No name-based or VID-only fuzzy matching
    is performed, and callers should present these as hints rather than merges.
    """
    result = {}
    for hid_device in hid_devices or ():
        vendor_id = _hex_id(hid_device.get("vendor_id"))
        product_id = _hex_id(hid_device.get("product_id"))
        candidates = []
        if vendor_id and product_id:
            for pnp_device in pnp_devices or ():
                pnp_vendor = _hex_id(pnp_device.get("vendor_id"))
                pnp_product = _hex_id(pnp_device.get("product_id"))
                if (vendor_id == pnp_vendor and product_id == pnp_product
                        and _transport_compatible(hid_device.get("transport"),
                                                  pnp_device.get("transport"))):
                    candidates.append(pnp_device)
        result[hid_device.get("id", "")] = sorted(
            candidates,
            key=lambda item: (str(item.get("name", "")).casefold(),
                              str(item.get("id", ""))),
        )
    return result
