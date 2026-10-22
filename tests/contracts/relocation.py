"""Shared installations and actual ZIP relocation; synthetic provider only."""
import json
import subprocess
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.execution.bundle.freeze import freeze
from src.execution.bundle.manifest import verify
from src.control.execution_cache import prepare_runtime
from src.control.runner_images import prepare_runner_image
from src.exporting.project import export_project
from src.exporting.validate import relocate

root=ROOT/'reports/development/meta-harness'/('plugin-versioning-'+uuid.uuid4().hex)
root.mkdir(parents=True)
recipe=json.loads((ROOT/'recipes/h0-sol.json').read_text())
knowledge=json.loads((ROOT/'knowledge/plugin-sdk/reference/manifest.json').read_text())
plugin=root/'technical plugin';plugin.mkdir()
(plugin/'index.mjs').write_text((ROOT/'knowledge/plugin-sdk/examples/echo.mjs').read_text())
(plugin/'plugin.json').write_text(json.dumps({'schemaVersion':1,'name':'technical-echo','version':'1.0.0','entry':'index.mjs','purpose':'Technical load fixture',
 'configSchema':{'type':'object'},'dependencies':[],'observes':[],'intervenes':[],'capabilities':['tools','public-context','tool-results'],
 'fallbackBehavior':'Propagate errors','assets':[],'tools':['example_echo']}))
records=[];runtime_paths=[];bundles=[]
for name,plugins in [('h0',[]),('technical',[{'path':str(plugin),'config':{'prefix':'fixture:'}}])]:
 bundle=freeze(ROOT,root/'objects',recipe,plugins,knowledge);bundles.append(bundle)
 runtime=prepare_runtime(bundle['path'],root/'cache');runtime_paths.append(runtime)
 logs=root/(name+' stored assembly');logs.mkdir()
 with (logs/'check.log').open('w') as log:
  prepare_runner_image(runtime,root/'runner-locks',log)
  subprocess.run(['node',str(runtime/'src/execution/bundle/check.mjs'),bundle['path'],str(logs)],cwd='/tmp',stdout=log,stderr=subprocess.STDOUT,check=True)
 subprocess.run([sys.executable,str(runtime/'run.py'),'--bundle',bundle['path'],'--verify'],cwd='/tmp',check=True)
 export=export_project(bundle['path'],root/'exports with spaces')
 # The actual ZIP must be sufficient: hide both the content store and expanded export.
 (root/'objects').rename(root/'hidden objects')
 expanded=Path(export['path']);expanded.rename(expanded.with_name('hidden expanded'))
 try:
  proof=relocate(export,root/(name+' relocated zip'))
 finally:
  (root/'hidden objects').rename(root/'objects')
  expanded.with_name('hidden expanded').rename(expanded)
 stored=json.loads((logs/'assembly.json').read_text())
 portable=json.loads(Path(proof['fakeProvider']).read_text())
 for field in ('bundleId','compositionId','framework','plugins'):
  assert stored[field]==portable[field],field
 assert verify(bundle['path'])['id']==proof['bundleId']
 export.update(proof);records.append(export)
 (root/'results.json').write_text(json.dumps(records,indent=2)+'\n')
assert runtime_paths[0]==runtime_paths[1], 'Candidate-specific runtime installation'
assert len(list((root/'cache/dependencies').glob('*.json')))==1
assert all({p.name for p in Path(b['path']).iterdir()}=={'bundle.json','recipe.json'} for b in bundles)
print(json.dumps({'results':str(root/'results.json'),'sharedRuntime':str(runtime_paths[0]),'dependencyInstallations':1,'modelCalls':0}))
