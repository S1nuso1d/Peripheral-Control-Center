"""Диагностика: что система видит у подключённых устройств и почему заряд может быть недоступен.

Запуск (без Qt):   python diagnose.py
Или из меню приложения: «Диагностика устройств…».
Отчёт сохраняется в %LOCALAPPDATA%\\BatteryTray\\diagnostics.txt и открывается.
В отчёт не попадают серийные номера и полные Bluetooth-адреса — только VID/PID, названия
и технические признаки интерфейсов.
"""
import ctypes
import os
import platform
import sys
import time
from pathlib import Path

from device_inventory import discover_hid_interfaces, hid_available
from windows_device_inventory import discover_windows_devices

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


def section_battery_providers(force: bool = False) -> list:
    """Report provider state; deep scans run only in the standalone CLI mode."""
    lines = []
    app_module = sys.modules.get("battery_tray")
    app_status = getattr(app_module, "PROVIDER_STATUS", {}) if app_module else {}
    for name in ("bluetooth", "ble_gatt", "hid_battery", "xinput", "hidpp"):
        current = app_status.get(name)
        if current:
            lines.append(
                f'App provider {name}: {current.get("status")} | '
                f'зарядов прочитано: {current.get("read", 0)}'
            )
            if current.get("error"):
                lines.append(f'  ошибка: {current["error"]}')

    try:
        import ble_battery
        status = ble_battery.diagnostics()
        devices = (ble_battery.read_devices(force=True) if force else
                   ble_battery.read_devices() if status.get("status") != "not_scanned" else [])
        lines.append(
            f'BLE Battery Service: {status.get("status")} | '
            f'видно BLE: {status.get("scanned", 0)} | '
            f'кандидатов: {status.get("candidates", 0)} | '
            f'прочитано: {len(devices)}'
        )
        for device in devices:
            lines.append(f'  {device["name"]}: {device["battery"]}%')
        for error in status.get("errors", []):
            lines.append(f'  ошибка BLE: {error}')
    except Exception as exc:
        lines.append(f'BLE Battery Service: ошибка провайдера: {exc!r}')

    try:
        import hid_battery
        status = hid_battery.diagnostics()
        devices = (hid_battery.read_devices(force=True) if force else
                   hid_battery.read_devices() if status.get("status") != "not_scanned" else [])
        lines.append(
            f'Standard HID Battery Strength: {status.get("status")} | '
            f'интерфейсов: {status.get("interfaces", 0)} | '
            f'проверено: {status.get("candidates", 0)} | '
            f'прочитано: {len(devices)}'
        )
        for device in devices:
            lines.append(f'  {device["name"]}: {device["battery"]}%')
        for error in status.get("errors", []):
            lines.append(f'  ошибка HID: {error}')
    except Exception as exc:
        lines.append(f'Standard HID Battery Strength: ошибка провайдера: {exc!r}')

    if not app_status.get("hidpp"):
        lines.append("Logitech HID++: провайдер ещё не запускался в этом процессе")

    return lines or ["  (провайдеры не вернули результатов)"]


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


def build_report(force_provider_scan: bool = False) -> str:
    out = ["=== Peripheral Control Center: диагностика ===", ""]
    for title, fn in (("Система", section_system), ("Устройства Windows", section_pnp),
                      ("HID-интерфейсы (hidapi)", section_hid),
                      ("Провайдеры заряда (BLE / HID / Logitech)", 
                       lambda: section_battery_providers(force_provider_scan)),
                      ("XInput", section_xinput)):
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
        "• BLE Battery Service читается только у устройств, рекламирующих службу 0x180F;",
        "  отсутствие рекламы не доказывает, что у устройства нет GATT-батареи.",
        "• Standard HID Battery Strength — это HID Generic Device Controls 0x06/0x20.",
        "• Строки с page 0xFF.. — интерфейсы производителя; для них нужен протокол модели.",
    ]
    return "\n".join(out)


def write_report(directory, force_provider_scan: bool = False) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "diagnostics.txt"
    text = build_report(force_provider_scan=force_provider_scan)
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    base = Path(os.environ.get("LOCALAPPDATA", ".")) / "BatteryTray"
    p = write_report(base, force_provider_scan=True)
    print(p.read_text(encoding="utf-8"))
    print(f"\nОтчёт сохранён: {p}")
