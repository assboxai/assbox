#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finite project development operations; production static checks only parse config."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def configuration(root=ROOT):
    config = tomllib.loads((root / 'chainman.toml').read_text())
    tasks = tomllib.loads((root / 'chainman/tasks.toml').read_text())['tasks']
    inventory = json.loads((root / 'development/tasks.json').read_text())['tasks']
    public = {item['name'] for item in inventory}
    if any(name not in public for name in tasks):
        raise ValueError('undeclared public task')
    if tasks['verify']['commands'] != [['python3', 'scripts/verify_candidate.py']]:
        raise ValueError('full gate must freeze before dispatch')
    updates = tomllib.loads((root / 'chainman/updates.toml').read_text())['updates']
    if updates['verify_task'] != 'verify' or updates['outputs'] != ['nix/dev/flake.lock']:
        raise ValueError('update acceptance or output scope changed')
    for name in ('rust', 'actions'):
        if updates['adapters'][name].get('explicit_only') is not True:
            raise ValueError('reviewed proposals cannot be automatic')
    if config['schema'] != 3:
        raise ValueError('unsupported Chainman schema')
    return config


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['config', 'runtime', 'generate', 'format-check', 'clean', 'vm-check'])
    parser.add_argument('check', nargs='?')
    args = parser.parse_args()
    if args.operation in ('config', 'runtime'):
        configuration()
        if args.operation == 'runtime':
            for command in (('config', 'validate'), ('preflight', 'verify'), ('deps-check',)):
                run('just', 'chainman', *command)
    elif args.operation == 'generate':
        for name in ('component_catalog', 'preset_catalog', 'product_docs'):
            run('python3', 'scripts/' + name + '.py')
    elif args.operation == 'format-check':
        run('cargo', 'fmt', '--all', '--check')
        paths = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*.nix') if
                 not set(p.relative_to(ROOT).parts) & {'.git', '.chainman', '.cache', 'target', 'reports'}]
        run('nixfmt', '--check', *paths)
    elif args.operation == 'clean':
        # Cargo owns this output; evidence and Chainman transactions have separate owners.
        run('cargo', 'clean')
    else:
        if args.check not in ('install-boot-vm', 'activation-recovery-vm', 'authenticated-release-vm'):
            parser.error('unknown VM check')
        system = subprocess.check_output(['nix', 'eval', '--impure', '--raw', '--expr', 'builtins.currentSystem'], text=True)
        run('nix', 'build', '--no-link', '--no-update-lock-file', '--no-write-lock-file',
            '.#checks.' + system + '.' + args.check)


if __name__ == '__main__':
    main()
