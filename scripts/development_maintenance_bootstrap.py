# SPDX-License-Identifier: GPL-3.0-or-later
# Copied verbatim into maintenance.yml's only writer step. No checkout or Action.
import base64
import hashlib
import json
import os
import re
import tempfile
import urllib.request

if os.environ.get('MAINTENANCE_READY') != 'provisioned-v1':
    raise SystemExit('administration-required: Environment readiness unavailable')
if (os.environ.get('MAINTENANCE_ENABLED') != 'enabled'
        or os.environ.get('REPOSITORY') != 'assboxai/assbox'
        or os.environ.get('REF') != 'refs/heads/master'
        or os.environ.get('EVENT') not in ('schedule', 'workflow_dispatch')):
    raise SystemExit('workflow admission refused')
base = os.environ['BASE']
if not re.fullmatch('[0-9a-f]{40}', base):
    raise SystemExit('invalid workflow base')

class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate API key')
        result[key] = value
    return result

def request(path):
    req = urllib.request.Request('https://api.github.com/repos/assboxai/assbox/git/' + path,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.build_opener(RejectRedirect()).open(req, timeout=30) as response:
        raw = response.read(4194305)
    if len(raw) > 4194304:
        raise ValueError('API response exceeds bound')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)

commit = request('commits/' + base)
if commit['sha'] != base:
    raise ValueError('workflow commit mismatch')

def trusted_blob(path):
    tree = commit['tree']['sha']
    parts = path.split('/')
    for index, part in enumerate(parts):
        entries = request('trees/' + tree)
        if entries.get('truncated'):
            raise ValueError('truncated trusted tree')
        matches = [entry for entry in entries['tree'] if entry['path'] == part]
        if len(matches) != 1:
            raise ValueError('trusted path unavailable')
        item = matches[0]
        if index < len(parts) - 1:
            if item['mode'] != '040000' or item['type'] != 'tree':
                raise ValueError('trusted directory mode')
            tree = item['sha']
        else:
            if item['mode'] != '100644' or item['type'] != 'blob':
                raise ValueError('trusted controller mode')
            blob = request('blobs/' + item['sha'])
            if blob['encoding'] != 'base64':
                raise ValueError('trusted blob encoding')
            raw = base64.b64decode(''.join(blob['content'].split()), validate=True)
            oid = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            if oid != item['sha'] or len(raw) != blob['size'] or len(raw) > 1048576:
                raise ValueError('trusted blob identity')
            return raw

controller = trusted_blob('scripts/development_maintenance_writer.py')
trusted_blob('development/maintenance-policy.json')
os.umask(0o077)
private = tempfile.mkdtemp(prefix='assbox-trusted-writer-', dir='/tmp')
os.chdir(private)
# Only the verified workflow-base source is executable. Artifacts remain JSON.
exec(compile(controller, 'trusted-base/development_maintenance_writer.py', 'exec'),
     {'__name__': '__main__'})
