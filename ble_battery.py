"""Bluetooth LE Battery Service provider.

Reads only the standardized Battery Level characteristic (0x2A19) from the
standard Battery Service (0x180F). It never pairs devices, writes GATT
characteristics, or guesses battery values.

The provider scans only for devices that advertise the Battery Service UUID.
Many peripherals do not advertise this UUID even when they expose a GATT
battery service; those devices require a Windows pairing-aware GATT lookup or
a manufacturer-specific provider and will remain undiscovered here.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
import uuid
from typing import Any

log = logging.getLogger("BatteryTray.ble")

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_STATUS_UUID = "00002bed-0000-1000-8000-00805f9b34fb"
SCAN_SECONDS = 4.0
CONNECT_TIMEOUT = 3.5
MAX_CANDIDATES = 4
CACHE_SECONDS = 240.0

try:
    from bleak import BleakClient, BleakScanner
except Exception as exc:  # optional on systems where BLE GATT is unavailable
    BleakClient = None
    BleakScanner = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""

_MAC_ADDRESS = re.compile(
    r"(?<![0-9A-F])(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}(?![0-9A-F])",
    re.IGNORECASE,
)


def _safe_error(exc: BaseException) -> str:
    """Redact Bluetooth MAC addresses from diagnostics and logs."""
    value = f"{type(exc).__name__}: {exc}"
    return _MAC_ADDRESS.sub("[Bluetooth address redacted]", value)[:240]


_lock = threading.Lock()
_cache: list[dict] = []
_last_scan = 0.0
_last_status: dict[str, Any] = {
    "provider": "ble_gatt",
    "available": BleakScanner is not None and BleakClient is not None,
    "status": "not_scanned",
    "scanned": 0,
    "candidates": 0,
    "read": 0,
    "errors": [],
    "last_scan": None,
}


def _canonical_uuid(value: Any) -> str:
    raw = str(value or "").strip().lower()
    # Advertisement parsers may return 16-bit or 32-bit Bluetooth UUIDs.
    if len(raw) == 4:
        raw = f"0000{raw}-0000-1000-8000-00805f9b34fb"
    elif len(raw) == 8:
        raw = f"{raw}-0000-1000-8000-00805f9b34fb"
    try:
        return str(uuid.UUID(raw)).lower()
    except (ValueError, TypeError, AttributeError):
        return raw


def parse_battery_level_status(raw: bytes | bytearray) -> dict[str, Any] | None:
    """Decode the standard Battery Level Status characteristic (UUID 0x2BED).

    Layout: Flags (1 byte), Power State (2 little-endian bytes), then the
    optional Identifier, Battery Level and Additional Status fields in that
    order when their corresponding flag bits are set.
    """
    data = bytes(raw or b"")
    if len(data) < 3:
        return None

    flags = data[0]
    if flags & 0xF8:  # reserved flag bits must be zero
        return None

    power_state = int.from_bytes(data[1:3], "little")
    battery_present = bool(power_state & 0x01)
    charge_state = (power_state >> 5) & 0x03
    offset = 3

    if flags & 0x01:  # Identifier Present
        if len(data) < offset + 1:
            return None
        offset += 1

    battery_level = None
    if flags & 0x02:  # Battery Level Present
        if len(data) < offset + 1:
            return None
        candidate = data[offset]
        offset += 1
        if not 0 <= candidate <= 100:
            return None
        battery_level = candidate

    if flags & 0x04:  # Additional Status Present
        if len(data) < offset + 1:
            return None
        offset += 1

    # Do not invent a percentage from the qualitative Good/Low/Critical bits.
    if not battery_present:
        battery_level = 0 if flags & 0x02 else None

    return {
        "battery": battery_level,
        "battery_present": battery_present,
        "charging": charge_state == 1 if charge_state != 0 else None,
        "charging_known": charge_state != 0,
    }


def _kind_from_name(name: str) -> str:
    value = name.casefold()
    if any(term in value for term in ("head", "earbud", "buds", "airpod", "науш")):
        return "headphones"
    if any(term in value for term in ("mouse", "мыш")):
        return "mouse"
    if any(term in value for term in ("keyboard", "клав")):
        return "keyboard"
    if any(term in value for term in ("gamepad", "controller", "xbox", "джойст")):
        return "gamepad"
    return "device"


def _stable_id(address: str, service_index: int) -> str:
    # Bluetooth addresses are deliberately not exposed in IDs or reports.
    token = hashlib.sha256(address.casefold().encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"ble:{token}:{service_index}"


async def _scan_and_read() -> tuple[list[dict], dict]:
    if BleakScanner is None or BleakClient is None:
        return [], {
            "provider": "ble_gatt", "available": False,
            "status": "dependency_missing", "scanned": 0, "candidates": 0,
            "read": 0, "errors": [_IMPORT_ERROR or "Bleak is not installed"],
            "last_scan": time.time(),
        }

    errors: list[str] = []
    try:
        # return_adv=True gives one BLEDevice and its advertisement per address.
        discovered = await BleakScanner.discover(timeout=SCAN_SECONDS, return_adv=True)
    except Exception as exc:
        return [], {
            "provider": "ble_gatt", "available": True, "status": "scan_failed",
            "scanned": 0, "candidates": 0, "read": 0,
            "errors": [_safe_error(exc)],
            "last_scan": time.time(),
        }

    candidates = []
    for address, pair in discovered.items():
        try:
            device, advertisement = pair
            advertised = {_canonical_uuid(item) for item in
                          (getattr(advertisement, "service_uuids", None) or [])}
            service_data = getattr(advertisement, "service_data", None) or {}
            advertised.update(_canonical_uuid(item) for item in service_data)
            if BATTERY_SERVICE_UUID not in advertised:
                continue
            candidates.append((device, advertisement))
        except Exception:
            continue

    results: list[dict] = []
    for device, advertisement in candidates[:MAX_CANDIDATES]:
        address = str(getattr(device, "address", "") or "")
        if not address:
            continue
        name = (getattr(advertisement, "local_name", None)
                or getattr(device, "name", None) or "Bluetooth LE device")
        try:
            client = BleakClient(device, timeout=CONNECT_TIMEOUT)
            async with client:
                service_index = 0
                for service in client.services:
                    if _canonical_uuid(service.uuid) != BATTERY_SERVICE_UUID:
                        continue
                    level = None
                    level_source = None
                    charging = None
                    charging_known = False

                    characteristic = service.get_characteristic(BATTERY_LEVEL_UUID)
                    if characteristic is not None:
                        try:
                            raw = bytes(await client.read_gatt_char(characteristic))
                            if raw and 0 <= raw[0] <= 100:
                                level = raw[0]
                                level_source = BATTERY_LEVEL_UUID
                            else:
                                errors.append(f"{name}: invalid or empty Battery Level value")
                        except Exception as exc:
                            errors.append(f"{name}: Battery Level read failed: {_safe_error(exc)}")

                    status_characteristic = service.get_characteristic(
                        BATTERY_LEVEL_STATUS_UUID
                    )
                    if status_characteristic is not None:
                        try:
                            status_raw = await client.read_gatt_char(status_characteristic)
                            status = parse_battery_level_status(status_raw)
                            if status is None:
                                errors.append(f"{name}: invalid Battery Level Status value")
                            else:
                                if level is None and status["battery"] is not None:
                                    level = status["battery"]
                                    level_source = BATTERY_LEVEL_STATUS_UUID
                                if status["charging_known"]:
                                    charging = status["charging"]
                                    charging_known = True
                        except Exception as exc:
                            errors.append(
                                f"{name}: Battery Level Status read failed: {_safe_error(exc)}"
                            )

                    if level is not None:
                        item = {
                            "id": _stable_id(address, service_index),
                            "name": name,
                            "battery": level,
                            "connected": True,
                            "kind": _kind_from_name(name),
                            "source": "ble_gatt",
                            "metadata": {
                                "service_uuid": BATTERY_SERVICE_UUID,
                                "characteristic_uuid": level_source,
                            },
                        }
                        if charging_known:
                            item["charging"] = charging
                            item["charging_known"] = True
                        results.append(item)
                    service_index += 1
        except Exception as exc:
            # A service UUID in advertising is only a candidate; it does not
            # guarantee the device is connectable or permits a GATT read.
            errors.append(f"{name}: {_safe_error(exc)}")

    status = {
        "provider": "ble_gatt",
        "available": True,
        "status": ("read_ok" if results else
                   "candidate_read_failed" if candidates else
                   "no_battery_service_advertised"),
        "scanned": len(discovered),
        "candidates": len(candidates),
        "read": len(results),
        "errors": errors[:12],
        "last_scan": time.time(),
    }
    return results, status


def read_devices(force: bool = False) -> list[dict]:
    """Return cached BLE battery readings, scanning at most once per cache period."""
    global _cache, _last_scan, _last_status
    with _lock:
        now = time.monotonic()
        if not force and _last_scan and now - _last_scan < CACHE_SECONDS:
            return [dict(item) for item in _cache]

        try:
            devices, status = asyncio.run(_scan_and_read())
        except RuntimeError as exc:
            # asyncio.run cannot be nested in an event loop. The app invokes this
            # provider from its background worker, where no loop is running.
            devices = []
            status = {
                "provider": "ble_gatt", "available": BleakScanner is not None,
                "status": "event_loop_error", "scanned": 0, "candidates": 0,
                "read": 0, "errors": [_safe_error(exc)], "last_scan": time.time(),
            }
        except Exception as exc:
            log.exception("BLE battery provider failed")
            devices = []
            status = {
                "provider": "ble_gatt", "available": BleakScanner is not None,
                "status": "provider_error", "scanned": 0, "candidates": 0,
                "read": 0, "errors": [_safe_error(exc)],
                "last_scan": time.time(),
            }

        _cache = devices
        _last_scan = time.monotonic()
        _last_status = status
        if status.get("errors"):
            log.info("BLE battery scan status: %s", status)
        return [dict(item) for item in _cache]


def invalidate_cache() -> None:
    """Force a fresh scan on the next read."""
    global _last_scan
    with _lock:
        _last_scan = 0.0


def diagnostics() -> dict:
    with _lock:
        return dict(_last_status, errors=list(_last_status.get("errors", [])),
                    cached_devices=len(_cache))
