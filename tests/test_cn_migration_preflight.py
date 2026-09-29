"""Exercise the read-only migration gate with real shell processes."""
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "altscreen/Toolbox/scripts"


class MigrationPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rgi-cn-gate-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        # Preserve /tmp spelling: the production test-root guard intentionally
        # refuses arbitrary host paths (macOS resolves it to /private/tmp).
        self.root = Path(self.tmp.name) / "root"
        self.card = Path(self.tmp.name) / "card"
        self.profile = self.card / "Toolbox/carplay_alt_screen/CN_P1002_BUILD.txt"
        self.put(self.profile, "target_train=MHI2Q_CN_AUG22_P1002\nbuild_status=PASS\n")
        self.version = self.root / "dev/shmem/version.txt"
        self.put(self.version, "Current train = 'MHI2Q_CN_AUG22_P1002'\n")
        self.cfg = self.root / "mnt/system/etc/eso/production/smartphone_integrator.json"
        self.put(self.cfg, '{"carplay":{"exec":"dio_manager"}}\n')
        self.env = {**os.environ, "ALTSCREEN_CHAIN_TESTING": "1",
                    "ALTSCREEN_CHAIN_ROOT": str(self.root),
                    "ALTSCREEN_SD_VOLUME": str(self.card)}

    def put(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def tree(self):
        # Both the device and SD are read-only during identification. In
        # particular, rejecting an old/foreign project must not rewrite its
        # backup, state markers, or the stock HMI JAR.
        return {(label, str(p.relative_to(base))): p.read_bytes()
                for label, base in (("device", self.root), ("card", self.card))
                for p in base.rglob("*") if p.is_file()}

    def run_gate(self):
        before = self.tree()
        proc = subprocess.run(["sh", str(SCRIPTS / "cn_migration_preflight.sh")],
                              env=self.env, capture_output=True, text=True)
        self.assertEqual(before, self.tree(), "preflight must never mutate the device")
        return proc

    def test_clean_cn_passes(self):
        p = self.run_gate()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("clean_install=YES", p.stdout)

    def test_other_train_and_prefix_collisions_refused(self):
        for train in ("MHI2Q_ER_AUG22_P5092", "MHI2Q_CN_AUG22_P10020", "", "NOT_MHI2Q_CN_AUG22_P1002"):
            with self.subTest(train=train):
                self.put(self.version, "Current train = " + train)
                p = self.run_gate()
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("firmware_mismatch", p.stdout)

    def test_existing_jar_refused_even_if_empty(self):
        self.put(self.root / "mnt/app/eso/hmi/lsd/jars/carplay_hook.jar", "")
        self.assertIn("previous_custom_installation_present", self.run_gate().stdout)

    def test_existing_runtime_refused(self):
        (self.root / "mnt/app/root/carplay-altscreen").mkdir(parents=True)
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_lookalike_runtime_owner_does_not_authorize_foreign_jar(self):
        runtime = self.root / "mnt/app/root/carplay-altscreen"
        self.put(runtime / ".mmi-cockpit-carplay-runtime-owner", "MMI-Cockpit-Carplay\n")
        self.put(self.root / "mnt/app/eso/hmi/lsd/jars/carplay_hook.jar", "foreign hook")
        self.put(self.card / "MMI-Cockpit-Carplay/state/INSTALLED", "")
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_jar_symlink_does_not_authorize_upgrade(self):
        jar = self.root / "mnt/app/eso/hmi/lsd/jars/carplay_hook.jar"
        self.put(self.root / "foreign.jar", "foreign hook")
        jar.parent.mkdir(parents=True)
        jar.symlink_to(self.root / "foreign.jar")
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_separate_navignore_patch_refused(self):
        self.put(self.root / "mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar", "old patch")
        self.assertIn("conflicting_NavActiveIgnore_jar", self.run_gate().stdout)

    def test_legacy_preload_refused(self):
        for value in ("libcn_carplay_zoom_v30.so", "libcarplay_hook.so", "carplay_startup.sh"):
            with self.subTest(value=value):
                self.put(self.cfg, value)
                self.assertNotEqual(self.run_gate().returncode, 0)

    def test_foreign_hook_not_overwritten(self):
        self.put(self.root / "mnt/app/root/hooks/carplay_startup.sh", "foreign configuration")
        self.assertIn("existing_hook_file", self.run_gate().stdout)

    def test_missing_profile_keeps_upstream_path(self):
        self.profile.unlink()
        self.put(self.version, "Current train = MHI2Q_ER_AUG22_P5092")
        self.assertEqual(self.run_gate().returncode, 0)

    def test_unknown_profile_not_sourced(self):
        self.put(self.profile, 'touch "$ALTSCREEN_CHAIN_ROOT/unwanted"\n')
        self.assertNotEqual(self.run_gate().returncode, 0)
        self.assertFalse((self.root / "unwanted").exists())

    def test_incomplete_build_refused(self):
        self.put(self.profile, "target_train=MHI2Q_CN_AUG22_P1002\nbuild_status=INCOMPLETE\n")
        self.assertIn("incomplete_build", self.run_gate().stdout)


class KnownProjectUpgrade(unittest.TestCase):
    """Use shipped payload identities; no stand-in bytes bypass identification."""

    put = MigrationPreflight.put
    tree = MigrationPreflight.tree
    run_gate = MigrationPreflight.run_gate

    def setUp(self):
        MigrationPreflight.setUp(self)
        raw = os.environ.get("CN_TEST_SD_DIR")
        self.package = Path(raw) if raw else REPO / "build/sd-cn-v2-sport-rgi-logs"
        if not (self.package / "SHA256SUMS-SD.txt").is_file():
            self.skipTest("set CN_TEST_SD_DIR to a built CN SD package for binary identity tests")
        helper = self.card / "Toolbox/scripts/cn_upgrade_transaction.sh"
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCRIPTS / "cn_upgrade_transaction.sh", helper)
        source = self.package / "Toolbox/carplay_alt_screen"
        runtime = self.root / "mnt/app/root/carplay-altscreen"
        self.jar = self.root / "mnt/app/eso/hmi/lsd/jars/carplay_hook.jar"
        pairs = {
            source / "hmi/carplay_hook-basevideo3.jar": self.jar,
            source / "universal/libcarplay_altscreen.so": runtime / "lib/libcarplay_altscreen.so",
            source / "rgi/libcarplay_hook.so": self.root / "mnt/app/root/hooks/libcarplay_hook.so",
            source / "rgi/maneuver_render": self.root / "mnt/app/root/hooks/maneuver_render",
            source / "mirror_display/release/carplay-alt111-mirror-display": runtime / "bin/mirror/carplay-alt111-mirror-display",
            source / "mirror_display/release/SHA256SUMS": runtime / "bin/mirror/SHA256SUMS",
        }
        for src, dst in pairs.items():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        self.put(runtime / ".mmi-cockpit-carplay-runtime-owner",
                 "owner=MMI-Cockpit-Carplay\nruntime=carplay-altscreen\n")
        self.put(runtime / "bin/mirror/.mmi-cockpit-carplay-mirror-owner",
                 "owner=MMI-Cockpit-Carplay\nmode=carplay-private111-direct-display-v2\n")
        self.put(self.card / "MMI-Cockpit-Carplay/state/INSTALLED", "")
        self.put(self.card / "MMI-Cockpit-Carplay/state/firmware_profile.txt", "UNIVERSAL\n")
        self.put(self.card / "MMI-Cockpit-Carplay/backup/original/COMPLETE", "")
        self.put(self.cfg,
                 '{"exec": "carplay_startup.sh", "envs": ["CARPLAY_PRELOAD_EXTRA=/mnt/app/root/carplay-altscreen/lib/libcarplay_altscreen.so"]}\n')

    # Only the upgrade-specific tests below should use this fully installed
    # fixture; the inherited clean/foreign tests are defined in the base class.
    def test_known_project_passes_without_restore(self):
        p = self.run_gate()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("inplace_upgrade=YES", p.stdout)

    def qnx_cksum(self, fail=False):
        bindir = Path(self.tmp.name) / "qnx-bin"
        wrapper = bindir / "cksum"
        script = ("#!/bin/sh\n" + ("exit 71\n" if fail else
                  'out=$(/usr/bin/cksum "$@") || exit $?\n'
                  'set -- $out\nprintf "%s      %s STDIN\\n" "$1" "$2"\n'))
        self.put(wrapper, script)
        wrapper.chmod(0o755)
        self.env["PATH"] = str(bindir) + os.pathsep + self.env["PATH"]

    def test_qnx_padded_stdin_checksum_allows_known_project(self):
        self.qnx_cksum()
        p = self.run_gate()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("inplace_upgrade=YES", p.stdout)

    def test_qnx_checksum_command_failure_is_refused(self):
        self.qnx_cksum(fail=True)
        p = self.run_gate()
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("inplace_upgrade=YES", p.stdout)

    def test_changed_jar_is_refused(self):
        self.jar.write_bytes(self.jar.read_bytes() + b"foreign-change")
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_known_identity_with_legacy_zoom_is_refused(self):
        self.put(self.root / "mnt/app/root/hooks/libcn_carplay_zoom_v30.so", "legacy")
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_restore_pending_is_not_an_upgrade(self):
        self.put(self.card / "MMI-Cockpit-Carplay/state/RESTORE_PENDING_REBOOT", "")
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_incomplete_runtime_is_refused(self):
        self.put(self.root / "mnt/app/root/carplay-altscreen/state/transaction.pending", "")
        self.assertNotEqual(self.run_gate().returncode, 0)


if __name__ == "__main__":
    unittest.main()
