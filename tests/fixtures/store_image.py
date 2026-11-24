# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapt the pinned QEMU module's image-builder interface to real SquashFS.

The complete tar stream comes from Nix's closureInfo. No files are filtered or
replaced. The guest mounts the output as SquashFS, through its declared virtio
serial, with the usual separate writable store overlay. This helper is used only
by disposable installer VMs; it is not a production filesystem tool.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


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


TAR_PREFIX = (
    '--create', '--absolute-names', '--verbatim-files-from',
    '--transform', 'flags=rSh;s|/nix/store/||',
    '--transform', r'flags=rSh;s|~nix~case~hack~[[:digit:]]\+||g',
    '--files-from',
)


def receipt_path(image):
    return image.with_suffix('.receipt.json')


def image_identity(image, closure):
    data = image.lstat()
    if (not stat.S_ISREG(data.st_mode) or data.st_uid != os.getuid()
            or data.st_nlink != 1 or data.st_mode & 0o222 or not data.st_size):
        raise ValueError('completed image must be an owned read-only regular file')
    return {
        'closure': closure,
        'device': data.st_dev,
        'inode': data.st_ino,
        'size': data.st_size,
        'ctime_ns': data.st_ctime_ns,
    }


def reusable(image, closure):
    try:
        with os.fdopen(os.open(receipt_path(image), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)) as receipt:
            if not stat.S_ISREG(os.fstat(receipt.fileno()).st_mode):
                return False
            return json.loads(receipt.read(2048)) == image_identity(image, closure)
    except (OSError, ValueError):
        return False


def run_tar(closure, tool, arguments, environment):
    directory = Path(environment.get('TMPDIR', ''))
    if (environment.get('USE_TMPDIR') == '1' and directory.is_absolute()
            and tuple(arguments) == (*TAR_PREFIX, closure)
            and reusable(directory / 'store.img', closure)):
        return
    os.execve(tool, [tool, *arguments], environment)


def run_image(closure, tool, arguments):
    invocation = command(tool, arguments)
    image = Path(arguments[-1])
    if reusable(image, closure):
        if sys.stdin.buffer.read(1):
            raise ValueError('unexpected input for the reusable image')
        print('Reusing completed read-only Nix store image.', flush=True)
        return

    receipt_path(image).unlink(missing_ok=True)
    if image.exists():
        image.chmod(0o600)
    subprocess.run(invocation, env=formatter_environment(), check=True)
    image.chmod(0o444)
    with tempfile.NamedTemporaryFile(mode='w', dir=image.parent, delete=False) as receipt:
        temporary = Path(receipt.name)
        try:
            json.dump(image_identity(image, closure), receipt)
            receipt.flush()
            temporary.replace(receipt_path(image))
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        operation, closure, tool, *arguments = sys.argv[1:]
        if operation == 'tar':
            run_tar(closure, tool, arguments, os.environ)
        elif operation == 'image':
            run_image(closure, tool, arguments)
        else:
            raise ValueError('unsupported pinned VM image-builder operation')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'disposable offline image: {error}', file=sys.stderr)
        raise SystemExit(2)
