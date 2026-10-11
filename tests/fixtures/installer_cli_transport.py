# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact external transport/time/password boundary; no privileged tool stubs."""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path('/var/lib/assbox-acceptance')


def dispatch(tool, args, case, root=ROOT):
    if tool == 'timedatectl':
        if args == ['show', '--property=Timezone', '--value']: return 'UTC'
        if args == ['show', '--property=NTPSynchronized', '--value']: return 'yes'
    elif tool == 'systemd-ask-password':
        if args in [['--echo=no', 'Choose an administrator password:'], ['--echo=no', 'Repeat the administrator password:']]:
            # Public disposable data, never a reusable operator password.
            return 'assbox-disposable-fixture-password-2026'
    elif tool == 'curl':
        limits = {'release.json': '65536', 'release.sigstore.json': '4194304',
                  'flake.lock': '8388608', 'assbox-source.tar.gz': '67108864'}
        asset = args[-1].rsplit('/', 1)[-1] if args else ''
        limit = '65536' if args and args[-1].endswith('/git/ref/tags/r-1') else limits.get(asset)
        expected = ['--disable', '--fail', '--silent', '--show-error', '--location', '--max-redirs', '5',
            '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '20', '--max-time', '300',
            '--max-filesize', limit, '--output']
        if len(args) == 20 and args[:18] == expected and args[-1] in case['urls']:
            destination = Path(args[18])
            if not destination.is_absolute() or destination.is_symlink() or not str(destination).startswith('/run/assbox-install/'):
                raise ValueError('fixture download destination escaped installation')
            shutil.copyfile(root / case['urls'][args[-1]], destination)
            return None
    elif tool == 'gh':
        if (len(args) == 6 and args[:3] == ['release', 'verify-asset', 'r-1']
                and args[3].endswith('/release.json') and args[-2:] == ['--repo', 'assboxai/assbox']):
            return None
        expected = ['attestation', 'verify', None, '--bundle', None, '--repo', 'assboxai/assbox',
            '--cert-identity', 'https://github.com/assboxai/assbox/.github/workflows/release.yml@refs/heads/master',
            '--source-ref', 'refs/heads/master', '--source-digest', case['revision'], '--signer-digest', case['revision'],
            '--cert-oidc-issuer', 'https://token.actions.githubusercontent.com', '--deny-self-hosted-runners',
            '--predicate-type', 'https://slsa.dev/provenance/v1', '--format', 'json']
        if (len(args) == len(expected) and all(want is None or want == got for want, got in zip(expected, args))
                and args[2].endswith('/release.json') and args[4].endswith('/release.sigstore.json')):
            return json.dumps(case['proof'])
    raise ValueError('unrecognized canonical external fixture call: ' + tool)


if __name__ == '__main__':
    if any(os.environ.get(k) for k in ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN')):
        raise ValueError('fixture received credentials')
    tool, *args = sys.argv[1:]
    with (ROOT / 'fixture-calls.jsonl').open('a') as log:
        # Password values are never logged; only the fixed request label.
        log.write(json.dumps([tool, *args]) + '\n')
    result = dispatch(tool, args, json.loads((ROOT / 'case.json').read_text()))
    if result is not None: print(result)
