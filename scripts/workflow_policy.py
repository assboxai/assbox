#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed workflow authority lint; not a proof of transitive script effects.

Actions-write credentials can also rerun workflows, regardless of original trigger.
Keep every workflow explicitly read-only and secret-free, except the designated
release publisher/advertiser jobs. Extending an allowlist requires source review.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
import yaml


class WorkflowLoader(yaml.SafeLoader):
    """GitHub's `on` is a key, not YAML 1.1 True; reject duplicate mapping keys."""


WorkflowLoader.yaml_implicit_resolvers = {
    char: [(tag, regex) for tag, regex in rules if tag != "tag:yaml.org,2002:bool"]
    for char, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.I), list("tTfF"))


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("workflow mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


WorkflowLoader.add_constructor("tag:yaml.org,2002:map", mapping)

CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
NIX = "cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWNLOAD = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
ATTEST = "actions/attest-build-provenance@a2bbfa25375fe432b6a289bc6b6cd05ecd0c4c32"
READ = {"contents": "read"}
RUNNERS = {"ubuntu-24.04", "ubuntu-24.04-arm"}
# This is an effect-entrypoint allowlist, not a blacklist of dangerous shell words.
READ_COMMANDS = {
    'test -f flake.lock && git ls-files --error-unmatch flake.lock',
    'nix develop --command scripts/verify',
    '''set -euo pipefail
nix flake lock
git add flake.lock
nix develop --command scripts/format
mkdir -p "$RUNNER_TEMP/assbox-bootstrap"
git diff HEAD --binary > "$RUNNER_TEMP/assbox-bootstrap/bootstrap.patch"
cp flake.lock "$RUNNER_TEMP/assbox-bootstrap/flake.lock"
nix develop --command rustc --version > "$RUNNER_TEMP/assbox-bootstrap/rustc-version.txt"
nix --version > "$RUNNER_TEMP/assbox-bootstrap/nix-version.txt"''',
}
ATTEST_READY = 'python3 scripts/release.py attest-ready "$RUNNER_TEMP/assbox-release/assets" "$RUNNER_TEMP/assbox-release/reports"'
PUBLISH = 'python3 scripts/release.py publish "$RUNNER_TEMP/assbox-release/assets" "$RUNNER_TEMP/assbox-release/reports"'
PROMOTE = 'python3 scripts/release.py promote "$RELEASE_TAG" "$RELEASE_ID"'
ATTACH = 'cp -- "$BUNDLE" "$RUNNER_TEMP/assbox-release/assets/release.sigstore.json"'
LIVE_VERIFY = 'python3 scripts/release.py live-verify "$RELEASE_TAG" "$SYSTEM" "/var/lib/assbox-public-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT-$SYSTEM"'
DISCOVER = 'python3 scripts/release.py discover "$RUNNER_TEMP/assbox-discovery.json"'


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


# The GitHub context contains credentials. Permit reviewed scalar reads, never
# whole-object serialization, wildcards or dynamic indexing. This is a deliberately
# restricted expression policy, not a general GitHub Actions expression parser.
GITHUB_SCALARS = {"repository", "ref", "sha", "workflow", "event_name", "run_id", "run_attempt"}
GITHUB_WORD = re.compile(r"\bgithub\b", re.I)
GITHUB_ACCESS = re.compile(r"github\s*(?:\.\s*([a-z_][a-z_0-9]*)|\[\s*['\"]([a-z_][a-z_0-9]*)['\"]\s*\])", re.I)
TOKEN_ACCESS = re.compile(r"github\s*(?:\.\s*token\b|\[\s*['\"]token['\"]\s*\])", re.I)
TOKEN_COMMAND_ENVS = {
    ("prepare", DISCOVER): {"GH_TOKEN": "${{ github.token }}"},
    ("publish", ATTEST_READY): {"GH_TOKEN": "${{ github.token }}"},
    ("publish", PUBLISH): {"GH_TOKEN": "${{ github.token }}"},
    ("advertise", PROMOTE): {
        "GH_TOKEN": "${{ github.token }}",
        "RELEASE_TAG": "${{ needs.publish.outputs.tag }}",
        "RELEASE_ID": "${{ needs.publish.outputs.release_id }}",
    },
}


def text_locations(value, path=()):
    """Visit mapping keys too; no workflow or job subtree is exempt from scanning."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield path + (key, "<mapping-key>"), key
            yield from text_locations(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from text_locations(child, path + (index,))


def credential_context(path, text):
    if TOKEN_ACCESS.search(text):
        return True
    # Scan the entire expression-bearing scalar, not a regex-extracted body:
    # quoted braces in format('}}{0}', toJSON(github)) must not truncate the scan.
    # This intentionally also rejects unreviewed context spellings in literals.
    if "${{" in text or (path and path[-1] == "if"):
        for word in GITHUB_WORD.finditer(text):
            access = GITHUB_ACCESS.match(text, word.start())
            if access is None or (access.group(1) or access.group(2)).lower() not in GITHUB_SCALARS:
                return True
    return False


def approved_token_binding(name, document, path, text):
    """Only one exact scalar env value in each reviewed command is an exception."""
    if (name != "release.yml" or len(path) != 6 or path[0] != "jobs"
            or path[2] != "steps" or path[4:] != ("env", "GH_TOKEN")
            or type(path[3]) is not int or text != "${{ github.token }}"):
        return False
    jobs = document.get("jobs")
    job = jobs.get(path[1]) if isinstance(jobs, dict) else None
    steps = job.get("steps") if isinstance(job, dict) else None
    if not isinstance(steps, list) or not 0 <= path[3] < len(steps):
        return False
    step = steps[path[3]]
    if not isinstance(step, dict) or set(step) - {"name", "id", "run", "env"}:
        return False
    command = step.get("run")
    expected = TOKEN_COMMAND_ENVS.get((path[1], command.strip())) if isinstance(command, str) else None
    return expected is not None and step.get("env") == expected


def readonly_action(step):
    action, options = step.get("uses"), step.get("with", {})
    if not isinstance(options, dict):
        return False
    if action == CHECKOUT:
        return options == {"persist-credentials": False}
    if action == NIX:
        return (set(options) == {"install_url", "enable_kvm", "extra_nix_config"}
                and options["install_url"] == "https://releases.nixos.org/nix/nix-2.35.2/install"
                and options["enable_kvm"] in (True, "${{ matrix.system == 'x86_64-linux' }}")
                and options["extra_nix_config"].splitlines() == [
                    "experimental-features = nix-command flakes", "accept-flake-config = false",
                    "max-jobs = 2", "cores = 2"])
    if action == UPLOAD:
        return options == {"name": "assbox-bootstrap-review", "path": "${{ runner.temp }}/assbox-bootstrap",
                           "if-no-files-found": "error"}
    return False


def check_document(name, document):
    errors = []
    def refuse(message): errors.append(f"{name}: {message}")
    if not isinstance(document, dict) or not isinstance(document.get("on"), dict) or not document["on"]:
        return [f"{name}: workflow must have an explicit nonempty event mapping"]
    # Authority does not depend on the event: even a push-only workflow may be
    # rerun through the scheduler credential's repository-wide Actions permission.
    release = name == "release.yml"
    if "workflow_dispatch" in document["on"] and document["on"]["workflow_dispatch"] not in (None, {}):
        refuse("dispatch control inputs are not supported")
    called = document["on"].get("workflow_call")
    if isinstance(called, dict) and "secrets" in called:
        refuse("reusable workflow secret declarations are not permitted")
    if set(document) - {"name", "on", "permissions", "concurrency", "jobs"}:
        refuse("unreviewed workflow-wide configuration/credentials")
    if document.get("permissions") != READ:
        refuse("explicit contents-read default required")
    for path, text in text_locations(document):
        if credential_context(path, text) and not approved_token_binding(name, document, path, text):
            refuse("credential-bearing GitHub context outside an exact approved command environment")
        if ("${{" in text or (path and path[-1] == "if")) and re.search(r"\bsecrets\b", text, re.I):
            refuse("secret context is not allowed in workflows")
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return errors + [f"{name}: jobs required"]
    if release and document["on"] != {"workflow_dispatch": None}:
        refuse("release trigger must remain inputless workflow_dispatch only")
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            refuse(f"invalid job {job_name}"); continue
        privileged = release and job_name in {"publish", "advertise"}
        permissions = job.get("permissions", document.get("permissions"))
        expected = ({"contents": "write", "id-token": "write", "attestations": "write"}
                    if privileged and job_name == "publish" else {"contents": "write"} if privileged else READ)
        if permissions != expected:
            refuse(f"unreviewed authority in {job_name}")
        allowed = {"runs-on", "timeout-minutes", "strategy", "steps", "permissions", "needs", "if", "outputs"}
        if privileged:
            allowed.add("environment")
            if job.get("environment") != "release-automation":
                refuse(f"{job_name} requires the protected release environment")
        if set(job) - allowed:
            refuse(f"unreviewed job environment, secrets, reusable call or execution context in {job_name}")
        runner = job.get("runs-on")
        if runner == "${{ matrix.runner }}":
            includes = job.get("strategy", {}).get("matrix", {}).get("include", [])
            if not includes or any(not isinstance(i, dict) or i.get("runner") not in RUNNERS for i in includes):
                refuse(f"{job_name} must resolve only reviewed hosted runners")
        elif not isinstance(runner, str) or runner not in RUNNERS:
            refuse(f"{job_name} must use a reviewed hosted runner")
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            refuse(f"steps required in {job_name}"); continue
        for step in steps:
            if not isinstance(step, dict):
                refuse(f"invalid step in {job_name}"); continue
            if not release:
                if set(step) - {"name", "uses", "with", "run"}:
                    refuse(f"unreviewed step credentials/condition/context in {job_name}")
                if "uses" in step:
                    if "run" in step or not readonly_action(step):
                        refuse(f"unreviewed action/options in {job_name}")
                elif "with" in step or step.get("run", "").strip() not in READ_COMMANDS:
                    refuse(f"unreviewed command effect in {job_name}")
            else:
                env = step.get("env", {})
                if not isinstance(env, dict):
                    refuse(f"invalid environment in {job_name}"); continue
                text = " ".join(strings({k: v for k, v in step.items() if k != "env"}))
                if re.search(r"github\s*(?:\.\s*token|\[\s*['\"]token['\"]\s*\])", text, re.I):
                    refuse(f"credential reference outside approved environment in {job_name}")
                for key, value in env.items():
                    if key in {"GH_TOKEN", "GITHUB_TOKEN"} or re.search(r"github\s*(?:\.\s*token|\[\s*['\"]token['\"]\s*\])", str(value), re.I):
                        command = step.get("run", "").strip()
                        approved = {("prepare", DISCOVER), ("publish", ATTEST_READY), ("publish", PUBLISH), ("advertise", PROMOTE)}
                        if key != "GH_TOKEN" or value != "${{ github.token }}" or (job_name, command) not in approved:
                            refuse(f"credential crosses its approved process boundary in {job_name}")
                if privileged:
                    if set(step) - {"name", "id", "uses", "with", "run", "env"}:
                        refuse(f"unreviewed privileged step configuration in {job_name}")
                    if "uses" in step:
                        allowed_actions = {CHECKOUT, DOWNLOAD, ATTEST} if job_name == "publish" else {CHECKOUT}
                        options = step.get("with", {})
                        approved_options = {
                            CHECKOUT: [{"ref": "${{ github.sha }}", "persist-credentials": False}],
                            DOWNLOAD: [
                                {"name": "release-assets", "path": "${{ runner.temp }}/assbox-release/assets"},
                                {"pattern": "native-*", "path": "${{ runner.temp }}/assbox-release/reports"},
                            ],
                            ATTEST: [{"subject-path": "${{ runner.temp }}/assbox-release/assets/release.json"}],
                        }
                        if (step["uses"] not in allowed_actions or "run" in step or "env" in step
                                or options not in approved_options.get(step["uses"], [])):
                            refuse(f"unreviewed privileged action/options in {job_name}")
                        if step["uses"] == ATTEST and step.get("id") != "attest":
                            refuse("attestation output identity changed")
                    elif step.get("run", "").strip() not in ({ATTEST_READY, PUBLISH, ATTACH} if job_name == "publish" else {PROMOTE}):
                        refuse(f"unreviewed privileged command in {job_name}")
                    else:
                        command = step["run"].strip()
                        expected_env = {
                            ATTEST_READY: {"GH_TOKEN": "${{ github.token }}"},
                            PUBLISH: {"GH_TOKEN": "${{ github.token }}"},
                            ATTACH: {"BUNDLE": "${{ steps.attest.outputs.bundle-path }}"},
                            PROMOTE: {"GH_TOKEN": "${{ github.token }}", "RELEASE_TAG": "${{ needs.publish.outputs.tag }}",
                                      "RELEASE_ID": "${{ needs.publish.outputs.release_id }}"},
                        }
                        if env != expected_env[command] or "with" in step:
                            refuse(f"unreviewed privileged command environment in {job_name}")
        if release and job_name == "publish":
            attest = [i for i, step in enumerate(steps) if step.get("uses") == ATTEST]
            if (len(attest) != 1 or attest[0] == 0 or steps[attest[0] - 1].get("run", "").strip() != ATTEST_READY
                    or steps[attest[0] - 1].get("env") != {"GH_TOKEN": "${{ github.token }}"}):
                refuse("attestation must immediately follow evidence/current-master revalidation")
    if release:
        if not {"publish", "advertise", "live-verify"} <= jobs.keys():
            refuse("release publication/verification jobs are required")
        else:
            live = jobs["live-verify"]
            expected_matrix = [
                {"system": "x86_64-linux", "runner": "ubuntu-24.04"},
                {"system": "aarch64-linux", "runner": "ubuntu-24.04-arm"},
            ]
            run_steps = [s for s in live.get("steps", []) if "run" in s]
            if (live.get("needs") != "publish" or live.get("strategy") != {"fail-fast": False, "matrix": {"include": expected_matrix}}
                    or len(run_steps) != 1 or run_steps[0]["run"].strip() != LIVE_VERIFY
                    or run_steps[0].get("env") != {"RELEASE_TAG": "${{ needs.publish.outputs.tag }}", "SYSTEM": "${{ matrix.system }}"}):
                refuse("public verification must exercise bootstrap and candidate clients on both architectures")
            needs = jobs["advertise"].get("needs")
            if not isinstance(needs, list) or set(needs) != {"publish", "live-verify"} or "if" in jobs["advertise"]:
                refuse("advertising requires successful completion of the whole public verification matrix")
    return errors


def check(root):
    errors = []
    workflows = sorted((root / ".github/workflows").glob("*.y*ml"))
    if not workflows:
        return ["no workflows found"]
    for path in workflows:
        try:
            if path.is_symlink():
                raise ValueError("workflow symlink")
            errors.extend(check_document(path.name, yaml.load(path.read_text(), Loader=WorkflowLoader)))
        except (ValueError, TypeError, AttributeError, KeyError, yaml.YAMLError) as error:
            errors.append(f"{path.name}: workflow policy could not complete: {error}")
    return errors


def main():
    errors = check(Path(__file__).resolve().parents[1])
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Workflow authority checks passed: all triggers, credentials and privileged entrypoints.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
