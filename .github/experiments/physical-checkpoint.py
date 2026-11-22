#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a hosted live checkpoint and validate its publication inputs."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys

REPO = 'assboxai/assbox'
REPO_ID = '1402455771'
OWNER_ID = '327835666'
REF = 'refs/heads/test/physical-checkpoint-x86-v7'
SOURCE = '24b3a4f3773d61aa236c22d8ee48ab42a39797e0'
TREE = 'dded0799163d8ca63d8e91948402fa633a401be8'
LOCK = 'ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
SYSTEM = 'x86_64-linux'
MARKER = b'ASSBOX_PHYSICAL_CHECKPOINT_READY ' + SOURCE.encode()
ISO = 'assbox-physical-checkpoint-x86_64-linux.iso'
MANIFEST = 'assbox-physical-checkpoint.json'
LOGS = ('bios-serial.log', 'uefi-serial.log')
FILE_LIMITS = {ISO: 2_147_483_647, **{name: 16 * 1024 * 1024 for name in LOGS}}
NIX_FLAGS = ('--no-update-lock-file', '--no-write-lock-file')
GATES = (('setup', '--no-hooks'), ('verify-lite',), ('verify-prepare',))
FILE_PATH = re.compile(r'/nix/store/[a-z0-9]{32}-[^/]+')
SQLITE_DRV = '/nix/store/9c4c1sxhr50h2blkr8x46306mygns01k-sqlite-3.54.1.drv'
SQLITE_BIN = '/nix/store/m7l1rwbyq8hicv2dmnpaiwfkccx6hbxv-sqlite-3.54.1-bin'


def run(*args, cwd):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def identity():
    expected = dict(GITHUB_REPOSITORY=REPO, GITHUB_REPOSITORY_ID=REPO_ID,
                    GITHUB_REPOSITORY_OWNER_ID=OWNER_ID, GITHUB_REF=REF,
                    GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_ATTEMPT='1',
                    RUNNER_ENVIRONMENT='github-hosted')
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ValueError('Workflow environment does not match the reviewed experiment')
    workflow = os.environ['GITHUB_SHA']
    run_id = os.environ['GITHUB_RUN_ID']
    if not re.fullmatch(r'[0-9a-f]{40}', workflow) or not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Invalid workflow commit or run ID')
    authority = Path(os.environ['GITHUB_WORKSPACE']) / 'authority'
    verify_checkout(authority, workflow)
    return dict(schema=1, kind='assbox-development-live-checkpoint', system=SYSTEM,
                sourceCommit=SOURCE, sourceTree=TREE, lockSha256=LOCK, workflowCommit=workflow,
                repository=REPO, repositoryId=int(REPO_ID), ownerId=int(OWNER_ID), workflowRef=REF,
                runId=int(run_id), runAttempt=1, releaseTag=f'physical-checkpoint-{run_id}-1-{SYSTEM}-dev')


def verify_checkout(root, revision):
    if run('git', 'rev-parse', 'HEAD', cwd=root) != revision or run('git', 'status', '--porcelain', cwd=root):
        raise ValueError('Checkout revision or cleanliness changed')


