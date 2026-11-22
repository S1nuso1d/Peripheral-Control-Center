import unittest

import ble_battery


class FakeAdvertisement:
    def __init__(self, service_uuids):
        self.service_uuids = service_uuids
        self.service_data = {}
        self.local_name = "Sample BLE Mouse"


class FakeDevice:
    address = "AA:BB:CC:DD:EE:FF"
    name = "Sample BLE Mouse"


class FakeCharacteristic:
    uuid = ble_battery.BATTERY_LEVEL_UUID


class FakeService:
    uuid = ble_battery.BATTERY_SERVICE_UUID

    def get_characteristic(self, _uuid):
        return FakeCharacteristic()


class FakeClient:
    def __init__(self, device, timeout):
        self.device = device
        self.timeout = timeout
        self.services = [FakeService()]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def read_gatt_char(self, _characteristic):
        return bytes([67])


class FakeScanner:
    @staticmethod
    async def discover(timeout, return_adv):
        assert timeout == ble_battery.SCAN_SECONDS
        assert return_adv is True
        return {
            FakeDevice.address: (
                FakeDevice(),
                FakeAdvertisement([ble_battery.BATTERY_SERVICE_UUID]),
            )
        }


class BleBatteryTests(unittest.IsolatedAsyncioTestCase):
    def test_reads_battery_level_status_from_advertisement_service_data(self):
        advertisement = FakeAdvertisement([])
        advertisement.service_data = {
            "180F": bytes([0x02, 0x21, 0x00, 88]),
        }
        result = ble_battery.advertised_battery_status(advertisement)
        self.assertEqual(result["battery"], 88)
        self.assertTrue(result["charging"])

    def test_ignores_advertisement_status_without_an_exact_level(self):
        advertisement = FakeAdvertisement([])
        power_state = 1 | (2 << 7)
        advertisement.service_data = {
            ble_battery.BATTERY_SERVICE_UUID:
                bytes([0x00]) + power_state.to_bytes(2, "little"),
        }
        self.assertIsNone(ble_battery.advertised_battery_status(advertisement)["battery"])

    def test_parses_battery_level_status_with_charging(self):
        # Flags: Battery Level present. Power State: battery present + charging.
        result = ble_battery.parse_battery_level_status(bytes([0x02, 0x21, 0x00, 73]))
        self.assertEqual(result["battery"], 73)
        self.assertTrue(result["battery_present"])
        self.assertTrue(result["charging"])
        self.assertTrue(result["charging_known"])

    def test_parses_optional_battery_level_status_fields_in_order(self):
        # Identifier, Battery Level, Additional Status are optional and follow
        # the two-byte Power State in the order declared by the flags.
        result = ble_battery.parse_battery_level_status(
            bytes([0x07, 0x41, 0x00, 1, 54, 0])
        )
        self.assertEqual(result["battery"], 54)
        self.assertFalse(result["charging"])
        self.assertTrue(result["charging_known"])

    def test_does_not_guess_percent_from_qualitative_power_state(self):
        # Battery present, charge level "low", but the percentage field is absent.
        power_state = 1 | (2 << 7)
        result = ble_battery.parse_battery_level_status(
            bytes([0x00]) + power_state.to_bytes(2, "little")
        )
        self.assertIsNone(result["battery"])
        self.assertIsNone(result["charging"])
        self.assertFalse(result["charging_known"])

    def test_rejects_invalid_or_truncated_battery_level_status(self):
        self.assertIsNone(ble_battery.parse_battery_level_status(b""))
        self.assertIsNone(ble_battery.parse_battery_level_status(bytes([0x02, 0x01])))
        self.assertIsNone(
            ble_battery.parse_battery_level_status(bytes([0x02, 0x01, 0x00, 101]))
        )
        self.assertIsNone(
            ble_battery.parse_battery_level_status(bytes([0x08, 0x01, 0x00]))
        )

    def test_short_and_full_service_uuids_normalize_identically(self):
        self.assertEqual(
            ble_battery._canonical_uuid("180F"),
            ble_battery.BATTERY_SERVICE_UUID,
        )
        self.assertEqual(
            ble_battery._canonical_uuid(ble_battery.BATTERY_SERVICE_UUID),
            ble_battery.BATTERY_SERVICE_UUID,
        )

    async def test_reads_only_the_standard_battery_level_characteristic(self):
        old_scanner, old_client = ble_battery.BleakScanner, ble_battery.BleakClient
        try:
            ble_battery.BleakScanner = FakeScanner
            ble_battery.BleakClient = FakeClient
            devices, status = await ble_battery._scan_and_read()
        finally:
            ble_battery.BleakScanner, ble_battery.BleakClient = old_scanner, old_client

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["battery"], 67)
        self.assertEqual(devices[0]["source"], "ble_gatt")
        self.assertEqual(status["status"], "read_ok")
        self.assertNotIn(FakeDevice.address, devices[0]["id"])

    async def test_ignores_devices_that_do_not_advertise_battery_service(self):
        old_scanner, old_client = ble_battery.BleakScanner, ble_battery.BleakClient

        class OtherScanner:
            @staticmethod
            async def discover(timeout, return_adv):
                return {
                    FakeDevice.address: (
                        FakeDevice(),
                        FakeAdvertisement(["0000180A-0000-1000-8000-00805F9B34FB"]),
                    )
                }

        try:
            ble_battery.BleakScanner = OtherScanner
            ble_battery.BleakClient = FakeClient
            devices, status = await ble_battery._scan_and_read()
        finally:
            ble_battery.BleakScanner, ble_battery.BleakClient = old_scanner, old_client

        self.assertEqual(devices, [])
        self.assertEqual(status["status"], "no_battery_service_advertised")
        self.assertEqual(status["candidates"], 0)


if __name__ == "__main__":
    unittest.main()
