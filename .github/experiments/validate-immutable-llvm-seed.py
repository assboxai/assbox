#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import the independently verified LLVM package on the ephemeral ARM runner."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from zipfile import ZipFile

LOCK = 'ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
SEED_RUN = 45085837980
SEED_CONTROLLER = 'b8f812f0ab52b9a6c287ca6633394ead0b949d3f'
SEED_SOURCE = 'c2d872c72ee0478f19e2ca28312deeaf77b446f6'
SEED_TREE = '91c656ad4debdb00c907c8d9147e058f5d3939ea'
SIZE_LIMIT = 4 * 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def extract(archive, directory, cache_tools):
    with ZipFile(archive) as package:
        members = package.infolist()
        require(3 <= len(members) <= 1028, 'Unexpected seed artifact file count')
        seen = set()
        size = 0
        for item in members:
            path = PurePosixPath(item.filename)
            parts = path.parts
            require(not path.is_absolute() and '..' not in parts, 'Invalid seed member path')
            if parts and parts[0] == 'assbox-arm-llvm-seed-evidence':
                parts = parts[1:]
            if item.is_dir():
                require(not parts or parts == ('signed-cache',), 'Unexpected seed directory')
                continue
            is_index = parts == ('index.json',)
            require(parts not in seen and (is_index or (
                len(parts) == 2 and parts[0] == 'signed-cache' and re.fullmatch(cache_tools.ASSET, parts[1])
            )), 'Unexpected or duplicate seed member')
            require(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG), 'Unexpected seed member type')
            seen.add(parts)
            size += item.file_size
            limit = 2 * 1024**2 if is_index else cache_tools.MAX_ASSET
            require(0 < item.file_size <= limit and size <= SIZE_LIMIT, 'Oversized seed member')
            with package.open(item) as stream, directory.joinpath(*parts).open('xb') as output:
                shutil.copyfileobj(stream, output)


def validate_seed(download, directory, pinned, cache_tools):
    entries = list(download.iterdir())
    require(len(entries) == 1 and entries[0].is_file(), 'Unexpected seed download inventory')
    archive, = entries
    require(0 < archive.stat().st_size == pinned['sizeInBytes'] <= SIZE_LIMIT
            and pinned['transportDigest'] == 'sha256:' + cache_tools.file_digest(archive),
            'Seed archive size or digest differs from the independently verified artifact')
    cache = directory / 'signed-cache'
    cache.mkdir(mode=0o700)
    extract(archive, directory, cache_tools)
    raw = cache_tools.bounded(directory / 'index.json', 2 * 1024**2)
    require(sha256(raw).hexdigest() == pinned['indexSha256'], 'Unexpected seed manifest digest')
    index = cache_tools.decoded(raw)
    require(cache_tools.encoded(index) == raw and index['schema'] == 1
            and index['kind'] == 'assbox-native-arm-llvm-store-seed' and index['runId'] == SEED_RUN
            and index['workflow'] == SEED_CONTROLLER and index['attempt'] == 1 and index['source'] == SEED_SOURCE
            and index['tree'] == SEED_TREE and index['lockSha256'] == LOCK and index['architecture'] == 'aarch64-linux'
            and re.search(r'\bLLVM version 21\.1\.8\b', index['nativeVersion']) and index['testedColdCorrectAndWrongKeys'] is True
            and index['publicKey'] == pinned['publicKey']
            and re.fullmatch(rf'assbox-arm-llvm-seed-{SEED_RUN}:[A-Za-z0-9+/]{{43}}=', index['publicKey']),
            'Unexpected signed ARM seed provenance')
    require({key: index[key] for key in ('derivation', 'outputs')} == pinned['package'],
            'Signed seed package and candidate inputs differ')
    cache_tools.validate_cache(cache, index)
    return index, cache
