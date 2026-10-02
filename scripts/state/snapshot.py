#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private application-state checkpoints; OS rollback never implies data rollback."""
import argparse, fcntl, hashlib, resource, json, os, pwd, shutil, stat, subprocess, sys, tarfile, tempfile, time
from pathlib import Path
class Refusal(Exception): pass

def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)

def durable_json(path,record):
    temporary=path.with_name('.'+path.name+'.new')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as stream:
        json.dump(record,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path);sync_directory(path.parent)

def home_parent(name,account):
    descriptor=os.open('/home/agent',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in Path(name).parts[:-1]:
            try: child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part,0o700,dir_fd=descriptor)
                os.chown(part,account.pw_uid,account.pw_gid,dir_fd=descriptor,follow_symlinks=False)
                os.fsync(descriptor)
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        return descriptor
    except BaseException:
        os.close(descriptor);raise

def metadata(config):
    # Keep checkpoint identity with its local persistent state. The worker's
    # disposable root can acquire a new systemd machine ID after each restart.
    identity=checked_root(config)/'instance-id'
    try:
        descriptor=os.open(identity,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError: pass
    else:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(os.urandom(32));stream.flush();os.fsync(stream.fileno())
        sync_directory(identity.parent)
    descriptor=os.open(identity,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor,'rb') as stream:
        st=os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077 or st.st_size!=32: raise Refusal('Checkpoint identity is not a private local record')
        instance=stream.read(33)
    return {'schema':1,'machine':hashlib.sha256(instance).hexdigest(),
            'system':str(Path('/run/current-system').resolve()),'paths':config['paths'],
            'consistency':'managed services stopped; direct CLI sessions must be quiesced',
            'created':int(time.time())}

def checked_root(config):
    root=Path(config['directory'])
    for parent in root.parents:
        st=parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022: raise Refusal('Unsafe backup parent')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    st=root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=0o700: raise Refusal('Backup directory must be root-owned 0700')
    return root

def userctl(config,*args,check=True):
    env={'HOME':'/home/agent','XDG_RUNTIME_DIR':'/run/user/1000','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus','PATH':'/run/current-system/sw/bin'}
    return subprocess.run([config['runuser'],'-u','agent','--',config['systemctl'],'--user',*args],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60,check=check)

def backup(config):
    root=checked_root(config); active=[]
    free=shutil.disk_usage(root).free - config['reserveMiB']*1024*1024
    if free < 128*1024*1024: raise Refusal('Insufficient free space for a state checkpoint and recovery reserve')
    ceiling=min(free,config['maxArchiveMiB']*1024*1024)
    try:
        for unit in config['units']:
            if userctl(config,'is-active','--quiet',unit,check=False).returncode==0:
                active.append(unit); userctl(config,'stop',unit)
        # Do not let root read through execution-owned source paths. The archive
        # writer has the same privileges as the data's owner, while its output
        # descriptor is an already-open root-private file.
        name='snapshot-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+str(time.time_ns())
        stage=Path(tempfile.mkdtemp(prefix='.snapshot-',dir=root))
        try:
            selected=[p for p in config['paths'] if (Path('/home/agent')/p).exists()]
            with (stage/'state.tar').open('xb') as output:
                os.chmod(stage/'state.tar',0o600)
                subprocess.run([config['runuser'],'-u','agent','--',config['tar'],'--create','--file=-','--one-file-system','--directory=/home/agent',*([] if selected else ['--files-from=/dev/null']),'--',*selected],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.DEVNULL,timeout=config['timeoutSeconds'],check=True,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_FSIZE,(ceiling,ceiling)))
                output.flush(); os.fsync(output.fileno())
            record=metadata(config);record['archiveSha256']=digest(stage/'state.tar')
            durable_json(stage/'manifest.json',record)
            stage.rename(root/name);sync_directory(root)
            print(name+' (private; may contain credentials and provider data)')
        finally:
            if stage.exists(): shutil.rmtree(stage)
        snapshots=sorted(root.glob('snapshot-*'))
        for old in snapshots[:-config['retain']]:
            if old.is_dir() and not old.is_symlink(): shutil.rmtree(old)
    finally:
        for unit in active: userctl(config,'start',unit,check=False)

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def inspect(config,name):
    if not name.startswith('snapshot-') or '/' in name or '..' in name: raise Refusal('Select a snapshot name, not an arbitrary path')
    root=checked_root(config); snapshot=root/name
    for path in [snapshot,snapshot/'state.tar',snapshot/'manifest.json']:
        st=path.lstat()
        if st.st_uid!=0 or st.st_mode&0o077 or path.is_symlink(): raise Refusal('Snapshot ownership or permissions changed')
    record=json.loads((snapshot/'manifest.json').read_text())
    if record.get('schema')!=1 or record.get('machine')!=metadata(config)['machine'] or record.get('archiveSha256')!=digest(snapshot/'state.tar'): raise Refusal('Snapshot identity or integrity does not match this instance')
    if not set(record['paths'])<=set(config['paths']): raise Refusal('Restore selection changed; export and review data explicitly')
    return snapshot,record

