"""Actual export relocation, without mounting the development repository into the clean container."""
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.execution.bundle.freeze import freeze,verify
from src.exporting.project import export_project
from src.control.paths import data_dir

root=data_dir()/'development/m1/relocation'
root.mkdir(parents=True,exist_ok=True)
recipe=json.loads((ROOT/'recipes/h0-sol.json').read_text())
knowledge=json.loads((ROOT/'knowledge/plugin-sdk/reference/manifest.json').read_text())
plugin=root/'technical plugin';plugin.mkdir(exist_ok=True)
(plugin/'index.mjs').write_text((ROOT/'knowledge/plugin-sdk/examples/echo.mjs').read_text())
(plugin/'plugin.json').write_text(json.dumps({'schemaVersion':1,'name':'technical-echo','version':'1.0.0','entry':'index.mjs','purpose':'Technical load fixture',
 'configSchema':{'type':'object'},'dependencies':[],'observes':[],'intervenes':[],'capabilities':['tools','public-context','tool-results'],
 'fallbackBehavior':'Propagate errors','assets':[],'tools':['example_echo']}))
records=[]
for name,plugins in [('h0',[]),('technical',[{'path':str(plugin),'config':{'prefix':'fixture:'}}])]:
 bundle=freeze(ROOT,root/'bundles',recipe,plugins,knowledge)
 export=export_project(bundle['path'],root/'exports with spaces')
 project=Path(export['path'])
 subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=project,check=True)
 subprocess.run(['node','install-runner.mjs'],cwd=project,check=True)
 logs=root/(name+' assembly '+export['id']);logs.mkdir()
 subprocess.run(['node',str(project/'src/execution/bundle/check.mjs'),str(project),str(logs)],cwd='/tmp',check=True)
 # Python, Node and their dependencies install in a clean build context containing only this export.
 # This image is a validation environment, not the shipped Solver Runner.
 dockerfile=root/'Relocation.Dockerfile'
 dockerfile.write_text('''FROM python:3.13-slim
COPY --from=node:24.13.0-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:24.13.0-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /relocated project
COPY package.json package-lock.json requirements.lock ./
RUN npm ci --ignore-scripts --no-audit --no-fund && pip install --require-hashes -r requirements.lock
COPY . .
WORKDIR /unrelated
''')
 # Build context contains only exported files, never the original checkout or installed modules.
 import shutil,tempfile
 with tempfile.TemporaryDirectory(prefix='phyexp-relocation-') as temporary:
  context=Path(temporary)
  for relative in [*bundle['manifest']['files'],'bundle.json']:
   target=context/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(project/relative,target)
  # A previous successful clean installation can serve as a dependency layer after exact lock verification.
  import hashlib
  lock_hashes={f:hashlib.sha256((project/f).read_bytes()).hexdigest() for f in ['package-lock.json','requirements.lock']}
  probe="import hashlib,json;from pathlib import Path;print(json.dumps({f:hashlib.sha256((Path('/relocated project')/f).read_bytes()).hexdigest() for f in ['package-lock.json','requirements.lock']}))"
  cached=subprocess.run(['docker','run','--rm','--network','none','phyexp-relocation:h0','python','-c',probe],capture_output=True,text=True)
  if cached.returncode==0 and json.loads(cached.stdout)==lock_hashes:
   dockerfile.write_text("FROM phyexp-relocation:h0\nRUN rm -rf '/relocated project'\nWORKDIR /relocated project\nCOPY . .\nRUN npm ci --ignore-scripts --no-audit --no-fund\nWORKDIR /unrelated\n")
  shutil.copyfile(dockerfile,context/'Dockerfile')
  (context/'.dockerignore').write_text('Dockerfile\n.dockerignore\n')
  subprocess.run(['docker','build','-t','phyexp-relocation:'+name,str(context)],check=True)
 script="import sys,json;sys.path.insert(0,'/relocated project');from src.execution.adapters.quantum_harbor import agent;from src.execution.bundle.freeze import verify;assert agent.__file__.startswith('/relocated project/');print(json.dumps({'agent':agent.__file__,'bundleId':verify('/relocated project')['id']}))"
 output=subprocess.check_output(['docker','run','--rm','--network','none','phyexp-relocation:'+name,'python','-c',script],text=True)
 subprocess.run(['docker','run','--rm','--network','none','-e','DSH_HOME=/tmp/dsh','phyexp-relocation:'+name,'node','--input-type=module','-e',
  "import {createRequire} from 'node:module';const r=createRequire('/relocated project/package.json');if(!r.resolve('@deepseek-ai/dsh-llm').startsWith('/relocated project/node_modules/'))throw Error('external dependency');console.log(r.resolve('@deepseek-ai/dsh-llm'));"],check=True)
 export.update(relocationValidation='passed',relocationPython=json.loads(output),fakeProviderEvidence=str(logs/'assembly.json'))
 (project.parent/'export.json').write_text(json.dumps(export,indent=2)+'\n')
 records.append(export)
 (root/'results.json').write_text(json.dumps(records,indent=2)+'\n')
print(str(root/'results.json'))
