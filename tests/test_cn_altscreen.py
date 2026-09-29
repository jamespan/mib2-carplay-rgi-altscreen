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

    def test_safearea_off_only_changes_phone_marker_and_selected_fps(self):
        for column in (1, 2):
            baseline = fps.apply(self.stock, fps.TARGETS['libcarplay_altscreen.so']['patches'], column)
            result = cn.patch(baseline, safe_area=False)
            self.assertEqual(cn.sha(cn.normalized(result)), cn.CN_MARKER_SHA)
            changed = {i for i, (a, b) in enumerate(zip(baseline, result)) if a != b}
            self.assertTrue(changed <= set(range(0xDF88, 0xDF8C)))
            self.assertEqual(result[cn.START:cn.END], self.stock[cn.START:cn.END])
            self.assertEqual(result[0x26218:0x2621C], self.stock[0x26218:0x2621C])
            self.assertEqual(result[0x2713C:0x27140], self.stock[0x2713C:0x27140])

    def test_safearea_can_be_disabled_and_restored_exactly(self):
        for column in (1, 2):
            baseline = fps.apply(self.stock, fps.TARGETS['libcarplay_altscreen.so']['patches'], column)
            enabled = cn.patch(baseline)
            disabled = cn.patch(enabled, safe_area=False)
            self.assertEqual(disabled, cn.patch(baseline, safe_area=False))
            self.assertEqual(cn.patch(disabled, safe_area=False), disabled)
            self.assertEqual(cn.patch(disabled), enabled)

    def test_safearea_off_rejects_foreign_binary(self):
        with self.assertRaises(ValueError):
            cn.patch(self.stock[:200] + b'changed!' + self.stock[208:], safe_area=False)


if __name__ == '__main__':
    unittest.main()
