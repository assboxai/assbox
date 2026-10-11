#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run one fixed verification stage with best-effort, nonsecret diagnostics."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('static', 'rust', 'mutations', 'nix')
INTERVAL = 30
MAX_LOG_BYTES = 8 * 1024 * 1024


def read_text(path):
    try:
        return path.read_text()
    except (OSError, UnicodeError):
        return ''


def counters(path, names):
    result = {}
    for line in read_text(path).splitlines():
        fields = line.replace(':', '').split()
        if len(fields) >= 2 and fields[0] in names and fields[1].isdigit():
            result[fields[0]] = int(fields[1])
    return result or None


def pressure(path):
    result = {}
    for line in read_text(path).splitlines():
        fields = line.split()
        if not fields or fields[0] not in ('some', 'full'):
            continue
        values = {}
        for field in fields[1:]:
            key, separator, value = field.partition('=')
            if separator and key in ('avg10', 'avg60', 'avg300', 'total'):
                try:
                    number = float(value)
                    if 0 <= number < float('inf'):
                        values[key] = number
                except ValueError:
                    pass
        if values:
            result[fields[0]] = values
    return result or None


def snapshot(workspace=ROOT, proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')):
    memory = counters(proc / 'meminfo', ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'))
    disks = {}
    for name, path in (('workspace', workspace), ('nix_store', Path('/nix/store'))):
        try:
            usage = shutil.disk_usage(path)
            disks[name] = dict(total=usage.total, free=usage.free)
        except OSError:
            disks[name] = None
    events = {}
    for line in read_text(proc / 'self/cgroup').splitlines():
        if not line.startswith('0::/'):
            continue
        relative = Path(line[4:])
        if relative.is_absolute() or '..' in relative.parts:
            continue
        current = cgroup / relative
        depth = 0
        while True:
            values = counters(current / 'memory.events',
                              ('low', 'high', 'max', 'oom', 'oom_kill', 'oom_group_kill'))
            if values is not None:
                events['self' if depth == 0 else f'ancestor-{depth}'] = values
            if current == cgroup:
                break
            current = current.parent
            depth += 1
    return dict(memory_kib=memory, disk_bytes=disks, cgroup_memory_events=events or None,
                pressure={name: pressure(proc / 'pressure' / name) for name in ('cpu', 'memory', 'io')})


class Diagnostics:
    def __init__(self, stage, directory):
        self.stage = stage
        self.stream = None
        self.bytes_written = 0
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.stream = (directory / (stage + '.jsonl')).open('w')
        except OSError:
            print('Verification diagnostics file unavailable; continuing with job output.', file=sys.stderr)

    def emit(self, event, **fields):
        # Only explicitly selected counters and metadata enter this record.
        record = dict(time=datetime.now(timezone.utc).isoformat(), stage=self.stage, event=event, **fields)
        try:
            record.update(snapshot())
        except (OSError, ValueError):
            record['metrics_unavailable'] = True
        line = json.dumps(record, sort_keys=True) + '\n'
        try:
            print('[verify-diagnostics] ' + line, end='', flush=True)
        except OSError:
            pass
        if self.stream is not None and (self.bytes_written < MAX_LOG_BYTES or event == 'finish'):
            try:
                self.stream.write(line)
                self.stream.flush()
                self.bytes_written += len(line.encode())
            except OSError:
                self.close()

    def close(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass
            self.stream = None


def observe(stage, directory, command):
    diagnostics = Diagnostics(stage, directory)
    received = []
    previous = {}
    child = None
    forwarded = 0
    code = 1

    def interrupted(signum, _frame):
        received.append(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.signal(signum, interrupted)
        diagnostics.emit('start', architecture=platform.machine())
        if received:
            code = 128 + received[0]
            return code
        child = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        next_sample = time.monotonic() + INTERVAL
        while True:
            while forwarded < len(received):
                signum = received[forwarded]
                try:
                    os.killpg(child.pid, signum)
                except ProcessLookupError:
                    pass
                forwarded += 1
                diagnostics.emit('signal', signal=signum)
            status = child.poll()
            if status is not None:
                code = status if status >= 0 else 128 - status
                if received and code == 0:
                    code = 128 + received[0]
                break
            now = time.monotonic()
            if now >= next_sample:
                diagnostics.emit('sample')
                next_sample = now + INTERVAL
            time.sleep(0.1)
    except OSError as error:
        # Log only the errno, never environment, command arguments or file content.
        print(f'Cannot run verification stage (errno {error.errno}).', file=sys.stderr)
        code = 127
    finally:
        diagnostics.emit('finish', exit_code=code)
        diagnostics.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--entered', action='store_true', help='Observe an already provisioned environment')
    args = parser.parse_args()
    directory = Path(os.environ['RUNNER_TEMP']) / 'assbox-verification' if os.environ.get('RUNNER_TEMP') else ROOT / 'reports/verification'
    command = ['scripts/verify', args.stage] if args.entered else ['nix', 'develop', '.#release-check', '--no-update-lock-file', '--no-write-lock-file', '--command', 'scripts/verify', args.stage]
    return observe(args.stage, directory, command)


if __name__ == '__main__':
    sys.exit(main())
