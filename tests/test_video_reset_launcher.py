"""Actual launcher must not start a new logo before the prior Sport offset is reset."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'altscreen/Toolbox/carplay_alt_screen/mirror_display/release'


class VideoResetLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='video-reset-')
        self.base = Path(self.temp.name)
        for name in ('start_vehicle.sh', 'select_logo.sh'):
            shutil.copyfile(RELEASE / name, self.base / name)
        self.fake = self.base / 'mirror'
        self.fake.write_text('''#!/bin/sh
          trap 'exit 0' TERM INT
          echo started >> "$RESET_TEST_STARTED"
          : > "$ALT111_MIRROR_BASE_READY_FILE"
          while :; do sleep 1; done
        ''')
        self.fake.chmod(0o755)
        self.started = self.base / 'started'
        self.ready = self.base / 'ready'
        self.request = self.base / 'carplay-video-reset.request'
        self.ack = self.base / 'carplay-video-reset.ack'
        self.env = dict(os.environ, ALT111_MIRROR_BIN=str(self.fake),
                        ALT111_MIRROR_TMP_ROOT=str(self.base),
                        ALT111_JAVA_BASE_READY_FILE=str(self.ready),
                        ALT111_MIRROR_ACTIVE_FILE=str(self.base / 'demand'),
                        RESET_TEST_STARTED=str(self.started))
        self.child = None

    def tearDown(self):
        if self.child:
            try: os.killpg(self.child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            self.child.wait()
        self.temp.cleanup()

    def launch(self):
        with (self.base / 'launch.log').open('w') as stream:
            self.child = subprocess.Popen(['/bin/sh', str(self.base/'start_vehicle.sh')],
                env=self.env, stdout=stream, stderr=stream, start_new_session=True)

    def wait_for(self, test, timeout=5):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if test(): return
            time.sleep(.02)
        self.fail((self.base/'launch.log').read_text())

    def test_cold_start_does_not_wait_for_java(self):
        self.launch()
        self.wait_for(self.started.exists)
        self.assertEqual(self.child.wait(timeout=5),0)
        self.assertFalse(self.request.exists())

    def test_used_offset_waits_for_matching_reset_ack(self):
        (self.base/'carplay-video-position.used').touch()
        self.ready.write_text('ready=1\nmode=direct-display\npid=old\n')
        self.ack.write_text('previous-launcher\n')
        self.launch()
        self.wait_for(self.request.exists)
        self.assertFalse(self.ready.exists(), 'old video phase must be cleared before reset')
        self.assertFalse(self.started.exists(), 'logo waits for reset')
        self.ack.write_text('wrong-launcher\n')
        time.sleep(1.2)
        self.assertFalse(self.started.exists(), 'unrelated ack must not start logo')
        self.ack.write_bytes(self.request.read_bytes())
        self.wait_for(self.started.exists)
        self.assertEqual(self.child.wait(timeout=5),0)
        self.assertIn('VIDEO_POSITION_RESET=PASS', (self.base/'launch.log').read_text())

    def test_missing_ack_times_out_without_starting_logo(self):
        (self.base/'carplay-video-position.used').touch()
        # Accelerate the actual 60-iteration gate; only this isolated fixture replaces sleep.
        bins=self.base/'bin';bins.mkdir()
        sleep=bins/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o755)
        self.env['PATH']=str(bins)+':'+self.env['PATH']
        self.launch()
        self.assertEqual(self.child.wait(timeout=5),3)
        self.assertFalse(self.started.exists())
        self.assertIn('logo_not_started', (self.base/'launch.log').read_text())

    def test_explicit_stop_while_waiting_never_starts_logo(self):
        (self.base/'carplay-video-position.used').touch()
        self.launch();self.wait_for(self.request.exists)
        (self.base/'MMI-Cockpit-Carplay.mirror.stop.requested').touch()
        self.assertEqual(self.child.wait(timeout=5),3)
        self.assertFalse(self.started.exists())


if __name__ == '__main__': unittest.main()
