#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner-run external Coder canaries. Never connect, authenticate or drive an app."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import uuid

PHASES = ('initial', 'disconnected', 'reconnected')
ROUTES = ('mac-codex-ssh', 'mac-claude-ssh', 'phone-mac-codex-ssh')
VARIANTS = ('selected-unenrolled', 'deselected')

# This exact, self-contained payload is pasted into the real app's guest project.
# HOME intentionally resolves on the machine that actually executes the command.
# An attempt is recorded before reading the role canary, including wrong-host execution.
TASK = r'''import fcntl,hashlib,json,os,sys,tempfile,uuid
from pathlib import Path
run,phase=sys.argv[1:]
assert str(uuid.UUID(run))==run and phase in ('initial','disconnected','reconnected')
os.umask(0o077)
root=Path.home()/'.local/share/assbox-coder-qualification'/run
assert root.is_dir()
fd=os.open(root/('attempt-'+phase),os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as output:output.write('attempt\n');output.flush();os.fsync(output.fileno())
lock=os.open(root/'task.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
with os.fdopen(lock,'w') as held:
 fcntl.flock(held,fcntl.LOCK_EX)
 canary=(root/'canary').read_bytes()
 assert canary.startswith(b'guest '),'command ran outside the prepared guest'
 path=root/'counter.json'
 counter=json.loads(path.read_text()) if path.exists() else {'executions':0,'phases':[]}
 counter['executions']+=1;counter['phases'].append(phase)
 def write(name,value):
  fd,tmp=tempfile.mkstemp(dir=root,prefix='.task-')
  with os.fdopen(fd,'w') as output:json.dump(value,output,sort_keys=True);output.flush();os.fsync(output.fileno())
  os.replace(tmp,root/name)
  fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
 write('counter.json',counter)
 write('task-result.json',{'run':run,'phase':phase,'canarySha256':hashlib.sha256(canary).hexdigest(),'pid':os.getpid(),'platform':sys.platform})
'''


class Refusal(Exception):
    pass


def root_for(run):
    if str(uuid.UUID(run)) != run:
        raise Refusal('use a fresh canonical UUID shared by both roles')
    return Path.home() / '.local/share/assbox-coder-qualification' / run


def fixture_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def versions_valid(versions):
    return isinstance(versions, dict) and set(versions) == {'app', 'agent', 'hypervisor', 'authMode'} and all(
        isinstance(v, str) and 1 <= len(v) <= 256 and not any(ord(c) < 32 for c in v) for v in versions.values())


