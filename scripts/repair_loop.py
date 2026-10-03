#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private, frozen-oracle sessions; one fresh interactive install per attempt."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import uuid
import candidate_snapshot as snapshot_module
from candidate_snapshot import (MAX_FILE, MAX_TREE, ROOT, canonical, capture, digest, git, manifest,
    materialize, read_raw, safe_path, verify_files)

EXITS = {'passed': 0, 'failed': 1, 'invalid': 2, 'blocked': 3, 'error': 4, 'cancelled': 130}
PROTECTED = ('tests/', 'scripts/', '.github/', 'chainman/', 'nix/dev/', 'development/', 'release/')
PROTECTED_FILES = {'flake.nix', 'flake.lock', 'chainman.lock', 'chainman.toml', 'justfile', 'Cargo.lock',
    'scripts/architecture.py', 'scripts/workflow_policy.py', 'scripts/candidate_snapshot.py',
    'scripts/repair_loop.py', 'scripts/verify_candidate.py', 'scripts/release-check', 'scripts/verify',
    'scripts/verify_prepare.py', 'scripts/development_check.py', 'scripts/bootstrap.py', 'scripts/release.py',
    'scripts/development_maintenance.py', 'scripts/development_maintenance_writer.py',
    'scripts/development_maintenance_bootstrap.py', 'scripts/development_maintenance_status.py',
    'scripts/development_maintenance_inspect.py',
    'nix/release-environments.nix'}
ARTIFACT_LIMIT = 64 * 1024 * 1024


class Blocked(Exception):
    pass


class Cancelled(Exception):
    def __init__(self, number): self.number = number


def protected(name):
    # The root flake defines the existing gates. Crate integration tests sit
    # outside the top-level tests directory but have the same judge ownership.
    return (name.startswith(PROTECTED) or name in PROTECTED_FILES
            or (name.startswith('crates/') and 'tests' in name.split('/')[1:-1]))


def regression_test(name):
    return (name.startswith(('tests/tooling/', 'tests/fixtures/'))
            or (name.startswith('crates/') and 'tests' in name.split('/')[1:-1]))


