"""Peripheral Control Center — мониторинг компьютерной периферии в Windows.

Источники данных (провайдеры):
  * bluetooth — DEVPKEY_Bluetooth_Battery из Windows;
  * ble_gatt  — стандартная BLE Battery Service (нужен bleak);
  * hid_battery — стандартные HID Battery Strength / Battery System (hidapi);
  * windows_pnp — батарейные свойства Windows PnP (в т.ч. грубый заряд/статус);
  * xinput    — геймпады Xbox (четыре категории заряда);
  * hidpp     — Logitech HID++ для совместимых приёмников (hidapi).
Новый источник = новая функция provider_xxx() в списке PROVIDERS.
История заряда (history.py) даёт оценку «хватит ещё ≈ N ч» и признак зарядки.

Запуск:  pip install PySide6   ->   python battery_tray.py
Данные и лог: %LOCALAPPDATA%\\BatteryTray
"""
import ctypes
import json
import logging
import os
import sys
import threading
import time
import uuid
from ctypes import wintypes as wt
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import (QDir, QLockFile, QObject, QPoint, QPointF, QPropertyAnimation,
                            QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor, QFont,
                           QFontMetrics, QGuiApplication, QIcon, QPainter, QPen, QPixmap,
                           QPolygonF)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

import hidpp
import ble_battery
import hid_battery
from windows_device_inventory import discover_windows_devices
import i18n
import taskbar
from history import History, format_hours
from i18n import tr
from settings_dialog import DevicesDialog
from device_inventory_dialog import DeviceInventoryDialog

APP_NAME = "BatteryTray"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
log = logging.getLogger(APP_NAME)


def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(DATA_DIR / "battery_tray.log", maxBytes=256_000,
                            backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


# --- Настройки ---------------------------------------------------------------

DEFAULTS = {"refresh_sec": 60, "low_level": 15, "show_offline": False, "hidden": [],
            "hidpp": True, "ble_battery": True, "hid_battery": True,
            "windows_pnp": True,
            "widget": True, "widget_dx": 0, "widget_dy": 0,
            "names": {}, "kinds": {}, "notify_charged": True,
            "tray_mode": "single", "lang": "auto"}


class Settings:
    def __init__(self):
        self.path = DATA_DIR / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def set(self, key, value):
        self.data[key] = value
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception:
            log.exception("cannot save settings")


# --- Низкоуровневый доступ к Windows ----------------------------------------

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wt.ULONG)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID), ("DevInst", wt.DWORD),
                ("Reserved", ctypes.c_size_t)]


def _key(guid: str, pid: int) -> DEVPROPKEY:
    u = uuid.UUID(guid)
    g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    return DEVPROPKEY(g, pid)


K_BATTERY = _key("{104EA319-6EE2-4701-BD47-8DDBF425BBE5}", 2)    # DEVPKEY_Bluetooth_Battery
K_CONNECTED = _key("{83DA6326-97A6-4088-9453-A1923F573B29}", 15)  # IsConnected
K_COD = _key("{2BD67D8B-8BEB-48D5-87E0-6CDA3428040A}", 10)        # Class of Device
K_FRIENDLY = _key("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)   # Friendly name
K_NAME = _key("{B725F130-47EF-101A-A5F1-02608C9EEBAC}", 10)       # DEVPKEY_NAME

DIGCF_PRESENT, DIGCF_ALLCLASSES = 0x2, 0x4
CR_BUFFER_SMALL = 0x1A
_api = {}


def _load_api():
    if _api:
        return _api
    sp = ctypes.WinDLL("setupapi", use_last_error=True)
    cm = ctypes.WinDLL("cfgmgr32")
    sp.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
    sp.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sp.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wt.DWORD,
                                         ctypes.POINTER(SP_DEVINFO_DATA)]
    sp.SetupDiEnumDeviceInfo.restype = wt.BOOL
    sp.SetupDiGetDeviceInstanceIdW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA),
                                               wt.LPWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    sp.SetupDiGetDeviceInstanceIdW.restype = wt.BOOL
    sp.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    sp.SetupDiDestroyDeviceInfoList.restype = wt.BOOL
    cm.CM_Get_DevNode_PropertyW.argtypes = [wt.DWORD, ctypes.POINTER(DEVPROPKEY),
                                            ctypes.POINTER(wt.ULONG), ctypes.c_void_p,
                                            ctypes.POINTER(wt.ULONG), wt.ULONG]
    cm.CM_Get_DevNode_PropertyW.restype = wt.DWORD
    _api.update(sp=sp, cm=cm)
    return _api


def _prop(devinst: int, key: DEVPROPKEY):
    """Свойство устройства как bytes или None."""
    cm = _load_api()["cm"]
    ptype, size = wt.ULONG(0), wt.ULONG(0)
    r = cm.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(key), ctypes.byref(ptype),
                                    None, ctypes.byref(size), 0)
    if r not in (0, CR_BUFFER_SMALL) or size.value == 0:
        return None
    buf = (ctypes.c_ubyte * size.value)()
    r = cm.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(key), ctypes.byref(ptype),
                                    buf, ctypes.byref(size), 0)
    return bytes(buf[:size.value]) if r == 0 else None


def _str_prop(devinst: int, key: DEVPROPKEY) -> str:
    raw = _prop(devinst, key)
    return raw.decode("utf-16-le", errors="ignore").rstrip("\x00").strip() if raw else ""


