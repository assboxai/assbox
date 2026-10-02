# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual private-display substrate probe; no agent or provider authentication."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

assert os.geteuid() == 1000
assert os.environ['DISPLAY'] == ':90'
assert 'WAYLAND_DISPLAY' not in os.environ and 'SSH_AUTH_SOCK' not in os.environ
assert os.environ['DBUS_SESSION_BUS_ADDRESS'].startswith('unix:')
auth = Path(os.environ['XAUTHORITY'])
assert auth.is_file() and auth.stat().st_mode & 0o777 == 0o600
root = Path('/home/agent')
xdotool, ffmpeg, xmessage = sys.argv[1:]
window = subprocess.Popen([xmessage, '-bg', 'blue', '-geometry', '300x200+10+10', 'Assbox private display'])
try:
    time.sleep(1)
    subprocess.run([xdotool, 'mousemove', '100', '150'], check=True)
    location = subprocess.check_output([xdotool, 'getmouselocation'], text=True)
    assert 'x:100 y:150' in location
    subprocess.run([ffmpeg, '-nostdin', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1280x800',
                    '-i', ':90', '-frames:v', '1', '-y', str(root / 'capture.png')], check=True, timeout=15)
    (root / 'display-result.json').write_text(json.dumps({'pid': os.getpid(), 'auth': str(auth), 'location': location}))
    while True:
        signal.pause()
finally:
    window.terminate()
    window.wait(timeout=5)
