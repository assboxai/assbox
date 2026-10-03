# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the delivered Wayland owner/ready scripts with explicit fake effect tools.

This does not run greetd, labwc, a real user manager, or a graphical application.
"""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
ROOT = Path(__file__).resolve().parents[2]


class WaylandSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='assbox-wayland-')
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name); self.log = self.dir/'log'
        tool = self.dir/'systemctl'
        tool.write_text(f'#!{sys.executable} -S\n' + '''import os, sys
line='systemctl '+ ' '.join(sys.argv[1:])
with open(os.environ['TEST_LOG'],'a') as file: file.write(line+'\\n')
if os.environ.get('FAIL') and os.environ['FAIL'] in line: sys.exit(7)
'''); tool.chmod(0o755)
        self.ready = self.dir/'ready'
        self.ready.write_text((ROOT/'modules/sessions/wayland-ready.sh').read_text().replace('@systemctl@',str(tool)))
        compositor = self.dir/'labwc'
        compositor.write_text(f'#!{sys.executable} -S\n' + '''import os, sys, subprocess, time
with open(os.environ['TEST_LOG'],'a') as file:
    file.write('labwc started\\n')
    file.write('inherited-display='+os.environ.get('WAYLAND_DISPLAY','')+'\\n')
if not os.environ.get('MISSING_DISPLAY'): os.environ['WAYLAND_DISPLAY']='wayland-test'
subprocess.run(['bash',os.environ['READY']],check=False)
if os.environ.get('BLOCK'): time.sleep(60)
sys.exit(int(os.environ.get('WM_STATUS','0')))
'''); compositor.chmod(0o755)
        self.script = self.dir/'session'
        self.script.write_text((ROOT/'modules/sessions/wayland.sh').read_text().replace('@systemctl@',str(tool)).replace('@labwc@',str(compositor)))
        self.env = dict(os.environ, TEST_LOG=str(self.log), READY=str(self.ready), WAYLAND_DISPLAY='stale-display', DISPLAY=':old')

    def run_session(self, **kwargs):
        result = subprocess.run(['bash',str(self.script)],env=dict(self.env,**kwargs),capture_output=True,text=True,timeout=8,check=False)
        return result, self.log.read_text().splitlines()

    def test_repeated_sessions_clear_stale_state_and_have_balanced_lifetimes(self):
        for _ in range(2):
            self.log.unlink(missing_ok=True)
            result,events=self.run_session()
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('stop assbox-graphical-session.target graphical-session.target',events[0])
            self.assertIn('inherited-display=',events)
            start=events.index('systemctl --user start assbox-graphical-session.target')
            self.assertGreater(start,events.index('labwc started'))
            self.assertIn('stop assbox-graphical-session.target graphical-session.target',events[-2])
            self.assertIn('unset-environment',events[-1])

    def test_compositor_failure_is_not_reported_as_success(self):
        result,events=self.run_session(WM_STATUS='9')
        self.assertEqual(result.returncode,9,result.stderr)
        self.assertIn('unset-environment',events[-1])

    def test_ready_import_and_partial_start_failures_terminate_session(self):
        for failure in ['import-environment','start assbox-graphical-session.target']:
            self.log.unlink(missing_ok=True)
            result,events=self.run_session(FAIL=failure,BLOCK='1')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('stop assbox-graphical-session.target graphical-session.target',events[-2])
            self.assertIn('unset-environment',events[-1])

    def test_missing_display_cannot_leave_a_stale_application_target(self):
        result,events=self.run_session(MISSING_DISPLAY='1',BLOCK='1')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('systemctl --user start assbox-graphical-session.target',events)
        self.assertIn('unset-environment',events[-1])

    def test_termination_cleans_up_lingering_user_manager_state(self):
        process=subprocess.Popen(['bash',str(self.script)],env=dict(self.env,BLOCK='1'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+5
            while not self.log.exists() or 'start assbox-graphical-session.target' not in self.log.read_text():
                self.assertLess(time.monotonic(),deadline); time.sleep(0.02)
            process.send_signal(signal.SIGTERM)
            _,stderr=process.communicate(timeout=5)
            self.assertEqual(process.returncode,143,stderr)
            self.assertIn('unset-environment',self.log.read_text().splitlines()[-1])
        finally:
            if process.poll() is None: process.kill(); process.communicate()

    def test_greetd_recurs_as_agent_instead_of_locked_password_greeter(self):
        source=(ROOT/'modules/presentation.nix').read_text()
        self.assertIn('default_session = { command = session; user = "agent"; };', ' '.join(source.split()))
        self.assertNotIn('initial_session',source)
        self.assertNotIn('agreety',source)

    def test_console_only_and_unfree_labels_match_actual_policy(self):
        base=(ROOT/'modules/access.nix').read_text()
        self.assertIn('enable = enabled;',base)
        self.assertIn('allowedTCPPorts = lib.optional enabled 22',base)
        self.assertIn('enable = cfg.network.discoverable;', (ROOT/'modules/base.nix').read_text())
        options=(ROOT/'modules/options.nix').read_text()
        self.assertIn('machine-wide',options.lower())

if __name__=='__main__': unittest.main()
