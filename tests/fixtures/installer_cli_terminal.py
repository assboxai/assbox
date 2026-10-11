# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded PTY dialogue for the ordinary production installer CLI."""
from __future__ import annotations
import codecs
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time

LABELS = [
    'Prepared empty ext4 root partition', 'Existing FAT EFI System Partition',
    'External backup partition (ext4/FAT/exFAT)', 'Hostname', 'Local timezone',
    'Platform: generic / macbookpro11-1 / macbookpro12-1',
    'What will this Assbox primarily do? assistant / coder / kiosk / custom',
    'Selected components, comma-separated; remove unwanted entries, none, or back',
    'Add all eight curated coding agents?', 'Use a managed worker for execution components?',
    'Presentation: headless / x11 / wayland', 'Install Tailscale support (enrollment happens separately)?',
    'Execution egress: internet / normal / offline', 'Execution computer use: none / browser / virtual-desktop',
    'Use this selection?', 'Enable Wi-Fi?', 'Enable audio and microphone devices?',
    'Enable camera devices?', 'Enable Bluetooth?', 'Allow suspend?',
    'Allow proprietary packages machine-wide (required by some components; persists after changing the selection)?',
    'Optional administrator SSH public key, or none',
    'Allow an external controller/editor/terminal to connect to the workload account over SSH?',
    'SSH exposure: tailscale / lan', 'Interfaces admitting SSH, comma-separated (confirm target names)',
    'Allowed source CIDRs, comma-separated, or none for any source on those interfaces',
    'Additional nixpkgs package attributes, comma-separated, or none',
]


class Dialogue:
    def __init__(self, inventory):
        required = {'root', 'esp', 'backup', 'target_by_id', 'admin_key'}
        if set(inventory) != required:
            raise ValueError('invalid canonical inventory fields')
        for name in ('root', 'esp', 'backup'):
            if not re.fullmatch(r'/dev/vd[a-z][1-9][0-9]*', inventory[name]):
                raise ValueError('inventory must resolve verified disposable by-id partitions')
        if (inventory['root'][:-1] != inventory['esp'][:-1]
                or inventory['backup'][:-1] == inventory['root'][:-1]
                or inventory['target_by_id'] != '/dev/disk/by-id/virtio-assbox-repair-target'
                or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+=*(?: [A-Za-z0-9._-]+)?', inventory['admin_key'])):
            raise ValueError('canonical device/key identity mismatch')
        phrase = 'INSTALL DISK ' + inventory['target_by_id'] + ' AS assbox-repair-vm'
        self.labels = LABELS + ['Type exactly: ' + phrase]
        self.answers = [inventory['root'], inventory['esp'], inventory['backup'], 'assbox-repair-vm',
            'UTC', 'generic', 'custom', 'none', 'n', 'n', 'headless', 'n', 'internet', 'none', 'y',
            'n', 'n', 'n', 'n', 'n', 'n', inventory['admin_key'], 'n', 'lan', 'eth1', '192.168.1.1/32', 'none', phrase]
        self.index = 0
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')

    def feed(self, raw):
        self.buffer = (self.buffer + self.decoder.decode(raw)).replace('\r\n', '\n')[-32768:]
        if re.search(r'(?:^|\n)(?:Retry|Try again|Retry the build).*\?[^\n]*: $', self.buffer):
            raise ValueError('in-process retry is a canonical installation failure')
        if self.index == len(self.labels):
            return None
        pattern = r'(?:^|\n)' + re.escape(self.labels[self.index]) + r'(?: \[[^\r\n]{0,512}\])?: $'
        if re.search(pattern, self.buffer):
            answer = self.answers[self.index]
            self.index += 1
            self.buffer = ''
            return answer + '\n'
        for label in self.labels:
            if re.search(r'(?:^|\n)' + re.escape(label) + r'(?: \[[^\r\n]{0,512}\])?: $', self.buffer):
                raise ValueError('unexpected wizard state W%02d' % (self.index + 1))
        if re.search(r'(?:^|\n)Type exactly: [^\n]+: $', self.buffer):
            raise ValueError('destructive confirmation does not identify intended disk')
        return None


def run(command, inventory, directory, prompt_seconds=120, total_seconds=10800):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    master, slave = pty.openpty()
    attributes = termios.tcgetattr(slave)
    attributes[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attributes)
    def terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    child = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                             preexec_fn=terminal, close_fds=True)
    os.close(slave)
    dialogue = Dialogue(inventory)
    start = time.monotonic()
    deadline = start + prompt_seconds
    total = 0
    status = 'failed'
    try:
        with (directory / 'installer-transcript.txt').open('wb') as transcript, (directory / 'phase-events.jsonl').open('w') as events:
            os.chmod(directory / 'installer-transcript.txt', 0o600)
            while True:
                now = time.monotonic()
                if now - start > total_seconds or (dialogue.index < 28 and now > deadline):
                    raise TimeoutError('wizard deadline W%02d' % (dialogue.index + 1))
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        raw = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        raw = b''
                    if not raw:
                        break
                    total += len(raw)
                    if total > 64 * 1024 * 1024:
                        raise ValueError('installer transcript exceeds retained bound')
                    transcript.write(raw); transcript.flush()
                    answer = dialogue.feed(raw)
                    if answer is not None:
                        events.write(json.dumps({'state': 'W%02d' % dialogue.index, 'status': 'answered', 'elapsed_seconds': now - start}) + '\n')
                        events.flush()
                        os.write(master, answer.encode())
                        deadline = time.monotonic() + prompt_seconds
                elif child.poll() is not None:
                    break
            code = child.wait(timeout=10)
            if code != 0 or dialogue.index != 28:
                raise ValueError('installer exit %d after %d/28 states' % (code, dialogue.index))
            status = 'passed'
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL); child.wait()
        os.close(master)
        (directory / 'terminal-summary.json').write_text(json.dumps({'status': status, 'states': dialogue.index,
            'exit_code': child.returncode, 'elapsed_seconds': time.monotonic() - start}) + '\n')


if __name__ == '__main__':
    inventory = json.loads(Path(sys.argv[2]).read_text())
    run([sys.argv[1], 'install', '--apply', '--release', 'r-1'], inventory, sys.argv[3])
