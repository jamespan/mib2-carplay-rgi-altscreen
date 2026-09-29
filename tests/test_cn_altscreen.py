"""Pinned binary composition and fail-closed identity checks, no target execution."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import patch_cn_altscreen as cn
import patch_altscreen_fps as fps


class CnOverlayTest(unittest.TestCase):
    def setUp(self):
        self.stock = (ROOT / 'altscreen/Toolbox/carplay_alt_screen/universal/libcarplay_altscreen.so').read_bytes()

    def test_matches_vehicle_validated_v21(self):
        self.assertEqual(cn.sha(cn.patch(self.stock)), cn.CN_SHA)

    def test_fps_composes_without_changing_geometry(self):
        patches = fps.TARGETS['libcarplay_altscreen.so']['patches']
        fps_first = cn.patch(fps.apply(self.stock, patches, 2))
        cn_first = fps.apply(cn.patch(self.stock), patches, 2)
        self.assertEqual(fps_first, cn_first)
        self.assertEqual(fps_first[0x14B84:0x14B88], bytes.fromhex('00f020e3'))

    def test_idempotent_in_both_fps_modes(self):
        for column in (1, 2):
            data = fps.apply(self.stock, fps.TARGETS['libcarplay_altscreen.so']['patches'], column)
            result = cn.patch(data)
            self.assertEqual(cn.patch(result), result)

    def test_rejects_foreign_or_damaged_binary(self):
        for data in (b'', self.stock[:-1], self.stock[:200] + b'changed!' + self.stock[208:]):
            with self.assertRaises(ValueError):
                cn.patch(data)

    def test_does_not_touch_elf_metadata_or_other_code(self):
        result = cn.patch(self.stock)
        allowed = set(range(cn.START, cn.END))
        for offset in (0x26218, 0x2713C, 0xDF88):
            allowed.update(range(offset, offset + 4))
        self.assertEqual(len(result), len(self.stock))
        self.assertTrue({i for i, (a, b) in enumerate(zip(self.stock, result)) if a != b} <= allowed)


if __name__ == '__main__':
    unittest.main()
