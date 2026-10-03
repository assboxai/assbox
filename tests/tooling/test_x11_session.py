# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute the shipped session script with explicit fake effect adapters.

This tests shell lifecycle/order/exit handling, not Xorg, Openbox, LightDM or
systemd behavior. Real graphical session acceptance remains a separate VM test.
"""
from __future__ import annotations
import os
import signal
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="assbox-x11-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.log = self.directory / "events"
        template = (ROOT / "modules/sessions/x11.sh").read_text()
        for name in ["systemctl", "xset", "openbox"]:
            tool = self.directory / name
            tool.write_text(f"#!{sys.executable} -S\n" +
                "import os, sys, time\n" +
                "from pathlib import Path\n" +
                f"name = {name!r}\n" +
                "event = name + ' ' + ' '.join(sys.argv[1:])\n" +
                "with open(os.environ['TEST_LOG'], 'a') as f: f.write(event + '\\n')\n" +
                "if os.environ.get('TEST_FAIL') and os.environ['TEST_FAIL'] in event: sys.exit(7)\n" +
                "if name == 'openbox':\n" +
                "    if os.environ.get('TEST_BLOCK'): time.sleep(60)\n" +
                "    sys.exit(int(os.environ.get('TEST_WM_STATUS', '0')))\n")
            tool.chmod(0o755)
            template = template.replace(f"@{name}@", str(tool))
        self.script = self.directory / "session.sh"
        self.script.write_text(template)
        self.env = dict(os.environ, TEST_LOG=str(self.log), DISPLAY=":7", XAUTHORITY="/tmp/test-auth")

    def run_session(self, **settings):
        result = subprocess.run(["bash", str(self.script)], env=dict(self.env, **settings),
                                capture_output=True, text=True, timeout=10, check=False)
        return result, self.log.read_text().splitlines()

    def test_exit_stops_target_and_clears_environment(self):
        result, events = self.run_session()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events.count("systemctl --user stop assbox-graphical-session.target graphical-session.target"), 2)
        self.assertEqual(events[-2], "systemctl --user stop assbox-graphical-session.target graphical-session.target")
        self.assertIn("unset-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY", events[-1])
        imported = next(i for i, line in enumerate(events) if "import-environment" in line)
        started = events.index("systemctl --user start assbox-graphical-session.target")
        self.assertLess(imported, started)
        self.assertLess(started, events.index("openbox "))

    def test_window_manager_failure_preserves_status_and_cleans_up(self):
        result, events = self.run_session(TEST_WM_STATUS="42")
        self.assertEqual(result.returncode, 42)
        self.assertIn("stop assbox-graphical-session.target graphical-session.target", events[-2])

    def test_import_failure_never_starts_application_target(self):
        result, events = self.run_session(TEST_FAIL="import-environment")
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("systemctl --user start assbox-graphical-session.target", events)
        self.assertNotIn("openbox ", events)
        self.assertIn("stop assbox-graphical-session.target graphical-session.target", events[-2])

    def test_start_failure_still_stops_partial_target(self):
        result, events = self.run_session(TEST_FAIL="start assbox-graphical-session.target")
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("openbox ", events)
        self.assertIn("stop assbox-graphical-session.target graphical-session.target", events[-2])

    def test_optional_dpms_failure_does_not_break_session(self):
        result, events = self.run_session(TEST_FAIL="xset ")
        self.assertEqual(result.returncode, 0)
        self.assertIn("openbox ", events)

    def test_termination_stops_target_not_only_the_window_manager(self):
        process = subprocess.Popen(["bash", str(self.script)], env=dict(self.env, TEST_BLOCK="1"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not self.log.exists() or "openbox " not in self.log.read_text():
                self.assertLess(time.monotonic(), deadline, "window manager did not start")
                time.sleep(0.02)
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr)
            self.assertIn("stop assbox-graphical-session.target graphical-session.target", self.log.read_text().splitlines()[-2])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_nix_selects_wrapper_and_disables_fake_target_ownership(self):
        nix = (ROOT / "modules/presentation.nix").read_text()
        self.assertIn('defaultSession = "none+assbox-x11"', nix)
        self.assertIn("${x11Session} &", nix)
        self.assertIn("X-NIXOS-SYSTEMD-AWARE", nix)
        self.assertIn('bindsTo = [ "graphical-session.target" ]', nix)
        self.assertNotIn("--user start graphical-session.target", nix)
        self.assertNotIn("--user start graphical-session.target", self.script.read_text())
        commands = nix[nix.index("services.xserver.displayManager.sessionCommands ="):]
        commands = commands[:commands.index("environment.systemPackages")]
        self.assertNotIn("start assbox-graphical-session.target", commands)


if __name__ == "__main__":
    unittest.main()
