import unittest

import hid_probe


class FakeDev:
    def __init__(self, module):
        self.m = module
        self.writes = []

    def open_path(self, path):
        if self.m.fail_open:
            raise OSError("busy")

    def close(self):
        pass

    def set_nonblocking(self, v):
        pass

    def get_feature_report(self, rid, length):
        return self.m.features.get(rid, [])

    def read(self, n, timeout_ms=0):
        return self.m.inputs.pop(0) if self.m.inputs else []

    def write(self, data):                      # зонд не должен писать никогда
        self.m.wrote.append(data)
        return len(data)

    send_feature_report = write


class FakeHid:
    def __init__(self, features=None, inputs=None, fail_open=False):
        self.features, self.inputs, self.fail_open, self.wrote = features or {}, inputs or [], fail_open, []

    def enumerate(self, v, p):
        return [
            {"vendor_id": 0x25A7, "product_id": 0xFA7C, "interface_number": 1, "usage_page": 0xFF00,
             "usage": 1, "manufacturer_string": "ARDOR GAMING", "product_string": "Receiver",
             "path": b"p1", "serial_number": "SECRET"},
            {"vendor_id": 0x25A7, "product_id": 0xFA7C, "interface_number": 0, "usage_page": 1,
             "usage": 2, "manufacturer_string": "ARDOR GAMING", "product_string": "Receiver", "path": b"p0"},
            {"vendor_id": 0x1111, "product_id": 0x2222, "interface_number": 0, "usage_page": 0xFF01,
             "usage": 1, "manufacturer_string": "Other", "product_string": "Other dev", "path": b"p2"},
        ]

    def device(self):
        return FakeDev(self)


def caps(info):
    return {"input_len": 33, "feature_len": 8, "feature_ids": [5, 6]}


class ProbeTests(unittest.TestCase):
    def test_candidate_offsets(self):
        data = bytes([0x05, 0x00, 87, 222, 10, 255])
        found = hid_probe.candidate_offsets(data, 87)
        self.assertIn((2, 87), found)        # равно проценту
        self.assertIn((3, 222), found)       # шкала 0–255
        self.assertEqual(hid_probe.candidate_offsets(data, None), [])

    def test_report_reads_declared_features_and_inputs_and_never_writes(self):
        fake = FakeHid(features={5: [5, 0, 0, 87, 0, 0, 0, 0]}, inputs=[[4, 1, 2, 3]] * 3)
        text = hid_probe.build_report("25A7:FA7C", 87, 0.5, fake, caps)
        self.assertIn("feature 0x05", text)
        self.assertIn("byte [3] = 87", text)
        self.assertIn("feature 0x06: empty/no response", text)
        self.assertIn("x3: 04 01 02 03", text)
        self.assertEqual(fake.wrote, [])                 # read-only
        self.assertNotIn("SECRET", text)
        self.assertNotIn("Other dev", text)              # другой VID:PID не трогаем

    def test_default_targets_only_vendor_defined(self):
        text = hid_probe.build_report(None, None, 0.2, FakeHid(), caps)
        self.assertIn("25A7:FA7C  iface 1", text)
        self.assertNotIn("iface 0  page 0x0001", text)   # стандартный интерфейс мыши пропущен
        self.assertIn("1111:2222", text)

    def test_open_failure_is_reported(self):
        text = hid_probe.build_report("25A7:FA7C", None, 0.1, FakeHid(fail_open=True), caps)
        self.assertIn("cannot open", text)

    def test_without_hidapi(self):
        saved = hid_probe.hid
        hid_probe.hid = None
        try:
            self.assertIn("hidapi is not installed", hid_probe.build_report())
        finally:
            hid_probe.hid = saved

    def test_candidate_groups_and_parse(self):
        groups = hid_probe.candidate_groups([
            {"vendor_id": 0x25A7, "product_id": 0xFA7C, "product": "Receiver",
             "manufacturer": "ARDOR GAMING", "vendor_defined": True, "transport": "USB"}])
        self.assertEqual(groups[0]["vid_pid"], "25A7:FA7C")
        self.assertEqual(hid_probe.parse_vid_pid("0x25a7:fa7c"), (0x25A7, 0xFA7C))


if __name__ == "__main__":
    unittest.main()
