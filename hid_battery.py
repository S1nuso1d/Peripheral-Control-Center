"""Generic Windows HID Battery Strength provider (read-only).

Uses the standard HID Generic Device Controls usage 0x06/0x20 ("Battery
Strength"). It inspects report capabilities and requests only existing input
or feature reports. It never sends output reports or SET_FEATURE commands.

A device is reported only when Windows' HID parser exposes Battery Strength
and a current report can be read and scaled using that report's logical range.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import threading
import time
from ctypes import wintypes
from typing import Any

from device_inventory import hid

log = logging.getLogger("BatteryTray.hid_battery")

HID_USAGE_PAGE_GENERIC_DEVICE = 0x06
HID_USAGE_BATTERY_STRENGTH = 0x20
HIDP_STATUS_SUCCESS = 0x00110000
HIDP_INPUT = 0
HIDP_FEATURE = 2

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_cache: list[dict] = []
_last_read = 0.0
_last_status: dict[str, Any] = {
    "provider": "hid_battery",
    "available": os.name == "nt",
    "status": "not_scanned",
    "interfaces": 0,
    "candidates": 0,
    "read": 0,
    "errors": [],
    "last_scan": None,
}
_lock = threading.Lock()
_api: dict[str, Any] = {}


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


class HIDP_VALUE_RANGE(ctypes.Structure):
    _fields_ = [
        ("UsageMin", ctypes.c_ushort),
        ("UsageMax", ctypes.c_ushort),
        ("StringMin", ctypes.c_ushort),
        ("StringMax", ctypes.c_ushort),
        ("DesignatorMin", ctypes.c_ushort),
        ("DesignatorMax", ctypes.c_ushort),
        ("DataIndexMin", ctypes.c_ushort),
        ("DataIndexMax", ctypes.c_ushort),
    ]


class HIDP_VALUE_NOT_RANGE(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("Reserved1", ctypes.c_ushort),
        ("StringIndex", ctypes.c_ushort),
        ("Reserved2", ctypes.c_ushort),
        ("DesignatorIndex", ctypes.c_ushort),
        ("Reserved3", ctypes.c_ushort),
        ("DataIndex", ctypes.c_ushort),
        ("Reserved4", ctypes.c_ushort),
    ]


class HIDP_VALUE_UNION(ctypes.Union):
    _fields_ = [("Range", HIDP_VALUE_RANGE), ("NotRange", HIDP_VALUE_NOT_RANGE)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("UsagePage", ctypes.c_ushort),
        ("ReportID", ctypes.c_ubyte),
        ("IsAlias", ctypes.c_ubyte),
        ("BitField", ctypes.c_ushort),
        ("LinkCollection", ctypes.c_ushort),
        ("LinkUsage", ctypes.c_ushort),
        ("LinkUsagePage", ctypes.c_ushort),
        ("IsRange", ctypes.c_ubyte),
        ("IsStringRange", ctypes.c_ubyte),
        ("IsDesignatorRange", ctypes.c_ubyte),
        ("IsAbsolute", ctypes.c_ubyte),
        ("HasNull", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte),
        ("BitSize", ctypes.c_ushort),
        ("ReportCount", ctypes.c_ushort),
        ("Reserved2", ctypes.c_ushort * 5),
        ("UnitsExp", ctypes.c_ulong),
        ("Units", ctypes.c_ulong),
        ("LogicalMin", ctypes.c_long),
        ("LogicalMax", ctypes.c_long),
        ("PhysicalMin", ctypes.c_long),
        ("PhysicalMax", ctypes.c_long),
        ("u", HIDP_VALUE_UNION),
    ]


def _load_api() -> dict[str, Any]:
    if _api:
        return _api
    if os.name != "nt":
        raise OSError("Generic HID Battery Strength is available only on Windows")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hid = ctypes.WinDLL("hid", use_last_error=True)

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
    hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetFeature.restype = wintypes.BOOLEAN
    hid.HidD_GetInputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetInputReport.restype = wintypes.BOOLEAN

    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    hid.HidP_GetCaps.restype = ctypes.c_long
    hid.HidP_GetValueCaps.argtypes = [
        ctypes.c_int, ctypes.POINTER(HIDP_VALUE_CAPS),
        ctypes.POINTER(ctypes.c_ushort), ctypes.c_void_p,
    ]
    hid.HidP_GetValueCaps.restype = ctypes.c_long
    hid.HidP_GetUsageValue.argtypes = [
        ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_ushort,
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.ULONG,
    ]
    hid.HidP_GetUsageValue.restype = ctypes.c_long
    _api.update(kernel32=kernel32, hid=hid)
    return _api


def scale_battery_strength(value: int, logical_min: int, logical_max: int) -> int | None:
    """Scale a HID Battery Strength value using the report's declared logical range."""
    try:
        value, logical_min, logical_max = int(value), int(logical_min), int(logical_max)
    except (TypeError, ValueError, OverflowError):
        return None
    if logical_max <= logical_min or logical_min < 0:
        return None
    if value < logical_min or value > logical_max:
        return None
    percent = round((value - logical_min) * 100 / (logical_max - logical_min))
    return max(0, min(100, percent))


