import json
import unittest

from windows_device_inventory import discover_windows_devices, normalize_pnp_devices


class WindowsDeviceInventoryTests(unittest.TestCase):
    def test_normalizes_usb_bluetooth_and_hid_nodes(self):
        rows = [
            {
                "name": "Wireless Receiver",
                "manufacturer": "ARDOR GAMING",
                "status": "OK",
                "deviceClass": "USB",
                "instanceId": r"USB\VID_25A7&PID_FA7C\SERIAL-SECRET",
                "hardwareIds": [r"USB\VID_25A7&PID_FA7C&REV_0100"],
                "battery": None,
            },
            {
                "name": "Wireless Headphones",
                "manufacturer": "Example",
                "status": "OK",
                "deviceClass": "Bluetooth",
                "instanceId": r"BTHLE\DEV_123456789ABC\7&ABCDEF",
                "hardwareIds": [],
                "battery": 83,
                "batterySource": "System.Devices.BatteryLife",
            },
            {
                "name": "HID-compliant device",
                "manufacturer": "Example",
                "status": "Error",
                "deviceClass": "HIDClass",
                "instanceId": r"HID\VID_046D&PID_C52B&MI_01\7&SERIAL-SECRET",
                "hardwareIds": [],
                "battery": "not available",
            },
        ]

        devices = normalize_pnp_devices(rows)

        self.assertEqual(len(devices), 3)
        receiver = next(item for item in devices if item["transport"] == "USB")
        self.assertEqual(receiver["vid_pid"], "25A7:FA7C")
        self.assertEqual(receiver["manufacturer"], "ARDOR GAMING")
        headphones = next(item for item in devices if item["transport"] == "Bluetooth")
        self.assertEqual(headphones["battery"], 83)
        self.assertEqual(headphones["battery_source"], "System.Devices.BatteryLife")
        hid_device = next(item for item in devices if item["transport"] == "HID")
        self.assertIsNone(hid_device["battery"])
        self.assertFalse(hid_device["connected"])

    def test_does_not_return_raw_instance_ids_or_serials(self):
        rows = [{
            "name": "Private device",
            "manufacturer": "Example",
            "status": "OK",
            "deviceClass": "USB",
            "instanceId": r"USB\VID_1234&PID_ABCD\MY-PRIVATE-SERIAL",
            "hardwareIds": [r"USB\VID_1234&PID_ABCD"],
        }]

        device = normalize_pnp_devices(rows)[0]
        serialized = json.dumps(device)

        self.assertNotIn("instanceId", device)
        self.assertNotIn("MY-PRIVATE-SERIAL", serialized)
        self.assertNotIn(r"USB\VID_1234", serialized)
        self.assertRegex(device["id"], r"^pnp:[0-9a-f]{12}$")

    def test_normalizes_coarse_charging_source_without_claiming_exact_precision(self):
        rows = [{
            "name": "Wireless keyboard",
            "manufacturer": "Example",
            "status": "OK",
            "deviceClass": "HIDClass",
            "instanceId": r"HID\\VID_1234&PID_5678\\INSTANCE",
            "batteryPlusCharging": 150,
        }]

        device = normalize_pnp_devices(rows)[0]
        self.assertEqual(device["battery"], 60)
        self.assertEqual(device["battery_source"], "System.Devices.BatteryPlusCharging")
        self.assertEqual(device["battery_precision"], "coarse")
        self.assertTrue(device["charging_known"])
        self.assertTrue(device["charging"])

    def test_decodes_windows_battery_plus_charging_bands(self):
        from windows_device_inventory import decode_battery_plus_charging

        self.assertEqual(decode_battery_plus_charging(5), (5, False))
        self.assertEqual(decode_battery_plus_charging(18), (18, False))
        self.assertEqual(decode_battery_plus_charging(60), (60, False))
        self.assertEqual(decode_battery_plus_charging(95), (95, False))
        self.assertEqual(decode_battery_plus_charging(105), (5, True))
        self.assertEqual(decode_battery_plus_charging(120), (18, True))
        self.assertEqual(decode_battery_plus_charging(150), (60, True))
        self.assertEqual(decode_battery_plus_charging(195), (95, True))
        self.assertIsNone(decode_battery_plus_charging(201))
        self.assertIsNone(decode_battery_plus_charging("unknown"))

    def test_accepts_single_object_and_empty_results(self):
        single = {
            "name": "Bluetooth mouse",
            "status": "OK",
            "deviceClass": "Bluetooth",
            "instanceId": r"BTHENUM\DEV_123456789ABC",
        }
        self.assertEqual(len(normalize_pnp_devices(single)), 1)
        self.assertEqual(normalize_pnp_devices([]), [])
        self.assertEqual(normalize_pnp_devices(None), [])

    def test_discovery_uses_injected_runner_and_parses_json(self):
        payload = [{
            "name": "USB receiver",
            "status": "OK",
            "deviceClass": "USB",
            "instanceId": r"USB\VID_25A7&PID_FA7C\INSTANCE",
            "hardwareIds": [],
        }]
        calls = []

        def runner(script):
            calls.append(script)
            return json.dumps(payload)

        devices = discover_windows_devices(runner=runner)

        self.assertEqual(len(calls), 1)
        self.assertIn("Get-PnpDevice -PresentOnly", calls[0])
        self.assertIn("System.Devices.BatteryLife", calls[0])
        self.assertEqual(devices[0]["vid_pid"], "25A7:FA7C")

    def test_invalid_json_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            discover_windows_devices(runner=lambda _script: "not-json")


if __name__ == "__main__":
    unittest.main()
