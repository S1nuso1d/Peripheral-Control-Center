"""Read-only HID probe for 2.4 GHz receivers and other vendor-protocol devices.

Purpose: capture what a device exposes so a battery profile can be written from facts, not
guesses. The probe NEVER writes to the device. It does only two things:
  1. GET_FEATURE for feature reports that the device's own HID descriptor declares;
  2. passively listens for input reports for a few seconds.
If you know the battery shown by the manufacturer's app (e.g. 87 %), pass it in: the report
marks bytes that match it, which usually pinpoints the battery byte after one or two captures.

Output has no serial numbers or device paths.

CLI:  python hid_probe.py --list
      python hid_probe.py 25A7:FA7C --battery 87 --listen 8
"""
from __future__ import annotations

import argparse
import ctypes
import os
import time
from pathlib import Path
from typing import Any, Callable

from device_inventory import discover_hid_interfaces, hid

MAX_DUMP = 96            # bytes shown per report
MAX_INPUT_VARIANTS = 12  # distinct input reports kept per interface


def candidate_groups(interfaces: list[dict] | None = None) -> list[dict]:
    """Devices worth probing: groups of interfaces (by VID:PID) that include a vendor-defined page."""
    interfaces = discover_hid_interfaces() if interfaces is None else interfaces
    groups: dict[tuple, dict] = {}
    for item in interfaces:
        if not item.get("vendor_defined") or item.get("transport") in ("Bluetooth", "I2C", "SPI"):
            continue
        key = (item["vendor_id"], item["product_id"])
        g = groups.setdefault(key, {"vid_pid": f"{key[0]:04X}:{key[1]:04X}", "names": set()})
        label = item.get("product") if "Unknown" not in str(item.get("product")) else item.get("manufacturer")
        g["names"].add(str(label))
    return [{"vid_pid": g["vid_pid"],
             "label": f"{' / '.join(sorted(g['names']))}  ({g['vid_pid']})"}
            for g in sorted(groups.values(), key=lambda g: g["vid_pid"])]


def parse_vid_pid(text: str) -> tuple[int, int]:
    vid, pid = text.replace("0x", "").replace("0X", "").split(":")
    return int(vid, 16), int(pid, 16)


# --- declared reports (Windows HID parser) -------------------------------------

def windows_caps(info: dict) -> dict:
    """Report lengths and the feature report IDs that the descriptor declares. {} on failure."""
    if os.name != "nt":
        return {}
    import hid_battery as hb
    api = hb._load_api()
    path = hb._path_to_windows_text(info["path"])
    handle = api["kernel32"].CreateFileW(path, hb.GENERIC_READ,
                                         hb.FILE_SHARE_READ | hb.FILE_SHARE_WRITE,
                                         None, hb.OPEN_EXISTING, 0, None)
    if not handle or handle == hb.INVALID_HANDLE_VALUE:
        return {}
    preparsed = ctypes.c_void_p()
    try:
        if not api["hid"].HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            return {}
        try:
            caps = hb.HIDP_CAPS()
            if api["hid"].HidP_GetCaps(preparsed, ctypes.byref(caps)) != hb.HIDP_STATUS_SUCCESS:
                return {}
            ids: set[int] = set()
            count = caps.NumberFeatureValueCaps
            if count:
                vcaps = (hb.HIDP_VALUE_CAPS * count)()
                actual = ctypes.c_ushort(count)
                if api["hid"].HidP_GetValueCaps(hb.HIDP_FEATURE, vcaps, ctypes.byref(actual),
                                                preparsed) == hb.HIDP_STATUS_SUCCESS:
                    ids = {vcaps[i].ReportID for i in range(actual.value)}
            if not ids and caps.FeatureReportByteLength:
                ids = {0}
            return {"input_len": caps.InputReportByteLength,
                    "feature_len": caps.FeatureReportByteLength,
                    "feature_ids": sorted(ids)}
        finally:
            if preparsed:
                api["hid"].HidD_FreePreparsedData(preparsed)
    finally:
        api["kernel32"].CloseHandle(handle)


# --- analysis -----------------------------------------------------------------

def candidate_offsets(data: bytes, battery: int | None) -> list[tuple[int, int]]:
    """Offsets whose byte equals the known battery %, or its 0–255 scaling (±1)."""
    if battery is None or not 0 <= battery <= 100:
        return []
    wanted = {battery}
    scaled = round(battery * 255 / 100)
    wanted |= {scaled - 1, scaled, scaled + 1}
    return [(i, b) for i, b in enumerate(data) if b in wanted and b not in (0, 255)]


def _hex(data: bytes) -> str:
    shown = data[:MAX_DUMP]
    text = " ".join(f"{b:02X}" for b in shown)
    return text + (" …" if len(data) > MAX_DUMP else "")


