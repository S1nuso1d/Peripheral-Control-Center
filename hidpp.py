"""Logitech HID++ 2.0: заряд устройств на донглах (Unifying, Bolt, Lightspeed).

Для таких устройств Windows не знает заряд, поэтому спрашиваем их напрямую по
протоколу HID++ (только чтение, ничего на устройстве не меняется).
Нужен необязательный пакет hidapi (pip install hidapi); без него модуль
просто ничего не возвращает.

Поддержано: функции батареи 0x1004 (Unified Battery) и 0x1000 (Battery Status).
Устройства с 0x1001 (Battery Voltage, часть игровых моделей G) пока не читаются:
там нужна таблица «напряжение → проценты», а выдумывать её значения не хочется.
"""
import logging
import time

from i18n import tr

log = logging.getLogger("BatteryTray")

try:
    import hid  # pip install hidapi
except Exception:  # пакет не установлен — провайдер отключён
    hid = None

VENDOR_ID = 0x046D
LONG_REPORT = 0x11
SW_ID = 0x0A                      # метка запроса (младший ниббл), чтобы отличать ответы
F_NAME, F_BATTERY_STATUS, F_UNIFIED = 0x0005, 0x1000, 0x1004
DEVICE_TYPES = {0: "keyboard", 2: "keyboard", 3: "mouse", 4: "mouse", 5: "mouse",
                8: "headphones", 11: "gamepad", 12: "gamepad"}
LEVEL_FLAGS = ((8, 100, "lvl_full"), (4, 60, "lvl_good"), (2, 20, "lvl_low"), (1, 5, "lvl_critical"))

_cache: dict = {}        # (path, devidx) -> индексы функций, имя, тип
_logged_ifaces = False


def _request(h, devidx: int, feat_idx: int, func: int, params: bytes = b"", timeout=0.5):
    """Один запрос HID++ 2.0. Возвращает параметры ответа или None (ошибка/таймаут)."""
    msg = bytearray(20)
    msg[0], msg[1], msg[2], msg[3] = LONG_REPORT, devidx, feat_idx, (func << 4) | SW_ID
    msg[4:4 + len(params)] = params
    h.write(bytes(msg))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = h.read(20, 100)
        if not r:
            continue
        r = bytes(r)
        if len(r) < 5 or r[0] not in (0x10, 0x11) or r[1] != devidx:
            continue
        if r[2] == 0x8F:                                   # ошибка HID++ 1.0 (нет устройства и т.п.)
            return None
        if r[2] == 0xFF and r[3] == feat_idx and r[4] == msg[3]:  # ошибка HID++ 2.0
            return None
        if r[2] == feat_idx and r[3] == msg[3]:
            return r[4:]
    return None


def _feature(h, devidx, cache, fid):
    """Индекс функции по её ID: число, 0 (не поддерживается) или None (нет ответа)."""
    if fid in cache:
        return cache[fid]
    r = _request(h, devidx, 0x00, 1, bytes([fid >> 8, fid & 0xFF]))
    if r is None:
        return None
    cache[fid] = r[0]
    return r[0]


def _read_battery(h, devidx, cache):
    """(процент, заряжается, подпись|None, подключён к питанию) или None."""
    fi = _feature(h, devidx, cache, F_UNIFIED)
    if fi is None:
        return None
    if fi:
        r = _request(h, devidx, fi, 1)           # getStatus
        if r:
            soc, level, status = r[0], r[1], r[2]
            charging = status in (1, 2)          # заряжается / медленная зарядка
            plugged = status in (1, 2, 3)        # 3 — зарядка завершена
            if 0 < soc <= 100:
                return soc, charging, None, plugged
            for flag, pct, key in LEVEL_FLAGS:   # процентов нет — только грубый уровень
                if level & flag:
                    return pct, charging, tr(key), plugged
    fi = _feature(h, devidx, cache, F_BATTERY_STATUS)
    if fi:
        r = _request(h, devidx, fi, 0)           # getBatteryLevelStatus
        if r and 0 < r[0] <= 100:
            return r[0], r[2] in (1, 2, 4), None, r[2] in (1, 2, 3, 4)
    return None


def _device_name(h, devidx, cache):
    fi = _feature(h, devidx, cache, F_NAME)
    if not fi:
        return None, None
    r = _request(h, devidx, fi, 0)               # количество символов
    if not r:
        return None, None
    count, name = r[0], b""
    while len(name) < count and len(name) < 64:
        r = _request(h, devidx, fi, 1, bytes([len(name)]))
        chunk = r[:16].split(b"\x00")[0] if r else b""
        if not chunk:
            break
        name += chunk
    r = _request(h, devidx, fi, 2)               # тип устройства
    return name[:count].decode("utf-8", "ignore") or None, (r[0] if r else None)


def read_devices() -> list:
    """Список устройств Logitech с зарядом: [{id, name, battery, charging, ...}]."""
    global _logged_ifaces
    if hid is None:
        return []
    try:
        infos = hid.enumerate(VENDOR_ID, 0)
    except Exception:
        log.warning("hid.enumerate failed", exc_info=True)
        return []
    ifaces = [i for i in infos
              if i.get("usage_page") in (0xFF00, 0xFF43) and i.get("usage") in (2, 0x0202)]
    if not _logged_ifaces:
        _logged_ifaces = True
        log.info("HID++ interfaces: %s", [(i.get("product_string"), hex(i.get("usage_page", 0)),
                                           hex(i.get("usage", 0))) for i in ifaces])

    out, seen = [], set()
    for info in ifaces:
        path = info["path"]
        receiver = "receiver" in (info.get("product_string") or "").lower()
        indices = list(range(1, 7)) if receiver else [0xFF, 0x00]
        h = hid.device()
        try:
            h.open_path(path)
        except Exception:
            log.info("cannot open HID path for %s", info.get("product_string"))
            continue
        try:
            for idx in indices:
                cache = _cache.setdefault((path, idx), {})
                bat = _read_battery(h, idx, cache)
                if bat is None:
                    continue
                if "name" not in cache:
                    cache["name"], cache["type"] = _device_name(h, idx, cache)
                name = cache["name"] or info.get("product_string") or f"Logitech {idx}"
                if name in seen:
                    continue
                seen.add(name)
                level, charging, label, plugged = bat
                dev = {"id": f"hidpp:{path.hex() if isinstance(path, bytes) else path}:{idx}",
                       "name": name, "battery": level, "connected": True,
                       "kind": DEVICE_TYPES.get(cache["type"]), "source": "hidpp",
                       "charging": charging, "plugged": plugged, "charging_known": True}
                if label:
                    dev["label"] = label
                out.append(dev)
        except Exception:
            log.warning("HID++ read failed", exc_info=True)
        finally:
            h.close()
    return out
