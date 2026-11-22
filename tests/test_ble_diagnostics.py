import unittest

import ble_battery


class BleDiagnosticsPrivacyTests(unittest.TestCase):
    def test_redacts_standard_bluetooth_mac_addresses(self):
        error = RuntimeError("connection failed for AA:BB:CC:DD:EE:FF")
        rendered = ble_battery._safe_error(error)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", rendered)
        self.assertIn("[Bluetooth address redacted]", rendered)


if __name__ == "__main__":
    unittest.main()
