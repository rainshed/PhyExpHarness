"""Actual isolated build contract; no model calls, credentials or task data."""
import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from src.execution.bundle.project import snapshot, build


def main():
    p=argparse.ArgumentParser(); p.add_argument('--image', required=True); p.add_argument('--output', type=Path, required=True)
    args=p.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    source=args.output/'source'; source.mkdir()
    spec={'runContract':'harbor-process-v1','entrypoint':['runtime/node','main.mjs'],
          'build':{'image':args.image,'argv':['/bin/sh','-c','mkdir -p runtime && cp "$(command -v node)" runtime/node && npm ci --no-audit --no-fund'], 'locks':['package-lock.json']}}
    package={'name':'isolated-build-contract','version':'1.0.0','scripts':{'postinstall':
        'node -e "if(process.env.PHYEXP_BUILD_SENTINEL)process.exit(9);require(\'fs\').writeFileSync(\'built.txt\',\'scripts ran without host credentials\')"'}}
    lock={'name':package['name'],'version':'1.0.0','lockfileVersion':3,'requires':True,'packages':{'':package}}
    for name,value in {'harness.json':spec,'package.json':package,'package-lock.json':lock}.items():
        (source/name).write_text(json.dumps(value))
    (source/'main.mjs').write_text('console.log("complete candidate")\n')
    os.environ['PHYEXP_BUILD_SENTINEL']='must-not-enter-build'
    resources=json.loads((ROOT/'schemas/execution/process-resources.json').read_text())['build']
    with (args.output/'build.log').open('w') as log:
        artifact,receipt=build(*snapshot(source),args.output/'cache',log,resources)
        second,reused=build(*snapshot(source),args.output/'cache',log,resources)
    assert receipt==reused and second==artifact
    with tarfile.open(artifact) as archive:
        names={m.name.removeprefix('./'):m for m in archive}
        assert archive.extractfile(names['built.txt']).read()==b'scripts ran without host credentials'
        assert names['runtime/node'].mode & 0o111
    (args.output/'validation.json').write_text(json.dumps({'status':'passed','receipt':receipt,'realModelCalls':0},indent=2))
    print(json.dumps({'status':'passed','artifact':str(artifact),'buildImage':receipt['inputs']['image'],'realModelCalls':0}))

if __name__=='__main__': main()
