"""Validate an actual ZIP in a relocated environment. Never calls a model provider."""
import hashlib,json,shutil,subprocess,tempfile,zipfile
from pathlib import Path
from src.execution.bundle.freeze import verify

def relocate(record,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    archive=Path(record['archive'])
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=record['archiveSha256']:raise ValueError('Export archive changed')
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path=Path(info.filename)
            if path.is_absolute() or '..' in path.parts or path.parts[0]!='harness' or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive entry')
        z.extractall(destination)
    project=destination/'harness';bundle=verify(project)
    if bundle['id']!=record['bundleId']:raise ValueError('Export identity mismatch')
    with (destination/'installation.log').open('w') as log:
        subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=project,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        subprocess.run(['node','install-runner.mjs'],cwd=project,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
        logs=destination/'assembly';logs.mkdir()
        subprocess.run(['node',str(project/'src/execution/bundle/check.mjs'),str(project),str(logs)],cwd='/tmp',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
        # The clean Docker context includes exported sources only; no host modules or repository mounts.
        with tempfile.TemporaryDirectory(prefix='phyexp-export-check-') as temporary:
            context=Path(temporary)
            for relative in [*bundle['files'],'bundle.json']:
                target=context/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(project/relative,target)
            dockerfile='''FROM python:3.13-slim
COPY --from=node:24.13.0-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:24.13.0-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /relocated project
COPY package.json package-lock.json requirements.lock ./
RUN npm ci --ignore-scripts --no-audit --no-fund && pip install --require-hashes -r requirements.lock
COPY . .
WORKDIR /unrelated
'''
            # Optional exact-lock cache from an earlier clean installation; sources are always replaced.
            lock_hashes={f:hashlib.sha256((project/f).read_bytes()).hexdigest() for f in ['package-lock.json','requirements.lock']}
            probe="import hashlib,json;from pathlib import Path;print(json.dumps({f:hashlib.sha256((Path('/relocated project')/f).read_bytes()).hexdigest() for f in ['package-lock.json','requirements.lock']}))"
            cached=subprocess.run(['docker','run','--rm','--network','none','phyexp-relocation:h0','python','-c',probe],capture_output=True,text=True,timeout=30)
            reused=cached.returncode==0 and json.loads(cached.stdout)==lock_hashes
            if reused:dockerfile="FROM phyexp-relocation:h0\nRUN rm -rf '/relocated project'\nWORKDIR /relocated project\nCOPY . .\nRUN npm ci --ignore-scripts --no-audit --no-fund\nWORKDIR /unrelated\n"
            (context/'Dockerfile').write_text(dockerfile);(context/'.dockerignore').write_text('Dockerfile\n.dockerignore\n')
            tag='phyexp-relocation:export-'+bundle['id'][:16]
            subprocess.run(['docker','build','-t',tag,str(context)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
        script="import sys,json;sys.path.insert(0,'/relocated project');from src.execution.adapters.quantum_harbor import agent;from src.execution.bundle.freeze import verify;assert agent.__file__.startswith('/relocated project/');print(json.dumps({'agent':agent.__file__,'bundleId':verify('/relocated project')['id']}))"
        result=json.loads(subprocess.check_output(['docker','run','--rm','--network','none',tag,'python','-c',script],text=True,timeout=30))
        node=subprocess.check_output(['docker','run','--rm','--network','none',tag,'node','--input-type=module','-e',"import {createRequire} from 'node:module';const r=createRequire('/relocated project/package.json');const p=r.resolve('@deepseek-ai/dsh-llm');if(!p.startsWith('/relocated project/node_modules/'))throw Error('external dependency');console.log(p);"],text=True,timeout=30).strip()
    proof={'status':'passed','exportId':record['id'],'bundleId':bundle['id'],'archiveSha256':record['archiveSha256'],
        'relocationValidation':'passed','realValidation':'not_run','modelCalls':0,'fakeProvider':str(logs/'assembly.json'),
        'python':result,'node':node,'cachedPythonLockVerified':reused,'originalRepositoryMounted':False}
    file=destination/'validation.json';file.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    return {**proof,'evidence':str(file)}
