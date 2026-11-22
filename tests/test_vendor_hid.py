import json
import tempfile
import unittest
from pathlib import Path

import vendor_hid

BASE = {"name": "Test Mouse", "kind": "mouse", "vid": "25A7", "pid": "FA7C", "usage_page": "FF00",
        "method": "feature", "report_id": 9, "length": 16,
        "battery": {"offset": 5, "min": 0, "max": 100, "invalid": [255]},
        "charging": {"offset": 6, "mask": 1}}


def profile(**changes):
    p, err = vendor_hid.validate_profile(dict(BASE, **changes))
    assert p, err
    return p


class FakeDev:
    def __init__(self, m):
        self.m = m

    def open_path(self, path):
        pass

    def close(self):
        pass

    def get_feature_report(self, rid, length):
        self.m.calls.append(("get", rid, length))
        return self.m.feature

    def read(self, n, timeout_ms=0):
        return self.m.inputs.pop(0) if self.m.inputs else []

    def write(self, data):
        self.m.calls.append(("write", bytes(data)))
        return len(data)


class FakeHid:
    def __init__(self, feature=None, inputs=None):
        self.feature, self.inputs, self.calls = feature or [], inputs or [], []

    def enumerate(self, v, p):
        return [{"vendor_id": 0x25A7, "product_id": 0xFA7C, "interface_number": 1,
                 "usage_page": 0xFF00, "usage": 1, "path": b"x"},
                {"vendor_id": 0x25A7, "product_id": 0xFA7C, "interface_number": 0,
                 "usage_page": 1, "usage": 2, "path": b"y"}]

    def device(self):
        return FakeDev(self)


class VendorHidTests(unittest.TestCase):
    def test_feature_report_parsed_with_charging(self):
        fake = FakeHid(feature=[9, 0, 0, 0, 0, 87, 1] + [0] * 9)
        out = vendor_hid.read_devices(fake, [profile()])
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual((d["name"], d["battery"], d["charging"], d["source"]),
                         ("Test Mouse", 87, True, "vendor_hid"))
        self.assertEqual(fake.calls, [("get", 9, 16)])       # только чтение

    def test_invalid_and_out_of_range_values_are_rejected(self):
        for raw in (255, 101):
            fake = FakeHid(feature=[9, 0, 0, 0, 0, raw, 0] + [0] * 9)
            self.assertEqual(vendor_hid.read_devices(fake, [profile()]), [])

    def test_scaled_range(self):
        p = profile(battery={"offset": 5, "min": 0, "max": 255})
        self.assertEqual(vendor_hid.parse_report(p, bytes([0, 0, 0, 0, 0, 128, 0]))["battery"], 50)

    def test_interface_filter(self):
        fake = FakeHid(feature=[9, 0, 0, 0, 0, 50, 0] + [0] * 9)
        self.assertEqual(vendor_hid.read_devices(fake, [profile(usage_page="FF42")]), [])
        self.assertEqual(len(vendor_hid.read_devices(fake, [profile(interface=1)])), 1)

    def test_input_method_waits_for_report_id(self):
        fake = FakeHid(inputs=[[4, 1, 1, 1, 1, 1, 1], [9, 0, 0, 0, 0, 64, 0] + [0] * 9])
        out = vendor_hid.read_devices(fake, [profile(method="input")])
        self.assertEqual(out[0]["battery"], 64)
        self.assertFalse([c for c in fake.calls if c[0] == "write"])

    def test_request_needs_explicit_allow_write(self):
        p, err = vendor_hid.validate_profile(dict(BASE, method="request", request="01 02"))
        self.assertIsNone(p)
        self.assertIn("allow_write", err)
        p = profile(method="request", request="01 02", allow_write=True, listen_ms=200)
        fake = FakeHid(inputs=[[9, 0, 0, 0, 0, 40, 0] + [0] * 9])
        out = vendor_hid.read_devices(fake, [p])
        self.assertEqual(out[0]["battery"], 40)
        self.assertIn(("write", b"\x01\x02"), fake.calls)

    def test_bad_profiles_are_reported_not_crashing(self):
        for bad in ({}, {"name": "x"}, dict(BASE, vid="zz"), dict(BASE, length=1),
                    dict(BASE, battery={"offset": 99}), dict(BASE, method="magic")):
            p, err = vendor_hid.validate_profile(bad)
            self.assertIsNone(p)
            self.assertTrue(err)

    def test_load_profiles_from_file(self):
        d = Path(tempfile.mkdtemp())
        (d / vendor_hid.PROFILE_FILE).write_text(json.dumps(
            {"profiles": [BASE, dict(BASE, name="off", enabled=False), {"name": "broken"}]}),
            encoding="utf-8")
        profiles, errors = vendor_hid.load_profiles([d])
        self.assertEqual([p["name"] for p in profiles], ["Test Mouse"])
        self.assertEqual(len(errors), 1)
        (d / vendor_hid.PROFILE_FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(vendor_hid.load_profiles([d])[0], [])

    def test_no_profiles_means_no_hid_access(self):
        fake = FakeHid()
        self.assertEqual(vendor_hid.read_devices(fake, []), [])
        self.assertEqual(vendor_hid.diagnostics()["status"], "no_profiles")
        self.assertEqual(fake.calls, [])

    def test_example_file_is_valid_json_and_disabled(self):
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / "vendor_profiles.example.json").read_text(encoding="utf-8"))
        profiles, errors = vendor_hid.load_profiles([root])
        self.assertEqual(profiles, [])               # пример выключен
        self.assertTrue(data["profiles"][0]["enabled"] is False)


if __name__ == "__main__":
    unittest.main()
