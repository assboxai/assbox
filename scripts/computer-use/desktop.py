#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execution-side display resource lease. Upstream agents own their tool loops."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import time


class Refusal(Exception):
    pass


SCRUB = {
    'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
    'AT_SPI_BUS_ADDRESS', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP',
    'DESKTOP_SESSION', 'SSH_AUTH_SOCK',
}


def clean_environment():
    return {k: v for k, v in os.environ.items() if k not in SCRUB}


def chromium_command(arguments, executable, profile, cache):
    """Only the selected browser owns this fresh profile and loopback endpoint."""
    protected = {
        '--user-data-dir', '--disk-cache-dir', '--profile-directory', '--password-store',
        '--remote-debugging-address', '--no-sandbox', '--disable-sandbox',
        '--disable-setuid-sandbox', '--disable-seccomp-filter-sandbox',
        '--single-process', '--no-zygote',
    }
    for argument in arguments:
        name, _, value = argument.partition('=')
        if name in protected or (name == '--headless' and value not in ('', 'new')):
            raise Refusal('browser profile, sandbox and listener are managed by Assbox')
        if name == '--remote-debugging-port' and (not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= 65535):
            raise Refusal('use --remote-debugging-port=0 or a valid loopback port')
    return [executable, '--headless=new', '--no-first-run',
            '--no-default-browser-check', '--disable-sync', '--password-store=basic',
            '--user-data-dir=' + str(profile), '--disk-cache-dir=' + str(cache),
            '--remote-debugging-address=127.0.0.1', *arguments]


def bus_address(process, cancelled):
    """Read a bounded readiness line while keeping the bus foreground-owned."""
    deadline = time.monotonic() + 5
    data = b''
    while time.monotonic() < deadline and not cancelled():
        if process.poll() is not None:
            raise Refusal('private session bus exited')
        if not select.select([process.stdout], [], [], .1)[0]:
            continue
        chunk = os.read(process.stdout.fileno(), 4097 - len(data))
        if not chunk:
            raise Refusal('private session bus did not report an address')
        data += chunk
        if len(data) > 4096:
            raise Refusal('private session bus address exceeded the limit')
        if b'\n' in data:
            address = data.split(b'\n', 1)[0].decode('ascii')
            if not address.startswith('unix:') or any(ord(c) < 32 for c in address):
                raise Refusal('private session bus reported an invalid address')
            return address
    raise Refusal('private session bus did not become ready')


def signal_groups(children, sig):
    # Signal groups even after a main process exits: its children may remain.
    for child in reversed(children):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass


def cleanup(children):
    signal_groups(children, signal.SIGTERM)
    deadline = time.monotonic() + 5
    for child in reversed(children):
        try:
            child.wait(timeout=max(.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    signal_groups(children, signal.SIGKILL)
    for child in children:
        child.wait()
        if child.stdout:
            child.stdout.close()


def run(mode, command, tools):
    if os.geteuid() != 1000:
        raise Refusal('computer use runs only as the unprivileged execution identity')
    if mode not in tools.get('modes', []):
        raise Refusal('this computer-use resource was not selected in configuration')
    if not command and mode != 'chromium':
        raise Refusal('supply an upstream command after --')
    runtime = Path('/run/user/1000')
    fd = os.open(runtime / 'assbox-computer-use.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    children = []
    stopping = False
    previous_handlers = {}

    def stop(*_):
        nonlocal stopping
        stopping = True
        signal_groups(children, signal.SIGTERM)

    def spawn(argv, *, infrastructure=False, stdout=None):
        if stopping:
            raise Refusal('computer use was cancelled')
        p = subprocess.Popen(argv, env=env, start_new_session=True,
                             stdin=subprocess.DEVNULL if infrastructure else None,
                             stdout=stdout, stderr=subprocess.DEVNULL if infrastructure else None)
        children.append(p)
        return p

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal('another execution desktop is active') from None
        env = clean_environment()
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, stop)
        with tempfile.TemporaryDirectory(prefix='assbox-desktop-', dir=runtime) as temporary:
            try:
                d = Path(temporary)
                d.chmod(0o700)
                if mode == 'chromium':
                    profile, cache = d / 'browser', d / 'cache'
                    profile.mkdir(mode=0o700)
                    cache.mkdir(mode=0o700)
                    command = chromium_command(command, tools['browser'], profile, cache)
                    env['XDG_CACHE_HOME'] = str(cache)
                if mode == 'display':
                    display = ':90'
                    socket_path = Path('/tmp/.X11-unix/X90')
                    if socket_path.exists() or Path('/tmp/.X90-lock').exists():
                        raise Refusal('private display number is occupied; never attach to an unrelated display')
                    auth = d / 'Xauthority'
                    auth.touch(mode=0o600)
                    subprocess.run([tools['xauth'], '-f', str(auth), 'add', display, '.', secrets.token_hex(16)],
                                   env=env, check=True, timeout=5, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    env.update(DISPLAY=display, XAUTHORITY=str(auth), XDG_SESSION_TYPE='x11')
                    screen = spawn([tools['xvfb'], display, '-screen', '0', '1280x800x24',
                                    '-auth', str(auth), '-nolisten', 'tcp', '-noreset'], infrastructure=True)
                    for _ in range(50):
                        if stopping or screen.poll() is not None:
                            raise Refusal('private X server stopped')
                        if socket_path.exists():
                            break
                        time.sleep(.1)
                    else:
                        raise Refusal('private display did not become ready')
                    bus = spawn([tools['dbus'], '--session', '--nofork', '--print-address=1'],
                                infrastructure=True, stdout=subprocess.PIPE)
                    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address(bus, lambda: stopping)
                    spawn([tools['wm']], infrastructure=True)
                app = spawn(command)
                while app.poll() is None and not stopping:
                    if any(child.poll() is not None for child in children[:-1]):
                        raise Refusal('private desktop resource failed; execution stopped')
                    time.sleep(.2)
                return app.returncode if app.poll() is not None else 130
            finally:
                cleanup(children)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['provider', 'display', 'browser', 'chromium'])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == '--' else args.command
    return run(args.mode, command, json.loads(Path('/etc/assbox/computer-use-tools.json').read_text()))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, Refusal, subprocess.SubprocessError) as error:
        print('Assbox computer use: ' + str(error), file=sys.stderr)
        sys.exit(78)