def _cap_usage(cap: HIDP_VALUE_CAPS) -> bool:
    if cap.UsagePage != HID_USAGE_PAGE_GENERIC_DEVICE:
        return False
    if cap.IsRange:
        return cap.UsageMin <= HID_USAGE_BATTERY_STRENGTH <= cap.UsageMax
    return cap.NotRange.Usage == HID_USAGE_BATTERY_STRENGTH


def _read_report_value(api, handle, preparsed, report_type: int, cap, report_length: int):
    if report_length <= 0:
        return None
    report = (ctypes.c_ubyte * report_length)()
    report[0] = cap.ReportID

    if report_type == HIDP_FEATURE:
        ok = api["hid"].HidD_GetFeature(handle, report, report_length)
    else:
        # Microsoft documents this as a one-shot snapshot operation, not a
        # streaming mechanism. That is appropriate for occasional battery reads.
        ok = api["hid"].HidD_GetInputReport(handle, report, report_length)
    if not ok:
        return None

    raw_value = ctypes.c_ulong(0)
    status = api["hid"].HidP_GetUsageValue(
        report_type,
        HID_USAGE_PAGE_GENERIC_DEVICE,
        cap.LinkCollection,
        HID_USAGE_BATTERY_STRENGTH,
        ctypes.byref(raw_value),
        preparsed,
        ctypes.cast(report, ctypes.c_void_p),
        report_length,
    )
    if status != HIDP_STATUS_SUCCESS:
        return None
    return scale_battery_strength(raw_value.value, cap.LogicalMin, cap.LogicalMax)


def _path_to_windows_text(path: Any) -> str:
    if isinstance(path, str):
        return path
    if isinstance(path, (bytes, bytearray)):
        return bytes(path).decode("utf-8", errors="strict")
    raise ValueError("Unsupported HID path type")


