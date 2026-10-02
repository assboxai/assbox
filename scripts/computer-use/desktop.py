#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execution-side display resource lease. Upstream agents own their tool loops."""
import argparse,fcntl,os,secrets,signal,socket,subprocess,sys,tempfile,time
from pathlib import Path
class Refusal(Exception):pass
SCRUB={'DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','AT_SPI_BUS_ADDRESS','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP','DESKTOP_SESSION','SSH_AUTH_SOCK'}
def clean_environment():return {k:v for k,v in os.environ.items() if k not in SCRUB}
def run(mode,command,tools):
 if os.geteuid()!=1000:raise Refusal('computer use runs only as the unprivileged execution identity')
 if not command:raise Refusal('supply an upstream command after --')
 runtime=Path('/run/user/1000');fd=os.open(runtime/'assbox-computer-use.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise Refusal('another execution desktop is active')
 env=clean_environment();children=[];stopping=False
 def stop(*_):
  nonlocal stopping
  stopping=True
  for child in reversed(children):
   try:os.killpg(child.pid,signal.SIGTERM)
   except ProcessLookupError:pass
 for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,stop)
 def spawn(argv,child_env=env):
  p=subprocess.Popen(argv,env=child_env,start_new_session=True,stdin=subprocess.DEVNULL if len(children)<2 and mode=='display' else None);children.append(p);return p
 try:
  with tempfile.TemporaryDirectory(prefix='assbox-desktop-',dir=runtime) as temporary:
   d=Path(temporary);d.chmod(0o700)
   if mode=='display':
    display=':90';socket_path=Path('/tmp/.X11-unix/X90')
    if socket_path.exists() or Path('/tmp/.X90-lock').exists():raise Refusal('private display number is occupied; never attach to an unrelated display')
    auth=d/'Xauthority';auth.touch(mode=0o600)
    subprocess.run([tools['xauth'],'-f',str(auth),'add',display,'.',secrets.token_hex(16)],check=True,stdout=subprocess.DEVNULL)
    env.update(DISPLAY=display,XAUTHORITY=str(auth),XDG_SESSION_TYPE='x11')
    screen=spawn([tools['xvfb'],display,'-screen','0','1280x800x24','-auth',str(auth),'-nolisten','tcp','-noreset'])
    for _ in range(50):
     if screen.poll() is not None:raise Refusal('private X server exited')
     if socket_path.exists():break
     time.sleep(.1)
    else:raise Refusal('private display did not become ready')
    # Private session bus: no physical controller accessibility or keyring bus.
    bus=subprocess.run([tools['dbus'],'--session','--print-address','--print-pid','--fork'],env=env,capture_output=True,text=True,check=True)
    lines=bus.stdout.splitlines();env['DBUS_SESSION_BUS_ADDRESS']=lines[0];bus_pid=int(lines[1]);
    spawn([tools['wm']])
   else:bus_pid=None
   app=spawn(command)
   while app.poll() is None and not stopping:
    if mode=='display' and children[0].poll() is not None:raise Refusal('private display failed; execution stopped')
    time.sleep(.2)
   return app.wait() if app.poll() is not None else 130
 finally:
  stop()
  for child in reversed(children):
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:
    os.killpg(child.pid,signal.SIGKILL);child.wait()
  if 'bus_pid' in locals() and bus_pid:
   try:os.kill(bus_pid,signal.SIGTERM)
   except ProcessLookupError:pass
  os.close(fd)
def main():
 import json
 a=argparse.ArgumentParser();a.add_argument('mode',choices=['provider','display','browser']);a.add_argument('command',nargs=argparse.REMAINDER);args=a.parse_args();command=args.command
 if command and command[0]=='--':command=command[1:]
 return run(args.mode,command,json.loads(Path('/etc/assbox/computer-use-tools.json').read_text()))
if __name__=='__main__':
 try:sys.exit(main())
 except (OSError,ValueError,Refusal,subprocess.SubprocessError) as e:print('Assbox computer use: '+str(e),file=sys.stderr);sys.exit(78)
