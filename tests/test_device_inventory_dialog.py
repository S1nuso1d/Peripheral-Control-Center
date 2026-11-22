import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class DeviceInventoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_lists_devices_and_copies_safe_report(self):
        from device_inventory_dialog import DeviceInventoryDialog

        devices = [{
            "id": "hid:25A7:FA7C:1:0123456789AB",
            "vendor_id": 0x25A7,
            "product_id": 0xFA7C,
            "interface_number": 1,
            "usage_page": 0xFF00,
            "usage": 2,
            "usage_page_name": "Vendor-defined",
            "manufacturer": "ARDOR GAMING",
            "product": "Wireless Receiver",
            "transport": "USB",
            "path_fingerprint": "0123456789AB",
            "vendor_defined": True,
            "battery_related_page": False,
            "protocol_hint": "Vendor-defined interface; manufacturer protocol required",
        }]
        dialog = DeviceInventoryDialog(discover_fn=lambda: devices)

        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertIn("ARDOR GAMING", dialog.report_text())
        self.assertIn("25A7:FA7C", dialog.report_text())
        self.assertNotIn("serial_number", dialog.report_text().lower())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
