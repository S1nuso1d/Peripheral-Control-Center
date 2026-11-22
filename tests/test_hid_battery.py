import os
import unittest

import hid_battery


class HidBatteryTests(unittest.TestCase):
    def test_scales_values_using_declared_logical_range(self):
        self.assertEqual(hid_battery.scale_battery_strength(0, 0, 100), 0)
        self.assertEqual(hid_battery.scale_battery_strength(50, 0, 100), 50)
        self.assertEqual(hid_battery.scale_battery_strength(255, 0, 255), 100)
        self.assertEqual(hid_battery.scale_battery_strength(10, 10, 110), 0)
        self.assertEqual(hid_battery.scale_battery_strength(60, 10, 110), 50)
        self.assertEqual(hid_battery.scale_battery_strength(110, 10, 110), 100)

    def test_rejects_unknown_or_invalid_logical_ranges(self):
        self.assertIsNone(hid_battery.scale_battery_strength(4, 0, 0))
        self.assertIsNone(hid_battery.scale_battery_strength(-1, 0, 100))
        self.assertIsNone(hid_battery.scale_battery_strength(101, 0, 100))
        self.assertIsNone(hid_battery.scale_battery_strength(5, -1, 100))
        self.assertIsNone(hid_battery.scale_battery_strength("bad", 0, 100))

    def test_detects_standard_battery_strength_usage(self):
        cap = hid_battery.HIDP_VALUE_CAPS()
        cap.UsagePage = 0x06
        cap.IsRange = 0
        cap.NotRange.Usage = 0x20
        self.assertTrue(hid_battery._cap_usage(cap))

    def test_rejects_other_hid_usages(self):
        cap = hid_battery.HIDP_VALUE_CAPS()
        cap.UsagePage = 0x01
        cap.NotRange.Usage = 0x20
        self.assertFalse(hid_battery._cap_usage(cap))
        cap.UsagePage = 0x06
        cap.NotRange.Usage = 0x01
        self.assertFalse(hid_battery._cap_usage(cap))

    def test_detects_usage_inside_a_range(self):
        cap = hid_battery.HIDP_VALUE_CAPS()
        cap.UsagePage = 0x06
        cap.IsRange = 1
        cap.Range.UsageMin = 0x10
        cap.Range.UsageMax = 0x30
        self.assertTrue(hid_battery._cap_usage(cap))

    @unittest.skipUnless(os.name == "nt", "Windows HID ABI layout only")
    def test_windows_native_structure_sizes(self):
        self.assertEqual(hid_battery.ctypes.sizeof(hid_battery.HIDP_CAPS), 64)
        self.assertEqual(hid_battery.ctypes.sizeof(hid_battery.HIDP_VALUE_CAPS), 72)


if __name__ == "__main__":
    unittest.main()
