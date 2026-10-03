# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic HTTP/verified-evidence boundary for the noninstalled Rust harness.

This is deliberately not cryptography. The VM separately runs the pinned real gh
against genuine signed upstream fixtures and a fixed test trust root.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import time

root = Path('/var/lib/assbox-acceptance')
tool, *args = sys.argv[1:]
case = json.loads((root / 'case.json').read_text())
assert not any(os.environ.get(k) for k in ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN'))
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps([tool, *args]) + '\n')
if tool == 'systemd-ask-password':
    assert args in [['--echo=no', 'Choose an administrator password:'], ['--echo=no', 'Repeat the administrator password:']]
    if case.get('pause_password'):
        (root / 'password-pid').write_text(str(os.getpid()))
        time.sleep(3600)
    print('disposable-test-password')
elif tool == 'timedatectl':
    assert args == ['show', '--property=NTPSynchronized', '--value']
    print(case.get('time', 'yes'))
elif tool == 'curl':
    assert args[:5] == ['--disable', '--fail', '--silent', '--show-error', '--location']
    assert args[args.index('--proto') + 1] == '=https'
    source = case['urls'].get(args[-1])
    if source is None:
        sys.exit(22)
    shutil.copyfile(root / source, args[args.index('--output') + 1])
elif tool == 'gh':
    if args[:2] == ['release', 'verify-asset']:
        assert args[-2:] == ['--repo', 'assboxai/assbox']
        sys.exit(case.get('immutable_exit', 0))
    assert args[:2] == ['attestation', 'verify']
    expected = {
        '--repo': 'assboxai/assbox',
        '--cert-identity': 'https://github.com/assboxai/assbox/.github/workflows/release.yml@refs/heads/master',
        '--source-ref': 'refs/heads/master',
        '--source-digest': 'a' * 40, '--signer-digest': 'a' * 40,
        '--cert-oidc-issuer': 'https://token.actions.githubusercontent.com',
        '--predicate-type': 'https://slsa.dev/provenance/v1', '--format': 'json',
    }
    assert '--deny-self-hosted-runners' in args
    for key, value in expected.items():
        assert args[args.index(key) + 1] == value, (key, args)
    if case.get('attestation_exit'):
        sys.exit(case['attestation_exit'])
    print(json.dumps(case['proof']))
else:
    raise AssertionError(tool)
