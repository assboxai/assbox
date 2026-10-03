#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Use the pinned upstream dry-run as a behavioral service compatibility oracle."""
import json, os, re, shlex, subprocess, sys

def verify(plan):
    if plan.get('platform')!='linux': raise ValueError('not a Linux service plan')
    files=plan.get('files',[])
    units=[row['content'] for row in files if row.get('path','').endswith('.service')]
    if len(units)!=1: raise ValueError('expected one foreground service')
    fields={}
    for line in units[0].splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);fields.setdefault(key,[]).append(value)
    if len(fields.get('ExecStart',[]))!=1: raise ValueError('ambiguous foreground command')
    argv=shlex.split(fields['ExecStart'][0])
    if argv[-3:]!=['daemon','start-sync','--takeover']: raise ValueError('foreground lifecycle changed')
    if fields.get('Restart')!=['on-failure']: raise ValueError('restart semantics changed')
    env=' '.join(fields.get('Environment',[]))
    for name in ['HAPPIER_DAEMON_STARTUP_SOURCE','HAPPIER_DAEMON_SERVICE_LABEL','HAPPIER_HOME_DIR']:
        if not re.search(r'\b'+name+r'=',env): raise ValueError('missing scoped environment contract')
    if 'background-service' not in env: raise ValueError('background service ownership changed')
    return argv

def main():
    binary=sys.argv[1]
    # This interface must neither install nor enable a provider-owned service.
    result=subprocess.run([binary,'daemon','service','install','--dry-run','--json'],stdin=subprocess.DEVNULL,capture_output=True,timeout=30,check=True)
    if len(result.stdout)>1024*1024: raise ValueError('excessive service plan')
    data=json.loads(result.stdout)
    verify(data.get('plan',data))
    paths=subprocess.run([binary,'daemon','service','paths'],stdin=subprocess.DEVNULL,capture_output=True,timeout=15,check=True)
    if len(paths.stdout)>65536: raise ValueError('excessive service paths')
    print('Pinned Happier foreground service contract is compatible; no vendor unit installed.')
if __name__=='__main__':main()
