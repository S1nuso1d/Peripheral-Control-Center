"""Profile-driven battery provider for vendor-protocol HID devices (2.4 GHz receivers etc.).

Instead of hard-coding every manufacturer, a device is described in vendor_profiles.json
(in %LOCALAPPDATA%\\BatteryTray, or next to the program). A profile says which interface to
open, how to obtain a report, and where the battery byte is. Profiles are written from facts
captured with hid_probe.py or from a documented protocol — never guessed.

Methods:
  "feature"  GET_FEATURE of a report the device declares (read-only)           [default]
  "input"    wait for an input report with the given report id (read-only)
  "request"  send `request` bytes, then read the reply  — WRITES to the device, so it only
             runs when the profile sets "allow_write": true. Use only a documented command.

Example (see vendor_profiles.example.json):
{"profiles": [{"name": "My Mouse", "kind": "mouse", "vid": "1234", "pid": "ABCD",
   "usage_page": "FF00", "method": "feature", "report_id": 9, "length": 33,
   "battery": {"offset": 5, "min": 0, "max": 100, "invalid": [255]},
   "charging": {"offset": 6, "mask": 1}}]}
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from device_inventory import hid

log = logging.getLogger("BatteryTray.vendor_hid")

PROFILE_FILE = "vendor_profiles.json"
METHODS = ("feature", "input", "request")
_lock = threading.Lock()
_status: dict[str, Any] = {"provider": "vendor_hid", "status": "not_scanned", "profiles": 0,
                           "read": 0, "errors": []}


def _hex_int(value: Any, field: str) -> int:
    if isinstance(value, int):
        return value
    return int(str(value).replace("0x", "").replace("0X", ""), 16)


def validate_profile(raw: Any) -> tuple[dict | None, str | None]:
    """Normalize one profile dict; returns (profile, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "profile is not an object"
    if raw.get("enabled") is False:
        return None, "disabled"
    try:
        name = str(raw["name"]).strip()
        vid, pid = _hex_int(raw["vid"], "vid"), _hex_int(raw["pid"], "pid")
        method = str(raw.get("method", "feature"))
        if not name or method not in METHODS:
            return None, f"{name or '?'}: bad name or method {method!r}"
        report_id = int(raw.get("report_id", 0))
        length = int(raw.get("length", 0))
        if not 0 <= report_id <= 255 or not 2 <= length <= 1024:
            return None, f"{name}: report_id/length out of range"
        battery = raw["battery"]
        bat = {"offset": int(battery["offset"]), "min": int(battery.get("min", 0)),
               "max": int(battery.get("max", 100)), "mask": int(battery.get("mask", 255)),
               "invalid": [int(v) for v in battery.get("invalid", [])]}
        if bat["max"] <= bat["min"] or not 0 <= bat["offset"] < length:
            return None, f"{name}: battery range/offset invalid"
        charging = None
        if "charging" in raw:
            ch = raw["charging"]
            charging = {"offset": int(ch["offset"]), "mask": int(ch.get("mask", 1))}
            if not 0 <= charging["offset"] < length:
                return None, f"{name}: charging offset invalid"
        request = b""
        if method == "request":
            if raw.get("allow_write") is not True:
                return None, f"{name}: method 'request' needs \"allow_write\": true"
            request = bytes.fromhex(str(raw.get("request", "")).replace(" ", ""))
            if not request:
                return None, f"{name}: empty request"
        profile = {
            "name": name, "kind": str(raw.get("kind", "device")), "vid": vid, "pid": pid,
            "usage_page": _hex_int(raw["usage_page"], "usage_page") if "usage_page" in raw else None,
            "usage": _hex_int(raw["usage"], "usage") if "usage" in raw else None,
            "interface": int(raw["interface"]) if "interface" in raw else None,
            "method": method, "report_id": report_id, "length": length, "request": request,
            "listen_ms": int(raw.get("listen_ms", 1500)), "battery": bat, "charging": charging,
            "response_prefix": bytes.fromhex(str(raw.get("response_prefix", "")).replace(" ", "")),
        }
        return profile, None
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"invalid profile ({type(exc).__name__}: {exc})"


def load_profiles(directories: list[Path] | None = None) -> tuple[list[dict], list[str]]:
    """Read vendor_profiles.json from the data dir and the program dir."""
    if directories is None:
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BatteryTray"
        directories = [local, Path(__file__).resolve().parent]
    profiles, errors = [], []
    for directory in directories:
        path = Path(directory) / PROFILE_FILE
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        for raw in data.get("profiles", []) if isinstance(data, dict) else []:
            profile, reason = validate_profile(raw)
            if profile:
                profiles.append(profile)
            elif reason != "disabled":
                errors.append(reason)
    return profiles, errors


def parse_report(profile: dict, data: bytes) -> dict | None:
    """Extract {'battery': int, 'charging': bool|None} from a report, or None if invalid."""
    bat = profile["battery"]
    if len(data) <= bat["offset"]:
        return None
    raw = data[bat["offset"]] & bat["mask"]
    if raw in bat["invalid"] or not bat["min"] <= raw <= bat["max"]:
        return None
    percent = round((raw - bat["min"]) * 100 / (bat["max"] - bat["min"]))
    charging = None
    ch = profile["charging"]
    if ch and len(data) > ch["offset"]:
        charging = bool(data[ch["offset"]] & ch["mask"])
    return {"battery": percent, "charging": charging}


def _fetch_report(dev, profile: dict) -> bytes | None:
    rid, length = profile["report_id"], profile["length"]
    if profile["method"] == "feature":
        data = bytes(dev.get_feature_report(rid, length) or b"")
        return data or None
    deadline = time.monotonic() + profile["listen_ms"] / 1000
    if profile["method"] == "request":
        dev.write(profile["request"])
    while time.monotonic() < deadline:
        raw = bytes(dev.read(length, 100) or b"")
        if not raw:
            continue
        if profile["method"] == "input" and rid and raw[0] != rid:
            continue
        if profile["response_prefix"] and not raw.startswith(profile["response_prefix"]):
            continue
        return raw
    return None


def _matches(profile: dict, info: dict) -> bool:
    if info.get("vendor_id") != profile["vid"] or info.get("product_id") != profile["pid"]:
        return False
    for key, field in (("usage_page", "usage_page"), ("usage", "usage"),
                       ("interface", "interface_number")):
        if profile[key] is not None and info.get(field) != profile[key]:
            return False
    return bool(info.get("path"))


def read_devices(hid_module: Any = None, profiles: list[dict] | None = None) -> list[dict]:
    """Read every device that has a matching profile. Returns provider records."""
    module = hid if hid_module is None else hid_module
    errors: list[str] = []
    if profiles is None:
        profiles, errors = load_profiles()
    results: list[dict] = []
    if profiles and module is not None:
        try:
            interfaces = module.enumerate(0, 0) or []
        except Exception as exc:
            interfaces, errors = [], errors + [f"hid.enumerate: {exc!r}"]
        for profile in profiles:
            for info in interfaces:
                if not _matches(profile, info):
                    continue
                parsed = None
                dev = module.device()
                try:
                    dev.open_path(info["path"])
                    data = _fetch_report(dev, profile)
                    parsed = parse_report(profile, data) if data else None
                except Exception as exc:
                    if len(errors) < 12:
                        errors.append(f"{profile['name']}: {type(exc).__name__}: {exc}"[:200])
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                if parsed:
                    item = {"id": f"vendor:{profile['vid']:04X}:{profile['pid']:04X}:"
                                  f"{info.get('interface_number', -1)}",
                            "name": profile["name"], "battery": parsed["battery"],
                            "connected": True, "kind": profile["kind"], "source": "vendor_hid"}
                    if parsed["charging"] is not None:
                        item["charging"], item["charging_known"] = parsed["charging"], True
                    results.append(item)
                    break  # one reading per profile
    with _lock:
        _status.update(status=("read_ok" if results else
                               "no_profiles" if not profiles else "no_reading"),
                       profiles=len(profiles), read=len(results), errors=errors[:12])
    return results


def diagnostics() -> dict:
    with _lock:
        return dict(_status, errors=list(_status["errors"]))
