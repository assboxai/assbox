# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapt the pinned QEMU module's image-builder interface to real SquashFS.

The complete tar stream comes from Nix's closureInfo. No files are filtered or
replaced. The guest mounts the output as SquashFS, through its declared virtio
serial, with the usual separate writable store overlay. This helper is used only
by disposable installer VMs; it is not a production filesystem tool.
"""
import os
from pathlib import Path
import stat
import sys


PREFIX = (
    '--quiet', '--force-uid=0', '--force-gid=0', '-L', 'nix-store',
    '-U', 'eb176051-bd15-49b7-9e6b-462e0b467019', '-T', '0',
    '--hard-dereference', '--tar=f',
)


def command(tool, arguments):
    if len(arguments) != len(PREFIX) + 1 or tuple(arguments[:-1]) != PREFIX:
        raise ValueError('unsupported pinned VM image-builder arguments')
    image = Path(arguments[-1])
    if image.name != 'store.img' or not image.is_absolute():
        raise ValueError('image must be the absolute disposable store.img path')
    # Refuse devices and redirects before the real formatter opens its output.
    # Restarts may replace only the same user's ordinary single-link image.
    if image.exists() or image.is_symlink():
        metadata = image.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid()):
            raise ValueError('existing image is not an owned regular file')
    return [tool, '-', str(image), '-tar', '-no-strip', '-comp', 'lz4',
            '-all-root', '-all-time', '0', '-mkfs-time', '0', '-noappend',
            '-no-duplicates',
            '-exit-on-error', '-processors', '1', '-mem', '256M',
            '-no-progress', '-quiet']


def formatter_environment():
    environment = os.environ.copy()
    # Nix sets SOURCE_DATE_EPOCH for builders. mksquashfs refuses it when the
    # explicit image and file timestamps above are also present, so keep the
    # adapter's reviewed timestamp policy authoritative at this boundary.
    environment.pop('SOURCE_DATE_EPOCH', None)
    return environment


if __name__ == '__main__':
    try:
        invocation = command(sys.argv[1], sys.argv[2:])
    except (IndexError, ValueError) as error:
        print(f'disposable offline image: {error}', file=sys.stderr)
        raise SystemExit(2)
    os.execve(invocation[0], invocation, formatter_environment())
