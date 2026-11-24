#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure the native runner's available filesystem space and KVM device."""
import fcntl
import json
import os
from pathlib import Path
import platform
import stat

assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
expected = {
    'GITHUB_ACTIONS': 'true',
    'RUNNER_ENVIRONMENT': 'github-hosted',
    'GITHUB_REPOSITORY_ID': '1402455771',
    'GITHUB_REPOSITORY_OWNER_ID': '327835666',
    'GITHUB_REF': 'refs/heads/test/x86-hosted-qualification-capacity',
    'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'GITHUB_RUN_ATTEMPT': '1',
}
assert all(os.environ.get(key) == value for key, value in expected.items())

def space(path):
    values = os.statvfs(path)
    return {'device': path.stat().st_dev, 'totalBytes': values.f_blocks * values.f_frsize,
            'runnerAvailableBytes': values.f_bavail * values.f_frsize}

device = Path('/dev/kvm')
kvm = {'exists': device.exists(), 'usable': False}
if kvm['exists']:
    kvm['characterDevice'] = stat.S_ISCHR(device.stat().st_mode)
    assert kvm['characterDevice']
    try:
        fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        try:
            api = fcntl.ioctl(fd, 0xAE00, 0)
            kvm['apiVersion'] = api
            if api == 12:
                machine = fcntl.ioctl(fd, 0xAE01, 0)
                os.close(machine)
                kvm['usable'] = True
        finally:
            os.close(fd)
    except OSError as error:
        kvm['errno'] = error.errno

memory = {}
for line in Path('/proc/meminfo').read_text().splitlines():
    name, _, data = line.partition(':')
    if name in ('MemTotal','MemAvailable'):
        units, suffix = data.split()
        assert suffix == 'kB'
        memory[name + 'Bytes'] = 1024 * int(units)

print(json.dumps({
    'architecture': 'x86_64-linux', 'authorityCommit': os.environ['GITHUB_SHA'],
    'runId': int(os.environ['GITHUB_RUN_ID']), 'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
    'runner': os.environ['RUNNER_ENVIRONMENT'], 'uid': os.getuid(),
    'rootFilesystem': space(Path('/')), 'workspaceFilesystem': space(Path(os.environ['RUNNER_TEMP'])),
    'memory': memory, 'effectiveCpuCount': len(os.sched_getaffinity(0)), 'kvm': kvm,
}, indent=2))
