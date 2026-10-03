#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native activation evidence and supervised launch. Account secrets are never persisted."""
import argparse,hashlib,json,math,os,re,selectors,signal,stat,subprocess,sys,time
from pathlib import Path
APPS={'chatgpt-desktop','claude-desktop'}
SURFACES={
 'chatgpt-desktop':{'codex-local','work-local','work-cloud-local-access','cloud-only','browser','computer-use','local-helpers','codex-ssh'},
 'claude-desktop':{'code-local','code-ssh','cowork','browser','local-helpers','connectors','provider-vm'},
}
class Refusal(Exception):pass
def trusted_json(path,owner=0):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or st.st_uid!=owner or st.st_mode&0o022 or st.st_size>65536:raise Refusal('untrusted or excessive policy record')
  with os.fdopen(fd,'r') as f:fd=None;return json.load(f)
 finally:
  if fd is not None:os.close(fd)
def scope(config):return hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def probe_observation(probe,row):
 env={'PATH':'/run/current-system/sw/bin','LANG':'C','ASSBOX_NATIVE_CLIENT':row['client'],'ASSBOX_NATIVE_MODE':row['mode'],'ASSBOX_NATIVE_REQUEST':json.dumps(row,sort_keys=True)}
 child=subprocess.Popen([str(probe)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,start_new_session=True)
 deadline=time.monotonic()+10;output=bytearray()
 try:
  with selectors.DefaultSelector() as selector:
   selector.register(child.stdout,selectors.EVENT_READ)
   while selector.get_map():
    remaining=deadline-time.monotonic()
    if remaining<=0:raise Refusal('native policy probe timed out')
    for key,_ in selector.select(remaining):
     chunk=os.read(key.fileobj.fileno(),8192)
     if not chunk:selector.unregister(key.fileobj);continue
     if len(output)+len(chunk)>65536:raise Refusal('native policy probe exceeded its output bound')
     output.extend(chunk)
  if child.wait(timeout=max(0.001,deadline-time.monotonic())):raise Refusal('native policy probe failed')
  return json.loads(output)
 finally:
  # Observers cannot leave privileged descendants behind after a timeout or exit.
  try:os.killpg(child.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  child.wait();child.stdout.close()
def check(app,config,root=Path('/run/assbox-native-policy')):
 row=config['apps'].get(app)
 if not row or not row.get('contract'):raise Refusal('native policy is not qualified for this client/account/platform; component stays staged')
 if (Path('/home/agent/.config/assbox/disabled')/app).exists():raise Refusal('native component was explicitly disabled')
 record=trusted_json(root/(app+'.json'))
 observed=record.get('observed')
 if type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=time.monotonic()-observed<=config['maximumAgeSeconds']:raise Refusal('native policy observation time is invalid or stale')
 if record.get('scope')!=scope(row) or record.get('state')!='verified' or record.get('boot')!=Path('/proc/sys/kernel/random/boot_id').read_text().strip() or time.monotonic()-record.get('observed',-1)>config['maximumAgeSeconds']:raise Refusal('native policy observations are missing, stale, or ineffective')
 return record

def status(app,config,requested=None,root=Path('/run/assbox-native-policy')):
 """Read current evidence only. Never run a probe, authenticate or authorize launch."""
 def result(state,reason):return {'app':app,'state':state,'reason':reason}
 row=config['apps'].get(app)
 if not row:return result('unavailable','application is not selected in the installed configuration')
 if requested is not None and requested not in {'none','managed-worker'}:raise Refusal('invalid requested native policy')
 if requested is not None and row['mode']!=requested:return result('stale','installed observations cover a different requested local-execution policy')
 if not row.get('contract'):return result('unavailable','no qualified contract for the exact installed client/account/platform')
 if (Path('/home/agent/.config/assbox/disabled')/app).exists():return result('unavailable','application was explicitly disabled')
 try:record=trusted_json(root/(app+'.json'))
 except FileNotFoundError:return result('pending','current native policy observations are not available yet')
 except (OSError,ValueError,Refusal):return result('ineffective','current native evidence cannot be trusted')
 if record.get('state')=='unsupported':return result('unavailable','installed contract is not qualified')
 if record.get('state')!='verified':return result('ineffective','current observations do not establish the requested policy')
 try:check(app,config,root)
 except (OSError,ValueError,TypeError,Refusal):return result('stale','observations are stale or no longer cover the installed scope')
 return result('verified','fresh observations cover the installed native policy; activation still checks independently')

def validate_observation(app,row,observation,qualification):
 contract=row['contract']
 expected={'app':app,'contract':contract['id'],'client':row['client'],'platform':row['platform'],'accountScopeDigest':contract['accountScopeDigest']}
 if any(qualification.get(k)!=v for k,v in expected.items()) or qualification.get('status')!='passed':raise Refusal('qualification does not bind this exact native client and account')
 if any(observation.get(k)!=v for k,v in expected.items()) or observation.get('policyRequestDigest')!=scope(row) or not observation.get('effectivePolicyDigest'):raise Refusal('incomplete or mismatched effective policy scope')
 if not re.fullmatch('[0-9a-f]{64}',str(observation.get('effectivePolicyDigest',''))):raise Refusal('invalid effective policy digest')
 surfaces=observation.get('surfaces',{})
 if set(surfaces)!=SURFACES[app]:raise Refusal('native surface inventory changed')
 required={'browser':'denied','local-helpers':'denied'}
 if app=='chatgpt-desktop':
  required.update({'codex-local':'denied','work-local':'denied','work-cloud-local-access':'denied','computer-use':'denied','cloud-only':'cloud-only' if row['cloud'] else 'denied','codex-ssh':'remote-only' if row['mode']=='managed-worker' else 'denied'})
 else:
  required.update({'code-local':'denied','code-ssh':'remote-only' if row['mode']=='managed-worker' else 'denied','cowork':'restricted' if row['localCowork'] else ('cloud-only' if row['cloud'] else 'denied'),'connectors':'cloud-only' if row['cloud'] else 'denied','provider-vm':'restricted' if row['localCowork'] else 'denied'})
  if row['localCowork']:
   vm=row.get('providerVmContract')
   if not vm:raise Refusal('local Cowork requires its separate provider VM contract')
   vm_qualification_path=Path(vm['qualification']).resolve(strict=True)
   if not str(vm_qualification_path).startswith('/nix/store/'):raise Refusal('provider VM qualification is not immutable')
   vm_qualification=trusted_json(vm_qualification_path)
   vm_expected={'app':app,'client':row['client'],'platform':row['platform'],'contract':vm['id'],'accountScopeDigest':vm['accountScopeDigest']}
   if vm_qualification.get('status')!='passed' or any(vm_qualification.get(k)!=v for k,v in vm_expected.items()):raise Refusal('provider VM qualification does not bind this client and entitlement')
   vm_probe=Path(vm['probe']).resolve(strict=True)
   if not str(vm_probe).startswith('/nix/store/'):raise Refusal('provider VM probe is not immutable')
   vm_observation=probe_observation(vm_probe,row)
   if any(vm_observation.get(k)!=v for k,v in vm_expected.items()) or vm_observation.get('policyRequestDigest')!=scope(row) or vm_observation.get('isolationVerified') is not True or vm_observation.get('entitlementVerified') is not True:raise Refusal('provider VM isolation or current entitlement is not verified')
 if any(surfaces.get(k)!=v for k,v in required.items()):raise Refusal('effective authority exceeds the selected native policy')

def refresh(config,root=Path('/run/assbox-native-policy')):
 if os.geteuid()!=0:raise Refusal('policy observation requires root')
 root.mkdir(mode=0o755,exist_ok=True)
 st=root.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=0o755:raise Refusal('unsafe native evidence directory')
 for app,row in config['apps'].items():
  state='unsupported';contract=row.get('contract');reason='no qualified native policy contract'
  if contract:
   try:
    probe=Path(contract['probe']).resolve(strict=True)
    if not str(probe).startswith('/nix/store/') or not contract.get('qualification'):raise Refusal('probe and qualification must come from reviewed immutable inputs')
    qualification_path=Path(contract['qualification']).resolve(strict=True)
    if not str(qualification_path).startswith('/nix/store/'):raise Refusal('mutable qualification is not trusted')
    qualification=trusted_json(qualification_path)
    observation=probe_observation(probe,row)
    validate_observation(app,row,observation,qualification)
    state='verified';reason='matching qualified native policy';
   except (OSError,ValueError,KeyError,subprocess.TimeoutExpired,Refusal):state='ineffective';reason='native policy probe could not establish the complete selected scope'
  record={'state':state,'reason':reason,'scope':scope(row),'observed':time.monotonic(),'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
  temporary=root/('.'+app+'.new');fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o644)
  with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
  os.replace(temporary,root/(app+'.json'))

def launch(app,config,args):
 if os.geteuid()!=1000:raise Refusal('native GUI runs only as the unprivileged controller account')
 check(app,config)
 child=subprocess.Popen([config['apps'][app]['client'],*args],start_new_session=True)
 def stop(*_):
  try:os.killpg(child.pid,signal.SIGTERM)
  except ProcessLookupError:pass
 for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,stop)
 try:
  while child.poll() is None:
   time.sleep(2)
   check(app,config)
  return child.returncode
 finally:
  stop()
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:
   os.killpg(child.pid,signal.SIGKILL);child.wait()
def main():
 a=argparse.ArgumentParser();a.add_argument('mode',choices=['refresh','check','launch','status']);a.add_argument('app',nargs='?',choices=sorted(APPS));a.add_argument('args',nargs=argparse.REMAINDER);args=a.parse_args()
 config=trusted_json(Path('/etc/assbox/native-policy.json').resolve(strict=True))
 if args.mode=='refresh':refresh(config);return 0
 if not args.app:raise Refusal('select a native application')
 if args.mode=='status':
  if len(args.args)>1:raise Refusal('status accepts only an optional requested policy')
  print(json.dumps(status(args.app,config,args.args[0] if args.args else None),sort_keys=True));return 0
 if args.mode=='check':print(check(args.app,config)['reason']);return 0
 return launch(args.app,config,args.args)
if __name__=='__main__':
 try:sys.exit(main())
 except (Refusal,OSError,ValueError,KeyError) as e:print('Assbox native policy: '+str(e),file=sys.stderr);sys.exit(78)
