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
