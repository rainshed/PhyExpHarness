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
    package={'name':'isolated-build-contract','version':'1.0.0','dependencies':{'is-odd':'3.0.1'},'scripts':{'postinstall':
        'node -e "if(process.env.PHYEXP_BUILD_SENTINEL||!require(\'is-odd\')(3))process.exit(9);require(\'fs\').writeFileSync(\'built.txt\',\'scripts ran without host credentials\')"'}}
    lock={'name':package['name'],'version':'1.0.0','lockfileVersion':3,'requires':True,'packages':{'':package,
      'node_modules/is-odd':{'version':'3.0.1','resolved':'https://registry.npmjs.org/is-odd/-/is-odd-3.0.1.tgz','integrity':'sha512-CQpnWPrDwmP1+SMHXZhtLtJv90yiyVfluGsX5iNCVkrhQtU3TQHsUWPG9wkdk9Lgd5yNpAg9jQEo90CBaXgWMA==','dependencies':{'is-number':'^6.0.0'}},
      'node_modules/is-number':{'version':'6.0.0','resolved':'https://registry.npmjs.org/is-number/-/is-number-6.0.0.tgz','integrity':'sha512-Wu1VHeILBK8KAWJUAiSZQX94GmOE45Rg6/538fKwiloUu21KncEkYGPqob2oSZ5mUT73vLGrHQjKw3KMPwfDzg=='}}}
    for name,value in {'harness.json':spec,'package.json':package,'package-lock.json':lock}.items():
        (source/name).write_text(json.dumps(value))
    (source/'main.mjs').write_text('console.log("complete candidate")\n')
    os.environ['PHYEXP_BUILD_SENTINEL']='must-not-enter-build'
    resources=json.loads((ROOT/'schemas/execution/process-resources.json').read_text())['build']
    contents,spec=snapshot(source)
    with (args.output/'build.log').open('w') as log:
        artifact,receipt=build(*snapshot(source),args.output/'cache',log,resources)
        second,reused=build(*snapshot(source),args.output/'cache',log,resources)
    assert receipt==reused and second==artifact
    with tarfile.open(artifact) as archive:
        names={m.name.removeprefix('./'):m for m in archive}
        assert archive.extractfile(names['built.txt']).read()==b'scripts ran without host credentials'
        assert names['runtime/node'].mode & 0o111
    import time,subprocess,re
    with (args.output/'capacity.log').open('w') as log:
        try:build(contents,spec,args.output/'capacity-cache',log,{**resources,'artifactBytes':1024})
        except ValueError as error:assert 'capacity' in str(error)
        else:raise AssertionError('Oversized artifact was accepted')
    cancelled_spec={**spec,'build':{**spec['build'],'argv':['/bin/sh','-c','sleep 600']}}
    expires=time.monotonic()+2
    with (args.output/'cancel.log').open('w') as log:
        try:build(contents,cancelled_spec,args.output/'cancel-cache',log,resources,cancel=lambda:time.monotonic()>=expires)
        except InterruptedError:pass
        else:raise AssertionError('Cancelled build completed')
    for file in ('capacity.log','cancel.log'):
        names=re.findall(r'^Build container (phyexp-build-[a-f0-9]+)$',(args.output/file).read_text(),re.M)
        for name in names:
            assert subprocess.run(['docker','inspect',name],capture_output=True).returncode!=0,'Build container survived closeout'
    (args.output/'validation.json').write_text(json.dumps({'status':'passed','receipt':receipt,'realModelCalls':0},indent=2))
    print(json.dumps({'status':'passed','artifact':str(artifact),'buildImage':receipt['inputs']['image'],'realModelCalls':0}))

if __name__=='__main__': main()