def probe_interface(info: dict, hid_module: Any = None, caps_reader: Callable = windows_caps,
                    listen_seconds: float = 6.0, battery: int | None = None) -> list[str]:
    """Probe one HID interface; returns report lines. Never writes to the device."""
    module = hid if hid_module is None else hid_module
    header = (f"== {info['vendor_id']:04X}:{info['product_id']:04X}  iface {info['interface_number']}"
              f"  page 0x{info['usage_page']:04X} usage 0x{info['usage']:04X}  "
              f"{info['manufacturer']} / {info['product']} ==")
    lines = [header]
    caps = {}
    try:
        caps = caps_reader(info) or {}
    except Exception as exc:
        lines.append(f"  caps: error {type(exc).__name__}: {exc}")
    if caps:
        lines.append(f"  caps: input_len={caps.get('input_len')} feature_len={caps.get('feature_len')}"
                     f" feature_ids={[f'0x{i:02X}' for i in caps.get('feature_ids', [])]}")

    dev = module.device()
    try:
        dev.open_path(info["_path"])
    except Exception as exc:
        lines.append(f"  cannot open: {type(exc).__name__}: {exc} (another program may hold it)")
        return lines
    try:
        for rid in caps.get("feature_ids", []):
            length = max(int(caps.get("feature_len") or 0), 2)
            try:
                raw = bytes(dev.get_feature_report(rid, length))
            except Exception as exc:
                lines.append(f"  feature 0x{rid:02X}: error {type(exc).__name__}: {exc}")
                continue
            if not raw:
                lines.append(f"  feature 0x{rid:02X}: empty/no response")
                continue
            lines.append(f"  feature 0x{rid:02X} ({len(raw)} bytes): {_hex(raw)}")
            for off, val in candidate_offsets(raw, battery):
                lines.append(f"    ← byte [{off}] = {val} (0x{val:02X}) matches battery {battery}%")

        seen: dict[bytes, int] = {}
        deadline = time.monotonic() + listen_seconds
        try:
            dev.set_nonblocking(0)
        except Exception:
            pass
        while time.monotonic() < deadline:
            try:
                raw = dev.read(max(int(caps.get("input_len") or 0), 64), 200)
            except Exception as exc:
                lines.append(f"  input: read error {type(exc).__name__}: {exc}")
                break
            if raw:
                data = bytes(raw)
                if data in seen or len(seen) < MAX_INPUT_VARIANTS:
                    seen[data] = seen.get(data, 0) + 1
        lines.append(f"  input (listened {listen_seconds:g} s): {len(seen)} distinct report(s)")
        for data, n in seen.items():
            lines.append(f"    x{n}: {_hex(data)}")
            for off, val in candidate_offsets(data, battery):
                lines.append(f"      ← byte [{off}] = {val} (0x{val:02X}) matches battery {battery}%")
    finally:
        try:
            dev.close()
        except Exception:
            pass
    return lines


def build_report(vid_pid: str | None = None, battery: int | None = None,
                 listen_seconds: float = 6.0, hid_module: Any = None,
                 caps_reader: Callable = windows_caps) -> str:
    module = hid if hid_module is None else hid_module
    out = ["=== HID probe (read-only: no writes to the device) ===",
           f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
           f"Battery reported by manufacturer app: {battery if battery is not None else 'unknown'}",
           f"Target: {vid_pid or 'all vendor-defined interfaces'}", ""]
    if module is None:
        return "\n".join(out + ["hidapi is not installed: pip install hidapi"])

    wanted = parse_vid_pid(vid_pid) if vid_pid else None
    interfaces = discover_hid_interfaces(module)
    raw_items = {(i.get("vendor_id"), i.get("product_id"), i.get("interface_number"),
                  i.get("usage_page"), i.get("usage")): i for i in (module.enumerate(0, 0) or [])}
    count = 0
    for item in interfaces:
        if wanted and (item["vendor_id"], item["product_id"]) != wanted:
            continue
        if not wanted and not item["vendor_defined"]:
            continue
        raw = raw_items.get((item["vendor_id"], item["product_id"], item["interface_number"],
                             item["usage_page"], item["usage"]))
        if not raw or not raw.get("path"):
            continue
        count += 1
        info = dict(item, path=raw["path"], _path=raw["path"])
        out += probe_interface(info, module, caps_reader, listen_seconds, battery) + [""]
    if not count:
        out.append("No matching HID interfaces found.")
    out += ["Send this file for analysis. Run it twice at different battery levels "
            "(e.g. 100% and 60%) to make the battery byte obvious."]
    return "\n".join(out)


def write_report(directory, vid_pid: str | None = None, battery: int | None = None,
                 listen_seconds: float = 6.0) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = f"_{vid_pid.replace(':', '-')}" if vid_pid else ""
    path = directory / f"hid_probe{suffix}.txt"
    path.write_text(build_report(vid_pid, battery, listen_seconds), encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only HID probe")
    parser.add_argument("vid_pid", nargs="?", help="e.g. 25A7:FA7C (default: all vendor-defined)")
    parser.add_argument("--list", action="store_true", help="list candidate devices")
    parser.add_argument("--battery", type=int, help="battery %% shown by the manufacturer app")
    parser.add_argument("--listen", type=float, default=6.0, help="seconds to listen for input")
    args = parser.parse_args()
    if args.list:
        for g in candidate_groups():
            print(g["label"])
    else:
        base = Path(os.environ.get("LOCALAPPDATA", ".")) / "BatteryTray"
        print(write_report(base, args.vid_pid, args.battery, args.listen).read_text(encoding="utf-8"))