def architecture(value):
    return {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64'}.get(value)


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 65536:
            raise Refusal('fixture artifact is not a bounded private owner file')
        with os.fdopen(fd, 'rb') as source:
            fd = None
            return source.read(65537)
    finally:
        if fd is not None:
            os.close(fd)


def write(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.record-')
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_root(run):
    root = root_for(run)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Refusal('fixture directory must be private and owned by this execution identity')
    return root


def prepare(run, role, route, variant, versions):
    if role not in ('controller', 'guest') or route not in ROUTES or variant not in VARIANTS:
        raise Refusal('select the exact role, Mac route and Tailscale variant')
    if not versions_valid(versions):
        raise Refusal('owner-reported versions require app, agent, hypervisor and non-secret authMode strings')
    root = root_for(run)
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.mkdir(mode=0o700)  # A fresh run never overwrites existing observations.
    canary = (role + ' ' + secrets.token_hex(32) + '\n').encode()
    fd = os.open(root / 'canary', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(canary)
        output.flush()
        os.fsync(output.fileno())
    write(root / 'prepared.json', {'schema': 1, 'run': run, 'role': role, 'route': route, 'tailscaleVariant': variant,
                                  'fixtureSha256': fixture_digest(),
                                  'ownerReportedVersions': versions, 'canarySha256': hashlib.sha256(canary).hexdigest()})
    return root


def processes():
    # comm excludes arguments, environment, keys, tokens and pairing URLs.
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,comm='], capture_output=True, text=True, timeout=10, check=True)
    if len(result.stdout) > 1024 * 1024:
        raise Refusal('process-name observation exceeded its bound')
    output = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and any(name in fields[2].lower() for name in ('codex', 'chatgpt', 'claude')):
            output.append({'pid': int(fields[0]), 'parent': int(fields[1]), 'commandName': fields[2]})
    return output[:256]


def record(run, phase):
    if phase not in PHASES:
        raise Refusal('unknown observation phase')
    root = private_root(run)
    prepared = json.loads(read(root / 'prepared.json'))
    if prepared.get('fixtureSha256') != fixture_digest():
        raise Refusal('fixture source changed during this run')
    if hashlib.sha256(read(root / 'canary')).hexdigest() != prepared['canarySha256']:
        raise Refusal('the role canary changed')
    report_path = root / 'record.json'
    report = json.loads(read(report_path)) if report_path.exists() else {
        **prepared, 'platform': platform.system(), 'architecture': platform.machine(), 'observations': {}}
    observations = report['observations']
    if set(observations) != set(PHASES[:PHASES.index(phase)]):
        raise Refusal('record each phase once and in order; start a fresh run after a failure')
    attempts = {p: read(root / ('attempt-' + p)).count(b'attempt\n') if (root / ('attempt-' + p)).exists() else 0 for p in PHASES}
    counter = json.loads(read(root / 'counter.json')) if (root / 'counter.json').exists() else {'executions': 0, 'phases': []}
    if prepared['role'] == 'controller':
        if any(attempts.values()) or counter['executions']:
            raise Refusal('the test command executed in the controller fixture')
    else:
        expected = ['initial'] if phase != 'reconnected' else ['initial', 'reconnected']
        expected_attempts = {'initial': 1, 'disconnected': 0, 'reconnected': int(phase == 'reconnected')}
        if counter != {'executions': len(expected), 'phases': expected} or attempts != expected_attempts:
            raise Refusal('guest execution was missing, replayed or occurred during the disconnected phase')
        task = json.loads(read(root / 'task-result.json'))
        if task.get('run') != run or task.get('phase') != expected[-1] or task.get('canarySha256') != prepared['canarySha256']:
            raise Refusal('task result does not prove access to the prepared guest canary')
    observations[phase] = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                           'canarySha256': prepared['canarySha256'],
                           'attempts': attempts, 'counter': counter, 'processNames': processes()}
    write(report_path, report)
    return report_path


def verify(controller, guest):
    host, remote = json.loads(read(controller)), json.loads(read(guest))
    if not isinstance(host, dict) or not isinstance(remote, dict):
        raise Refusal('records must be objects')
    for key in ('schema', 'run', 'route', 'tailscaleVariant', 'ownerReportedVersions', 'fixtureSha256'):
        if host.get(key) != remote.get(key):
            raise Refusal('records cover different runs or declared route scopes')
    if host.get('role') != 'controller' or remote.get('role') != 'guest':
        raise Refusal('provide separate controller and guest records')
    if host.get('schema') != 1 or host.get('fixtureSha256') != fixture_digest() or host.get('route') not in ROUTES or host.get('tailscaleVariant') not in VARIANTS:
        raise Refusal('record schema, source or route is not current')
    root_for(host['run'])
    if not versions_valid(host.get('ownerReportedVersions')):
        raise Refusal('records need the complete declared client/agent/auth scope')
    if host.get('canarySha256') == remote.get('canarySha256'):
        raise Refusal('controller and guest canaries must be independently generated')
    if host.get('platform') != 'Darwin' or remote.get('platform') != 'Linux' or not architecture(host.get('architecture')) or architecture(host.get('architecture')) != architecture(remote.get('architecture')):
        raise Refusal('Mac/guest observations require matching CPU architecture and their actual OS roles')
    for report in (host, remote):
        if not re.fullmatch('[0-9a-f]{64}', str(report.get('canarySha256', ''))):
            raise Refusal('invalid role canary digest')
        if not isinstance(report.get('observations'), dict) or set(report['observations']) != set(PHASES):
            raise Refusal('all initial, disconnected and reconnected observations are required')
        for phase in PHASES:
            observation = report['observations'][phase]
            if not isinstance(observation, dict):
                raise Refusal('invalid phase observation')
            expected = [] if report['role'] == 'controller' else (['initial', 'reconnected'] if phase == 'reconnected' else ['initial'])
            attempts = {p: int(p in expected) for p in PHASES}
            if observation.get('canarySha256') != report['canarySha256'] or observation.get('counter') != {'executions': len(expected), 'phases': expected} or observation.get('attempts') != attempts:
                raise Refusal('recorded observations show fallback, replay or a changed canary')
    return {'run': host['run'], 'route': host['route'], 'tailscaleVariant': host['tailscaleVariant'],
            'canaryDisconnectFixture': 'passed', 'routeQualification': 'not_established',
            'limits': 'Observed fixture paths only. Requires independent app/client/helper/auth, SSH channels, egress, host-sharing and mobile evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('prepare')
    setup.add_argument('--run-id', required=True)
    setup.add_argument('--role', choices=['controller', 'guest'], required=True)
    setup.add_argument('--route', choices=ROUTES, required=True)
    setup.add_argument('--tailscale', choices=VARIANTS, required=True)
    setup.add_argument('--versions', type=Path, required=True)
    prompt = commands.add_parser('prompt')
    prompt.add_argument('--run-id', required=True)
    prompt.add_argument('--phase', choices=PHASES, required=True)
    collect = commands.add_parser('record')
    collect.add_argument('--run-id', required=True)
    collect.add_argument('--phase', choices=PHASES, required=True)
    compare = commands.add_parser('verify')
    compare.add_argument('--controller', type=Path, required=True)
    compare.add_argument('--guest', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.run_id, args.role, args.route, args.tailscale, json.loads(read(args.versions))))
    elif args.command == 'prompt':
        root_for(args.run_id)
        print('In the selected external app, use the prepared guest project and run this exact command once. Do not change project/host or replay an uncertain operation:\n')
        print('python3 -c ' + shlex.quote(TASK) + ' ' + shlex.quote(args.run_id) + ' ' + shlex.quote(args.phase))
    elif args.command == 'record':
        print(record(args.run_id, args.phase))
    else:
        print(json.dumps(verify(args.controller, args.guest), sort_keys=True, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('External Coder fixture: ' + str(error), file=sys.stderr)
        sys.exit(1)