def restore(config,name,apply):
    snapshot,record=inspect(config,name)
    if not apply:
        print(json.dumps(record,indent=2));print('Preview only. Close direct CLI sessions. Restore with --apply stops the execution user; keep an independent admin connection.');return
    subprocess.run([config['loginctl'],'terminate-user','1000'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            try:
                if entry.stat().st_uid==1000: raise Refusal('Execution processes remain; stop them before restoring state')
            except FileNotFoundError: pass
    root=checked_root(config);stage=Path(tempfile.mkdtemp(prefix='recovery-',dir=root))
    restored=stage/'restored';restored.mkdir(mode=0o700)
    account=pwd.getpwnam('agent')
    # The archive is local and root-private. Still reject devices and links;
    # restore never imports a copied account, worker identity or another HOME.
    with tarfile.open(snapshot/'state.tar') as archive:
        members=archive.getmembers()
        for member in members:
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or not any(member.name==p or member.name.startswith(p+'/') for p in record['paths']): raise Refusal('Unexpected archive path')
            if not (member.isfile() or member.isdir()): raise Refusal('Links/devices need explicit manual export; automatic restore refused')
        archive.extractall(restored,members=members,filter='data')
    journal={'snapshot':name,'moved':[],'installed':[],'operation':None,'state':'prepared'}
    def persist(): durable_json(stage/'journal.json',journal)
    persist()
    try:
        for name in record['paths']:
            source=restored/name
            if not source.exists(): continue
            parent=home_parent(name,account);leaf=Path(name).name
            try:
                old=stage/'previous'/name;old.parent.mkdir(parents=True,exist_ok=True)
                try: os.stat(leaf,dir_fd=parent,follow_symlinks=False);exists=True
                except FileNotFoundError: exists=False
                if exists:
                    journal['operation']={'path':name,'phase':'move-old'};persist()
                    os.rename(leaf,old,src_dir_fd=parent);os.fsync(parent);sync_directory(old.parent)
                    journal['moved'].append(name);journal['operation']=None;persist()
                directory=source.is_dir()
                journal['operation']={'path':name,'phase':'install'};persist()
                os.rename(source,leaf,dst_dir_fd=parent);os.fsync(parent);sync_directory(source.parent)
                journal['installed'].append(name);journal['operation']=None;persist()
                if directory:
                    for _,dirs,files,descriptor in os.fwalk(leaf,topdown=False,dir_fd=parent,follow_symlinks=False):
                        for item in files: os.chown(item,account.pw_uid,account.pw_gid,dir_fd=descriptor,follow_symlinks=False)
                        os.fchown(descriptor,account.pw_uid,account.pw_gid)
                else: os.chown(leaf,account.pw_uid,account.pw_gid,dir_fd=parent,follow_symlinks=False)
            finally: os.close(parent)
        journal['state']='restored';persist()
    except BaseException:
        journal['state']='needs-recovery';persist();raise
    print('State restored; execution remains stopped. Previous state and a recovery journal remain in '+stage.name+'. Review before restarting or deleting them.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['backup','list','restore']);parser.add_argument('name',nargs='?');parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if os.geteuid()!=0: raise Refusal('Application-state backups and restore require the owner')
    config=json.loads(Path('/etc/assbox/state.json').read_text());os.umask(0o077)
    descriptor=os.open(checked_root(config)/'operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.mode=='backup': backup(config)
    elif args.mode=='list':
        for path in sorted(checked_root(config).glob('snapshot-*')): print(path.name)
    elif args.name: restore(config,args.name,args.apply)
    else: raise Refusal('Select a snapshot name')
if __name__=='__main__':
    try: main()
    except (Refusal,OSError,ValueError,KeyError,subprocess.SubprocessError):
        print('Assbox state operation refused or incomplete; inspect root-private records. No state compatibility or credential migration is inferred from an OS rollback.',file=sys.stderr);sys.exit(78)
