# SPDX-License-Identifier: GPL-3.0-or-later
"""Disposable VM controller for the installer's explicit, same-process retry."""
import errno
import os
from pathlib import Path
import pty
import select
import sys

root = Path('/var/lib/assbox-acceptance')
pid, terminal = pty.fork()
if pid == 0:
    os.execv(sys.argv[1], [sys.argv[1], '--ignored', '--exact', 'acceptance::install_apply', '--nocapture'])
tail = b''
with (root / 'terminal.log').open('wb', buffering=0) as log:
    while True:
        if select.select([terminal], [], [], 0.1)[0]:
            try:
                data = os.read(terminal, 4096)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not data:
                break
            log.write(data)
            tail = (tail + data)[-1024:]
            if b'Retry this exact build after correcting the problem? [y/N]:' in tail:
                (root / 'retry-ready').touch()
                tail = b''
        answer = root / 'retry-answer'
        if answer.exists():
            os.write(terminal, answer.read_bytes())
            answer.unlink()
os.close(terminal)
_, status = os.waitpid(pid, 0)
(root / 'terminal-status').write_text(str(os.waitstatus_to_exitcode(status)))
