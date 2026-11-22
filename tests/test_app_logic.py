"""Тесты кода, который импортирует PySide6. Без PySide6 пропускаются (в CI он ставится)."""
import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 не установлен")
class PureLogicTests(unittest.TestCase):
    def setUp(self):
        import battery_tray as bt
        import i18n
        i18n.set_language("ru")
        self.bt = bt

    def test_kind_from_cod(self):
        k = self.bt.kind_from_cod
        self.assertEqual(k(0x240404), "headphones")
        self.assertEqual(k(0x002540), "keyboard")
        self.assertEqual(k(0x002580), "mouse")
        self.assertEqual(k(0x002508), "gamepad")
        self.assertIsNone(k(0x000000))

    def test_guess_kind(self):
        g = self.bt.guess_kind
        self.assertEqual((g("WH-1000XM4"), g("MX Master 3"), g("Foo")),
                         ("headphones", "mouse", "device"))

    def test_collect_survives_failing_provider_and_dedupes(self):
        bt = self.bt
        dev = {"id": "a", "name": "Mouse", "battery": 50, "connected": True,
               "kind": "mouse", "source": "bluetooth"}
        saved, saved_hid = list(bt.PROVIDERS), bt.discover_hid_interfaces
        try:
            bt.discover_hid_interfaces = lambda: []
            bt.PROVIDERS[:] = [("ok", lambda: [dev, dict(dev, id="b")]), ("bad", lambda: 1 / 0)]
            res = bt.collect_devices()
        finally:
            bt.PROVIDERS[:] = saved
            bt.discover_hid_interfaces = saved_hid
        self.assertEqual([d["name"] for d in res], ["Mouse"])

    def test_collect_reports_connected_devices_without_battery(self):
        bt = self.bt
        saved = (list(bt.PROVIDERS), bt.discover_hid_interfaces, bt.BT_WITHOUT_BATTERY)
        try:
            bt.PROVIDERS[:] = []
            bt.BT_WITHOUT_BATTERY = [{"name": "Headset B", "connected": True, "kind": "headphones"}]
            bt.discover_hid_interfaces = lambda: [{
                "vendor_id": 0x25A7, "product_id": 0xFA7C, "product": "ARDOR Receiver",
                "manufacturer": "ARDOR GAMING", "vendor_defined": True, "transport": "USB"}]
            bt.collect_devices()
            found = [(u["name"], u["reason"]) for u in bt.UNSUPPORTED]
        finally:
            bt.PROVIDERS[:] = saved[0]
            bt.discover_hid_interfaces, bt.BT_WITHOUT_BATTERY = saved[1], saved[2]
        self.assertEqual(found, [("Headset B", "bluetooth"), ("ARDOR Receiver", "vendor")])

    def test_tooltip_line(self):
        t = self.bt.App.tooltip_line
        self.assertEqual(t({"name": "M", "battery": 42, "hours_left": 13.6}),
                         "M — 42% (хватит ещё ≈ 14 ч)")
        self.assertEqual(t({"name": "B", "battery": 70, "charging": True}),
                         "B — 70% (заряжается)")
        self.assertEqual(t({"name": "P", "battery": 35, "label": "Низкий"}), "P — Низкий")


@unittest.skipUnless(HAVE_QT, "PySide6 не установлен")
class UiSmokeTests(unittest.TestCase):
    """Отрисовка не должна падать (проверка на «пустом» экране, offscreen)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def devices(self):
        import time
        now = time.time()
        series = [(now - i * 1800, 80 - i) for i in range(20, -1, -1)]
        return [
            {"id": "1", "orig": "Mouse", "name": "Mouse", "kind": "mouse", "battery": 72,
             "connected": True, "charging": False, "hours_left": 12.0,
             "series": series, "spark": series},
            {"id": "2", "orig": "Buds", "name": "Buds", "kind": "headphones", "battery": 18,
             "connected": True, "charging": True, "series": [], "spark": []},
            {"id": "3", "orig": "Pad", "name": "Pad", "kind": "gamepad", "battery": 35,
             "label": "Низкий", "connected": False, "series": [], "spark": []},
        ]

    def test_popup_collapsed_and_expanded(self):
        import battery_tray as bt
        p = bt.Popup()
        p.set_devices(self.devices())
        collapsed = p.height()
        self.assertFalse(p.grab().isNull())
        p.expanded = "Mouse"
        p.set_devices(self.devices())
        self.assertEqual(p.height(), collapsed + bt.Popup.CHART_H)
        self.assertFalse(p.grab().isNull())

    def test_popup_shows_found_but_unreadable_devices(self):
        import battery_tray as bt
        extra = [{"name": "Headset B", "kind": "headphones", "reason": "bluetooth", "detail": ""},
                 {"name": "ARDOR Receiver", "kind": "mouse", "reason": "vendor", "detail": "25A7:FA7C"}]
        p = bt.Popup()
        p.set_devices(self.devices())
        plain = p.height()
        p.set_devices(self.devices(), extra)
        self.assertEqual(p.height(), plain + p.unsupported_height())
        self.assertGreater(p.unsupported_height(), 0)
        self.assertFalse(p.grab().isNull())
        # Ничего не читается, но устройства видны: карточка не должна быть «пустой».
        p.set_devices([], extra)
        self.assertGreater(p.height(), p.PAD * 2 + p.EMPTY_H)
        self.assertFalse(p.grab().isNull())
        # Больше U_SHOW записей — добавляется строка «и ещё N».
        many = [dict(extra[0], name=f"Dev {i}") for i in range(p.U_SHOW + 2)]
        p.set_devices([], many)
        self.assertEqual(p.unsupported_height(), p.U_HEAD + p.U_SHOW * p.UROW_H + p.U_MORE_H)
        self.assertFalse(p.grab().isNull())
        p.set_devices([], [])
        self.assertEqual(p.unsupported_height(), 0)

    def test_popup_empty(self):
        import battery_tray as bt
        p = bt.Popup()
        p.set_devices([])
        self.assertFalse(p.grab().isNull())

    def test_taskbar_widget_and_icon(self):
        import battery_tray as bt
        w = bt.TaskbarWidget()
        w.set_devices(self.devices())
        self.assertGreater(w.width(), 1)
        self.assertFalse(w.grab().isNull())
        self.assertFalse(bt.make_tray_icon(42).isNull())
        self.assertFalse(bt.make_tray_icon(42, approximate=True).isNull())
        self.assertFalse(bt.make_tray_icon(None).isNull())

    def test_devices_dialog_roundtrip(self):
        import battery_tray as bt
        from settings_dialog import DevicesDialog
        settings = {"names": {"Mouse": "Моя мышь"}, "kinds": {}, "hidden": ["Pad"]}
        devs = self.devices()
        for d in devs:
            d["auto_kind"] = d["kind"]
        dlg = DevicesDialog(devs, settings)
        names, kinds, hidden = dlg.result_data()
        self.assertEqual(names, {"Mouse": "Моя мышь"})
        self.assertEqual(kinds, {})
        self.assertEqual(hidden, ["Pad"])
        self.assertTrue(bt)


if __name__ == "__main__":
    unittest.main()
