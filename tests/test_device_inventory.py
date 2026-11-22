import unittest

from device_inventory import discover_hid_interfaces, usage_page_name


class FakeHid:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def enumerate(self, vendor_id, product_id):
        self.calls.append((vendor_id, product_id))
        return self.rows


class DeviceInventoryTests(unittest.TestCase):
    def test_discovers_and_normalizes_multiple_interfaces(self):
        fake = FakeHid([
            {
                "vendor_id": 0x1234,
                "product_id": 0x5678,
                "interface_number": 2,
                "usage_page": 0xFF00,
                "usage": 0x0001,
                "manufacturer_string": "Example",
                "product_string": "Wireless Receiver",
                "path": b"\\\\?\\hid#vid_1234&pid_5678&mi_02",
                "serial_number": "MUST_NOT_LEAK",
                "bus_type": 1,
            },
            {
                "vendor_id": 0x1234,
                "product_id": 0x5678,
                "interface_number": 3,
                "usage_page": 0x85,
                "usage": 0x0001,
                "manufacturer_string": "Example",
                "product_string": "Wireless Receiver",
                "path": b"\\\\?\\hid#vid_1234&pid_5678&mi_03",
                "bus_type": 2,
            },
        ])

        devices = discover_hid_interfaces(fake)

        self.assertEqual(fake.calls, [(0, 0)])
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["vendor_id"], 0x1234)
        self.assertTrue(all(item["manufacturer"] == "Example" for item in devices))
        self.assertEqual(
            {item["transport"] for item in devices},
            {"USB", "Bluetooth"},
        )
        battery_page = next(item for item in devices if item["usage_page"] == 0x85)
        self.assertTrue(battery_page["battery_related_page"])
        self.assertIn("Battery System", battery_page["usage_page_name"])

    def test_vendor_defined_page_is_flagged_without_claiming_battery_support(self):
        fake = FakeHid([{
            "vendor_id": 0x25A7,
            "product_id": 0xFA7C,
            "interface_number": 1,
            "usage_page": 0xFF00,
            "usage": 2,
            "manufacturer_string": "ARDOR GAMING",
            "product_string": "Wireless Receiver",
            "path": b"receiver-path",
        }])

        device = discover_hid_interfaces(fake)[0]

        self.assertTrue(device["vendor_defined"])
        self.assertFalse(device["battery_related_page"])
        self.assertIn("manufacturer protocol required", device["protocol_hint"])
        self.assertEqual(device["transport"], "HID (transport unknown)")

    def test_identifiers_are_stable_and_sensitive_fields_are_omitted(self):
        row = {
            "vendor_id": 0x046D,
            "product_id": 0xC52B,
            "interface_number": 1,
            "usage_page": 0xFF00,
            "usage": 2,
            "manufacturer_string": "Logitech",
            "product_string": "Receiver",
            "path": b"private-path",
            "serial_number": "PRIVATE-SERIAL",
        }

        first = discover_hid_interfaces(FakeHid([row]))[0]
        second = discover_hid_interfaces(FakeHid([row]))[0]

        self.assertEqual(first["id"], second["id"])
        self.assertNotIn("path", first)
        self.assertNotIn("serial_number", first)
        self.assertNotIn("PRIVATE-SERIAL", repr(first))
        self.assertNotIn("private-path", repr(first))

    def test_empty_enumeration_returns_empty_list(self):
        self.assertEqual(discover_hid_interfaces(FakeHid([])), [])

    def test_battery_and_power_usage_page_names(self):
        self.assertEqual(usage_page_name(0x85), "Battery System")
        self.assertEqual(usage_page_name(0x84), "Power Device")


if __name__ == "__main__":
    unittest.main()
