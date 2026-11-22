import unittest

import ble_battery
import diagnose


class BleDiagnosticsPrivacyTests(unittest.TestCase):
    def test_diagnostic_module_imports(self):
        self.assertTrue(callable(diagnose.build_report))
        self.assertTrue(callable(diagnose.write_report))

    def test_redacts_standard_bluetooth_mac_addresses(self):
        error = RuntimeError("connection failed for AA:BB:CC:DD:EE:FF")
        rendered = ble_battery._safe_error(error)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", rendered)
        self.assertIn("[Bluetooth address redacted]", rendered)


if __name__ == "__main__":
    unittest.main()
