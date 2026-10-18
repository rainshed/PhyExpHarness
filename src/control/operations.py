"""Fixed development workspace tools. Model-supplied code runs only in bounded containers."""
import json
import os
import subprocess
import uuid
from pathlib import Path
from .store import Refused

MAX_FILE=2_000_000
MAX_WORKSPACE=16_000_000

def workspace_path(root,relative):
    root=Path(root).resolve();relative=Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:raise Refused('Workspace-relative path required')
    target=root/relative
    if not target.resolve().is_relative_to(root) or any(p.is_symlink() for p in [target,*list(target.parents)[:len(relative.parts)-1]]):
        raise Refused('Workspace path escapes its boundary')
    return target

def read_workspace(root,path):
    file=workspace_path(root,path)
    if file.is_dir():return {'files':[str(p.relative_to(root)) for p in sorted(file.rglob('*')) if p.is_file() and not p.is_symlink()][:500]}
    if file.stat().st_size>MAX_FILE:raise Refused('File too large')
    return {'path':path,'content':file.read_text()}

def write_workspace(root,path,content):
    if not isinstance(content,str) or len(content.encode())>MAX_FILE:raise Refused('Workspace file limit exceeded')
    target=workspace_path(root,path)
    size=sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file() and not p.is_symlink())
    if size+len(content.encode())-(target.stat().st_size if target.is_file() else 0)>MAX_WORKSPACE:raise Refused('Workspace limit exceeded')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content)
    return {'path':path,'bytes':target.stat().st_size}

def execute_workspace(root,command,image,seconds=30):
    if not isinstance(command,str) or not command or len(command)>32000:raise Refused('Invalid development command')
    name='phyexp-check-'+str(uuid.uuid4())
    args=['docker','run','--rm','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--pids-limit','64','--memory','512m','--cpus','1','--tmpfs','/tmp:rw,exec,nosuid,size=128m,mode=1777',
        '--mount',f'type=bind,source={Path(root).resolve()},target=/opt/phyexp/workspace,readonly','--workdir','/opt/phyexp/workspace',
        *[value for key in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'] for value in ['--env',key+'=']],
        '--entrypoint','sh',image,'-lc',command]
    # Direct argv; generated shell text is interpreted only inside the credential-free container.
    try:
        import tempfile
        with tempfile.TemporaryFile() as output:
            process=subprocess.Popen(args,stdout=output,stderr=subprocess.STDOUT)
            try:process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                subprocess.run(['docker','rm','-f',name],capture_output=True);process.wait(timeout=5)
                return {'exitCode':None,'reason':'check_timeout','output':'Development check exceeded its time limit'}
            output.seek(0);text=output.read(16001).decode(errors='replace')
            return {'exitCode':process.returncode,'output':text[:16000],'clipped':len(text)>16000,'workspaceReadOnly':True}
    finally:subprocess.run(['docker','rm','-f',name],capture_output=True)