def _read_interface(info: dict, api) -> int | None:
    path = _path_to_windows_text(info.get("path"))
    handle = api["kernel32"].CreateFileW(
        path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None

    preparsed = ctypes.c_void_p()
    try:
        if not api["hid"].HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            return None
        try:
            caps = HIDP_CAPS()
            if api["hid"].HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                return None

            report_types = (
                (HIDP_FEATURE, caps.NumberFeatureValueCaps, caps.FeatureReportByteLength),
                (HIDP_INPUT, caps.NumberInputValueCaps, caps.InputReportByteLength),
            )
            for report_type, count, report_length in report_types:
                if not count or not report_length:
                    continue
                value_caps = (HIDP_VALUE_CAPS * count)()
                actual_count = ctypes.c_ushort(count)
                status = api["hid"].HidP_GetValueCaps(
                    report_type, value_caps, ctypes.byref(actual_count), preparsed
                )
                if status != HIDP_STATUS_SUCCESS:
                    continue
                for cap in value_caps[:actual_count.value]:
                    if not _cap_usage(cap):
                        continue
                    value = _read_report_value(api, handle, preparsed, report_type,
                                               cap, report_length)
                    if value is not None:
                        return value
            return None
        finally:
            if preparsed:
                api["hid"].HidD_FreePreparsedData(preparsed)
    finally:
        api["kernel32"].CloseHandle(handle)


def _kind(name: str) -> str:
    value = name.casefold()
    if any(term in value for term in ("head", "ear", "buds", "науш")):
        return "headphones"
    if any(term in value for term in ("mouse", "мыш")):
        return "mouse"
    if any(term in value for term in ("keyboard", "клав")):
        return "keyboard"
    if any(term in value for term in ("controller", "gamepad", "xbox", "джойст")):
        return "gamepad"
    return "device"


def read_devices(force: bool = False) -> list[dict]:
    """Read standard HID Battery Strength values from present HID interfaces."""
    global _cache, _last_read, _last_status
    with _lock:
        now = time.monotonic()
        if not force and _last_read and now - _last_read < 60.0:
            return [dict(item) for item in _cache]

        if os.name != "nt":
            _cache = []
            _last_status = dict(_last_status, status="windows_only", read=0,
                                last_scan=time.time())
            _last_read = now
            return []

        if hid is None:
            _cache = []
            _last_status = dict(_last_status, status="hidapi_missing", interfaces=0,
                                candidates=0, read=0, errors=["hidapi is not installed"],
                                last_scan=time.time())
            _last_read = now
            return []

        try:
            interfaces = hid.enumerate(0, 0) or []
        except Exception as exc:
            interfaces = []
            errors = [f"hid.enumerate: {type(exc).__name__}: {exc}"[:240]]
        else:
            errors = []

        candidates = 0
        results = []
        try:
            api = _load_api()
        except Exception as exc:
            _last_status = {
                "provider": "hid_battery", "available": False,
                "status": "windows_hid_api_unavailable", "interfaces": len(interfaces),
                "candidates": 0, "read": 0,
                "errors": [f"{type(exc).__name__}: {exc}"[:240]],
                "last_scan": time.time(),
            }
            _last_read = time.monotonic()
            return []

        for info in interfaces:
            if not isinstance(info, dict) or not info.get("path"):
                continue
            candidates += 1
            name = (str(info.get("product_string") or "").strip()
                    or str(info.get("manufacturer_string") or "").strip()
                    or "HID peripheral")
            try:
                level = _read_interface(info, api)
            except Exception as exc:
                if len(errors) < 12:
                    errors.append(f"{name}: {type(exc).__name__}: {exc}"[:240])
                continue
            if level is None:
                continue
            try:
                path = _path_to_windows_text(info["path"])
            except Exception:
                path = f'{info.get("vendor_id", 0)}:{info.get("product_id", 0)}:{info.get("interface_number", -1)}'
            token = hashlib.sha256(path.casefold().encode("utf-8", errors="replace")).hexdigest()[:12]
            results.append({
                "id": f"hid-battery:{token}",
                "name": name,
                "battery": level,
                "connected": True,
                "kind": _kind(name),
                "source": "hid_battery",
            })

        _cache = results
        _last_status = {
            "provider": "hid_battery", "available": True,
            "status": "read_ok" if results else "no_standard_battery_strength",
            "interfaces": len(interfaces), "candidates": candidates,
            "read": len(results), "errors": errors[:12], "last_scan": time.time(),
        }
        _last_read = time.monotonic()
        return [dict(item) for item in _cache]


def invalidate_cache() -> None:
    global _last_read
    with _lock:
        _last_read = 0.0


def diagnostics() -> dict:
    with _lock:
        return dict(_last_status, errors=list(_last_status.get("errors", [])),
                    cached_devices=len(_cache))


if __name__ == "__main__":
    for device in read_devices(force=True):
        print(f'{device["name"]}: {device["battery"]}%')
    print(diagnostics())
