# SPDX-License-Identifier: GPL-3.0-or-later
"""Canary protocol fixtures on temporary files; no SSH, Desktop or provider task."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('external_coder',ROOT/'tests/fixtures/external_coder.py')
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
VERSIONS={'app':'fixture-app','agent':'fixture-cli','hypervisor':'fixture-vm','authMode':'scoped fixture'}

class ExternalCoderTests(unittest.TestCase):
    def prepare(self,home,run,role):
        with patch.object(Path,'home',return_value=home):
            return fixture.prepare(run,role,'mac-codex-ssh','deselected',VERSIONS)

    def task(self,home,run,phase):
        previous=os.umask(0o077)
        try:
            with patch.object(Path,'home',return_value=home),patch.object(sys,'argv',['task',run,phase]):
                exec(fixture.TASK,{})
        finally:os.umask(previous)

    def record(self,home,run,role,phase):
        with patch.object(Path,'home',return_value=home),patch.object(fixture,'processes',return_value=[]),\
             patch.object(fixture.platform,'system',return_value='Darwin' if role=='controller' else 'Linux'),\
             patch.object(fixture.platform,'machine',return_value='arm64' if role=='controller' else 'aarch64'):
            return fixture.record(run,phase)

    def test_full_counter_sequence_and_tampered_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            host,guest=Path(temporary)/'host',Path(temporary)/'guest'
            run=str(uuid.uuid4())
            self.prepare(host,run,'controller');self.prepare(guest,run,'guest')
            self.task(guest,run,'initial')
            for phase in fixture.PHASES:
                if phase=='reconnected':self.task(guest,run,phase)
                host_record=self.record(host,run,'controller',phase)
                guest_record=self.record(guest,run,'guest',phase)
            result=fixture.verify(host_record,guest_record)
            self.assertEqual(result['canaryDisconnectFixture'],'passed')
            self.assertEqual(result['routeQualification'],'not_established')
            remote=json.loads(fixture.read(guest_record))
            bad=copy.deepcopy(remote)
            bad['observations']['disconnected']['attempts']['disconnected']=1
            fixture.write(guest_record,bad)
            with self.assertRaisesRegex(fixture.Refusal,'fallback, replay'):
                fixture.verify(host_record,guest_record)

    def test_duplicate_guest_execution_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);run=str(uuid.uuid4());self.prepare(home,run,'guest')
            self.task(home,run,'initial');self.task(home,run,'initial')
            with self.assertRaisesRegex(fixture.Refusal,'replayed'):
                self.record(home,run,'guest','initial')

    def test_controller_fallback_attempt_is_detected_before_canary_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);run=str(uuid.uuid4());self.prepare(home,run,'controller')
            with self.assertRaises(AssertionError):self.task(home,run,'initial')
            with self.assertRaisesRegex(fixture.Refusal,'controller fixture'):
                self.record(home,run,'controller','initial')

    def test_existing_run_and_skipped_phases_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);run=str(uuid.uuid4());self.prepare(home,run,'guest')
            with self.assertRaises(FileExistsError):self.prepare(home,run,'guest')
            with self.assertRaisesRegex(fixture.Refusal,'in order'):
                self.record(home,run,'guest','reconnected')

if __name__=='__main__':unittest.main()