def atomic(path, value):
    path = Path(path)
    temporary = path.parent / ('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def private(path, worktree=ROOT, create=False):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink(): raise ValueError('state path contains a symlink')
    resolved = path.resolve()
    if resolved == worktree or worktree in resolved.parents or resolved in worktree.parents:
        raise ValueError('state must be outside and separate from source')
    if create:
        resolved.mkdir(mode=0o700, parents=True, exist_ok=False)
    info = resolved.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('state must be an owned private directory')
    return resolved


def state_home():
    root = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')).resolve() / 'assbox/repair'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return private(root)


def export_commit(root, revision):
    oid = git(root, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    files = {}
    for item in filter(None, git(root, 'ls-tree', '-rz', oid).split(b'\0')):
        metadata, name = item.split(b'\t', 1)
        mode, kind, blob = metadata.split()
        if kind != b'blob' or mode not in (b'100644', b'100755'):
            raise ValueError('unsupported oracle source')
        size = int(git(root, 'cat-file', '-s', blob.decode()))
        if size > MAX_FILE: raise ValueError('oracle file exceeds source bound')
        raw = git(root, 'cat-file', 'blob', blob.decode())
        files[safe_path(name.decode())] = mode.decode(), raw
        if sum(len(value[1]) for value in files.values()) > MAX_TREE:
            raise ValueError('oracle tree exceeds source bound')
    return files, oid


def file_identity(files):
    return digest(canonical(manifest(files)))


def resource_policy(memory_gib=10, disk_gib=100):
    values = (memory_gib, disk_gib)
    if any(type(value) is not int or not 1 <= value < 2**23 for value in values):
        raise ValueError('resource guardrails require positive whole GiB within the evidence bound')
    return {'available_memory_bytes': memory_gib * 1024**3,
            'available_disk_bytes': disk_gib * 1024**3}


def controller_files():
    files = {}
    for name, filename in [('scripts/repair_loop.py', __file__),
                           ('scripts/candidate_snapshot.py', snapshot_module.__file__)]:
        path = Path(filename).resolve()
        files[name] = read_raw(path.parent, path.name)
    return files


def initialise(worktree, destination=None, oracle_ref='HEAD', oracle_source=None,
               include_new=(), purpose='repair', retain_disks=False, memory_gib=10, disk_gib=100):
    resources = resource_policy(memory_gib, disk_gib)
    worktree = Path(worktree).resolve()
    candidate, _ = capture(worktree, include_new)
    if oracle_source is None:
        oracle, revision = export_commit(worktree, oracle_ref)
        origin = {'kind': 'commit', 'commit': revision, 'requested_ref': oracle_ref}
    else:
        # Explicit external exports support initial implementation qualification.
        # Their synthetic commit is an identity, never a reviewed public commit.
        oracle_source = Path(oracle_source).resolve()
        oracle, _ = capture(oracle_source)
        origin = {'kind': 'cooperative-external-snapshot', 'path': str(oracle_source),
                  'commit': git(oracle_source, 'rev-parse', 'HEAD').decode().strip()}
    required = ('tests/nix/installer-cli-driver.nix', 'tests/fixtures/installer_cli_terminal.py',
                'tests/fixtures/installer_cli_cases.py', 'development/canonical-scenario.json')
    if any(name not in oracle for name in required):
        raise Blocked('oracle has no canonical CLI harness; select an explicitly reviewed oracle source')
    for name, value in oracle.items():
        if protected(name):
            if purpose == 'dependency-verification' and name in ('chainman.lock', 'nix/dev/flake.lock'):
                continue
            if candidate.get(name) != value:
                raise Blocked('candidate changes protected oracle surface: ' + name)
    controller = controller_files()
    for name, value in controller.items():
        if name in oracle and oracle[name] != value:
            raise Blocked('running controller differs from the reviewed oracle: ' + name)
    destination = (Path(destination).absolute() if destination else
                   state_home() / ('session-' + uuid.uuid4().hex))
    destination = private(destination, worktree, create=True)
    materialize(oracle, destination / 'oracle')
    for path in (destination / 'oracle').rglob('*'):
        if path.is_file() and '.git' not in path.parts:
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
    scenario = json.loads(oracle['development/canonical-scenario.json'][1])
    session = dict(schema=1, kind='assbox-repair-session', id=uuid.uuid4().hex,
        worktree=str(worktree), created_at=time.time(), oracle=origin,
        oracle_sha256=file_identity(oracle), oracle_manifest=manifest(oracle),
        controller_code_sha256=file_identity(controller),
        protected_manifest=manifest({name: value for name, value in candidate.items()
            if protected(name)}),
        include_new=list(include_new), purpose=purpose, isolation='cooperative-single-user',
        budgets=scenario['budgets'], resource_policy=resources,
        resource_policy_sha256=digest(canonical(resources)), retain_disks=retain_disks)
    (destination / 'runs').mkdir(mode=0o700)
    atomic(destination / 'oracle-manifest.json', session['oracle_manifest'])
    atomic(destination / 'resource-policy.json', resources)
    (destination / 'resource-policy.json').chmod(0o400)
    atomic(destination / 'session.json', session)
    return destination


@contextlib.contextmanager
def locked(path):
    path = private(path)
    fd = os.open(path / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise Blocked('session already in use') from error
        yield path, json.loads((path / 'session.json').read_bytes())
    finally:
        os.close(fd)


def check_oracle(path, session):
    if file_identity(controller_files()) != session.get('controller_code_sha256'):
        raise Blocked('controller code drift; create a separately reviewed session')
    files, _ = capture(path / 'oracle')
    if manifest(files) != session['oracle_manifest'] or file_identity(files) != session['oracle_sha256']:
        raise Blocked('oracle-drift')
    scenario = json.loads(files['development/canonical-scenario.json'][1])
    if session['budgets'] != scenario['budgets']: raise Blocked('frozen budget drift')
    try:
        _, resources = read_raw(path, 'resource-policy.json')
        if (resources != canonical(session['resource_policy'])
                or digest(resources) != session.get('resource_policy_sha256')):
            raise ValueError('resource binding mismatch')
    except (OSError, ValueError, KeyError) as error:
        raise Blocked('frozen resource guardrail drift; create a separately reviewed session') from error
    return files


def candidate_files(path, session, additions=()):
    check_oracle(path, session)
    files, _ = capture(Path(session['worktree']), [*session['include_new'], *additions])
    records = {row['path']: row for row in manifest(files)}
    for row in session['protected_manifest']:
        if records.get(row['path']) != row:
            raise Blocked('protected source drift: ' + row['path'])
    old_paths = {row['path'] for row in session['protected_manifest']}
    for name in files:
        if protected(name) and name not in old_paths:
            if not regression_test(name):
                raise Blocked('new protected source requires a new reviewed session: ' + name)
    return files


def memory_available():
    values = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split()) >= 2 and line.split()[1].isdigit()}
    available = values['MemAvailable']
    try:
        relative = next(line.split('::', 1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        current = Path('/sys/fs/cgroup') / relative.lstrip('/')
        while current != Path('/sys/fs'):
            maximum = (current / 'memory.max').read_text().strip()
            if maximum != 'max':
                available = min(available, max(0, int(maximum) - int((current / 'memory.current').read_text())))
            if current == Path('/sys/fs/cgroup'): break
            current = current.parent
    except (OSError, StopIteration, ValueError):
        pass
    return available


def capabilities(path, session):
    host = platform.machine()
    system = {'x86_64': 'x86_64-linux', 'aarch64': 'aarch64-linux', 'arm64': 'aarch64-linux'}.get(host)
    issues = []
    if platform.system() != 'Linux' or system is None: issues.append('native Linux x86-64 or ARM required')
    tools = {tool: shutil.which(tool) for tool in ('nix', 'qemu-img')}
    if not all(tools.values()): issues.append('Nix/QEMU tools unavailable')
    kvm = os.access('/dev/kvm', os.R_OK | os.W_OK)
    if system == 'x86_64-linux' and not kvm: issues.append('accessible KVM required on x86-64')
    memory = memory_available()
    if memory < session['resource_policy']['available_memory_bytes']: issues.append('available memory below frozen guardrail')
    volumes = {}
    for name, root in [('state', path), ('store', Path('/nix/store'))]:
        if not root.exists(): issues.append('Nix store unavailable'); continue
        info = os.statvfs(root)
        # Dynamic-inode filesystems such as Btrfs report both inode counts as
        # zero. That is unavailable capacity information, not exhaustion.
        inode_capacity_reported = info.f_files > 0
        volumes[name] = dict(device=root.stat().st_dev, available_bytes=info.f_bavail * info.f_frsize,
            inode_capacity_reported=inode_capacity_reported,
            available_inodes=info.f_favail if inode_capacity_reported else None)
        if (volumes[name]['available_bytes'] < session['resource_policy']['available_disk_bytes']
                or (inode_capacity_reported and info.f_favail == 0)):
            issues.append(name + ' capacity below frozen guardrail')
    return dict(schema=1, status='blocked' if issues else 'ready', issues=issues, host_system=system,
        guest_system=system, accelerator='kvm' if kvm else 'tcg', available_memory_bytes=memory,
        resource_policy=session['resource_policy'], resource_policy_sha256=session['resource_policy_sha256'],
        controller_code_sha256=session['controller_code_sha256'],
        volumes=volumes, tools=tools, isolation=session['isolation'], vm_executed=False,
        guardrails_are_qualified_requirements=False)


def history(path):
    summaries = []
    for run in sorted((path / 'runs').iterdir()):
        if not run.is_dir() or not run.name.isdigit(): continue
        summary = run / 'summary.json'
        summaries.append(json.loads(summary.read_bytes()) if summary.exists() else
                         dict(status='incomplete', attempt_id=run.name, elapsed_seconds=0))
    return summaries


def budget(path, session):
    results = history(path)
    limits = session['budgets']
    if any(r['status'] == 'incomplete' for r in results):
        raise Blocked('incomplete prior attempt requires evidence review in a new session')
    if len([r for r in results if r['status'] != 'built']) >= limits['max_attempts']: raise Blocked('attempt budget exhausted')
    if sum(r.get('driver_seconds', 0) for r in results) >= limits['cumulative_driver_seconds']:
        raise Blocked('cumulative driver budget exhausted')
    count = limits['repeated_failure_limit']
    recent = results[-count:]
    if len(recent) == count and recent[0].get('failure_fingerprint') and len({r.get('failure_fingerprint') for r in recent}) == 1:
        raise Blocked('repeated identical failure without progress; review evidence')
    return len(results) + 1


def environment(run):
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE') if key in os.environ}
    for name in ('home', 'tmp', 'cache'):
        (run / name).mkdir(mode=0o700, exist_ok=True)
    env.update(HOME=str(run / 'home'), TMPDIR=str(run / 'tmp'), XDG_CACHE_HOME=str(run / 'cache'))
    return env


def process(command, run, logfile, timeout, cleanup):
    child = subprocess.Popen(command, cwd=run, env=environment(run), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
    start = time.monotonic()
    retained = 0
    output_open = True
    try:
        with logfile.open('xb') as stream:
            os.chmod(logfile, 0o600)
            while True:
                if time.monotonic() - start > timeout: raise Blocked('phase deadline exceeded')
                if output_open and select.select([child.stdout], [], [], 0.2)[0]:
                    data = os.read(child.stdout.fileno(), 65536)
                    if not data:
                        output_open = False
                        continue
                    keep = data[:max(0, ARTIFACT_LIMIT - retained)]
                    stream.write(keep); stream.flush(); retained += len(keep)
                    if len(keep) < len(data): cleanup['log_truncated'] = True
                elif child.poll() is not None:
                    break
                elif not output_open:
                    time.sleep(0.05)
        result = child.wait(timeout=10)
        return result, time.monotonic() - start
    finally:
        def group_alive():
            for item in Path('/proc').iterdir():
                if item.name.isdigit():
                    try:
                        fields = (item / 'stat').read_text().rsplit(')', 1)[1].split()
                        if int(fields[2]) == child.pid and fields[0] != 'Z': return True
                    except (OSError, ValueError, IndexError): pass
            return False
        # The group may outlive an exited parent and still hold its output pipe.
        # Drain it as well as the direct child, using only this run's fresh group.
        if group_alive():
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            deadline = time.monotonic() + 10
            while group_alive() and time.monotonic() < deadline:
                child.poll(); time.sleep(0.05)
            if group_alive():
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        child.wait(timeout=10)
        child.stdout.close()
        # Detect any surviving member of this owned group. Never use stale PIDs
        # to kill unrelated processes or a host's Nix daemon.
        cleanup['owned_group_drained'] = not group_alive()
        cleanup['daemon_builder_cancellation_proven'] = False


def driver_command(path, run, receipt, system):
    return ['nix', 'build', '--impure', '--no-link', '--print-out-paths', '--no-update-lock-file',
        '--no-write-lock-file', '--file', str(path / 'oracle/tests/nix/installer-cli-driver.nix'),
        '--argstr', 'candidateSource', str(run / 'source'), '--argstr', 'candidateRevision', receipt['synthetic_commit_oid'],
        '--argstr', 'candidateContent', receipt['source_content_sha256'], '--argstr', 'system', system]


def event(path, value):
    fd = os.open(path / 'ledger.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())


def once(path, session, additions=(), build_only=False):
    files = candidate_files(path, session, additions)
    runtime = capabilities(path, session)
    if runtime['issues']: raise Blocked('; '.join(runtime['issues']))
    number = budget(path, session)
    run = path / 'runs' / ('%06d' % number)
    run.mkdir(mode=0o700)
    receipt = materialize(files, run / 'source')
    atomic(run / 'source-manifest.json', manifest(files)); atomic(run / 'candidate-snapshot.json', receipt)
    atomic(run / 'runtime.json', runtime)
    event(path, dict(event='attempt-start', attempt_id=run.name, candidate_snapshot=receipt,
                    resource_policy_sha256=session['resource_policy_sha256'], time=time.time()))
    start = time.monotonic(); driver_start = None; status = 'error'; failure = None
    cleanup = {'owned_group_drained': False, 'daemon_builder_cancellation_proven': False}
    summary = dict(schema=1, kind='assbox-canonical-run', attempt_id=run.name, nonce=uuid.uuid4().hex,
        candidate_snapshot=receipt, candidate_content_sha256=receipt['source_content_sha256'],
        oracle_sha256=session['oracle_sha256'], root_lock_sha256=digest(files['flake.lock'][1]),
        resource_policy=session['resource_policy'], resource_policy_sha256=session['resource_policy_sha256'],
        controller_code_sha256=session['controller_code_sha256'],
        dev_lock_sha256=digest(files['nix/dev/flake.lock'][1]), chainman_revision=files['chainman.lock'][1].decode().strip(),
        host_system=runtime['host_system'], guest_system=runtime['guest_system'], accelerator=runtime['accelerator'],
        isolation=session['isolation'], vm_executed=False, postboot=[], started_at=time.time())
    phase = 'driver-build'
    try:
        check_oracle(path, session)
        # Reviewed boundary: minimal no-worker seed, ordinary CLI build, source
        # mirror and .driver only. No worker disk/test-result dependency is built.
        command = driver_command(path, run, receipt, runtime['host_system'])
        code, _ = process(command, run, run / 'build.log', session['budgets']['per_run_seconds'], cleanup)
        if code: raise RuntimeError('driver build exit ' + str(code))
        paths = [line for line in (run / 'build.log').read_text(errors='replace').splitlines()
                 if line.startswith('/nix/store/') and ' ' not in line]
        if len(paths) != 1: raise RuntimeError('driver output identity unavailable')
        driver = Path(paths[0]); program = driver / 'bin/nixos-test-driver'
        if not program.is_file(): raise RuntimeError('driver program unavailable')
        summary['driver_store_path'] = str(driver)
        verify_files(run / 'source', files)
        if candidate_files(path, session, additions) != files: raise Blocked('source-drift')
        check_oracle(path, session)
        if build_only:
            status = 'built'
            return run
        phase = 'driver-execution'; driver_start = time.monotonic()
        (run / 'driver-output').mkdir(mode=0o700)
        code, elapsed = process([str(program), '--output_directory', str(run / 'driver-output')],
            run, run / 'driver.log', session['budgets']['per_run_seconds'] - (time.monotonic() - start), cleanup)
        summary['driver_exit_code'] = code
        summary['vm_executed'] = (run / 'driver-output/vm-started.json').is_file()
        summary['driver_seconds'] = elapsed
        phase = 'postboot-state'
        post = run / 'driver-output/target/postboot.json'
        if post.exists(): summary['postboot'] = json.loads(post.read_bytes())
        if code or not summary['vm_executed'] or summary['postboot'] != [{'id': 'P%02d' % n, 'status': 'passed'} for n in range(1, 15)]:
            raise RuntimeError('canonical driver/assertion failure; see retained logs')
        verify_files(run / 'source', files)
        if git(run / 'source', 'status', '--porcelain'): raise Blocked('snapshot drift')
        if candidate_files(path, session, additions) != files: raise Blocked('source-drift')
        check_oracle(path, session)
        if not cleanup['owned_group_drained']: raise RuntimeError('owned child cleanup incomplete')
        status = 'passed'
    except Blocked as error:
        status, failure = 'blocked', str(error)
    except Cancelled as error:
        status, failure = 'cancelled', 'signal-' + str(error.number)
        summary['exit_code'] = 128 + error.number
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        summary['vm_executed'] = (run / 'driver-output/vm-started.json').is_file()
        status, failure = ('failed' if summary['vm_executed'] else 'error'), str(error)
    finally:
        if (run / 'driver-output/vm-started.json').is_file(): summary['vm_executed'] = True
        cleanup['disk_retention_requested'] = session['retain_disks']
        cleanup['disks_removed'] = 0
        if cleanup['owned_group_drained'] and not session['retain_disks']:
            for image in (run / 'tmp').rglob('*.qcow2'):
                if image.is_file() and not image.is_symlink():
                    try:
                        image.unlink(); cleanup['disks_removed'] += 1
                    except OSError:
                        cleanup['disk_cleanup_incomplete'] = True
                        if status == 'passed': status, failure = 'error', 'disposable disk cleanup incomplete'
        if driver_start is not None: summary['driver_seconds'] = time.monotonic() - driver_start
        artifact_names = ['build.log', 'driver.log', 'runtime.json', 'source-manifest.json', 'candidate-snapshot.json',
            'driver-output/vm-started.json', 'driver-output/installer/installer-transcript.txt',
            'driver-output/installer/phase-events.jsonl', 'driver-output/installer/fixture-calls.jsonl',
            'driver-output/installer/fixture-release.json', 'driver-output/installer/instrumentation.json',
            'driver-output/installer/.assbox-install.json', 'driver-output/installer/journal.txt',
            'driver-output/target/journal.txt', 'driver-output/target/systemctl-failed.txt', 'driver-output/target/postboot.json']
        summary['artifacts'] = []
        for name in artifact_names:
            artifact = run / name
            item = dict(path=name, status='unavailable')
            if artifact.is_file() and not artifact.is_symlink() and artifact.stat().st_size <= ARTIFACT_LIMIT:
                raw = artifact.read_bytes(); item.update(status='retained', bytes=len(raw), sha256=digest(raw))
            summary['artifacts'].append(item)
        summary.update(status=status, finished_at=time.time(), elapsed_seconds=time.monotonic() - start,
            failure_class=None if status in ('passed', 'built') else phase, failure=failure,
            exit_code=summary.get('exit_code', EXITS.get(status, 0)), cleanup=cleanup)
        if failure:
            # Assertion/state features deliberately exclude candidate paths/keys.
            log = run / 'driver.log'
            features = [line.strip() for line in log.read_text(errors='replace').splitlines()[-200:]
                        if 'AssertionError' in line or 'wizard deadline W' in line] if log.exists() else []
            summary['failure_fingerprint'] = digest(canonical([phase, failure, features]))
        atomic(run / 'cleanup.json', cleanup)
        atomic(run / 'summary.json', summary)
        event(path, dict(event='attempt-finish', attempt_id=run.name, status=status, time=time.time()))
        print(str(run), flush=True)
    return run


def inspect(path, session):
    results = history(path)
    try:
        files = candidate_files(path, session)
        current = file_identity(files)
        integrity = 'current'
    except (Blocked, ValueError, OSError) as error:
        current, integrity = None, str(error)
    for result in results:
        result['current_candidate'] = (integrity == 'current' and result.get('candidate_content_sha256') == current)
        if result.get('status') == 'passed':
            expected_post = [{'id': 'P%02d' % n, 'status': 'passed'} for n in range(1, 15)]
            complete = (result.get('vm_executed') is True and result.get('exit_code') == 0
                and result.get('postboot') == expected_post and result.get('oracle_sha256') == session['oracle_sha256']
                and result.get('cleanup', {}).get('owned_group_drained') is True)
            try:
                run = path / 'runs' / result['attempt_id']
                receipt = result['candidate_snapshot']
                snapshot_files, _ = capture(run / 'source')
                complete = (complete and file_identity(snapshot_files) == result['candidate_content_sha256']
                    == receipt['source_content_sha256']
                    and git(run / 'source', 'rev-parse', 'HEAD').decode().strip() == receipt['synthetic_commit_oid'])
            except (ValueError, OSError, KeyError, subprocess.SubprocessError): complete = False
            if not complete:
                result.update(status='incomplete', reason='passing execution evidence is incomplete')
            elif not result['current_candidate']:
                result['status'] = 'stale'
    return dict(schema=1, session=str(path), oracle_sha256=session['oracle_sha256'], integrity=integrity,
                attempts=results, vm_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'preflight', 'build', 'once', 'status', 'finalize', 'canonical'])
    parser.add_argument('--session', type=Path)
    parser.add_argument('--worktree', type=Path, default=ROOT)
    parser.add_argument('--oracle-ref', default='HEAD')
    parser.add_argument('--oracle-source', type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--summary-output', type=Path)
    parser.add_argument('--include-new', action='append', default=[])
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--retain-disks', action='store_true')
    parser.add_argument('--minimum-memory-gib', type=int)
    parser.add_argument('--minimum-disk-gib', type=int)
    args = parser.parse_args()
    if args.command not in ('init', 'canonical') and (args.minimum_memory_gib is not None or args.minimum_disk_gib is not None):
        parser.error('resource guardrails can only be selected when creating a session')
    resources = {'memory_gib': args.minimum_memory_gib if args.minimum_memory_gib is not None else 10,
                 'disk_gib': args.minimum_disk_gib if args.minimum_disk_gib is not None else 100}
    try:
        resource_policy(**resources)
    except ValueError as error:
        parser.error(str(error))
    def cancel(number, frame): raise Cancelled(number)
    for number in (signal.SIGINT, signal.SIGTERM): signal.signal(number, cancel)
    try:
        if args.command == 'init':
            print(initialise(args.worktree, args.session, args.oracle_ref, args.oracle_source, args.include_new, retain_disks=args.retain_disks, **resources)); return 0
        if args.command == 'canonical':
            worktree = args.snapshot or args.worktree
            oracle = args.oracle_source or (Path(os.environ['ASSBOX_ORACLE_SOURCE']) if os.environ.get('ASSBOX_ORACLE_SOURCE') else None)
            session_path = initialise(worktree, oracle_ref=args.oracle_ref, oracle_source=oracle,
                include_new=args.include_new, purpose='dependency-verification', retain_disks=args.retain_disks, **resources)
        else:
            if args.session is None: parser.error('--session is required')
            session_path = args.session
        with locked(session_path) as (path, session):
            if args.command == 'status':
                result = inspect(path, session); print(json.dumps(result, sort_keys=True)); return 0
            if args.command == 'preflight':
                candidate_files(path, session, args.include_new)
                result = capabilities(path, session); atomic(path / 'preflight.json', result)
                print(json.dumps(result, sort_keys=True)); return 3 if result['issues'] else 0
            if args.command == 'finalize':
                result = inspect(path, session)
                if not result['attempts'] or result['attempts'][-1]['status'] != 'passed': raise Blocked('no current canonical pass')
                run = path / 'runs' / result['attempts'][-1]['attempt_id']
                subprocess.run(['nix', 'run', 'path:' + str(run / 'source/nix/dev') + '#just', '--',
                    'verify', '--oracle-source', str(path / 'oracle'),
                    '--minimum-memory-gib', str(session['resource_policy']['available_memory_bytes'] // 1024**3),
                    '--minimum-disk-gib', str(session['resource_policy']['available_disk_bytes'] // 1024**3)],
                    cwd=run / 'source', check=True)
                if candidate_files(path, session) != capture(run / 'source')[0]: raise Blocked('source-drift')
                atomic(path / 'finalization.json', dict(schema=1, status='passed', system=result['attempts'][-1]['host_system'],
                    candidate_snapshot=result['attempts'][-1]['candidate_snapshot'], remote_writes=False))
                return 0
            run = once(path, session, args.include_new, build_only=args.command == 'build')
            summary = json.loads((run / 'summary.json').read_bytes())
            if args.summary_output: atomic(args.summary_output, summary)
            return summary['exit_code']
    except Blocked as error:
        print(json.dumps(dict(status='blocked', reason=str(error), vm_executed=False))); return 3
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps(dict(status='invalid', reason=str(error), vm_executed=False))); return 2


if __name__ == '__main__':
    raise SystemExit(main())
