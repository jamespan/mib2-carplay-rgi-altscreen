import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from patch_video_phase import patch, OFFSET, OLD, NEW, TARGET
from patch_altscreen_fps import apply


class VideoPhaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / "altscreen/Toolbox/carplay_alt_screen/mirror_display/release/carplay-alt111-mirror-display").read_bytes()

    def test_exact_first_frame_only_change(self):
        out = patch(self.raw)
        self.assertEqual([i for i, (a,b) in enumerate(zip(self.raw,out)) if a != b], [0x2897])
        self.assertEqual(len(out), len(self.raw))
        # Branch target unchanged, now unconditional. Marker call still reaches 0x101c94.
        word = int.from_bytes(out[OFFSET:OFFSET+4], "little")
        self.assertEqual(word >> 24, 0xea)
        self.assertEqual(0x102894 + 8 + (word & 0xffffff) * 4, 0x102d14)
        self.assertEqual(out[0x2d14:0x2d24], bytes.fromhex("0100a0e308119fe544219fe5dbfbffeb"))
        # Subsequent presents use a separate loop, not the first-frame marker branch.
        self.assertEqual(out[0x2964:0x2974], bytes.fromhex("7c0600eb015085e2000050e34201000a"))
        # Failed initial present still branches around the publication path.
        self.assertEqual(out[0x26b8:0x26c4], bytes.fromhex("270700eb004050e26d00001a"))
        # Logo completion sets r6=1; original EQ skipped publication for that exact case.
        self.assertEqual(out[0x2ebc:0x2ec8], bytes.fromhex("0160a0e30e0300ebf7fdffea"))

    def test_idempotent(self):
        out = patch(self.raw)
        self.assertEqual(patch(out), out)

    def test_preserves_complete_fps_variant(self):
        fast = apply(self.raw, TARGET["patches"], 2)
        out = patch(fast)
        for p in TARGET["patches"]:
            self.assertEqual(out[p[0]:p[0]+4], bytes.fromhex(p[2]))
        self.assertEqual(patch(out), out)

    def test_unknown_input_rejected(self):
        corrupt = bytearray(self.raw); corrupt[0x3100] ^= 1
        with self.assertRaises(ValueError): patch(corrupt)
        corrupt = bytearray(self.raw); corrupt[OFFSET] ^= 1
        with self.assertRaises(ValueError): patch(corrupt)

    def test_mixed_fps_rejected(self):
        corrupt = bytearray(self.raw)
        p = TARGET["patches"][0]; corrupt[p[0]:p[0]+4] = bytes.fromhex(p[2])
        with self.assertRaises(ValueError): patch(corrupt)


if __name__ == "__main__": unittest.main()
