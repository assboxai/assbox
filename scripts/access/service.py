#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner lifecycle bridge: withdraw owned exposure before stopping its backend."""
import json, os, subprocess, sys
from pathlib import Path
AGENT = r'''
import json,os,subprocess,sys
from pathlib import Path
phase,action,id,systemctl,units=sys.argv[1:]
if os.geteuid()!=1000:raise SystemExit(78)
root=Path.home()/'.config/assbox/disabled';root.mkdir(mode=0o700,parents=True,exist_ok=True);marker=root/id
if phase=='prepare':
 fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write('disabled by owner\n')
elif action=='enable':
 marker.unlink(missing_ok=True)
 subprocess.run([systemctl,'--user','start',*json.loads(units)],check=True)
else:subprocess.run([systemctl,'--user','stop',*json.loads(units)],check=True)
'''
def main():
    if os.geteuid()!=0:raise ValueError('owner required')
    action,id=sys.argv[1:]
    if action not in ['stop','disable','enable']:raise ValueError('unknown action')
    cfg=json.loads(Path('/etc/assbox/service-control.json').read_text());units=cfg['units'].get(id)
    if not units:raise ValueError('no managed service for this selected component')
    env={'HOME':'/home/agent','XDG_RUNTIME_DIR':'/run/user/1000','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus','PATH':'/run/current-system/sw/bin'}
    def agent(phase):subprocess.run([cfg['runuser'],'-u','agent','--',cfg['python'],'-c',AGENT,phase,action,id,cfg['systemctl'],json.dumps(units)],env=env,stdin=subprocess.DEVNULL,check=True,timeout=90)
    if action!='enable':
        agent('prepare') # Revocation marker prevents a timer from republishing.
        if cfg.get('serve'):
            subprocess.run([cfg['serve'],'withdraw-component',id,'/etc/assbox/serve.json'],stdin=subprocess.DEVNULL,check=True,timeout=90)
    agent('apply')
    print(id+': '+action+'; setup, authentication and native qualification remain separate')
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError):
        print('Owner service action refused or incomplete. Owned exposure must be withdrawn before stopping a published backend.',file=sys.stderr);sys.exit(78)
