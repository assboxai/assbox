#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Remove the installer's persisted API credentials before candidate execution."""
import os
from pathlib import Path
import re
import stat
import tempfile

MAX_CONFIG = 256 * 1024


def sanitized(contents):
    if len(contents) > MAX_CONFIG:
        raise ValueError('Nix configuration exceeds the cleanup bound')
    lines = contents.decode('utf-8').splitlines(keepends=True)
    result = []
    continuation = False
    for line in lines:
        if re.match(r'^\s*!?include\s+', line):
            raise ValueError('Indirect Nix configuration requires separate cleanup review')
        credential = re.match(r'^\s*(?:extra-)?access-tokens\s*=', line)
        if credential or continuation:
            continuation = line.rstrip().endswith('\\')
            continue
        result.append(line)
    return (''.join(result).rstrip('\n') + '\naccess-tokens =\n').encode('utf-8')


def rewrite(path, owner):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != owner):
            raise ValueError('Unexpected Nix configuration ownership or file type')
        contents = sanitized(stream.read(MAX_CONFIG + 1))
    temporary_fd, temporary = tempfile.mkstemp(prefix='.assbox-nix-', dir=path.parent)
    try:
        with os.fdopen(temporary_fd, 'wb') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Credential cleanup requires the trusted runner administrator')
    rewrite('/etc/nix/nix.conf', 0)
