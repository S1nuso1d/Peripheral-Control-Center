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

try:
    import hid  # pip install hidapi
except Exception:
    hid = None

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
KNOWN_USAGE_PAGES = {0x01: "Generic Desktop", 0x06: "Generic Device Controls (батарея)",
                     0x0C: "Consumer", 0xFF00: "Vendor-defined (часто HID++/служебный)",
                     0xFF01: "Vendor-defined", 0xFF02: "Vendor-defined", 0xFF43: "Vendor-defined"}


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
            f"Python: {sys.version.split()[0]}  hidapi: {'есть' if hid else 'НЕ установлен'}"]


def section_pnp() -> list:
    lines = []
    try:
        raw = _powershell(PS_PNP)
        data = json.loads(raw) if raw else []
    except Exception as e:
        return [f"Не удалось получить список устройств Windows: {e!r}"]
    if isinstance(data, dict):
        data = [data]

    lines.append("— Bluetooth-устройства: заряд, который знает Windows —")
    bt = [d for d in data if re.match(r"^(BTHENUM|BTHLE)\\DEV_", d.get("id", ""), re.I)]
    if not bt:
        lines.append("  (Bluetooth-устройств не найдено)")
    for d in bt:
        batt = d.get("battery")
        lines.append(f"  {d.get('name') or '?'}  | статус {d.get('status')}  | заряд: "
                     f"{str(batt) + '%' if batt is not None else 'Windows НЕ сообщает'}")

    lines.append("")
    lines.append("— USB/HID: пары VID:PID (так находят приёмники и донглы) —")
    seen = {}
    for d in data:
        m = VID_PID.search(d.get("id", ""))
        if m and d.get("id", "").upper().startswith(("USB", "HID")):
            key = (m.group(1).upper(), m.group(2).upper())
            seen.setdefault(key, set()).add(d.get("name") or d.get("cls") or "?")
    for (vid, pid), names in sorted(seen.items()):
        lines.append(f"  {vid}:{pid}  {'; '.join(sorted(names))}")
    if not seen:
        lines.append("  (не найдено)")
    return lines


def section_hid() -> list:
    if hid is None:
        return ["hidapi не установлен: pip install hidapi (без него HID-интерфейсы не показать)"]
    try:
        infos = hid.enumerate(0, 0)
    except Exception as e:
        return [f"hid.enumerate не удался: {e!r}"]
    rows = {}
    for i in infos:
        key = (i.get("vendor_id", 0), i.get("product_id", 0), i.get("usage_page", 0),
               i.get("usage", 0), i.get("interface_number", -1))
        rows[key] = (i.get("manufacturer_string") or "", i.get("product_string") or "")
    lines = []
    for (vid, pid, page, usage, iface), (man, prod) in sorted(rows.items()):
        flag = "  <== ARDOR?" if "ardor" in (man + prod).lower() else ""
        page_name = KNOWN_USAGE_PAGES.get(page, "")
        lines.append(f"  {vid:04X}:{pid:04X}  iface {iface}  page 0x{page:04X} usage 0x{usage:04X}"
                     f"  {man} / {prod}  {page_name}{flag}")
    return lines or ["  (HID-устройств не найдено)"]


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
    out = ["=== Battery Tray: диагностика ===", ""]
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
