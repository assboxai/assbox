"""Trusted temporary controller; finite compatibility evidence only."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

SOURCE = '8bedc753f862051d9a1ebc49a13c17b3933e80f9'
REF = 'refs/heads/test/canonical-finite-v60'


def candidate_environment(destination):
    environment = {key: os.environ[key] for key in
        ('PATH', 'LANG', 'LC_ALL', 'TZ', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE')
        if key in os.environ}
    home = destination / 'home'
    home.mkdir(mode=0o700)
    environment.update(HOME=str(home), XDG_CACHE_HOME=str(home / '.cache'),
        XDG_STATE_HOME=str(destination / 'state'),
        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
        GIT_CONFIG_COUNT='0', GIT_TERMINAL_PROMPT='0')
    return environment


def git(source, *args):
    return subprocess.check_output(['git', *args], cwd=source, text=True).strip()


def main():
    source, destination = (Path(arg).resolve() for arg in sys.argv[1:3])
    system = sys.argv[3]
    native = platform.machine() + '-linux'
    expected = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='assboxai/assbox',
        GITHUB_REPOSITORY_ID='1402455771', GITHUB_REPOSITORY_OWNER_ID='327835666',
        GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF=REF,
        RUNNER_ENVIRONMENT='github-hosted')
    if (platform.system() != 'Linux' or native != system or
        system not in ('x86_64-linux', 'aarch64-linux') or
        any(os.environ.get(key) != value for key, value in expected.items()) or
        git(source, 'rev-parse', 'HEAD') != SOURCE or git(source, 'status', '--porcelain=v1')):
        raise ValueError('finite controller source, native architecture or authority mismatch')
    if destination.parent != Path(os.environ['RUNNER_TEMP']).resolve() or destination.name != 'assbox-finite-checks':
        raise ValueError('unexpected external evidence directory')
    destination.mkdir(mode=0o700)
    environment = candidate_environment(destination)
    report = dict(schema=1, kind='native-finite-gates-not-full-verification',
        sourceCommit=SOURCE, sourceTree=git(source, 'rev-parse', 'HEAD^{tree}'),
        workflowCommit=os.environ['GITHUB_SHA'], workflowRef=REF,
        runId=int(os.environ['GITHUB_RUN_ID']), runAttempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
        architecture=native, cpuAffinity=sorted(os.sched_getaffinity(0)),
        isolation='cooperative same-user; not hostile-code isolation',
        fullVerifyQualified=False, gates=[], exitStatus=1,
        lockSha256={path:hashlib.sha256((source / path).read_bytes()).hexdigest()
            for path in ('flake.lock', 'chainman.lock', 'nix/dev/flake.lock', 'Cargo.lock')})
    try:
        for name, arguments in (
            ('setup', ['setup', '--no-hooks']),
            ('verify-lite', ['verify-lite']),
            ('verify-prepare', ['verify-prepare'])):
            command = ['nix', 'run', '--no-update-lock-file', '--no-write-lock-file',
                       'path:./nix/dev#just', '--', *arguments]
            record = dict(name=name, command=command, status='running')
            report['gates'].append(record)
            started = time.monotonic()
            print('Starting finite gate:', name, flush=True)
            with (destination / (name + '.log')).open('xb') as log:
                process = subprocess.Popen(command, cwd=source, env=environment,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
                try:
                    code = process.wait(timeout=3*60*60)
                except BaseException:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                    record.update(status='cancelled', daemonBuilderCleanup='not proven')
                    raise
            record.update(status='passed' if code == 0 else 'failed',
                exitStatus=code, seconds=round(time.monotonic()-started, 3))
            print('Completed finite gate:', name, 'exit', code, flush=True)
            if code:
                report['exitStatus'] = code
                return code
        report['exitStatus'] = 0
        return 0
    finally:
        report['sourceUnchanged'] = git(source, 'rev-parse', 'HEAD') == SOURCE
        report['worktreeClean'] = not git(source, 'status', '--porcelain=v1')
        current = {path:hashlib.sha256((source/path).read_bytes()).hexdigest()
                   for path in report['lockSha256']}
        report['locksUnchanged'] = current == report['lockSha256']
        if not (report['sourceUnchanged'] and report['worktreeClean'] and report['locksUnchanged']):
            report['exitStatus'] = 1
        report['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (destination / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
        print(json.dumps(report, sort_keys=True), flush=True)
        if report['exitStatus']:
            raise SystemExit(report['exitStatus'])


if __name__ == '__main__':
    raise SystemExit(main())
