# SPDX-License-Identifier: GPL-3.0-or-later
"""Executable subprocess/SSH-merge regressions and labeled source contracts."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_worker import ROOT, configuration, w


class SshScopeTests(unittest.TestCase):
    MANAGED = "Host assbox-worker\n  HostName 10.77.0.2\n  User agent\n"

    def test_existing_global_defaults_keep_global_scope(self):
        existing = "User operator\nPort 2200\nHost other\n  HostName example.org\n"
        merged = w.merge_ssh_config(existing, self.MANAGED)
        self.assertTrue(merged.endswith("Host *\n# END ASSBOX WORKER\n" + existing))
        self.assertEqual(w.merge_ssh_config(merged, self.MANAGED), merged)

    def test_existing_global_include_and_match_are_preserved(self):
        existing = "Include config.d/*\nMatch host other\n  User operator\n"
        self.assertIn("Host *\n# END ASSBOX WORKER\n" + existing,
                      w.merge_ssh_config(existing, self.MANAGED))

    def test_openssh_separator_and_quoting_forms_conflict(self):
        for existing in ("Host=assbox-worker", 'Host "assbox-worker"',
                         "HOST = assbox-worker # managed elsewhere", "Host ASSBOX-WORKER", 'Host other "assbox-worker"'):
            with self.subTest(existing=existing), self.assertRaises(w.Refusal):
                w.merge_ssh_config(existing + "\n", self.MANAGED)

    def test_quoted_comment_is_not_a_host_alias(self):
        existing = 'Host other # assbox-worker\n  User another\n'
        self.assertTrue(w.merge_ssh_config(existing, self.MANAGED).endswith(existing))

    def test_unclosed_host_quote_refuses_without_modification(self):
        with self.assertRaises(w.Refusal):
            w.merge_ssh_config('Host "assbox-worker\n', self.MANAGED)


@unittest.skipUnless(sys.platform == "linux", "Linux process-group contract")
class ProcessLifetimeTests(unittest.TestCase):
    def orphan_fixture(self, close_pipes, publish_delay=0):
        # The isolated harness adopts/reaps grandchildren instead of leaving
        # zombies with an unrelated container init. It never changes the test
        # runner's subreaper state or signal dispositions.
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'descendant'
            # The private pipe is fixture synchronization, not a longer sleep
            # masking a race. Readiness is signalled only after write_text closes
            # the PID file and the descendant sets its stdout/stderr policy.
            child = '''import os,sys,time,pathlib,select
read_fd,write_fd=os.pipe()
pid=os.fork()
if pid:
    os.close(write_fd)
    try:
        ready,_,_=select.select([read_fd],[],[],3)
        if not ready or os.read(read_fd,1)!=b'R':
            os._exit(70)
    finally:
        os.close(read_fd)
    os._exit(0)
os.close(read_fd)
time.sleep(float(sys.argv[3]))
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
if sys.argv[2] == 'close':
    os.close(1);os.close(2)
os.write(write_fd,b'R')
os.close(write_fd)
time.sleep(60)
'''
            harness = '''import ctypes,os,pathlib,signal,sys,time
sys.path.insert(0,sys.argv[1])
import worker
libc=ctypes.CDLL(None,use_errno=True)
assert libc.prctl(36,1,0,0,0)==0  # PR_SET_CHILD_SUBREAPER, isolated process only
pidfile=pathlib.Path(sys.argv[2])
reaped=False
try:
    try:
        result=worker.bounded_capture([sys.executable,'-c',sys.argv[3],str(pidfile),sys.argv[4],sys.argv[5]],timeout=4)
        assert sys.argv[4]=='close' and result==''
    except worker.Refusal as error:
        assert sys.argv[4]=='inherit', str(error)
        assert str(error)=='Remote health response timed out', str(error)
    assert pidfile.exists(), 'fixture failed to publish descendant identity before capture completed'
    pid=int(pidfile.read_text())
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        observed,status=os.waitpid(pid,os.WNOHANG)
        if observed:
            reaped=True
            assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
            print('descendant-killed-and-reaped')
            break
        time.sleep(.01)
    else:
        raise AssertionError('descendant still alive after health completion')
finally:
    if not reaped and pidfile.exists():
        pid=int(pidfile.read_text())
        try: os.kill(pid,signal.SIGKILL)
        except ProcessLookupError: pass
        try: os.waitpid(pid,0)
        except ChildProcessError: pass
'''
            result = subprocess.run(
                [sys.executable, '-c', harness, str(ROOT/'scripts/worker'),
                 str(pidfile), child, 'close' if close_pipes else 'inherit', str(publish_delay)],
                capture_output=True, text=True, timeout=12,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'descendant-killed-and-reaped')

    def test_exited_leader_with_inherited_pipes_does_not_leave_live_child(self):
        self.orphan_fixture(False)

    def test_successful_leader_with_closed_pipes_still_cleans_up_child(self):
        self.orphan_fixture(True)

    def test_delayed_descendant_with_inherited_pipes_is_ready_before_leader_exit(self):
        self.orphan_fixture(False, publish_delay=0.15)

    def test_delayed_descendant_with_closed_pipes_is_ready_before_leader_exit(self):
        self.orphan_fixture(True, publish_delay=0.15)

    def test_closed_pipes_do_not_remove_process_exit_deadline(self):
        with self.assertRaises(w.Refusal):
            w.bounded_capture([sys.executable, '-c',
                               'import os,time;os.close(1);os.close(2);time.sleep(30)'], timeout=1)

    def test_failed_spawn_restores_signal_handler(self):
        handler = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(FileNotFoundError):
            w.bounded_capture(['/definitely-not-an-assbox-executable'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), handler)

    def test_cancellation_during_spawn_does_not_lose_the_child_handle(self):
        real_popen = w.subprocess.Popen
        started = []
        handler = signal.getsignal(signal.SIGTERM)
        def cancel_before_returning_handle(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            started.append(child)
            os.kill(os.getpid(), signal.SIGTERM)
            return child
        try:
            with patch.object(w.subprocess, 'Popen', side_effect=cancel_before_returning_handle):
                with self.assertRaises(SystemExit) as failure:
                    w.bounded_capture([sys.executable, '-c', 'import time;time.sleep(30)'])
            self.assertEqual(failure.exception.code, 143)
            self.assertEqual(signal.getsignal(signal.SIGTERM), handler)
            with self.assertRaises(ProcessLookupError):
                os.kill(started[0].pid, 0)
        finally:
            for child in started:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()

    def test_positive_bounds_are_required_before_launch(self):
        with patch.object(w.subprocess, 'Popen') as launch:
            for kwargs in ({'timeout': 0}, {'limit': 0}, {'timeout': -1}, {'limit': -1}):
                with self.subTest(kwargs=kwargs), self.assertRaises(w.Refusal):
                    w.bounded_capture([sys.executable, '-c', 'pass'], **kwargs)
            launch.assert_not_called()

    def test_malformed_utf8_is_not_a_health_response(self):
        with self.assertRaises(UnicodeError):
            w.bounded_capture([sys.executable, '-c', 'import os;os.write(1,b"\\xff")'])

    def test_health_retries_encoding_failure_as_unready(self):
        c = configuration()
        good = 'ASSBOX-WORKER-HEALTH/1\n' + c['buildId'] + '\n'
        with patch.object(w, 'require_user'), patch.object(w, 'artifact_manifest'), \
                patch.object(w.time, 'sleep'), patch.object(w, 'bounded_capture',
                side_effect=[UnicodeDecodeError('utf8', b'\xff', 0, 1, 'invalid'), good]) as capture:
            with patch.object(w.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=200, pw_gid=200)):
                w.check(c)
            self.assertEqual(capture.call_count, 2)


class NativeWiringSourceContracts(unittest.TestCase):
    """Checks source presence/order only; native gates exercise the actual tools."""
    def test_retry_uses_authoritative_engine_and_has_no_guest_start_dependency(self):
        s = (ROOT/'modules/worker/boot-retry.nix').read_text()
        self.assertIn('internal boot-check --retry', s)
        self.assertIn('OnUnitInactiveSec = "5min"', s)
        self.assertNotIn('requires =', s)
        engine = (ROOT/'crates/imperative-shell/assbox-engine/src/manage.rs').read_text()
        body = engine.split('fn boot_check_with_retry(', 1)[1].split('pub fn components_set(', 1)[0]
        self.assertLess(body.index('state_entry_exists(TXN)'), body.index('receipt.matches('))
        self.assertLess(body.index('current != probe::profile_system()'), body.index('receipt.matches('))
        self.assertIn('retry_only && pending.is_none()', body)
        self.assertLess(body.index('require_worker_health('), body.index('BootAcceptance::new('))
        self.assertLess(body.index('cleanup_locked()?'), body.index('BootAcceptance::new('))

    def test_public_stop_pauses_retries_without_terminating_the_engine(self):
        with patch.object(w.sys, 'argv', ['worker.py', 'stop']), \
                patch.object(w, 'load_config', return_value=configuration()), \
                patch.object(w, 'require_user'), patch.object(w, 'run') as run:
            self.assertEqual(w.main(), 0)
        argv = run.call_args.args[0]
        self.assertIn('assbox-worker-boot-retry.timer', argv)
        self.assertIn('assbox-worker.service', argv)
        self.assertNotIn('assbox-worker-boot-retry.service', argv)

    def test_guest_policy_assertions_are_part_of_native_evaluation_gate(self):
        s = (ROOT/'tests/nix/worker-policy.nix').read_text()
        for text in ('guestPolicy.assertions', 'guestPolicy.allowNoPasswordLogin',
                     'guestPolicy.passwordAuthentication', 'guestPolicy.healthShell', 'auditClosure.drvPath'):
            self.assertIn(text, s)

    def test_host_transport_disables_proxy_and_local_commands(self):
        source = (ROOT/'modules/worker/default.nix').read_text()
        self.assertEqual(source.count('ProxyCommand none'), 2)
        self.assertEqual(source.count('ProxyJump none'), 2)
        self.assertEqual(source.count('RemoteCommand none'), 2)
        self.assertEqual(source.count('PermitLocalCommand no'), 2)


class EffectiveAliasPolicy(unittest.TestCase):
    def test_repeated_directives_are_preserved(self):
        fields = w.parse_ssh_settings('identityfile /one\nidentityfile /two\nlocalforward 123 localhost:1\n')
        self.assertEqual(fields['identityfile'], ['/one', '/two'])
        with self.assertRaises(w.Refusal):
            w.validate_ssh_settings(configuration(), fields)

    def test_root_doctor_evaluates_user_configuration_as_controller(self):
        c = configuration()
        with patch.object(w.os, 'geteuid', return_value=0), \
             patch.object(w.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_gid=100)), \
             patch.object(w, 'bounded_capture', return_value='hostname 10.77.0.2\n') as capture, \
             patch.object(w, 'validate_ssh_settings'):
            w.verify_ssh_config(c)
        self.assertEqual(capture.call_args.kwargs['credentials'], (1000, 100))
        self.assertEqual(capture.call_args.args[0], [c['tools']['ssh'], '-G', 'assbox-worker'])

    def test_failed_alias_preflight_preserves_user_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / '.ssh'
            directory.mkdir(mode=0o700)
            config = directory / 'config'
            original = 'IdentityFile /some/other/key\n'
            config.write_text(original)
            managed = home / 'managed'
            managed.write_text(SshScopeTests.MANAGED)
            c = configuration()
            c['sshConfig'] = str(managed)
            with patch.object(w, 'require_user'), \
                 patch.object(w.pwd, 'getpwnam', return_value=SimpleNamespace(pw_dir=str(home))), \
                 patch.object(w, 'verify_ssh_config', side_effect=w.Refusal('extra identity')):
                with self.assertRaises(w.Refusal):
                    w.setup_ssh(c)
            self.assertEqual(config.read_text(), original)
            self.assertEqual(list(directory.iterdir()), [config])
