"""Run real INSTALL with a file-only /tmp and a regular-file /ramdisk fixture.

Only its normal JAR size/checksum build substitutions are applied. Inert payload
bytes satisfy the early file checks, then a deliberately wrong firmware train
stops every successful lock acquisition before any installation can begin.
CN_TEST_SHELL=/bin/mksh exercises the same entrypoint in the host-test container.
"""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "altscreen/Toolbox/scripts"
OWNER = "owner=CN_RGI_INSTALL_V1 pid="


class InstallerLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rgi-cn-lock-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.card = self.base / "card"
        self.scripts = self.card / "Toolbox/scripts"
        self.lock = self.root / "ramdisk/cn-rgi-install.lock"
        self.lock.parent.mkdir(parents=True)
        self.legacy_lock = self.root / "tmp/cn-rgi-install.lock"
        self.legacy_lock.parent.mkdir(parents=True)
        self.shell = os.environ.get("CN_TEST_SHELL", "/bin/sh")
        self.env = {**os.environ, "ALTSCREEN_CHAIN_TESTING": "1",
                    "ALTSCREEN_CHAIN_ROOT": str(self.root),
                    "ALTSCREEN_CHAIN_VOLUME": str(self.card),
                    "ALTSCREEN_SD_VOLUME": str(self.card)}
        for name in ("cn_migration_preflight.sh", "cn_upgrade_transaction.sh",
                     "altscreen_chain_test.sh", "rgi_companion.sh"):
            self.put(self.scripts / name, (SOURCE / name).read_bytes())
        payload = self.card / "Toolbox/carplay_alt_screen"
        self.put(payload / "CN_P1002_BUILD.txt",
                 "target_train=MHI2Q_CN_AUG22_P1002\nbuild_status=PASS\n")
        jar = payload / "hmi/carplay_hook-basevideo3.jar"
        self.put(jar, b"inert lock-test JAR; never installed\n")
        checksum = subprocess.check_output(["cksum"], input=jar.read_bytes()).decode().split()[0]
        installer = (SOURCE / "install_mmi_cockpit_carplay_rx.sh").read_text()
        installer = installer.replace("@CARPLAY_JAR_SIZE@", str(jar.stat().st_size))
        installer = installer.replace("@CARPLAY_JAR_CKSUM@", checksum)
        self.installer = self.scripts / "install_mmi_cockpit_carplay_rx.sh"
        self.put(self.installer, installer)
        mirror = payload / "mirror_display/release"
        self.put(mirror / "BUILD_INFO.txt",
                 "release_binary_status=PRIVATE111_DIRECT_DISPLAY_V2\n"
                 "vehicle_zip_status=READY_FOR_VEHICLE_TEST\n")
        self.put(mirror / "logo.rgba", b"inert logo")
        self.put(mirror / "watermark.rgba", b"inert watermark")
        self.put(self.root / "dev/shmem/version.txt", "Current train = WRONG_TEST_TRAIN\n")
        self.put(self.root / "mnt/app/eso/hmi/lsd/jars/carplay_hook.jar", b"keep-existing-jar")
        self.put(self.root / "mnt/system/etc/eso/production/smartphone_integrator.json",
                 '{"carplay":{"exec":"dio_manager"}}\n')
        self.put(self.card / "MMI-Cockpit-Carplay/backup/original/fixture", b"keep-backup")
        self.bin = self.base / "bin"
        mkdir = shutil.which("mkdir")
        self.put(self.bin / "mkdir", '#!/bin/sh\n'
                 'for arg do\n'
                 '  case "$arg" in "$ALTSCREEN_CHAIN_ROOT/tmp/"*)\n'
                 '    echo "fixture: /tmp does not support subdirectories: $arg" >&2\n'
                 '    exit 95;;\n'
                 '  esac\n'
                 'done\n'
                 f'exec "{mkdir}" "$@"\n')
        (self.bin / "mkdir").chmod(0o755)
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]

    @staticmethod
    def put(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)

    def snapshot(self):
        result = {}
        for label, base in (("device", self.root), ("card", self.card)):
            for path in base.rglob("*"):
                # Volatile lock changes are checked separately; all other state
                # must stay untouched when this firmware gate refuses INSTALL.
                if label == "device" and path.is_relative_to(self.root / "tmp"):
                    continue
                key = label + "/" + str(path.relative_to(base))
                mode = stat.S_IMODE(path.lstat().st_mode)
                if path.is_symlink():
                    result[key] = ("link", os.readlink(path))
                elif path.is_file():
                    result[key] = ("file", mode, path.read_bytes())
        return result

    def invoke(self, timeout=10):
        before = self.snapshot()
        p = subprocess.run([self.shell, str(self.installer)], env=self.env,
                           capture_output=True, text=True, timeout=timeout)
        self.assertEqual(before, self.snapshot(), "lock tests must not mutate installed files or backups")
        self.assertNotEqual(p.returncode, 0)
        return p

    def assert_refused(self, p, marker="lock exists with an unverified or inactive owner"):
        self.assertIn(marker, p.stdout + p.stderr)
        self.assertNotIn("CN_PREFLIGHT=", p.stdout)

    def test_flat_tmp_acquires_then_gate_refuses_and_releases(self):
        probe = subprocess.run(["mkdir", str(self.root / "tmp/probe")], env=self.env,
                               capture_output=True, text=True)
        self.assertEqual(probe.returncode, 95)
        p = self.invoke()
        self.assertIn("CN_PREFLIGHT=FAIL firmware_mismatch", p.stdout)
        self.assertFalse(self.lock.exists())

    def test_active_pid_is_preserved(self):
        content = f"{OWNER}{os.getpid()}\n".encode()
        self.lock.write_bytes(content)
        self.assert_refused(self.invoke(), "CN install already running")
        self.assertEqual(content, self.lock.read_bytes())

    def test_dead_pid_is_preserved_without_automatic_reaping(self):
        child = subprocess.Popen([self.shell, "-c", "exit 0"])
        child.wait(timeout=5)
        content = f"{OWNER}{child.pid}\n".encode()
        self.lock.write_bytes(content)
        p = self.invoke()
        self.assert_refused(p)
        self.assertIn("Full_MMI_reboot_then_retry_INSTALL", p.stdout)
        self.assertEqual(content, self.lock.read_bytes())

    def test_empty_owner_publication_window_is_preserved(self):
        self.lock.touch()
        self.assert_refused(self.invoke())
        self.assertEqual(b"", self.lock.read_bytes())

    def test_malformed_records_are_preserved(self):
        records = (b"garbage\n", f"{OWNER}not-a-pid\n".encode(),
                   f"{OWNER}0\n".encode(), f"{OWNER}1\n".encode(),
                   f"{OWNER}{os.getpid()}".encode(),
                   f"{OWNER}{os.getpid()}\n\n".encode(),
                   f"{OWNER}{os.getpid()}\0\n".encode(), b"x" * 129)
        for content in records:
            with self.subTest(content=content):
                self.lock.write_bytes(content)
                self.assert_refused(self.invoke())
                self.assertEqual(content, self.lock.read_bytes())

    def test_legacy_empty_directory_is_preserved(self):
        self.lock.mkdir()
        self.assert_refused(self.invoke())
        self.assertTrue(self.lock.is_dir())

    def test_legacy_directory_with_pid_is_preserved(self):
        self.lock.mkdir()
        self.put(self.lock / "pid", f"{os.getpid()}\n")
        self.assert_refused(self.invoke())
        self.assertEqual(f"{os.getpid()}\n", (self.lock / "pid").read_text())

    def test_symlink_is_preserved_without_writing_target(self):
        target = self.base / "foreign-lock"
        target.write_bytes(b"keep-target")
        self.lock.symlink_to(target)
        self.assert_refused(self.invoke())
        self.assertTrue(self.lock.is_symlink())
        self.assertEqual(b"keep-target", target.read_bytes())

    def test_dangling_symlink_is_preserved(self):
        target = self.base / "missing-target"
        self.lock.symlink_to(target)
        self.assert_refused(self.invoke())
        self.assertTrue(self.lock.is_symlink())
        self.assertFalse(target.exists())

    def test_fifo_is_refused_without_blocking(self):
        os.mkfifo(self.lock)
        self.assert_refused(self.invoke(timeout=5))
        self.assertTrue(stat.S_ISFIFO(self.lock.lstat().st_mode))

    def test_missing_parent_reports_real_creation_error(self):
        self.lock.parent.rmdir()
        p = self.invoke()
        self.assertIn("CN install lock could not be created", p.stdout)
        self.assertIn(str(self.lock), p.stderr)
        self.assertTrue(p.stderr.strip(), "the original redirection error must be visible")
        self.assertNotIn("invalid", p.stdout)
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.legacy_lock.exists(), "must not fall back to /tmp")

    def test_ramdisk_symlink_is_refused_before_writing_target(self):
        self.lock.parent.rmdir()
        target = self.base / "alternate-ramdisk"
        target.mkdir()
        self.lock.parent.symlink_to(target, target_is_directory=True)
        p = self.invoke()
        self.assert_refused(p, "CN install lock parent is a symlink")
        self.assertEqual([], list(target.iterdir()))
        self.assertTrue(self.lock.parent.is_symlink())

    def test_old_tmp_lock_file_requires_reboot_and_is_preserved(self):
        content = f"{OWNER}{os.getpid()}\n".encode()
        self.legacy_lock.write_bytes(content)
        p = self.invoke()
        self.assert_refused(p, "legacy CN install lock exists")
        self.assertIn("Full_MMI_reboot_then_retry_INSTALL", p.stdout)
        self.assertEqual(content, self.legacy_lock.read_bytes())
        self.assertFalse(self.lock.exists())

    def test_old_tmp_lock_directory_requires_reboot_and_is_preserved(self):
        self.legacy_lock.mkdir()
        self.put(self.legacy_lock / "pid", f"{os.getpid()}\n")
        p = self.invoke()
        self.assert_refused(p, "legacy CN install lock exists")
        self.assertEqual(f"{os.getpid()}\n", (self.legacy_lock / "pid").read_text())
        self.assertFalse(self.lock.exists())

    def test_old_tmp_dangling_lock_symlink_is_preserved(self):
        target = self.base / "old-missing-target"
        self.legacy_lock.symlink_to(target)
        self.assert_refused(self.invoke(), "legacy CN install lock exists")
        self.assertTrue(self.legacy_lock.is_symlink())
        self.assertFalse(target.exists())
        self.assertFalse(self.lock.exists())

    def pause_after_acquisition(self):
        ready = self.base / "recover-entered"
        proceed = self.base / "recover-proceed"
        self.env["LOCK_TEST_READY"] = str(ready)
        self.env["LOCK_TEST_PROCEED"] = str(proceed)
        self.put(self.scripts / "cn_upgrade_transaction.sh",
                 '#!/bin/sh\n[ "$1" = recover ] || exit 91\n'
                 ': > "$LOCK_TEST_READY"\n'
                 'while [ ! -f "$LOCK_TEST_PROCEED" ]; do sleep 0.02; done\nexit 0\n')
        proc = subprocess.Popen([self.shell, str(self.installer)], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 5
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(ready.exists(), "installer did not reach recovery after acquiring lock")
        self.assertEqual(f"{OWNER}{proc.pid}\n", self.lock.read_text())
        return proc, proceed

    def test_two_real_installers_do_not_share_the_lock(self):
        proc, proceed = self.pause_after_acquisition()
        held = self.lock.read_bytes()
        self.assert_refused(self.invoke(), "CN install already running")
        self.assertEqual(held, self.lock.read_bytes())
        proceed.touch()
        out, err = proc.communicate(timeout=5)
        self.assertIn("CN_PREFLIGHT=FAIL firmware_mismatch", out, err)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(self.lock.exists())

    def check_changed_owner_at_release(self, change):
        proc, proceed = self.pause_after_acquisition()
        changed = change(self.lock.read_bytes())
        self.lock.write_bytes(changed)
        proceed.touch()
        out, err = proc.communicate(timeout=5)
        self.assertIn("CN install lock ownership changed", out + err)
        self.assertEqual(changed, self.lock.read_bytes())
        self.assertEqual(proc.returncode, 1)

    def test_release_preserves_changed_complete_owner(self):
        self.check_changed_owner_at_release(lambda _: f"{OWNER}{os.getpid()}\n".encode())

    def test_release_preserves_extra_newline_same_shell_text(self):
        self.check_changed_owner_at_release(lambda old: old + b"\n")

    def test_release_preserves_embedded_nul(self):
        self.check_changed_owner_at_release(lambda old: old[:-1] + b"\0\n")


if __name__ == "__main__":
    unittest.main()
