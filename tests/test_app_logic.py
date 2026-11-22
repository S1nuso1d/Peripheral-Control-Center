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
        saved = list(bt.PROVIDERS)
        try:
            bt.PROVIDERS[:] = [("ok", lambda: [dev, dict(dev, id="b")]), ("bad", lambda: 1 / 0)]
            res = bt.collect_devices()
        finally:
            bt.PROVIDERS[:] = saved
        self.assertEqual([d["name"] for d in res], ["Mouse"])

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
