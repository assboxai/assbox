#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual generated SSH configuration with OpenSSH, without connections."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if len(sys.argv) != 4:
        raise SystemExit('usage: native-ssh-policy.py WORKER_MODULE AGENT_CONFIG HEALTH_CONFIG')
    spec = importlib.util.spec_from_file_location('worker', sys.argv[1])
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    managed = Path(sys.argv[2]).read_text()
    config = {**worker.FIXED_DIRS, 'guestAddress': '10.77.0.2'}

    def settings(path, alias):
        result = subprocess.run(['ssh', '-G', '-F', str(path), alias],
                                check=True, capture_output=True, text=True, timeout=10)
        return worker.parse_ssh_settings(result.stdout)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / 'config'
        globals_ = 'User operator\nPort 2200\nHost other\n  HostName example.org\n'
        merged = worker.merge_ssh_config(globals_, managed)
        path.write_text(merged)
        other = settings(path, 'other')
        assert other['user'] == ['operator'] and other['port'] == ['2200']
        assert other['hostname'] == ['example.org']
        worker.validate_ssh_settings(config, settings(path, 'assbox-worker'))
        health = settings(sys.argv[3], 'assbox-worker-health')
        worker.validate_ssh_settings(config, health, health=True)
        assert health['identityfile'] == ['/var/lib/assbox-worker-health/health_ed25519']
        assert '/var/lib/assbox-worker-identity/health_ed25519' not in health['identityfile']
        assert worker.merge_ssh_config(merged, managed) == merged
        # Accumulating directives must survive parsing and cause refusal. The
        # managed first-value settings alone cannot neutralize these globals.
        for setting in ('IdentityFile /tmp/unrelated-key',
                        'CertificateFile /tmp/unrelated-cert',
                        'LocalForward 127.0.0.1:43210 localhost:80',
                        'RemoteForward 43210 localhost:80',
                        'DynamicForward 127.0.0.1:43211'):
            for included in (False, True):
                extra = setting + '\n'
                if included:
                    include = root / 'included'
                    include.write_text(extra)
                    extra = 'Include ' + str(include) + '\n'
                path.write_text(worker.merge_ssh_config(extra, managed))
                try:
                    worker.validate_ssh_settings(config, settings(path, 'assbox-worker'))
                except worker.Refusal:
                    pass
                else:
                    raise AssertionError('Unsafe accumulated setting accepted: ' + setting)
        # Unrelated aliases can retain their own keys and forwarding rules.
        extra = 'Host other\n IdentityFile /tmp/other-key\n LocalForward 43210 localhost:80\n'
        path.write_text(worker.merge_ssh_config(extra, managed))
        worker.validate_ssh_settings(config, settings(path, 'assbox-worker'))
    print('Generated SSH policy passed, including accumulated identities and forwards.')


if __name__ == '__main__':
    main()
