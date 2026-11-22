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
                    characteristic = service.get_characteristic(BATTERY_LEVEL_UUID)
                    if characteristic is None:
                        service_index += 1
                        continue
                    raw = bytes(await client.read_gatt_char(characteristic))
                    if not raw:
                        errors.append(f"{name}: empty Battery Level value")
                        service_index += 1
                        continue
                    level = raw[0]
                    if not 0 <= level <= 100:
                        errors.append(f"{name}: invalid Battery Level value {level}")
                        service_index += 1
                        continue
                    results.append({
                        "id": _stable_id(address, service_index),
                        "name": name,
                        "battery": level,
                        "connected": True,
                        "kind": _kind_from_name(name),
                        "source": "ble_gatt",
                        "charging": None,
                        "metadata": {
                            "service_uuid": BATTERY_SERVICE_UUID,
                            "characteristic_uuid": BATTERY_LEVEL_UUID,
                        },
                    })
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
