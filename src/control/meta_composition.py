"""Immutable, local trusted Meta compositions. This is provenance, not an experiment scheduler."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from .store import Refused, encoded

POLICY='stop-review-v1'
VERSION='meta-composition-v1'

def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()

def validate(manifest,root):
    if manifest.get('version')!=VERSION or not isinstance(manifest.get('plugins'),list):raise Refused('Unknown Meta composition')
    ids=set();enabled=[]
    for p in manifest['plugins']:
        if not isinstance(p,dict) or not isinstance(p.get('id'),str) or p['id'] in ids or p.get('scope') not in ['host','meta','reviewer']:raise Refused('Invalid Meta plugin identity/scope')
        ids.add(p['id']);module=p.get('module','')
        if Path(module).name!=module or not module.endswith('.mjs') or not (root/module).is_file() or (root/module).is_symlink():raise Refused('Meta plugin source unavailable')
        if type(p.get('enabled')) is not bool or not isinstance(p.get('config'),dict):raise Refused('Meta plugin enabled/config required')
        if p['enabled']:enabled.append(p)
    for p in enabled:
        for need in p.get('requires',[]):
            if need not in ['systemPrompt','tools','subagents'] and not any((q['id']==need or need in q.get('provides',[])) and q['scope'] in ['host',p['scope']] for q in enabled):raise Refused('Missing Meta plugin dependency: '+need)
    if not any('metaControl' in p.get('provides',[]) and p['scope']=='host' for p in enabled):raise Refused('Meta control service required')
    return manifest

def freeze(source,data,config):
    if config.get('metaCompositionConfig',{}).get('version')!=VERSION:
        from .meta_native_composition import freeze as freeze_native
        return freeze_native(source,data,config)
    from .meta_context import system_prompt
    source=Path(source);data=Path(data);plugin=source/'packages/meta-harness'
    manifest=validate(json.loads((plugin/'composition.json').read_text()),plugin)
    # A caller may select declarative settings, never an arbitrary host path or source upload.
    if config.get('metaCompositionConfig') is not None:manifest=validate(config['metaCompositionConfig'],plugin)
    system=system_prompt({**config,'stopPolicy':POLICY})
    reviewer=(plugin/'reviewer.md').read_text()
    files={}
    for root in [plugin,source/'src/execution']:
        for file in sorted(root.rglob('*')):
            if file.is_file() and not file.is_symlink() and '__pycache__' not in file.parts and 'node_modules' not in file.parts:
                files[file.relative_to(source).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    for rel in ['src/control/meta_worker.mjs','src/control/meta_gateway.mjs','package-lock.json']:
        files[rel]=hashlib.sha256((source/rel).read_bytes()).hexdigest()
    image=subprocess.run(['docker','image','inspect','phyexp-runner:0.2.1-rc.2','--format','{{.Id}}'],capture_output=True,text=True,timeout=30)
    if image.returncode or not image.stdout.strip().startswith('sha256:'):raise Refused('Meta Runner image unavailable')
    document={'version':VERSION,'composition':manifest,'files':files,'systemPrompt':system,'reviewerPrompt':reviewer,
              'runnerImage':image.stdout.strip(),'stopPolicy':POLICY,'reviewerModelPolicy':'inherit-meta',
              'lockSha256':files['package-lock.json'],'parentId':manifest.get('parentId'),
              'hostBoundary':'frozen trusted plugins; generated code runs in separate Runner'}
    id=digest(document);parent=data/'meta-compositions';parent.mkdir(parents=True,exist_ok=True);dest=parent/id
    if not dest.exists():
        temp=Path(tempfile.mkdtemp(dir=parent,prefix='.building-'))
        try:
            for rel in files:
                target=temp/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/rel,target)
            (temp/'manifest.json').write_text(encoded({**document,'id':id})+'\n')
            # Host dependencies are tied to this lock; runtime dependencies are in the immutable image.
            (temp/'node_modules').symlink_to(source/'node_modules',target_is_directory=True)
            try:os.rename(temp,dest)
            except FileExistsError:shutil.rmtree(temp)
        except BaseException:
            if temp.exists():shutil.rmtree(temp)
            raise
    verify(data,{'id':id},source)
    return {'id':id,'version':VERSION,'preset':manifest['id'],'parentId':manifest.get('parentId'),
            'runnerImage':document['runnerImage'],'lockSha256':document['lockSha256'],
            'plugins':manifest['plugins'],'stopPolicy':POLICY}

def verify(data,reference,source):
    id=reference['id']
    if len(id)!=64 or any(c not in '0123456789abcdef' for c in id):raise Refused('Invalid Meta composition identity')
    root=Path(data)/'meta-compositions'/id
    try:document=json.loads((root/'manifest.json').read_text())
    except (OSError,ValueError) as error:raise Refused('Frozen Meta composition missing; restoration refused') from error
    if document.get('version')=='meta-composition-v2':
        from .meta_native_composition import verify as verify_native
        return verify_native(data,reference,source)
    if document.get('id')!=id or digest({k:v for k,v in document.items() if k!='id'})!=id:raise Refused('Meta composition manifest changed')
    for rel,sha in document['files'].items():
        file=root/rel
        if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=sha:raise Refused('Frozen Meta source changed: '+rel)
    if hashlib.sha256((Path(source)/'package-lock.json').read_bytes()).hexdigest()!=document['lockSha256']:raise Refused('Meta host dependency lock changed; restore matching dependencies first')
    return root,document