def _bt_nodes():
    """Узлы BTHENUM/BTHLE вида ...\\DEV_xxxx: (instance_id, devinst)."""
    sp = _load_api()["sp"]
    invalid = ctypes.c_void_p(-1).value
    for enumerator in ("BTHENUM", "BTHLE"):
        h = sp.SetupDiGetClassDevsW(None, enumerator, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
        if not h or h == invalid:
            continue
        try:
            i = 0
            while True:
                info = SP_DEVINFO_DATA()
                info.cbSize = ctypes.sizeof(info)
                if not sp.SetupDiEnumDeviceInfo(h, i, ctypes.byref(info)):
                    break
                i += 1
                buf = ctypes.create_unicode_buffer(512)
                if sp.SetupDiGetDeviceInstanceIdW(h, ctypes.byref(info), buf, 512, None):
                    if "\\DEV_" in buf.value.upper():
                        yield buf.value, info.DevInst
        finally:
            sp.SetupDiDestroyDeviceInfoList(h)


# --- Определение типа устройства ----------------------------------------------

def kind_from_cod(cod: int):
    """Тип по Bluetooth Class of Device (если Windows его знает)."""
    major = (cod >> 8) & 0x1F
    if major == 4:
        return "headphones"
    if major == 2:
        return "phone"
    if major == 5:
        sub = (cod >> 6) & 0x3
        if sub in (1, 3):
            return "keyboard"
        if sub == 2:
            return "mouse"
        if ((cod >> 2) & 0xF) in (1, 2):
            return "gamepad"
    return None


def guess_kind(name: str) -> str:
    """Запасной вариант: тип по названию."""
    n = name.lower()
    table = [
        ("headphones", ("buds", "head", "airpod", "earb", "earphone", "wh-", "wf-",
                        "jbl", "bose", "наушник")),
        ("mouse", ("mouse", "mx master", "mx anywhere", "pebble", "мыш")),
        ("keyboard", ("keyboard", "keys", "k380", "клав")),
        ("gamepad", ("controller", "gamepad", "dualsense", "dualshock", "xbox", "джойстик")),
        ("phone", ("iphone", "phone", "galaxy", "pixel")),
    ]
    for kind, words in table:
        if any(w in n for w in words):
            return kind
    return "device"


# --- Провайдеры данных -------------------------------------------------------

def provider_bluetooth() -> list:
    out = []
    for iid, dev in _bt_nodes():
        raw = _prop(dev, K_BATTERY)
        if not raw or raw[0] > 100:
            continue
        conn = _prop(dev, K_CONNECTED)
        # если Windows не сообщает статус подключения — считаем устройство подключённым
        connected = True if not conn else bool(conn[0])
        name = _str_prop(dev, K_FRIENDLY) or _str_prop(dev, K_NAME) or tr("device")
        cod_raw = _prop(dev, K_COD)
        kind = None
        if cod_raw and len(cod_raw) >= 4:
            kind = kind_from_cod(int.from_bytes(cod_raw[:4], "little"))
        out.append({"id": iid, "name": name, "battery": raw[0], "connected": connected,
                    "kind": kind or guess_kind(name), "source": "bluetooth"})
    return out


class XINPUT_BATTERY_INFORMATION(ctypes.Structure):
    _fields_ = [("BatteryType", ctypes.c_ubyte), ("BatteryLevel", ctypes.c_ubyte)]


def provider_xinput() -> list:
    if "xinput" not in _api:
        _api["xinput"] = None
        for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                _api["xinput"] = ctypes.WinDLL(dll)
                break
            except OSError:
                continue
    xi = _api["xinput"]
    if xi is None:
        return []
    out = []
    labels = (tr("lvl_empty"), tr("lvl_low"), tr("lvl_medium"), tr("lvl_full"))
    percents = (10, 35, 65, 100)
    for idx in range(4):
        info = XINPUT_BATTERY_INFORMATION()
        if xi.XInputGetBatteryInformation(idx, 0, ctypes.byref(info)) != 0:
            continue
        if info.BatteryType in (0, 1, 0xFF):  # нет / проводной / неизвестно
            continue
        lvl = min(info.BatteryLevel, 3)
        out.append({"id": f"xinput:{idx}", "name": tr("xbox", idx + 1),
                    "battery": percents[lvl], "label": labels[lvl], "connected": True,
                    "kind": "gamepad", "source": "xinput"})
    return out


def provider_logitech() -> list:
    out = hidpp.read_devices()
    for d in out:
        d["kind"] = d["kind"] or guess_kind(d["name"])
    return out


def provider_ble_battery() -> list:
    out = ble_battery.read_devices()
    for device in out:
        device["kind"] = device.get("kind") or guess_kind(device["name"])
    return out


def provider_hid_battery() -> list:
    out = hid_battery.read_devices()
    for device in out:
        device["kind"] = device.get("kind") or guess_kind(device["name"])
    return out


_windows_battery_cache = []
_windows_battery_cache_at = 0.0
_windows_battery_cache_lock = threading.Lock()


def provider_windows_pnp() -> list:
    """Read Windows' published battery values with a bounded PnP refresh rate."""
    global _windows_battery_cache, _windows_battery_cache_at
    with _windows_battery_cache_lock:
        now = time.monotonic()
        if _windows_battery_cache_at and now - _windows_battery_cache_at < 120:
            return [dict(device) for device in _windows_battery_cache]

    # Do not hold the cache lock during PowerShell / PnP enumeration: a manual
    # refresh from the GUI must never wait for this potentially slow operation.
    devices = discover_windows_devices()
    out = []
    for device in devices:
        if device.get("battery") is None or not device.get("connected"):
            continue
        kind = device.get("kind") or guess_kind(device["name"])
        item = {
            "id": device["id"],
            "name": device["name"],
            "battery": device["battery"],
            "connected": True,
            "kind": kind,
            "source": "windows_pnp",
            "battery_source": device.get("battery_source"),
            "battery_precision": device.get("battery_precision", "reported"),
        }
        if device.get("charging_known"):
            item["charging"] = bool(device.get("charging"))
            item["charging_known"] = True
        if device.get("battery_precision") == "coarse":
            item["label"] = {
                5: tr("lvl_critical"),
                18: tr("lvl_low"),
                60: tr("lvl_medium"),
                95: tr("lvl_full"),
            }.get(device["battery"], tr("lvl_medium"))
        out.append(item)

    with _windows_battery_cache_lock:
        _windows_battery_cache = out
        _windows_battery_cache_at = time.monotonic()
        return [dict(device) for device in _windows_battery_cache]


PROVIDERS = [
    ("bluetooth", provider_bluetooth),
    ("ble_gatt", provider_ble_battery),
    ("hid_battery", provider_hid_battery),
    ("windows_pnp", provider_windows_pnp),
    ("xinput", provider_xinput),
    ("hidpp", provider_logitech),
]
DISABLED_PROVIDERS: set = set()
PROVIDER_STATUS: dict = {}


def collect_devices() -> list:
    items = []
    PROVIDER_STATUS.clear()
    for name, fn in PROVIDERS:
        if name in DISABLED_PROVIDERS:
            PROVIDER_STATUS[name] = {"status": "disabled", "read": 0}
            continue
        started = time.monotonic()
        try:
            found = fn()
            items += found
            PROVIDER_STATUS[name] = {
                "status": "ok" if found else "no_data",
                "read": len(found),
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        except Exception as exc:
            PROVIDER_STATUS[name] = {
                "status": "error", "read": 0,
                "error": f"{type(exc).__name__}: {exc}"[:240],
            }
            log.exception("provider %s failed", name)
    # Геймпад, который Windows уже показывает по Bluetooth (с процентами), из XInput не берём
    if any(d["kind"] == "gamepad" and d["connected"] for d in items if d["source"] == "bluetooth"):
        items = [d for d in items if d["source"] != "xinput"]
    best = {}
    for d in items:  # одно устройство может быть и в BTHENUM, и в BTHLE
        cur = best.get(d["name"].lower())
        if cur is None or (d["connected"] and not cur["connected"]):
            best[d["name"].lower()] = d
    result = sorted(best.values(), key=lambda d: (not d["connected"], d["name"].lower()))
    return result


# --- Оформление ------------------------------------------------------------------

GLYPHS = {"headphones": "\uE7F6", "mouse": "\uE962", "keyboard": "\uE765",
          "gamepad": "\uE7FC", "phone": "\uE8EA", "device": "\uE702"}
ICON_FAMILIES = ["Segoe Fluent Icons", "Segoe MDL2 Assets"]

DARK = dict(bg=QColor(30, 30, 34, 245), border=QColor(255, 255, 255, 28),
            fg=QColor("#f1f5f9"), dim=QColor("#64748b"), track=QColor(255, 255, 255, 25),
            empty=QColor("#475569"), muted=QColor("#94a3b8"), light=False)
LIGHT = dict(bg=QColor(246, 246, 248, 248), border=QColor(0, 0, 0, 30),
             fg=QColor("#0f172a"), dim=QColor("#94a3b8"), track=QColor(0, 0, 0, 22),
             empty=QColor("#cbd5e1"), muted=QColor("#64748b"), light=True)


def system_theme() -> dict:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return LIGHT if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 1 else DARK
    except Exception:
        return DARK


def level_color(level: int, light: bool = False) -> QColor:
    if level < 20:
        return QColor("#dc2626" if light else "#f87171")
    if level < 50:
        return QColor("#d97706" if light else "#fbbf24")
    return QColor("#16a34a" if light else "#4ade80")


def make_tray_icon(level, approximate: bool = False) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(28, 28, 32))
    p.drawRoundedRect(QRectF(0, 0, 64, 64), 16, 16)
    if level is None:
        f = QFont()
        f.setFamilies(ICON_FAMILIES)
        f.setPixelSize(38)
        p.setFont(f)
        p.setPen(QColor("#cbd5e1"))
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, GLYPHS["device"])
    else:
        f = QFont("Segoe UI", weight=QFont.Bold)
        f.setPixelSize((30 if level < 100 else 26) if approximate
                       else (46 if level < 100 else 34))
        p.setFont(f)
        p.setPen(level_color(level))
        text = f"≈{level}" if approximate else str(level)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


