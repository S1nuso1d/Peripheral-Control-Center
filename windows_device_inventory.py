"""Read-only Windows PnP inventory for Peripheral Control Center.

Raw PnP instance IDs and hardware-ID strings are used only for normalization;
they are never returned to callers or included in reports.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from typing import Any, Callable

VID_PID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.IGNORECASE)

POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$classes = @('Bluetooth', 'HIDClass', 'Mouse', 'Keyboard', 'AudioEndpoint',
             'MEDIA', 'USB', 'Xbox', 'GameController')
$devices = @(Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match '^(USB|HID|BTHENUM|BTHLE|BTH|SWD\\MMDEVAPI)' -or
    $classes -contains $_.Class
})
$rows = foreach ($device in $devices) {
    $manufacturer = $null
    $description = $null
    $hardwareIds = @()
    $battery = $null
    $batterySource = $null

    # Generic Windows shell battery property. It is not populated for every
    # peripheral, but when present it represents remaining battery life in %.
    try {
        $p = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName '{49CD1F76-5626-4B17-A4E8-18B4AA1A2213} 10' -ErrorAction Stop
        if ($null -ne $p.Data) {
            $candidate = [int]$p.Data
            if ($candidate -ge 0 -and $candidate -le 100) {
                $battery = $candidate
                $batterySource = 'System.Devices.BatteryLife'
            }
        }
    } catch {}

    try {
        $p = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName 'DEVPKEY_Device_Manufacturer' -ErrorAction Stop
        $manufacturer = $p.Data
    } catch {}

    try {
        $p = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName 'DEVPKEY_Device_BusReportedDeviceDesc' -ErrorAction Stop
        $description = $p.Data
    } catch {}

    try {
        $p = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName 'DEVPKEY_Device_HardwareIds' -ErrorAction Stop
        $hardwareIds = @($p.Data)
    } catch {}

    if ($null -eq $battery -and $device.InstanceId -match '^(BTHENUM|BTHLE)\\DEV_') {
        try {
            $p = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction Stop
            if ($null -ne $p.Data) {
                $candidate = [int]$p.Data
                if ($candidate -ge 0 -and $candidate -le 100) {
                    $battery = $candidate
                    $batterySource = 'DEVPKEY_Bluetooth_Battery'
                }
            }
        } catch {}
    }

    [pscustomobject]@{
        name = $device.FriendlyName
        description = $description
        manufacturer = $manufacturer
        status = $device.Status
        deviceClass = $device.Class
        instanceId = $device.InstanceId
        hardwareIds = @($hardwareIds)
        battery = $battery
        batterySource = $batterySource
    }
}

if ($null -eq $rows) {
    '[]'
} else {
    ConvertTo-Json -InputObject @($rows) -Depth 4 -Compress
}
"""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(part for part in (_text(item) for item in value) if part)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value).strip()


def _battery(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= 100 else None


def _transport(instance_id: str, device_class: str) -> str:
    upper = instance_id.upper()
    if upper.startswith(("BTHENUM\\", "BTHLE\\", "BTH\\")):
        return "Bluetooth"
    if upper.startswith("USB\\"):
        return "USB"
    if upper.startswith("HID\\"):
        return "HID"
    if upper.startswith("SWD\\MMDEVAPI\\"):
        return "Windows audio endpoint"
    if device_class.casefold() == "bluetooth":
        return "Bluetooth"
    if device_class.casefold() == "usb":
        return "USB"
    return "Windows PnP"


def _device_kind(name: str, device_class: str) -> str:
    value = f"{name} {device_class}".casefold()
    if "keyboard" in value or "клав" in value:
        return "keyboard"
    if "mouse" in value or "мыш" in value:
        return "mouse"
    if any(term in value for term in ("headphone", "headset", "earbud", "науш")):
        return "headphones"
    if any(term in value for term in ("gamepad", "controller", "xbox", "джойст")):
        return "gamepad"
    if "audio" in value or "sound" in value:
        return "audio"
    return "device"


def normalize_pnp_devices(raw_devices: Any) -> list[dict]:
    """Normalize Get-PnpDevice output without returning raw instance IDs."""
    if raw_devices is None or raw_devices == "":
        return []
    if isinstance(raw_devices, Mapping):
        raw_devices = [raw_devices]
    if not isinstance(raw_devices, list):
        raise ValueError("Unexpected Windows PnP JSON structure")

    normalized = []
    for raw in raw_devices:
        if not isinstance(raw, Mapping):
            continue

        instance_id = _text(raw.get("instanceId") or raw.get("InstanceId"))
        name = _text(raw.get("name") or raw.get("FriendlyName"))
        description = _text(raw.get("description"))
        manufacturer = _text(raw.get("manufacturer"))
        device_class = _text(raw.get("deviceClass") or raw.get("Class"))
        status = _text(raw.get("status") or raw.get("Status")) or "Unknown"
        display_name = name or description or device_class or "Unknown Windows device"

        hardware_ids = _text(raw.get("hardwareIds"))
        match = VID_PID.search(f"{instance_id} {hardware_ids}")
        vendor_id = match.group(1).upper() if match else None
        product_id = match.group(2).upper() if match else None

        identity = instance_id or f"{display_name}|{device_class}|{vendor_id}|{product_id}"
        fingerprint = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:12]
        battery = _battery(raw.get("battery"))

        normalized.append({
            "id": f"pnp:{fingerprint}",
            "name": display_name,
            "manufacturer": manufacturer or "Unknown manufacturer",
            "device_class": device_class or "Unknown",
            "status": status,
            "connected": status.casefold() == "ok",
            "transport": _transport(instance_id, device_class),
            "vendor_id": vendor_id,
            "product_id": product_id,
            "vid_pid": f"{vendor_id}:{product_id}" if vendor_id and product_id else "—",
            "battery": battery,
            "battery_source": _text(raw.get("batterySource") or raw.get("battery_source")),
            "kind": _device_kind(display_name, device_class),
        })

    normalized.sort(key=lambda item: (
        item["transport"].casefold(),
        item["manufacturer"].casefold(),
        item["name"].casefold(),
        item["id"],
    ))
    return normalized


def _run_powershell(script: str, timeout: int = 30) -> str:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Windows PowerShell was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Windows PnP enumeration timed out after {timeout} seconds") from exc

    stdout = completed.stdout
    stderr = completed.stderr
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        detail = _text(stderr) or _text(stdout) or f"exit code {completed.returncode}"
        raise RuntimeError(f"Windows PnP enumeration failed: {detail[:500]}")
    return _text(stdout)


def discover_windows_devices(runner: Callable[[str], str] | None = None) -> list[dict]:
    """Enumerate relevant present Windows PnP devices using a read-only query.

    A runner can be injected in tests. No raw instance IDs or serial numbers
    escape the normalization layer.
    """
    output = (runner or _run_powershell)(POWERSHELL_SCRIPT)
    if not output:
        return []
    try:
        raw_devices = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Windows PnP returned invalid JSON") from exc
    return normalize_pnp_devices(raw_devices)
