#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture raw working source and create an independent clean Git identity."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 16 * 1024 * 1024
MAX_TREE = 128 * 1024 * 1024


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(root, *args, data=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_CONFIG_COUNT='0', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    return subprocess.check_output(['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null',
        '-c', 'core.fsmonitor=false', '-c', 'core.autocrlf=false', '-C', str(root), *args],
        env=env, input=data, stderr=subprocess.PIPE)


def safe_path(name):
    if (not name or name.startswith('/') or '\\' in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(p in ('', '.', '..', '.git') for p in name.split('/'))):
        raise ValueError('unsafe source path')
    name.encode('utf-8', errors='strict')
    return name


def admitted_new(name):
    safe_path(name)
    return not any(p in {'.chainman', '.cache', 'target', 'reports', '__pycache__', 'node_modules',
                        '.direnv', '.wrangler', '.ssh', '.aws', '.gnupg', '.config'} for p in name.split('/')) and not name.endswith(
                        ('.pem', '.qcow2', '.img', '.pyc')) and not Path(name).name.startswith(('.dev.vars', '.env'))


def read_raw(root, name):
    path = root / safe_path(name)
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('source parent is a symlink')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE:
            raise ValueError('source must be a bounded ordinary independent file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_FILE + 1)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(path.stat(follow_symlinks=False)) != identity(after) or len(raw) > MAX_FILE:
            raise ValueError('source changed while reading')
        return ('100755' if before.st_mode & 0o111 else '100644', raw)
    finally:
        os.close(fd)


def capture(root, include_new=()):
    root = Path(root).resolve()
    entries = git(root, 'ls-files', '--stage', '-z').split(b'\0')
    names = set()
    for entry in filter(None, entries):
        metadata, path = entry.split(b'\t', 1)
        mode, oid, stage = metadata.split()
        if stage != b'0' or mode not in (b'100644', b'100755'):
            raise ValueError('unsupported or unmerged source index')
        names.add(safe_path(path.decode('utf-8')))
    flags = git(root, 'ls-files', '-v', '-z').split(b'\0')
    if any(item and (item[:1].islower() or item[:1] == b'S') for item in flags):
        raise ValueError('hidden source index flags')
    head = git(root, 'ls-tree', '-r', '-z', 'HEAD').split(b'\0')
    for item in filter(None, head):
        metadata, path = item.split(b'\t', 1)
        if metadata.split()[0] not in (b'100644', b'100755'):
            raise ValueError('unsupported source tree mode')
        names.add(safe_path(path.decode('utf-8')))
    untracked = {p.decode('utf-8') for p in filter(None,
        git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0'))}
    selected = set(include_new)
    if selected - untracked or any(not admitted_new(p) for p in selected):
        raise ValueError('new source inclusion is missing, ignored or prohibited')
    if untracked - selected:
        raise ValueError('explicit --include-new required: ' + ', '.join(sorted(untracked - selected)[:20]))
    names |= selected
    if any(not admitted_new(name) for name in names):
        raise ValueError('tracked cache, output or secret path is prohibited')
    files = {}
    for name in sorted(names):
        try:
            files[name] = read_raw(root, name)
        except FileNotFoundError:
            if name in selected:
                raise
    if sum(len(raw) for _, raw in files.values()) > MAX_TREE:
        raise ValueError('source inventory too large')
    records = manifest(files)
    for name, value in files.items():
        if read_raw(root, name) != value:
            raise ValueError('source drift')
    for name in names - set(files):
        if os.path.lexists(root / name):
            raise ValueError('deleted source reappeared during capture')
    if set(filter(None, git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))) != untracked:
        raise ValueError('source membership drift')
    if (git(root, 'ls-files', '--stage', '-z').split(b'\0') != entries
            or git(root, 'ls-files', '-v', '-z').split(b'\0') != flags
            or git(root, 'ls-tree', '-r', '-z', 'HEAD').split(b'\0') != head):
        raise ValueError('source Git inventory drift')
    return files, records


def manifest(files):
    return [{'path': p, 'mode': m, 'sha256': digest(raw)}
            for p, (m, raw) in sorted(files.items(), key=lambda i: i[0].encode())]


def materialize(files, destination, policy=None):
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    git(destination, 'init', '--quiet', '--object-format=sha1', '--template=')
    index = bytearray()
    for name, (mode, raw) in files.items():
        safe_path(name)
        if mode not in ('100644', '100755'):
            raise ValueError('invalid source mode')
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o755 if mode == '100755' else 0o644)
        oid = git(destination, 'hash-object', '--no-filters', '-w', '--stdin', data=raw).strip()
        index.extend(mode.encode() + b' ' + oid + b'\t' + name.encode() + b'\0')
    git(destination, 'update-index', '-z', '--index-info', data=bytes(index))
    tree = git(destination, 'write-tree').decode().strip()
    commit = (f'tree {tree}\nauthor Assbox Candidate <candidate@assbox.invalid> 946684800 +0000\n'
              'committer Assbox Candidate <candidate@assbox.invalid> 946684800 +0000\n\n'
              'Assbox verification snapshot v1\n').encode()
    oid = git(destination, 'hash-object', '-t', 'commit', '-w', '--stdin', data=commit).decode().strip()
    git(destination, 'update-ref', '--no-deref', 'HEAD', oid)
    if git(destination, 'status', '--porcelain'):
        raise ValueError('raw source is not clean under Git attributes')
    policy = policy or json.loads((ROOT / 'development/candidate-snapshot-policy.json').read_bytes())
    return dict(schema=1, kind='candidate-snapshot-identity', git_object_format='sha1', parents=[], publishable=False, protocol='assbox-candidate-snapshot-v1', policy_sha256=digest(canonical(policy)),
                source_content_sha256=digest(canonical(manifest(files))), git_tree_oid=tree,
                synthetic_commit_oid=oid)


def verify_files(root, files):
    for name, value in files.items():
        if read_raw(Path(root), name) != value:
            raise ValueError('source changed: ' + name)
