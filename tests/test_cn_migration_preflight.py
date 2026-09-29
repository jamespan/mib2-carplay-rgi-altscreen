"""Exercise the read-only migration gate with real shell processes."""
import os
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
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

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


if __name__ == "__main__":
    unittest.main()