def file_proof(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError(f'Unexpected checkpoint file {path.name}')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(bytes=info.st_size, sha256=digest)


def validate(files, scope):
    if files.is_symlink() or {path.name for path in files.iterdir()} != {MANIFEST, ISO, *LOGS}:
        raise ValueError('Unexpected checkpoint artifact inventory')
    file_proof(files / MANIFEST, 16 * 1024)
    manifest = json.loads((files / MANIFEST).read_bytes())
    results = dict(finiteGateExits={gate[0]: 0 for gate in GATES}, productInstallationQualified=False,
                   physicalHardwareQualified=False, vmAccelerator='kvm',
                   biosVM='passed', uefiUSBVM='passed')
    expected = dict(**scope, **results)
    if (not isinstance(manifest, dict) or set(manifest) != {*expected, 'assets'}
            or any(type(manifest[key]) is not type(value) or manifest[key] != value
                   for key, value in expected.items())):
        raise ValueError('Checkpoint manifest differs from the admitted scope and gate results')
    actual = {name: file_proof(files / name, limit) for name, limit in FILE_LIMITS.items()}
    if manifest['assets'] != actual:
        raise ValueError('Checkpoint artifact bytes differ from the bound digests')
    for name in LOGS:
        if MARKER not in (files / name).read_bytes():
            raise ValueError(f'{name} has no readiness marker for the exact source')
    print(json.dumps(manifest, sort_keys=True))


def build_sqlite(source, logs):
    attribute = '.#nixosConfigurations.x86_64-linux-physical-checkpoint.pkgs.sqlite'
    selected = run('nix', 'eval', '--raw', *NIX_FLAGS, attribute + '.drvPath', cwd=source)
    output = run('nix', 'eval', '--raw', *NIX_FLAGS, attribute + '.bin.outPath', cwd=source)
    if selected != SQLITE_DRV or output != SQLITE_BIN:
        raise ValueError('SQLite differs from the reviewed checkpoint dependency')
    print('Building exact SQLite with the full native test suite and four test workers', flush=True)
    try:
        with (logs / 'sqlite-build.log').open('xb') as log:
            built = subprocess.run(
                ('nix', 'build', '--max-jobs', '1', '--cores', '4', '--keep-failed', '--no-link',
                 '--print-out-paths', '-L', *NIX_FLAGS, selected + '^bin'),
                cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=3600,
            )
    except subprocess.TimeoutExpired:
        (logs / 'sqlite-status.tsv').write_text(f'124\t{selected}\t{output}\n')
        raise
    (logs / 'sqlite-status.tsv').write_text(f'{built.returncode}\t{selected}\t{output}\n')
    if built.returncode:
        with (logs / 'sqlite-derivation.log').open('xb') as log:
            subprocess.run(('nix', 'log', selected), cwd=source, stdout=log, stderr=subprocess.STDOUT)
        built.check_returncode()
    if run('nix', 'path-info', '--offline', output, cwd=source) != output:
        raise ValueError('SQLite build did not register the reviewed output')


def build(files, scope, logs):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Checkpoint qualification requires native Linux x86-64')
    source = Path(os.environ['GITHUB_WORKSPACE']) / 'product'
    verify_checkout(source, SOURCE)
    if (run('git', 'rev-parse', 'HEAD^{tree}', cwd=source) != TREE
            or file_proof(source / 'flake.lock', 1024 * 1024)['sha256'] != LOCK):
        raise ValueError('Product tree or flake lock differs from the reviewed checkpoint source')
    prefill = json.loads((logs / 'kernel-formatter-seed.json').read_bytes())
    pin = json.loads((Path(__file__).resolve().parent / 'v71-x86-kernel-formatter.json').read_bytes())
    if any(prefill.get(key) != value for key, value in pin.items()) or prefill.get('signatureRequired') is not True:
        raise ValueError('Checkpoint cache receipt differs from the reviewed signed inputs')
    for gate in GATES:
        print(f'Running native checkpoint gate {gate[0]}', flush=True)
        with (logs / (gate[0] + '.log')).open('xb') as output:
            subprocess.run(('nix', 'run', *NIX_FLAGS, 'path:./nix/dev#just', '--', *gate), cwd=source,
                           stdout=output, stderr=subprocess.STDOUT, timeout=1200, check=True)
        verify_checkout(source, SOURCE)

    build_sqlite(source, logs)
    boot_attr = f'.#checks.{SYSTEM}.physical-checkpoint-boot'
    image_attr = f'.#packages.{SYSTEM}.physical-checkpoint-iso'
    boot_drv = run('nix', 'eval', '--raw', *NIX_FLAGS, boot_attr + '.drvPath', cwd=source)
    image_drv = run('nix', 'eval', '--raw', *NIX_FLAGS, image_attr + '.drvPath', cwd=source)
    inputs = run('nix-store', '--query', '--references', boot_drv, cwd=source).splitlines()
    if image_drv not in inputs:
        raise ValueError('The boot check does not reference the selected image derivation')
    print('Building and booting the exact ISO in BIOS and UEFI USB modes', flush=True)
    with (logs / 'boot-build.log').open('xb') as log:
        boot = subprocess.check_output(
            ('nix', 'build', '--no-link', '--print-out-paths', '-L', *NIX_FLAGS, boot_attr),
            cwd=source, stderr=log, text=True,
        ).strip()
    image = run('nix', 'build', '--no-link', '--print-out-paths', *NIX_FLAGS, image_attr, cwd=source)
    if not FILE_PATH.fullmatch(boot) or not FILE_PATH.fullmatch(image):
        raise ValueError('Expected one boot result and one image store path')
    (logs / 'store-paths.txt').write_text(f'{boot_drv}\n{image_drv}\n{boot}\n{image}\n')
    if (Path(boot) / 'passed').read_bytes().strip() != MARKER:
        raise ValueError('The boot derivation did not report completion for the exact source')
    iso, = (Path(image) / 'iso').glob('*.iso')
    files.mkdir(mode=0o700)
    file_proof(iso, FILE_LIMITS[ISO])
    shutil.copyfile(iso, files / ISO)
    for name in LOGS:
        shutil.copyfile(Path(boot) / name, files / name)
    assets = {name: file_proof(files / name, limit) for name, limit in FILE_LIMITS.items()}
    manifest = dict(**scope, assets=assets, finiteGateExits={gate[0]: 0 for gate in GATES},
                    productInstallationQualified=False, physicalHardwareQualified=False,
                    vmAccelerator='kvm', biosVM='passed', uefiUSBVM='passed')
    (files / MANIFEST).write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    verify_checkout(source, SOURCE)
    validate(files, scope)


if __name__ == '__main__':
    scope = identity()
    temporary = Path(os.environ['RUNNER_TEMP'])
    files = temporary / 'assbox-checkpoint-assets'
    mode, = sys.argv[1:]
    if mode == 'build':
        build(files, scope, temporary / 'assbox-checkpoint-logs')
    elif mode == 'validate':
        validate(files, scope)
    else:
        raise SystemExit('Expected build or validate')
