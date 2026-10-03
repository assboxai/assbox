# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import clear_unused_runner_tools as clearance
import workflow_policy


class RunnerClearanceTests(unittest.TestCase):
    def test_reviewed_paths_are_fixed_sdk_directories(self):
        self.assertEqual(tuple(str(path) for path in clearance.PATHS), (
            '/usr/local/lib/android', '/usr/share/dotnet',
            '/opt/hostedtoolcache', '/usr/local/.ghcup'))

    def test_local_and_self_hosted_contexts_refuse_before_deletion(self):
        contexts = [{}, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted',
                         'GITHUB_EVENT_NAME': 'workflow_dispatch'}]
        for environment in contexts:
            with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(os, 'geteuid', return_value=0), \
                    mock.patch.object(clearance, 'clear_directories') as remove:
                with self.assertRaises(ValueError):
                    clearance.main()
                remove.assert_not_called()

    def test_hosted_context_requires_numeric_run_and_exact_source(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(os, 'geteuid', return_value=0):
            environment = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                               GITHUB_REPOSITORY='example/repository', GITHUB_REPOSITORY_ID='123',
                               GITHUB_REPOSITORY_OWNER_ID='456', GITHUB_EVENT_NAME='workflow_dispatch',
                               GITHUB_SHA='a' * 40, GITHUB_RUN_ID='1', GITHUB_RUN_ATTEMPT='1', RUNNER_TEMP=temporary)
            self.assertEqual(clearance.validate_environment(environment), (Path(temporary), os.getuid()))
            for name, value in [('GITHUB_SHA', 'unreviewed'), ('GITHUB_RUN_ID', '0'),
                                ('GITHUB_REPOSITORY_OWNER_ID', '-1'), ('RUNNER_TEMP', '.')]:
                changed = dict(environment, **{name: value})
                with self.subTest(name=name), self.assertRaises(ValueError):
                    clearance.validate_environment(changed)

    def test_redirected_directory_refuses_entire_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, external, redirect = root / 'first', root / 'external', root / 'redirect'
            first.mkdir(); external.mkdir()
            (external / 'keep').write_text('preserved')
            redirect.symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                clearance.clear_directories((first, redirect), os.getuid(), root.stat().st_dev, [])
            self.assertTrue(first.is_dir())
            self.assertEqual((external / 'keep').read_text(), 'preserved')

    def test_nested_mount_refuses_before_removing_other_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / 'first', root / 'second'
            first.mkdir(); second.mkdir()
            with self.assertRaises(ValueError):
                clearance.clear_directories((first, second), os.getuid(), root.stat().st_dev, [second / 'mounted'])
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())

    def test_wrong_volume_and_regular_file_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, regular = root / 'directory', root / 'regular'
            directory.mkdir(); regular.write_text('preserved')
            for paths, device in [((directory,), root.stat().st_dev + 1),
                                  ((directory, regular), root.stat().st_dev)]:
                with self.assertRaises(ValueError):
                    clearance.clear_directories(paths, os.getuid(), device, [])
                self.assertTrue(directory.is_dir())
                self.assertEqual(regular.read_text(), 'preserved')

    def test_clearance_does_not_follow_child_symlink_or_remove_unselected_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected, external = root / 'selected', root / 'external'
            selected.mkdir(); external.mkdir()
            (selected / 'unused').write_text('unused')
            (external / 'keep').write_text('preserved')
            (selected / 'redirect').symlink_to(external, target_is_directory=True)
            self.assertEqual(clearance.clear_directories((selected, root / 'absent'), os.getuid(), root.stat().st_dev, []), [str(selected)])
            self.assertFalse(selected.exists())
            self.assertEqual((external / 'keep').read_text(), 'preserved')

    def test_workflows_refuse_missing_conditional_redirected_or_reordered_clearance(self):
        root = Path(__file__).resolve().parents[2]
        for path in (root / '.github/workflows').glob('*.yml'):
            original = workflow_policy.yaml.load(path.read_text(), Loader=workflow_policy.WorkflowLoader)
            self.assertEqual(workflow_policy.check_document(path.name, original), [])
            for name, job in original['jobs'].items():
                for index, step in enumerate(job['steps']):
                    if step.get('uses') != workflow_policy.NIX:
                        continue
                    for mutation in ('missing', 'conditional', 'redirected', 'reordered', 'duplicate'):
                        with self.subTest(workflow=path.name, job=name, mutation=mutation):
                            document = copy.deepcopy(original)
                            steps = document['jobs'][name]['steps']
                            selected = steps[index - 1]
                            if mutation == 'missing':
                                steps.pop(index - 1)
                            elif mutation == 'conditional':
                                selected['if'] = 'false'
                            elif mutation == 'redirected':
                                selected['run'] += '\nsudo rm -rf /home/runner'
                            elif mutation == 'reordered':
                                steps[index - 1], steps[index] = steps[index], selected
                            else:
                                steps.insert(index - 1, copy.deepcopy(selected))
                            self.assertTrue(workflow_policy.check_document(path.name, document))


if __name__ == '__main__':
    unittest.main()
