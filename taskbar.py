"""Положение панели задач Windows и расчёт места для мини-виджета.

Все координаты здесь — физические пиксели (как их отдаёт Win32).
Математика расположения (compute_position) не зависит от Windows и тестируется отдельно.
"""
import ctypes
from ctypes import wintypes as wt
from dataclasses import dataclass


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


SWP_NOSIZE, SWP_NOACTIVATE = 0x0001, 0x0010
HWND_TOPMOST = -1
_api: dict = {}


def _load():
    if not _api:
        u = ctypes.WinDLL("user32")
        u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowW.restype = wt.HWND
        u.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowExW.restype = wt.HWND
        u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(_RECT)]
        u.GetWindowRect.restype = wt.BOOL
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.UINT]
        u.SetWindowPos.restype = wt.BOOL
        s = ctypes.WinDLL("shell32")
        s.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
        s.SHQueryUserNotificationState.restype = ctypes.c_long
        _api.update(user=u, shell=s)
    return _api


def _rect_of(hwnd):
    r = _RECT()
    if hwnd and _load()["user"].GetWindowRect(hwnd, ctypes.byref(r)):
        return Rect(r.left, r.top, r.right, r.bottom)
    return None


def taskbar_rects():
    """(панель задач, область трея или None) либо None, если панель не найдена."""
    u = _load()["user"]
    tb_hwnd = u.FindWindowW("Shell_TrayWnd", None)
    tb = _rect_of(tb_hwnd)
    if tb is None or tb.width <= 0 or tb.height <= 0:
        return None
    notify = _rect_of(u.FindWindowExW(tb_hwnd, None, "TrayNotifyWnd", None))
    if notify is not None and not (notify.width > 0 and tb.left <= notify.left < tb.right):
        notify = None
    return tb, notify


def fullscreen_app_active() -> bool:
    """True, если на переднем плане полноэкранное приложение/игра/презентация."""
    state = ctypes.c_int(0)
    if _load()["shell"].SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value in (2, 3, 4)  # BUSY, D3D_FULL_SCREEN, PRESENTATION_MODE


def set_topmost(hwnd: int, x: int, y: int):
    """Переместить окно в (x, y) и поднять поверх всех, не забирая фокус."""
    _load()["user"].SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)


def compute_position(tb: Rect, notify, w: int, h: int, dx: int, dy: int,
                     screen: Rect, gap: int = 8, fallback_tray: int = 220):
    """Где разместить виджет w×h: слева от трея, по центру высоты панели.

    Возвращает (x, y) или None, если виджет показывать не нужно:
    панель вертикальная или скрыта (автоскрытие).
    """
    if tb.width < tb.height:
        return None  # вертикальная панель — не поддерживается
    visible = min(tb.bottom, screen.bottom) - max(tb.top, screen.top)
    if visible < 10:
        return None  # панель спрятана за краем экрана
    right = (notify.left - gap) if notify is not None else (tb.right - fallback_tray)
    x = max(right - w + dx, tb.left)
    y = tb.top + (tb.height - h) // 2 + dy
    return x, y
