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
    "m_inventory": ("Инвентаризация устройств…", "Device inventory…"),
    "m_diagnostics": ("Создать диагностический отчёт…", "Create diagnostics report…"),
    "diagnostics_error_title": ("Ошибка диагностики", "Diagnostics error"),
    "diagnostics_error_message": ("Не удалось создать отчёт. Подробности в логе.",
                                   "Could not create the report. See the application log."),
    "m_devices": ("Устройства", "Devices"),
    "m_no_devices": ("Нет устройств", "No devices"),
    "m_configure": ("Настроить устройства…", "Configure devices…"),
    "m_show_offline": ("Показывать отключённые", "Show disconnected"),
    "m_hidpp": ("Logitech на донглах (HID++)", "Logitech on dongles (HID++)"),
    "m_ble_battery": ("Bluetooth LE: стандартная служба батареи", "Bluetooth LE: standard Battery Service"),
    "m_hid_battery": ("Стандартные HID-отчёты заряда", "Standard HID battery reports"),
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
    # окно обнаруженных HID-интерфейсов
    "inventory_title": ("Инвентаризация устройств", "Device inventory"),
    "inventory_device": ("Устройство", "Device"),
    "inventory_tab_hid": ("HID-интерфейсы", "HID interfaces"),
    "inventory_tab_windows": ("Устройства Windows", "Windows devices"),
    "inventory_class": ("Класс", "Class"),
    "inventory_battery": ("Заряд", "Battery"),
    "inventory_status": ("Статус", "Status"),
    "windows_inventory_hint": ("Список получен из Windows PnP. В нём могут быть отдельные узлы одного составного устройства; совпадения по VID/PID помогают найти приёмник, но не доказывают поддержку его протокола.",
                              "This list comes from Windows PnP. A composite device may have multiple nodes; matching VID/PID helps identify a receiver but does not prove its protocol is supported."),
    "windows_inventory_count": ("Найдено узлов Windows PnP: {}", "Windows PnP nodes found: {}"),
    "windows_inventory_empty": ("Подходящие устройства Windows не обнаружены.", "No matching Windows devices were detected."),
    "windows_inventory_error": ("Не удалось получить список Windows PnP: {}", "Could not enumerate Windows PnP devices: {}"),
    "inventory_manufacturer": ("Производитель", "Manufacturer"),
    "inventory_vid_pid": ("VID:PID", "VID:PID"),
    "inventory_interface": ("Интерфейс", "Interface"),
    "inventory_usage_page": ("Usage page", "Usage page"),
    "inventory_usage": ("Usage", "Usage"),
    "inventory_transport": ("Подключение", "Transport"),
    "inventory_pnp_matches": ("Совпадения PnP", "PnP matches"),
    "inventory_protocol": ("Поддержка данных", "Data support"),
    "inventory_hint": ("Здесь показаны HID-интерфейсы, видимые Windows через hidapi. Наличие интерфейса не означает, что устройство предоставляет заряд; для интерфейсов производителя может потребоваться отдельный протокол.",
                        "This lists HID interfaces visible through hidapi. An interface does not imply battery telemetry; vendor interfaces may require a dedicated protocol."),
    "inventory_count": ("Найдено HID-интерфейсов: {}", "HID interfaces found: {}"),
    "inventory_empty": ("HID-интерфейсы не обнаружены.", "No HID interfaces were detected."),
    "inventory_error": ("Не удалось получить список HID-интерфейсов: {}", "Could not enumerate HID interfaces: {}"),
    "inventory_report_title": ("Peripheral Control Center — отчёт HID-интерфейсов", "Peripheral Control Center — HID interface report"),
    "inventory_refresh": ("Обновить список", "Refresh list"),
    "inventory_copy": ("Копировать отчёт", "Copy report"),
    "inventory_copied": ("Отчёт скопирован в буфер обмена.", "Report copied to clipboard."),
    "close": ("Закрыть", "Close"),
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
