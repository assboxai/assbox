#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reclaim fixed unused SDK directories on an ephemeral GitHub-hosted Linux runner."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import time

PATHS = tuple(Path(name) for name in (
    '/usr/local/lib/android', '/usr/share/dotnet',
    '/opt/hostedtoolcache', '/usr/local/.ghcup'))


def validate_environment(environment):
    if (os.geteuid() != 0 or platform.system() != 'Linux'
            or environment.get('GITHUB_ACTIONS') != 'true'
            or environment.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or environment.get('GITHUB_EVENT_NAME') not in (
                'workflow_dispatch', 'schedule', 'push', 'pull_request', 'workflow_run', 'workflow_call')):
        raise ValueError('Clearance requires an ephemeral hosted Linux workflow runner')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', environment.get('GITHUB_REPOSITORY', '')):
        raise ValueError('Missing workflow repository identity')
    for name in ('GITHUB_REPOSITORY_ID', 'GITHUB_REPOSITORY_OWNER_ID', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        if not re.fullmatch(r'[1-9][0-9]*', environment.get(name, '')):
            raise ValueError('Missing numeric workflow identity')
    if not re.fullmatch(r'[0-9a-f]{40}', environment.get('GITHUB_SHA', '')):
        raise ValueError('Missing workflow source identity')
    temporary = Path(environment.get('RUNNER_TEMP', ''))
    if not temporary.is_absolute() or temporary.resolve() != temporary:
        raise ValueError('Unexpected runner temporary path')
    metadata = temporary.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid == 0:
        raise ValueError('Unexpected runner temporary ownership')
    return temporary, metadata.st_uid


def mount_points():
    points = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        value = line.split()[4]
        value = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)
        points.append(Path(value))
    return points


def clear_directories(paths, runner_uid, root_device, mounts):
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError('Symlink-resistant directory deletion is required')
    admitted = []
    for path in paths:
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Refusing a redirected toolchain directory')
        if not path.exists():
            continue
        metadata = path.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid not in (0, runner_uid)
                or metadata.st_dev != root_device):
            raise ValueError('Unexpected toolchain directory type, owner or volume')
        if any(mount == path or path in mount.parents for mount in mounts):
            raise ValueError('Refusing a mounted toolchain directory')
        admitted.append(path)
    # Admit the entire fixed set before removing anything.
    for path in admitted:
        shutil.rmtree(path)
        if path.exists():
            raise ValueError('Toolchain clearance was incomplete')
    return [str(path) for path in admitted]


def main():
    temporary, runner_uid = validate_environment(os.environ)
    before = shutil.disk_usage('/')
    started = time.monotonic()
    removed = clear_directories(PATHS, runner_uid, Path('/').stat().st_dev, mount_points())
    after = shutil.disk_usage('/')
    facts = dict(schema=1, kind='hosted-runner-toolchain-clearance',
                 system=platform.machine() + '-linux', source_commit=os.environ['GITHUB_SHA'],
                 run_id=int(os.environ['GITHUB_RUN_ID']), run_attempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
                 removed_directories=removed, before_available_bytes=before.free,
                 after_available_bytes=after.free, observed_free_bytes_increase=after.free - before.free,
                 seconds=round(time.monotonic() - started, 2))
    output = temporary / 'assbox-runner-clearance.json'
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(facts, sort_keys=True, separators=(',', ':')) + '\n')
    print(json.dumps(facts, sort_keys=True))


if __name__ == '__main__':
    main()