def taskbar_is_light() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except Exception:
        return False


def clamp(v, lo, hi):
    return max(lo, min(v, hi)) if lo <= hi else lo


class Popup(QWidget):
    """Карточка со списком устройств. Клик по строке раскрывает график заряда,
    клик по графику переключает период (24 ч → 3 дня → 7 дней)."""
    W, PAD, ROW_H, CHART_H = 300, 14, 68, 104
    PERIODS = (24, 72, 168)

    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.theme = DARK
        self.last_hidden = 0.0
        self.devices = []
        self.expanded = None  # orig-имя устройства с раскрытым графиком
        self.period = 24
        self._anchor = None
        self._anim = None
        self.set_devices([])

    def hideEvent(self, e):
        self.last_hidden = time.monotonic()
        super().hideEvent(e)

    def row_height(self, d) -> int:
        return self.ROW_H + (self.CHART_H if d.get("orig") == self.expanded else 0)

    def set_devices(self, devices):
        self.devices = devices
        if self.expanded not in {d.get("orig") for d in devices}:
            self.expanded = None
        total = sum(self.row_height(d) for d in devices) if devices else self.ROW_H
        self.setFixedSize(self.W, self.PAD * 2 + total)
        if self.isVisible() and self._anchor is not None:
            self._place(self._anchor)  # высота изменилась — пересчитать положение
        self.update()

    def _place(self, anchor: QPoint):
        """Ставит карточку у края экрана, где реально находится панель задач."""
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        full, area, m = screen.geometry(), screen.availableGeometry(), 12
        w, h = self.width(), self.height()
        cx = clamp(anchor.x() - w // 2, area.left() + m, area.right() - w - m)
        cy = clamp(anchor.y() - h // 2, area.top() + m, area.bottom() - h - m)
        if area.top() > full.top():
            x, y = cx, area.top() + m
        elif area.left() > full.left():
            x, y = area.left() + m, cy
        elif area.right() < full.right():
            x, y = area.right() - w - m, cy
        else:
            x, y = cx, area.bottom() - h - m
        self.move(x, y)

    def show_near(self, anchor: QPoint):
        self.theme = system_theme()
        self._anchor = anchor
        self._place(anchor)
        self.setWindowOpacity(0.0)
        self.show()
        self._anim = QPropertyAnimation(self, b"windowOpacity")  # мягкое появление
        self._anim.setDuration(120)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def mousePressEvent(self, e):
        y, top = e.position().y(), self.PAD
        for d in self.devices:
            h = self.row_height(d)
            if top <= y < top + h:
                if d.get("orig") == self.expanded and y >= top + self.ROW_H:
                    i = self.PERIODS.index(self.period)  # клик по графику: следующий период
                    self.period = self.PERIODS[(i + 1) % len(self.PERIODS)]
                else:
                    self.expanded = None if d.get("orig") == self.expanded else d.get("orig")
                self.set_devices(self.devices)
                return
            top += h

    def paintEvent(self, _):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(t["border"], 1))
        p.setBrush(t["bg"])
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 14, 14)

        if not self.devices:
            p.setPen(t["muted"])
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignCenter,
                       tr("no_devices_popup"))
            return

        icon_font = QFont()
        icon_font.setFamilies(ICON_FAMILIES)
        icon_font.setPixelSize(22)
        top = self.PAD
        for d in self.devices:
            self._paint_row(p, t, d, top, icon_font)
            top += self.row_height(d)

    def _paint_row(self, p, t, d, top, icon_font):
        alive = d["connected"]
        fg = t["fg"] if alive else t["dim"]
        accent = level_color(d["battery"], t["light"]) if alive else t["empty"]
        left, right = self.PAD + 46, self.width() - self.PAD
        expanded = d.get("orig") == self.expanded

        p.setFont(icon_font)
        p.setPen(fg)
        p.drawText(QRectF(self.PAD, top, 36, self.ROW_H), Qt.AlignCenter,
                   GLYPHS.get(d["kind"], GLYPHS["device"]))
        # шеврон: подсказка, что строку можно раскрыть
        cx, cy, k = self.PAD + 18, top + self.ROW_H - 9, (2 if expanded else -2)
        p.setPen(QPen(t["dim"], 1.4))
        p.drawLine(QPointF(cx - 4, cy - k), QPointF(cx, cy + k))
        p.drawLine(QPointF(cx, cy + k), QPointF(cx + 4, cy - k))

        p.setFont(QFont("Segoe UI", 10))
        p.setPen(fg)
        name = p.fontMetrics().elidedText(d["name"], Qt.ElideRight, right - left - 70)
        p.drawText(QRectF(left, top + 8, right - left - 68, 20),
                   Qt.AlignLeft | Qt.AlignVCenter, name)

        p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        p.setPen(accent if alive else fg)
        p.drawText(QRectF(right - 68, top + 8, 68, 20), Qt.AlignRight | Qt.AlignVCenter,
                   d.get("label") or f"{d['battery']}%")

        bar = QRectF(left, top + 36, right - left, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(t["track"])
        p.drawRoundedRect(bar, 2.5, 2.5)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * d["battery"] / 100,
                                 bar.height()), 2.5, 2.5)

        note = None
        if alive and d.get("charging"):
            note = tr("charging")
        elif alive and d.get("hours_left"):
            note = format_hours(d["hours_left"])
        if note:
            tx, ny = left, top + 46
            if d.get("charging"):  # маленькая молния
                p.setPen(Qt.NoPen)
                p.setBrush(level_color(100, t["light"]))
                p.drawPolygon(QPolygonF([QPointF(left + x, ny + y) for x, y in
                                         ((5, 0), (0, 7), (3.5, 7), (2, 13), (8, 5), (4.5, 5))]))
                tx = left + 13
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(t["muted"])
            p.drawText(QRectF(tx, ny, right - tx - 90, 14), Qt.AlignLeft | Qt.AlignVCenter, note)

        if not expanded:  # в свёрнутом виде — маленький график за 24 часа
            spark = d.get("spark") or []
            if alive and len(spark) >= 3:
                now = time.time()
                t0 = now - 24 * 3600
                x0, x1, sy0, sy1 = right - 84, right, top + 47, top + 59
                pts = [QPointF(x0 + (ts - t0) / (now - t0) * (x1 - x0),
                               sy1 - lv / 100 * (sy1 - sy0)) for ts, lv in spark if ts >= t0]
                if len(pts) >= 3:
                    c = QColor(accent)
                    c.setAlpha(200)
                    p.setPen(QPen(c, 1.4))
                    p.setBrush(Qt.NoBrush)
                    p.drawPolyline(QPolygonF(pts))
        else:
            self._paint_chart(p, t, d, top + self.ROW_H, accent)

    def _paint_chart(self, p, t, d, top, accent):
        """Большой график: шкала 0–100%, окно времени = выбранный период."""
        x0, x1 = self.PAD + 2, self.width() - self.PAD
        y0, y1 = top + 4, top + self.CHART_H - 24
        now = time.time()
        span = self.period * 3600
        t_start = now - span

        p.setPen(QPen(t["track"], 1))
        for lv in (0, 50, 100):
            y = y1 - lv / 100 * (y1 - y0)
            p.drawLine(QPointF(x0, y), QPointF(x1, y))

        pts = [(ts, lv) for ts, lv in d.get("series", []) if ts >= t_start]
        p.setFont(QFont("Segoe UI", 8))
        if len(pts) >= 2:
            qp = [QPointF(x0 + (ts - t_start) / span * (x1 - x0), y1 - lv / 100 * (y1 - y0))
                  for ts, lv in pts]
            fill = QColor(accent)
            fill.setAlpha(40)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPolygon(QPolygonF(qp + [QPointF(qp[-1].x(), y1), QPointF(qp[0].x(), y1)]))
            p.setPen(QPen(accent, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(qp))
        else:
            p.setPen(t["muted"])
            p.drawText(QRectF(x0, y0, x1 - x0, y1 - y0), Qt.AlignCenter, tr("chart_empty"))

        p.setPen(t["muted"])
        p.drawText(QRectF(x0, y1 + 4, 120, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("chart_ago", tr(f"p{self.period}")))
        p.drawText(QRectF(x1 - 120, y1 + 4, 120, 14), Qt.AlignRight | Qt.AlignVCenter,
                   tr("chart_now"))


class TaskbarWidget(QWidget):
    """Компактный виджет рядом с треем: иконка и процент для каждого устройства.

    Клик — карточка, правая кнопка — меню, перетаскивание — подстройка положения.
    """
    H, PAD, GAP, ICON = 32, 8, 12, 16
    clicked = Signal(QPoint)
    context = Signal(QPoint)
    moving = Signal()
    moved = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.devices, self.widths = [], []
        self.light, self.hover = False, False
        self.dx = self.dy = 0
        self._press, self._drag = None, False
        self.text_font = QFont("Segoe UI", 9, QFont.DemiBold)
        self.icon_font = QFont()
        self.icon_font.setFamilies(ICON_FAMILIES)
        self.icon_font.setPixelSize(15)
        self.set_devices([])

    def set_devices(self, devices):
        self.devices = sorted(devices, key=lambda d: d["battery"])[:4]
        fm = QFontMetrics(self.text_font)
        self.widths = [self.ICON + 4 + fm.horizontalAdvance(
            d.get("label") or f"{d['battery']}%") for d in self.devices]
        total = self.PAD * 2 + sum(self.widths) + self.GAP * max(len(self.widths) - 1, 0)
        self.setFixedSize(max(total, 1), self.H)
        self.light = taskbar_is_light()
        self.update()

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fg = QColor("#0f172a") if self.light else QColor("#f1f5f9")
        bg = QColor(fg)
        bg.setAlpha(24 if self.hover else 1)  # alpha=1: окно остаётся кликабельным
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 6, 6)
        x = self.PAD
        for d, w in zip(self.devices, self.widths):
            p.setFont(self.icon_font)
            p.setPen(fg)
            p.drawText(QRectF(x, 0, self.ICON, self.height()), Qt.AlignCenter,
                       GLYPHS.get(d["kind"], GLYPHS["device"]))
            p.setFont(self.text_font)
            p.setPen(level_color(d["battery"], self.light))
            p.drawText(QRectF(x + self.ICON + 4, 0, w - self.ICON - 4, self.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, d.get("label") or f"{d['battery']}%")
            x += w + self.GAP

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.dx, self.dy)
            self._drag = False

    def mouseMoveEvent(self, e):
        if self._press and e.buttons() & Qt.LeftButton:
            p0, dx0, dy0 = self._press
            d = e.globalPosition().toPoint() - p0
            if self._drag or d.manhattanLength() > 8:
                self._drag = True
                self.dx, self.dy = dx0 + d.x(), dy0 + d.y()
                self.moving.emit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            self.context.emit(e.globalPosition().toPoint())
        elif e.button() == Qt.LeftButton and self._press:
            if self._drag:
                self.moved.emit()
            else:
                self.clicked.emit(self.mapToGlobal(self.rect().center()))
            self._press, self._drag = None, False


# --- Логика приложения --------------------------------------------------------------

class Monitor(QObject):
    updated = Signal(list)

    def __init__(self):
        super().__init__()
        self._busy = False
        self._last = None

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            devices = collect_devices()
            sig = [(d["name"], d["battery"], d["connected"]) for d in devices]
            if sig != self._last:  # в лог пишем только изменения
                self._last = sig
                log.info("devices: %s", sig)
            self.updated.emit(devices)
        except Exception:
            log.exception("refresh failed")
        finally:
            self._busy = False


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except Exception:
        return False


def set_autostart(on: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE) as k:
        if on:
            if getattr(sys, "frozen", False):  # собранный .exe
                cmd = f'"{sys.executable}"'
            else:
                exe = sys.executable.replace("python.exe", "pythonw.exe")
                cmd = f'"{exe}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


class App:
    MAX_DEVICE_TRAYS = 5

    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)

        # один экземпляр приложения
        self.lock = QLockFile(QDir.temp().filePath(f"{APP_NAME}.lock"))
        if not self.lock.tryLock(100):
            sys.exit(0)

        self.settings = Settings()
        i18n.set_language(self.settings["lang"])
        if not self.settings["hidpp"]:
            DISABLED_PROVIDERS.add("hidpp")
        if not self.settings["ble_battery"]:
            DISABLED_PROVIDERS.add("ble_gatt")
        if not self.settings["hid_battery"]:
            DISABLED_PROVIDERS.add("hid_battery")
        if not self.settings["windows_pnp"]:
            DISABLED_PROVIDERS.add("windows_pnp")
        self.devices = []
        self.notified, self.notified_full = set(), set()
        self.dev_trays = {}  # orig-имя -> отдельная иконка в трее
        self.history = History(DATA_DIR / "history.json")

        self.popup = Popup()
        self.tray = QSystemTrayIcon(make_tray_icon(None))
        self.tray.setToolTip(tr("loading"))
        self.tray.activated.connect(lambda reason: self.on_activated(reason, self.tray))
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.build_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.widget = TaskbarWidget()
        self.widget.dx, self.widget.dy = self.settings["widget_dx"], self.settings["widget_dy"]
        self.widget.clicked.connect(self.toggle_popup)
        self.widget.context.connect(self.menu.popup)
        self.widget.moving.connect(self.place_widget)
        self.widget.moved.connect(self.save_widget_offsets)
        self.place_timer = QTimer()  # раз в секунду: положение и «поверх всех»
        self.place_timer.timeout.connect(self.place_widget)
        self.place_timer.start(1000)
        self._logged_rects = False

        self.monitor = Monitor()
        self.monitor.updated.connect(self.on_updated)
        self.timer = QTimer()
        self.timer.timeout.connect(self.monitor.refresh)
        self.timer.start(self.settings["refresh_sec"] * 1000)
        self.monitor.refresh()
        log.info("started")

    # --- меню (пересобирается при каждом открытии) ---

    def build_menu(self):
        m = self.menu
        m.clear()
        m.addAction(tr("m_refresh"), self.refresh_devices)
        m.addAction(tr("m_inventory"), self.open_inventory_dialog)
        m.addAction(tr("m_diagnostics"), self.open_diagnostics_report)

        sub = m.addMenu(tr("m_devices"))
        if not self.devices:
            sub.addAction(tr("m_no_devices")).setEnabled(False)
        for d in self.devices:
            act = sub.addAction(d["name"])
            act.setCheckable(True)
            act.setChecked(d["orig"] not in self.settings["hidden"])
            act.toggled.connect(lambda on, n=d["orig"]: self.set_visible(n, on))
        sub.addSeparator()
        sub.addAction(tr("m_configure"), self.open_devices_dialog)

        self.check_item(m, "m_show_offline", self.settings["show_offline"], self.set_show_offline)
        self.check_item(m, "m_per_device", self.settings["tray_mode"] == "per_device",
                        self.set_tray_mode)
        self.check_item(m, "m_widget", self.settings["widget"], self.set_widget)
        m.addAction(tr("m_widget_reset"), self.reset_widget)
        self.check_item(m, "m_notify_full", self.settings["notify_charged"],
                        lambda on: self.settings.set("notify_charged", on))
        self.check_item(m, "m_hidpp", self.settings["hidpp"], self.set_hidpp)
        self.check_item(m, "m_ble_battery", self.settings["ble_battery"],
                        self.set_ble_battery)
        self.check_item(m, "m_hid_battery", self.settings["hid_battery"],
                        self.set_hid_battery)
        self.check_item(m, "m_windows_pnp", self.settings["windows_pnp"],
                        self.set_windows_pnp)

        self.radio_menu(m, tr("m_interval"), "refresh_sec",
                        [(v, tr(f"i{v}")) for v in (30, 60, 120, 300)], self.set_interval)
        self.radio_menu(m, tr("m_threshold"), "low_level",
                        [(v, f"{v}%") for v in (10, 15, 20, 30)],
                        lambda v: self.settings.set("low_level", v))
        self.radio_menu(m, tr("m_language"), "lang",
                        [("auto", tr("lang_auto")), ("ru", "Русский"), ("en", "English")],
                        self.set_language)

        self.check_item(m, "m_autostart", autostart_enabled(), self.safe_autostart)
        m.addAction(tr("m_log"), lambda: os.startfile(str(DATA_DIR)))
        m.addSeparator()
        m.addAction(tr("m_quit"), self.qt.quit)

    @staticmethod
    def check_item(menu, key, checked, handler):
        act = menu.addAction(tr(key))
        act.setCheckable(True)
        act.setChecked(checked)
        act.toggled.connect(handler)

    def radio_menu(self, parent, title, key, options, setter):
        sub = parent.addMenu(title)
        group = QActionGroup(sub)
        for value, text in options:
            act = QAction(text, sub, checkable=True)
            act.setChecked(self.settings[key] == value)
            act.triggered.connect(lambda _=False, v=value: setter(v))
            group.addAction(act)
            sub.addAction(act)

    def open_inventory_dialog(self):
        """Show every HID interface, even when no battery provider supports it."""
        dialog = DeviceInventoryDialog()
        dialog.exec()

    def open_diagnostics_report(self):
        """Generate and open the full Windows / Bluetooth / HID diagnostic report."""
        try:
            from diagnose import write_report
            report = write_report(DATA_DIR)
            os.startfile(str(report))
        except Exception:
            log.exception("cannot create diagnostics report")
            self.notify(tr("diagnostics_error_title"), tr("diagnostics_error_message"),
                        QSystemTrayIcon.Warning)

    # --- обработчики настроек ---

    def set_visible(self, orig, on):
        hidden = set(self.settings["hidden"])
        hidden.discard(orig) if on else hidden.add(orig)
        self.settings.set("hidden", sorted(hidden))
        self.render()

    def open_devices_dialog(self):
        dlg = DevicesDialog(self.devices, self.settings)
        if dlg.exec():
            names, kinds, hidden = dlg.result_data()
            self.settings.set("names", names)
            self.settings.set("kinds", kinds)
            self.settings.set("hidden", hidden)
            self.apply_overrides(self.devices)
            self.render()

    def set_show_offline(self, on):
        self.settings.set("show_offline", on)
        self.render()

    def set_tray_mode(self, on):
        self.settings.set("tray_mode", "per_device" if on else "single")
        self.render()

    def set_language(self, code):
        self.settings.set("lang", code)
        i18n.set_language(code)
        self.render()

    def set_widget(self, on):
        self.settings.set("widget", on)
        self.place_widget()

    def reset_widget(self):
        self.widget.dx = self.widget.dy = 0
        self.save_widget_offsets()
        self.place_widget()

    def save_widget_offsets(self):
        self.settings.set("widget_dx", self.widget.dx)
        self.settings.set("widget_dy", self.widget.dy)

    def set_hidpp(self, on):
        self.settings.set("hidpp", on)
        (DISABLED_PROVIDERS.discard if on else DISABLED_PROVIDERS.add)("hidpp")
        self.monitor.refresh()

    def set_ble_battery(self, on):
        self.settings.set("ble_battery", on)
        (DISABLED_PROVIDERS.discard if on else DISABLED_PROVIDERS.add)("ble_gatt")
        ble_battery.invalidate_cache()
        self.monitor.refresh()

    def set_hid_battery(self, on):
        self.settings.set("hid_battery", on)
        (DISABLED_PROVIDERS.discard if on else DISABLED_PROVIDERS.add)("hid_battery")
        hid_battery.invalidate_cache()
        self.monitor.refresh()

    def set_windows_pnp(self, on):
        self.settings.set("windows_pnp", on)
        (DISABLED_PROVIDERS.discard if on else DISABLED_PROVIDERS.add)("windows_pnp")
        self.invalidate_windows_battery_cache()
        self.monitor.refresh()

    @staticmethod
    def invalidate_windows_battery_cache():
        global _windows_battery_cache_at
        with _windows_battery_cache_lock:
            _windows_battery_cache_at = 0.0

    def refresh_devices(self):
        """Force BLE, HID and Windows PnP providers to query hardware on refresh."""
        ble_battery.invalidate_cache()
        hid_battery.invalidate_cache()
        self.invalidate_windows_battery_cache()
        self.monitor.refresh()

    def set_interval(self, sec):
        self.settings.set("refresh_sec", sec)
        self.timer.setInterval(sec * 1000)

    def safe_autostart(self, on):
        try:
            set_autostart(on)
        except Exception:
            log.exception("autostart failed")

    # --- мини-виджет у панели задач ---

    def place_widget(self):
        """Показать виджет слева от трея (или скрыть, если не нужен/не получается)."""
        w = self.widget
        live = [d for d in self.visible_devices() if d["connected"]]
        try:
            if not self.settings["widget"] or not live or taskbar.fullscreen_app_active():
                w.hide()
                return
            rects = taskbar.taskbar_rects()
            if rects is None:
                w.hide()
                return
            tb, notify = rects
            if not self._logged_rects:
                self._logged_rects = True
                log.info("taskbar=%s notify=%s", tb, notify)
            screen = QGuiApplication.primaryScreen()
            dpr, g = screen.devicePixelRatio(), screen.geometry()
            pos = taskbar.compute_position(
                tb, notify, round(w.width() * dpr), round(w.height() * dpr),
                round(w.dx * dpr), round(w.dy * dpr),
                taskbar.Rect(0, 0, round(g.width() * dpr), round(g.height() * dpr)))
            if pos is None:
                w.hide()
                return
            if not w.isVisible():
                w.show()
            taskbar.set_topmost(int(w.winId()), *pos)
        except Exception:
            log.exception("place_widget failed")
            w.hide()

    # --- данные ---

    def apply_overrides(self, devices):
        """Свои названия и типы значков (исходное имя сохраняется в d['orig'])."""
        names, kinds = self.settings["names"], self.settings["kinds"]
        for d in devices:
            d.setdefault("orig", d["name"])
            d.setdefault("auto_kind", d["kind"])
            d["name"] = names.get(d["orig"]) or d["orig"]
            d["kind"] = kinds.get(d["orig"]) or d["auto_kind"]

    def visible_devices(self):
        return [d for d in self.devices
                if d["orig"] not in self.settings["hidden"]
                and (d["connected"] or self.settings["show_offline"])]

    def on_updated(self, devices):
        now = time.time()
        self.apply_overrides(devices)
        for d in devices:
            known = d.get("charging_known", False)  # провайдер сам знает статус зарядки
            d["hours_left"], d["series"], d["spark"] = None, [], []
            if not known:
                d["charging"] = False
            if not d["connected"]:
                continue
            key = d["orig"]  # история привязана к исходному имени: переименование её не теряет
            self.history.add(key, d["battery"], now)
            d["series"] = self.history.series(key, 168, now)
            d["spark"] = [pt for pt in d["series"] if pt[0] >= now - 86400]
            if not known:
                d["charging"] = self.history.charging(key, now)
            if not d["charging"] and not d.get("label"):  # у XInput уровни слишком грубые
                d["hours_left"] = self.history.hours_left(key)
        self.history.save()
        self.devices = devices
        self.render()
        self.check_notifications()

    def render(self):
        vis = self.visible_devices()
        self.popup.set_devices(vis)
        live = [d for d in vis if d["connected"]]
        if live:
            lowest = min(live, key=lambda device: device["battery"])
            self.tray.setIcon(make_tray_icon(
                lowest["battery"], lowest.get("battery_precision") == "coarse"
            ))
            self.tray.setToolTip("\n".join(self.tooltip_line(d) for d in live))
        else:
            self.tray.setIcon(make_tray_icon(None))
            self.tray.setToolTip(tr("tray_none"))
        self.widget.set_devices(live)
        self.sync_device_trays(live)
        self.place_widget()

    def sync_device_trays(self, live):
        """Режим «иконка на каждое устройство»: до 5 самых разряженных."""
        want = []
        if self.settings["tray_mode"] == "per_device":
            want = sorted(live, key=lambda d: d["battery"])[:self.MAX_DEVICE_TRAYS]
        keep = {d["orig"] for d in want}
        for key in [k for k in self.dev_trays if k not in keep]:
            old = self.dev_trays.pop(key)
            old.hide()
            old.deleteLater()
        for d in want:
            icon = self.dev_trays.get(d["orig"])
            if icon is None:
                icon = QSystemTrayIcon()
                icon.setContextMenu(self.menu)
                icon.activated.connect(lambda reason, ic=icon: self.on_activated(reason, ic))
                self.dev_trays[d["orig"]] = icon
            icon.setIcon(make_tray_icon(
                d["battery"], d.get("battery_precision") == "coarse"
            ))
            icon.setToolTip(self.tooltip_line(d))
            if not icon.isVisible():
                icon.show()
        self.tray.setVisible(not want)  # общая иконка нужна, только если отдельных нет

    @staticmethod
    def tooltip_line(d):
        line = f"{d['name']} — {d.get('label') or str(d['battery']) + '%'}"
        if d.get("charging"):
            line += f" ({tr('charging')})"
        elif d.get("hours_left"):
            line += f" ({format_hours(d['hours_left'])})"
        return line

    # --- уведомления ---

    def notify(self, title, text, icon=QSystemTrayIcon.Information):
        target = self.tray if self.tray.isVisible() else next(iter(self.dev_trays.values()),
                                                              self.tray)
        target.showMessage(title, text, icon, 6000)

    def check_notifications(self):
        low = self.settings["low_level"]
        for d in self.visible_devices():
            if not d["connected"]:
                continue
            charging = d.get("charging")
            if d["battery"] <= low and d["id"] not in self.notified and not charging:
                self.notified.add(d["id"])
                text = d.get("label") or f"{d['battery']}%"
                self.notify(tr("low_title"), f"{d['name']}: {text}", QSystemTrayIcon.Warning)
            elif d["battery"] > low + 5:
                self.notified.discard(d["id"])

            plugged = charging or d.get("plugged")
            if (self.settings["notify_charged"] and plugged and d["battery"] >= 100
                    and not d.get("label") and d["id"] not in self.notified_full):
                self.notified_full.add(d["id"])
                self.notify(tr("full_title"), f"{d['name']}: 100%")
            elif d["battery"] < 95:
                self.notified_full.discard(d["id"])

    # --- карточка ---

    def on_activated(self, reason, tray=None):
        if reason not in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            return
        geo = (tray or self.tray).geometry()
        self.toggle_popup(geo.center() if not geo.isEmpty() else QCursor.pos())

    def toggle_popup(self, anchor):
        if self.popup.isVisible():
            self.popup.hide()
            return
        if time.monotonic() - self.popup.last_hidden < 0.25:
            return  # клик по иконке только что закрыл карточку — не открывать заново
        self.monitor.refresh()
        self.popup.show_near(anchor)

    def run(self):
        sys.exit(self.qt.exec())


if __name__ == "__main__":
    if sys.platform != "win32":
        i18n.set_language("auto")
        sys.exit(tr("windows_only"))
    setup_logging()
    try:
        App().run()
    except Exception:
        log.exception("fatal")
        raise
