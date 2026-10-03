#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reconcile only Assbox-owned Serve paths; never enroll, reset Serve or enable Funnel."""
import argparse, fcntl, json, os, stat, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit
STATE = Path('/var/lib/assbox-serve')
class Refusal(Exception): pass

def command(binary, *args):
    if not isinstance(binary,str) or not binary:
        raise Refusal('Withdraw owned exposure while Tailscale is enabled before deselecting it')
    result = subprocess.run([binary, *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    if result.returncode or len(result.stdout) > 1024*1024:
        raise Refusal('Tailscale control is unavailable; owned exposure was not changed')
    return result.stdout

def paths(config):
    output = {}
    for item in config['mappings']:
        url = urlsplit(item['publicUrl'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise Refusal('Serve needs an exact HTTPS URL without credentials')
        path = url.path or '/'
        if not path.startswith('/') or any(c not in '/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in path):
            raise Refusal('Invalid Serve path')
        port = url.port or 443
        key = url.hostname + ':' + str(port) + path
        if key in output: raise Refusal('Duplicate owned Serve path')
        output[key] = {'host':url.hostname,'https':port,'path':path,'target':'http://127.0.0.1:'+str(item['port']),'component':item['component']}
    return output

def existing(status, item):
    return status.get('Web', {}).get(item['host']+':'+str(item['https']), {}).get('Handlers', {}).get(item['path'])

def persist(record, owned):
    fd,tmp=tempfile.mkstemp(dir=STATE,prefix='.owned-')
    with os.fdopen(fd,'w') as f:
        json.dump(owned,f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,record)
    fd=os.open(STATE,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def run(config, withdraw=False, component=None):
    if os.geteuid()!=0: raise Refusal('Only the owner may manage dashboard exposure')
    STATE.mkdir(mode=0o700, exist_ok=True)
    info=STATE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700: raise Refusal('Unsafe Serve state directory')
    lock=os.open(STATE/'lock', os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, 'w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        record=STATE/'owned.json'
        old={}
        if record.exists() or record.is_symlink():
            st=record.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077 or st.st_size>65536: raise Refusal('Unsafe Serve ownership record')
            old=json.loads(record.read_text())
        if component:
            desired={key:item for key,item in old.items() if item.get('component')!=component}
        else:
            desired={} if withdraw else paths(config)
            desired={key:item for key,item in desired.items() if not (Path('/home/agent/.config/assbox/disabled')/item['component']).exists()}
        if not old and not desired: return
        binary=config['tailscale']
        status=json.loads(command(binary, 'serve', 'status', '--json'))
        # Remove stale routes first. An owner-replaced route is left untouched.
        for key,item in list(old.items()):
            if desired.get(key)==item: continue
            current=existing(status,item)
            if current=={'Proxy':item['target']}:
                command(binary, 'serve', '--https='+str(item['https']), '--set-path='+item['path'], 'off')
            del old[key]
            persist(record,old)
        for key,item in desired.items():
            current=existing(status,item)
            if current and current!={'Proxy':item['target']}: raise Refusal('The requested path belongs to another owner-managed Serve mapping')
            if current and key not in old: raise Refusal('Existing Serve path is not owned by Assbox; choose a distinct path')
            if current!={'Proxy':item['target']}:
                # Never publish an unenrolled machine or the wrong tailnet name.
                daemon=json.loads(command(binary,'status','--json'))
                dns=daemon.get('Self',{}).get('DNSName','').rstrip('.')
                if daemon.get('BackendState')!='Running' or dns!=item['host']: raise Refusal('Enrollment and exact dashboard DNS name require owner setup')
                old[key]=item
                persist(record,old) # Journal ownership before the external mutation.
                command(binary, 'serve', '--bg', '--https='+str(item['https']), '--set-path='+item['path'], item['target'])
            old[key]=item
        persist(record,old)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=['reconcile','withdraw','withdraw-component']); parser.add_argument('arguments',nargs='+'); args=parser.parse_args()
    component=args.arguments[0] if args.mode=='withdraw-component' else None
    config=args.arguments[-1]
    if (component and len(args.arguments)!=2) or (not component and len(args.arguments)!=1):raise Refusal('invalid operation')
    run(json.loads(Path(config).read_text()),args.mode=='withdraw',component)
if __name__=='__main__':
    try: main()
    except (Refusal,OSError,ValueError,KeyError,subprocess.TimeoutExpired):
        print('Assbox Serve: exposure is setup-required or conflicts with owner state; inspect the redacted ownership record.',file=sys.stderr);sys.exit(78)
