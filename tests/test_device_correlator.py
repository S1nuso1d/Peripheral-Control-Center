import unittest

from device_correlator import correlate_hid_to_pnp


class DeviceCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.hid = [{
            "id": "hid:25A7:FA7C:1:abc",
            "vendor_id": 0x25A7,
            "product_id": 0xFA7C,
            "transport": "USB",
        }]

    def test_matches_exact_vid_pid_and_compatible_transport(self):
        pnp = [
            {"id": "pnp:1", "vendor_id": "25A7", "product_id": "FA7C",
             "transport": "USB", "name": "Receiver"},
            {"id": "pnp:2", "vendor_id": "25A7", "product_id": "FA7C",
             "transport": "Bluetooth", "name": "Other transport"},
            {"id": "pnp:3", "vendor_id": "25A7", "product_id": "FA7D",
             "transport": "USB", "name": "Different product"},
        ]
        matches = correlate_hid_to_pnp(self.hid, pnp)
        self.assertEqual([item["id"] for item in matches[self.hid[0]["id"]]], ["pnp:1"])

    def test_retains_multiple_candidates_instead_of_merging(self):
        pnp = [
            {"id": "pnp:b", "vendor_id": "25A7", "product_id": "FA7C",
             "transport": "HID", "name": "Child"},
            {"id": "pnp:a", "vendor_id": "25A7", "product_id": "FA7C",
             "transport": "USB", "name": "Parent"},
        ]
        matches = correlate_hid_to_pnp(self.hid, pnp)[self.hid[0]["id"]]
        self.assertEqual({item["id"] for item in matches}, {"pnp:a", "pnp:b"})

    def test_unknown_hid_transport_does_not_block_exact_id_match(self):
        device = dict(self.hid[0], transport="HID (transport unknown)")
        pnp = [{"id": "pnp:1", "vendor_id": 0x25A7, "product_id": 0xFA7C,
                "transport": "USB"}]
        self.assertEqual(len(correlate_hid_to_pnp([device], pnp)[device["id"]]), 1)

    def test_missing_ids_do_not_use_name_fallback(self):
        device = dict(self.hid[0], vendor_id=0, product_id=0)
        pnp = [{"id": "pnp:1", "vendor_id": "25A7", "product_id": "FA7C",
                "transport": "USB", "name": "Same name"}]
        self.assertEqual(correlate_hid_to_pnp([device], pnp)[device["id"]], [])


if __name__ == "__main__":
    unittest.main()
