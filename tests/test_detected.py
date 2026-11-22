import unittest

from detected import build_unsupported


def iface(vid, pid, product, manufacturer="", vendor=True, transport="USB"):
    return {"vendor_id": vid, "product_id": pid, "product": product,
            "manufacturer": manufacturer, "vendor_defined": vendor, "transport": transport}


class DetectedTests(unittest.TestCase):
    def test_connected_bluetooth_without_battery_is_listed(self):
        out = build_unsupported(
            [{"name": "Headset X", "connected": True},
             {"name": "Old Speaker", "connected": False}], [], [])
        self.assertEqual([(d["name"], d["reason"]) for d in out], [("Headset X", "bluetooth")])
        self.assertEqual(out[0]["kind"], "headphones")

    def test_vendor_interfaces_grouped_by_vid_pid(self):
        out = build_unsupported([], [
            iface(0x25A7, 0xFA7C, "ARDOR Receiver", "ARDOR GAMING"),
            iface(0x25A7, 0xFA7C, "ARDOR Receiver", "ARDOR GAMING"),
        ], [])
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["reason"], out[0]["detail"]), ("vendor", "25A7:FA7C"))

    def test_already_read_devices_are_excluded(self):
        out = build_unsupported(
            [{"name": "Mouse M1", "connected": True}],
            [iface(1, 2, "Wireless Receiver")], ["mouse m1", "Wireless Receiver"])
        self.assertEqual(out, [])

    def test_non_vendor_and_bluetooth_hid_are_ignored(self):
        out = build_unsupported([], [iface(1, 2, "Kbd", vendor=False),
                                     iface(3, 4, "BT thing", transport="Bluetooth")], [])
        self.assertEqual(out, [])

    def test_generic_names_do_not_become_entries(self):
        out = build_unsupported([], [iface(1, 2, "Unknown HID device", "Unknown manufacturer")], [])
        self.assertEqual(out, [])

    def test_limit(self):
        nodes = [{"name": f"Dev{i}", "connected": True} for i in range(20)]
        self.assertEqual(len(build_unsupported(nodes, [], [])), 6)


if __name__ == "__main__":
    unittest.main()
