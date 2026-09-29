"""Run real GEM shell scripts in an isolated MMX/card fixture; never touch a car."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "altscreen/Toolbox/scripts"


class StoreLogs(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="carplay-logs-", dir="/tmp")
        self.base = Path(self.sandbox.name)
        self.root = self.base / "mmx"
        self.card = self.base / "sd"
        self.bin = self.base / "bin"
        self.launchers = self.base / "gem"
        for path in (self.root / "tmp", self.card / "Toolbox", self.bin, self.launchers):
            path.mkdir(parents=True)
        for name in ("store_carplay_logs.sh", "finish_mmi_cockpit_carplay_test.sh", "carplay_verbose_off.sh"):
            shutil.copy2(SCRIPTS / name, self.launchers / name)
        self.env = dict(os.environ, ALTSCREEN_CHAIN_TESTING="1",
                        ALTSCREEN_CHAIN_ROOT=str(self.root), ALTSCREEN_CHAIN_VOLUME=str(self.card),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.executable("pidin", '#!/bin/sh\nprintf "fixture pidin %s\\n" "$*"\n')
        # Model the real vehicle's mkdir -p EEXIST behavior, not desktop mkdir.
        self.executable("mkdir", '#!/bin/sh\nif [ "$1" = -p ] && [ -d "$2" ]; then exit 17; fi\nexec /bin/mkdir "$@"\n')
        (self.root / "tmp/carplay_hook.log").write_text("Identify patched\nSent 0x5200\n")
        (self.root / "tmp/carplay_java.log.1").write_text("RG activate\n")
        (self.root / "tmp/mmi-mirror-basevideo.ready").touch()

    def tearDown(self):
        self.sandbox.cleanup()

    def executable(self, name, text, folder=None):
        p = (folder or self.bin) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        p.chmod(0o755)
        return p

    def run_script(self, name="store_carplay_logs.sh", *args):
        return subprocess.run([os.environ.get("TEST_SHELL", "/bin/sh"), str(self.launchers / name), *args],
                              env=self.env, text=True, capture_output=True, timeout=20)

    def save(self, n=1):
        return self.card / f"MMI-Cockpit-Carplay/logs/rgi/collect_{n}"

    def test_repeat_collection_and_qnx_existing_directory(self):
        first = self.run_script()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.run_script().returncode, 0)
        self.assertIn("verbose_before=off", (self.save(1) / "info.txt").read_text())
        self.assertIn("verbose_before=on", (self.save(2) / "info.txt").read_text())
        self.assertEqual((self.save(1) / "tmp/carplay_hook.log").read_bytes(),
                         (self.save(2) / "tmp/carplay_hook.log").read_bytes())
        self.assertTrue((self.save(1) / "tmp/mmi-mirror-basevideo.ready").is_file())
        self.assertTrue((self.root / "tmp/carplay_verbose").exists())
        (self.save(1).parent / "collect_009").mkdir()
        shutil.rmtree(self.save(1))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertTrue(self.save(10).is_dir())
        self.assertFalse(self.save(1).exists())

    def test_whitelist_limits_rotations_and_symlinks(self):
        content = b"x" * (1048576 + 50) + b"end"
        (self.root / "tmp/carplay_hook.log").write_bytes(content)
        (self.root / "tmp/carplay_hook.log.2").symlink_to(self.root / "tmp/carplay_hook.log")
        (self.root / "tmp/carplay111_h264").write_text("shared memory must stay out")
        (self.root / "tmp/carplay_cover.jpg").write_text("private image")
        (self.root / "tmp/unrelated.log").write_text("not a CarPlay log")
        os.mkfifo(self.root / "tmp/maneuver_render.log")
        config = self.root / "mnt/system/etc/eso/production"
        config.mkdir(parents=True)
        (config / "dio_manager.json").write_text('{"iap2": [20992]}')
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual((self.save() / "tmp/carplay_hook.log").read_bytes(), content[-1048576:])
        self.assertTrue((self.save() / "tmp/carplay_java.log.1").exists())
        for name in ("carplay_hook.log.2", "carplay111_h264", "carplay_cover.jpg", "unrelated.log", "maneuver_render.log"):
            self.assertFalse((self.save() / "tmp" / name).exists(), name)
        self.assertEqual((self.save() / "config/dio_manager.json").read_bytes(), (config / "dio_manager.json").read_bytes())
        self.assertIn("TRUNCATED", (self.save() / "info.txt").read_text())

    def test_probe_timeout_keeps_logs_and_reports_warning(self):
        self.executable("pidin", '#!/bin/sh\n[ "$1" != arguments ] || exec sleep 30\necho fixture\n')
        before = time.monotonic()
        result = self.run_script()
        self.assertLess(time.monotonic() - before, 10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PASS_WITH_WARNINGS", result.stdout)
        self.assertTrue((self.save() / "tmp/carplay_hook.log").is_file())
        self.assertIn("probe_incomplete=processes.txt", (self.save() / "info.txt").read_text())

    def test_copy_failure_preserves_successful_files(self):
        config = self.root / "mnt/system/etc/eso/production"
        config.mkdir(parents=True)
        (config / "dio_manager.json").write_text("fixture")
        self.executable("cp", "#!/bin/sh\nexit 9\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.save() / "tmp/carplay_hook.log").is_file())
        self.assertIn("copy_failed=", (self.save() / "info.txt").read_text())

    def test_updated_gem_does_not_forward_collection_to_old_runtime(self):
        runtime = self.root / "mnt/app/root/carplay-altscreen/bin"
        runtime.mkdir(parents=True)
        self.executable("store_carplay_logs.sh", "#!/bin/sh\nexit 93\n", runtime)
        self.assertEqual(self.run_script().returncode, 0)
        self.assertTrue(self.save().is_dir())

    def test_verbose_off_preserves_saved_logs_and_persistent_marker(self):
        self.assertEqual(self.run_script().returncode, 0)
        persistent = self.root / "mnt/app/carplay_verbose"
        persistent.parent.mkdir(parents=True)
        persistent.touch()
        result = self.run_script("carplay_verbose_off.sh")
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.root / "tmp/carplay_verbose").exists())
        self.assertTrue(persistent.exists())
        self.assertTrue(self.save().is_dir())
        self.assertIn("persistent marker left unchanged", result.stdout)

    def test_collection_failure_still_restores_and_returns_restore_status(self):
        self.executable("store_carplay_logs.sh", "#!/bin/sh\necho collect >> \"$ALTSCREEN_CHAIN_ROOT/order\"\nexit 8\n", self.launchers)
        self.executable("altscreen_chain_test.sh", "#!/bin/sh\nexit 9\n", self.launchers)
        self.executable("stop_mmi_cockpit_carplay_test.sh", "#!/bin/sh\necho restore >> \"$ALTSCREEN_CHAIN_ROOT/order\"\nexit 7\n", self.launchers)
        result = self.run_script("finish_mmi_cockpit_carplay_test.sh")
        self.assertEqual(result.returncode, 7)
        self.assertEqual((self.root / "order").read_text(), "collect\nrestore\n")
        self.assertIn("restoring originals anyway", result.stdout)

    def test_collect_before_forward_to_existing_old_runtime_restore(self):
        self.executable("store_carplay_logs.sh", "#!/bin/sh\necho collect >> \"$ALTSCREEN_CHAIN_ROOT/order\"\nexit 8\n", self.launchers)
        runtime = self.root / "mnt/app/root/carplay-altscreen/bin"
        self.executable("altscreen_chain_test.sh", "#!/bin/sh\nexit 0\n", runtime)
        self.executable("finish_mmi_cockpit_carplay_test.sh", "#!/bin/sh\necho old-runtime-restore >> \"$ALTSCREEN_CHAIN_ROOT/order\"\nexit 6\n", runtime)
        result = self.run_script("finish_mmi_cockpit_carplay_test.sh")
        self.assertEqual(result.returncode, 6)
        self.assertEqual((self.root / "order").read_text(), "collect\nold-runtime-restore\n")

    def test_bad_test_root_rejected_before_writes(self):
        self.env["ALTSCREEN_CHAIN_ROOT"] = "/"
        self.assertEqual(self.run_script().returncode, 2)
        self.assertFalse(self.save().exists())


if __name__ == "__main__":
    unittest.main()
