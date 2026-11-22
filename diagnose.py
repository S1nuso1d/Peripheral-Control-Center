"""Диагностика: что система видит у подключённых устройств и почему заряд может быть недоступен.

Запуск (без Qt):   python diagnose.py
Или из меню приложения: «Диагностика устройств…».
Отчёт сохраняется в %LOCALAPPDATA%\\BatteryTray\\diagnostics.txt и открывается.
В отчёт не попадают серийные номера и полные Bluetooth-адреса — только VID/PID, названия
и технические признаки интерфейсов.
"""
import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from device_inventory import discover_hid_interfaces, hid_available
from windows_device_inventory import discover_windows_devices

PS_PNP = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$bat = '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2'
Get-PnpDevice -PresentOnly |
  Where-Object { $_.InstanceId -match '^(USB|HID|BTHENUM|BTHLE|BTH)' } |
  ForEach-Object {
    $b = $null
    if ($_.InstanceId -match '^(BTHENUM|BTHLE)\\DEV_') {
      $p = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $bat
      if ($p -and $null -ne $p.Data) { $b = [int]$p.Data }
    }
    [pscustomobject]@{ status = $_.Status; cls = $_.Class; name = $_.FriendlyName
                       id = $_.InstanceId; battery = $b }
  } | ConvertTo-Json -Compress
"""

VID_PID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I)


def _mask(instance_id: str) -> str:
    """Убираем серийник/Bluetooth-адрес из идентификатора."""
    s = re.sub(r"DEV_([0-9A-F]{8})([0-9A-F]{4})", r"DEV_********\2", instance_id, flags=re.I)
    parts = s.split("\\")
    return "\\".join(parts[:2]) if len(parts) > 2 and not s.upper().startswith("BTH") else s


def _powershell(script: str, timeout: int = 90) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        capture_output=True, timeout=timeout, creationflags=0x08000000)
    return out.stdout.decode("utf-8", errors="replace").strip()


def section_system() -> list:
    return [f"Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Windows: {platform.platform()}",
            f"Python: {sys.version.split()[0]}  hidapi: {'есть' if hid_available() else 'НЕ установлен'}"]


def section_pnp() -> list:
    try:
        devices = discover_windows_devices()
    except Exception as exc:
        return [f"Не удалось получить список устройств Windows: {exc!r}"]

    if not devices:
        return ["  (подходящих Windows PnP-устройств не найдено)"]

    lines = []
    for device in devices:
        battery = f'{device["battery"]}%' if device["battery"] is not None else "Windows не сообщает"
        lines.append(
            f'  {device["name"]} | {device["manufacturer"]} | '
            f'{device["vid_pid"]} | {device["device_class"]} | '
            f'{device["transport"]} | статус {device["status"]} | заряд: {battery}'
        )
    return lines


def section_hid() -> list:
    try:
        devices = discover_hid_interfaces()
    except Exception as e:
        return [f"Не удалось перечислить HID-интерфейсы: {e!r}"]

    lines = []
    for device in devices:
        label = (device["manufacturer"] + " " + device["product"]).lower()
        flag = "  <== ARDOR?" if "ardor" in label else ""
        lines.append(
            f'  {device["vendor_id"]:04X}:{device["product_id"]:04X}  '
            f'iface {device["interface_number"]}  '
            f'page 0x{device["usage_page"]:04X} usage 0x{device["usage"]:04X}  '
            f'{device["manufacturer"]} / {device["product"]}  '
            f'{device["usage_page_name"]}  {device["transport"]}  '
            f'{device["protocol_hint"]}  fingerprint {device["path_fingerprint"]}{flag}'
        )
    return lines or ["  (HID-интерфейсов не найдено)"]


def section_xinput() -> list:
    for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            xi = ctypes.WinDLL(dll)
            break
        except (OSError, AttributeError):
            xi = None
    if xi is None:
        return ["XInput недоступен"]

    class Info(ctypes.Structure):
        _fields_ = [("BatteryType", ctypes.c_ubyte), ("BatteryLevel", ctypes.c_ubyte)]

    lines = []
    for idx in range(4):
        info = Info()
        r = xi.XInputGetBatteryInformation(idx, 0, ctypes.byref(info))
        if r == 0:
            lines.append(f"  слот {idx}: тип батареи {info.BatteryType}, уровень {info.BatteryLevel}")
    return lines or ["  (XInput-геймпадов нет)"]


def build_report() -> str:
    out = ["=== Peripheral Control Center: диагностика ===", ""]
    for title, fn in (("Система", section_system), ("Устройства Windows", section_pnp),
                      ("HID-интерфейсы (hidapi)", section_hid), ("XInput", section_xinput)):
        out.append(f"## {title}")
        try:
            out += fn()
        except Exception as e:
            out.append(f"  ошибка раздела: {e!r}")
        out.append("")
    out += [
        "## Как читать",
        "• Если у устройства «Windows НЕ сообщает» заряд, а оно на донгле 2.4 ГГц — процент",
        "  можно получить только по протоколу производителя (нужны VID:PID и модель).",
        "• Строки с page 0xFF.. — служебные интерфейсы производителя: через них обычно и",
        "  запрашивают заряд.",
    ]
    return "\n".join(out)


def write_report(directory) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "diagnostics.txt"
    text = build_report()
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    base = Path(os.environ.get("LOCALAPPDATA", ".")) / "BatteryTray"
    p = write_report(base)
    print(p.read_text(encoding="utf-8"))
    print(f"\nОтчёт сохранён: {p}")
