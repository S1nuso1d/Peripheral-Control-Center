"""Локализация: русский и английский. tr("ключ", *аргументы) -> строка."""
LANG = "ru"

# ключ: (русский, английский)
STR = {
    # общее
    "loading": ("Peripheral Control Center: загрузка…", "Peripheral Control Center: loading…"),
    "tray_none": ("Нет подключённых устройств с данными о заряде",
                  "No connected devices with battery data"),
    "no_devices_popup": ("Нет устройств с данными о заряде", "No devices with battery data"),
    "device": ("Устройство", "Device"),
    "xbox": ("Геймпад Xbox {}", "Xbox controller {}"),
    "charging": ("заряжается", "charging"),
    "windows_only": ("Приложение рассчитано на Windows 10/11.",
                     "This app is designed for Windows 10/11."),
    # уровни (XInput / HID++)
    "lvl_empty": ("Разряжен", "Empty"),
    "lvl_low": ("Низкий", "Low"),
    "lvl_medium": ("Средний", "Medium"),
    "lvl_full": ("Полный", "Full"),
    "lvl_good": ("Хороший", "Good"),
    "lvl_critical": ("Критический", "Critical"),
    # оценка времени
    "left_min": ("хватит ещё ≈ {} мин", "≈ {} min left"),
    "left_h": ("хватит ещё ≈ {} ч", "≈ {} h left"),
    "left_d": ("хватит ещё ≈ {} дн", "≈ {} d left"),
    # график
    "chart_empty": ("Пока мало данных", "Not enough data yet"),
    "chart_ago": ("−{}", "−{}"),
    "chart_now": ("сейчас", "now"),
    "p24": ("24 ч", "24 h"),
    "p72": ("3 дн", "3 d"),
    "p168": ("7 дн", "7 d"),
    # уведомления
    "low_title": ("Низкий заряд", "Low battery"),
    "full_title": ("Заряжено", "Fully charged"),
    # меню
    "m_refresh": ("Обновить", "Refresh"),
    "m_devices": ("Устройства", "Devices"),
    "m_no_devices": ("Нет устройств", "No devices"),
    "m_configure": ("Настроить устройства…", "Configure devices…"),
    "m_show_offline": ("Показывать отключённые", "Show disconnected"),
    "m_hidpp": ("Logitech на донглах (HID++)", "Logitech on dongles (HID++)"),
    "m_widget": ("Мини-виджет у панели задач", "Taskbar mini-widget"),
    "m_widget_reset": ("Сбросить положение виджета", "Reset widget position"),
    "m_per_device": ("Отдельная иконка для каждого устройства", "Separate tray icon per device"),
    "m_notify_full": ("Уведомлять о полной зарядке", "Notify when fully charged"),
    "m_interval": ("Обновлять каждые", "Refresh every"),
    "i30": ("30 секунд", "30 seconds"),
    "i60": ("1 минуту", "1 minute"),
    "i120": ("2 минуты", "2 minutes"),
    "i300": ("5 минут", "5 minutes"),
    "m_threshold": ("Порог низкого заряда", "Low battery threshold"),
    "m_language": ("Язык", "Language"),
    "lang_auto": ("Как в системе", "System default"),
    "m_autostart": ("Запускать с Windows", "Start with Windows"),
    "m_log": ("Открыть папку с логом", "Open log folder"),
    "m_quit": ("Выход", "Quit"),
    # окно настройки устройств
    "dlg_title": ("Устройства", "Devices"),
    "dlg_hint": ("Свои названия и типы значков. Пустое название — как у устройства.",
                 "Custom names and icon types. Leave the name empty to keep the original."),
    "col_show": ("Показывать", "Show"),
    "col_device": ("Устройство", "Device"),
    "col_name": ("Своё название", "Custom name"),
    "col_type": ("Тип", "Type"),
    "kind_device": ("Другое", "Other"),
    "kind_headphones": ("Наушники", "Headphones"),
    "kind_mouse": ("Мышь", "Mouse"),
    "kind_keyboard": ("Клавиатура", "Keyboard"),
    "kind_gamepad": ("Геймпад", "Gamepad"),
    "kind_phone": ("Телефон", "Phone"),
    "ok": ("ОК", "OK"),
    "cancel": ("Отмена", "Cancel"),
}


def detect_language() -> str:
    """'ru' для русской локали Windows, иначе 'en'."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
            return "ru" if buf.value.lower().startswith("ru") else "en"
    except Exception:
        pass
    return "ru"


def set_language(code: str):
    """code: 'auto', 'ru' или 'en'."""
    global LANG
    LANG = detect_language() if code == "auto" else (code if code in ("ru", "en") else "ru")


def tr(key: str, *args) -> str:
    pair = STR.get(key)
    text = pair[0 if LANG == "ru" else 1] if pair else key
    return text.format(*args) if args else text
