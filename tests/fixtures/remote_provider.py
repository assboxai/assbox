#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Credential-free lifecycle fixture; never used by a production module."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

names = {
    'claude': 'claude-code-remote', 'cursor-agent': 'cursor-worker',
    'openclaw': 'openclaw-node', 'happy': 'happy-remote',
    'assbox-vscode': 'vscode-tunnel', 'claude-desktop': 'claude-desktop',
    'code': 'vscode', 'zeditor': 'zed', 'emacs': 'emacs',
}
name = names.get(Path(sys.argv[0]).name)
if os.environ.get('ASSBOX_TEST_ONBOARD') == '1' or name is None:
    # Onboarding can log in/configure/pair without running a daemon or network call.
    sys.exit(0)
state = Path.home() / 'lifecycle-fixture'
state.mkdir(mode=0o700, exist_ok=True)
with (state / (name + '.starts')).open('a') as stream:
    stream.write(str(time.monotonic()) + '\n')
mode_path = state / (name + '.mode')
mode = mode_path.read_text().strip() if mode_path.exists() else 'run'
print('TEST_PROVIDER_SECRET', flush=True)
if mode.startswith('exit'):
    sys.exit(int(mode[4:]))
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])
temporary = state / (name + '.pids.tmp')
temporary.write_text(json.dumps([os.getpid(), child.pid]))
temporary.replace(state / (name + '.pids'))
if mode == 'fork-exit':
    # Models a GUI launcher handing off to a long-lived child.
    sys.exit(0)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
while True:
    time.sleep(1)
