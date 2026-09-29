#!/usr/bin/env python3
"""Private splash staging and real launcher session/recovery regression tests."""

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "altscreen/Toolbox/carplay_alt_screen/mirror_display/release"
SPEC = importlib.util.spec_from_file_location("logos", ROOT / "tools/stage_private_logos.py")
LOGOS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOGOS)


class SplashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="altscreen-splash-")
        self.base = Path(self.temp.name)
        self.release = self.base / "release"
        self.release.mkdir()
        for name in ("start_vehicle.sh", "select_logo.sh"):
            shutil.copyfile(RELEASE / name, self.release / name)
        self.entropy = self.base / "entropy"
        self.entropy.write_bytes(bytes(16))
        self.logo = b"AL111LG1" + struct.pack("<II", 1, 1) + bytes(4)
        (self.release / "logo.rgba").write_bytes(self.logo)
        self.env = dict(os.environ, ALT111_LOGO_RANDOM_DEVICE=str(self.entropy))
        for key in ("ALT111_LOGO_ASSET", "ALT111_LOGO_FIXED_ASSET", "ALT111_LOGO_PICK_SOURCE", "ALT111_LOGO_PICK_DETAIL"):
            self.env.pop(key, None)
        self.groups = []

    def tearDown(self):
        for pid in self.groups:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.temp.cleanup()

    def pool(self, count=16):
        (self.release / "logo_pool.count").write_text(str(count) + "\n")
        for index in range(1, count + 1):
            (self.release / f"logo_{index}.rgba").write_bytes(self.logo)

    def select(self, **extra):
        output = subprocess.check_output(["/bin/sh", "-eu", "-c", '''
          . "$1/select_logo.sh"
          select_startup_logo "$1" "$2"
          printf '%s\n' "$ALT111_LOGO_ASSET" "$ALT111_LOGO_PICK_SOURCE" "$ALT111_LOGO_FIXED_ASSET" "$ALT111_LOGO_PICK_DETAIL"
        ''', "test", str(self.release), str(self.base)], env=dict(self.env, **extra), text=True)
        return output.splitlines()

    def test_default_without_private_assets(self):
        result = self.select()
        self.assertEqual(result[:3], [str(self.release / "logo.rgba"), "default", ""])

    def test_qnx_entropy_path_selects_numbered_pool(self):
        self.pool()
        crc = int(subprocess.check_output(["cksum", str(self.entropy)]).split()[0])
        result = self.select()
        self.assertEqual(result[:3], [str(self.release / f"logo_{crc % 16 + 1}.rgba"), "dd_urandom", ""])
        self.assertFalse(list(self.base.glob("MMI-Cockpit-Carplay.logo-random.*")))

    def test_entropy_failure_keeps_valid_default(self):
        self.pool()
        self.entropy.write_bytes(b"short")
        result = self.select()
        self.assertEqual(result[0], str(self.release / "logo.rgba"))
        self.assertEqual(result[3], "random_read_failed")

    def test_missing_asset_and_bad_count_keep_default(self):
        (self.release / "logo_pool.count").write_text("2\n")
        self.assertEqual(self.select()[0], str(self.release / "logo.rgba"))
        (self.release / "logo_pool.count").write_text("$(touch invalid)\n")
        self.assertEqual(self.select()[3], "invalid_pool_count")

    def test_fixed_override_remains_fixed(self):
        self.pool()
        result = self.select(ALT111_LOGO_ASSET="/explicit/logo.rgba")
        self.assertEqual(result[:3], ["/explicit/logo.rgba", "override", "/explicit/logo.rgba"])

    def test_same_session_recovery_retains_choice(self):
        self.pool()
        first = self.select()
        self.entropy.write_bytes(b"x" * 16)
        second = self.select(ALT111_LOGO_ASSET=first[0], ALT111_LOGO_FIXED_ASSET="",
                             ALT111_LOGO_PICK_SOURCE=first[1])
        self.assertEqual(first[:3], second[:3])

    def test_stager_rejects_invalid_pool_before_writing(self):
        source = self.base / "source"
        source.mkdir()
        (source / "logo_1.rgba").write_bytes(self.logo)
        (source / "logo_3.rgba").write_bytes(self.logo)
        with self.assertRaises(ValueError):
            LOGOS.stage_pool(source, self.release)
        self.assertFalse((self.release / "logo_1.rgba").exists())
        (source / "logo_3.rgba").rename(source / "logo_2.rgba")
        (source / "logo_2.rgba").write_bytes(self.logo[:-1])
        with self.assertRaises(ValueError):
            LOGOS.stage_pool(source, self.release)
        self.assertFalse((self.release / "logo_1.rgba").exists())

    def test_stager_copies_bytes_and_updates_checksums(self):
        source = self.base / "source"
        source.mkdir()
        for index in (1, 2):
            (source / f"logo_{index}.rgba").write_bytes(self.logo)
        result = LOGOS.stage_pool(source, self.release)
        self.assertEqual(result["count"], 2)
        self.assertEqual((self.release / "logo_1.rgba").read_bytes(), self.logo)
        for line in (self.release / "SHA256SUMS").read_text().splitlines():
            checksum, name = line.split("  ", 1)
            self.assertEqual(checksum, hashlib.sha256((self.release / name).read_bytes()).hexdigest())

    def wait_for(self, predicate, timeout=18):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        self.fail("launcher condition timed out: " + (self.base / "launcher.log").read_text())

    def launch(self, ready):
        self.pool()
        self.records = self.base / "launches"
        fake = self.base / "fake-mirror"
        fake.write_text('''#!/bin/sh
          trap 'exit 0' TERM INT
          printf '%s %s\\n' "$$" "$ALT111_LOGO_ASSET" >> "$SPLASH_RECORDS"
          if [ "$SPLASH_READY" = 1 ]; then : > "$ALT111_MIRROR_BASE_READY_FILE"; fi
          while :; do sleep 1; done
        ''')
        fake.chmod(0o755)
        (self.base / "demand").touch()
        env = dict(self.env, ALT111_MIRROR_BIN=str(fake), ALT111_MIRROR_TMP_ROOT=str(self.base),
                   ALT111_JAVA_BASE_READY_FILE=str(self.base / "base-ready"),
                   ALT111_MIRROR_ACTIVE_FILE=str(self.base / "demand"),
                   SPLASH_RECORDS=str(self.records), SPLASH_READY=str(int(ready)))
        with (self.base / "launcher.log").open("a") as log:
            child = subprocess.Popen(["/bin/sh", str(self.release / "start_vehicle.sh")],
                                     env=env, stdout=log, stderr=log, start_new_session=True)
        self.groups.append(child.pid)
        child.wait(timeout=5)
        self.assertEqual(child.returncode, 0)
        self.wait_for(lambda: self.records.exists())
        return env

    def lines(self):
        return self.records.read_text().splitlines()

    def test_real_launcher_new_session_after_present_and_abnormal_recovery(self):
        self.launch(ready=True)
        original = self.lines()[0].split(" ", 1)[1]
        # Force a different deterministic random sample for the next draw.
        for value in range(1, 256):
            self.entropy.write_bytes(bytes([value]) * 16)
            if self.select()[0] != original:
                break
        expected = self.select()[0]
        hook = self.base / "MMI-Cockpit-Carplay.altscreen_hook.log"
        hook.write_text("PHASE=DIRECT111_TAP_STOP_STALE stream=old\n")
        time.sleep(1.2)
        self.assertEqual(len(self.lines()), 1)
        with hook.open("a") as stream:
            stream.write("PHASE=DIRECT111_TAP_STOP stream=current\n")
        self.wait_for(lambda: len(self.lines()) >= 2)
        self.assertEqual(self.lines()[1].split(" ", 1)[1], expected)
        # A sidecar crash within that session must retain exactly this asset.
        time.sleep(1.2)
        os.kill(int(self.lines()[1].split()[0]), signal.SIGKILL)
        self.wait_for(lambda: len(self.lines()) >= 3)
        self.assertEqual(self.lines()[2].split(" ", 1)[1], expected)

    def test_real_launcher_restarts_before_first_present(self):
        self.launch(ready=False)
        hook = self.base / "MMI-Cockpit-Carplay.altscreen_hook.log"
        hook.write_text("PHASE=DIRECT111_TAP_STOP stream=before_present\n")
        self.wait_for(lambda: len(self.lines()) >= 2)
        log = (self.base / "MMI-Cockpit-Carplay.mirror.log").read_text()
        self.assertIn("phase=before_first_present", log)
        self.assertGreaterEqual(log.count("random_source=dd_urandom"), 2)


if __name__ == "__main__":
    unittest.main()
