"""Explicit real relocation acceptance with repositories/stores hidden by Linux mount namespaces.

Re-freezes a supplied Meta-authored source against the current trusted adapter,
records both identities, exports it, then uses only that exact exported bundle.
The strategy source is preserved; this is a separate platform-version validation,
not an extra sample in the original scientific comparison.
"""
import argparse,hashlib,json,os,shutil,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.execution.bundle.project import freeze_project
from src.execution.bundle.manifest import resolve
from src.exporting.project import export_project


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--build-cache',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--quantum-harbor',type=Path,required=True)
    parser.add_argument('--task',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--hide-path',type=Path,action='append',default=[])
    parser.add_argument('--podman-config',type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    origin=resolve(args.bundle);cfg=json.loads(args.config.read_text());assert args.task in cfg['tasks']
    assert origin.manifest['schemaVersion']==3
    recipe=json.loads(origin.asset('recipe.json').read_text())
    for key,value in cfg['solver'].items():assert recipe.get(key)==value,'Authorized Solver differs'
    source=out/'source';source.mkdir()
    modes=origin.manifest['buildReceipt'].get('inputs',{}).get('sourceModes',{})
    for name,file in origin.assets.items():
        if name.startswith('candidate/'):
            rel=name.removeprefix('candidate/');target=source/rel;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(file,target);target.chmod(modes.get(rel,0o644))
    with (out/'build.log').open('w') as log:
        frozen=freeze_project(ROOT,out/'objects',source,recipe,args.build_cache,log,recipe['processResources']['build'])
    assert frozen['manifest']['sources']==origin.manifest['sources'],'Strategy source changed'
    export=export_project(frozen['path'],out/'exports')
    relocated=out/'relocated';relocated.mkdir()
    with zipfile.ZipFile(export['archive']) as archive:archive.extractall(relocated)
    project=relocated/'harness';assert resolve(project).manifest['id']==frozen['id']
    environment={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV')}
    tools=out/'host-tools';tools.mkdir()
    if args.podman_config:
        # Declared host container-engine compatibility client; no original repo imports.
        shutil.copyfile(ROOT/'scripts/podman-single-uid.py',tools/'docker')
        (tools/'docker').chmod(0o755)
        environment['PHYEXP_PODMAN_CONFIG']=str(args.podman_config.resolve())
    with (out/'installation.log').open('w') as log:
        subprocess.run(['uv','venv','--python','3.13',str(out/'.venv')],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
        python=str(out/'.venv/bin/python')
        subprocess.run(['uv','pip','install','--python',python,'--require-hashes','-r',str(project/'requirements.lock')],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    environment['PATH']=str(out/'.venv/bin')+':'+str(tools)+':'+environment['PATH']
    lock=out/'task-lock.json';lock.write_text(json.dumps(cfg['taskImageLocks'][args.task]))
    hidden=sorted(set([ROOT.resolve(),args.bundle.resolve().parent,source,out/'objects',Path(export['path']).parent,*[p.resolve() for p in args.hide_path]]),key=str)
    hidden=[p for p in hidden if not any(p!=q and p.is_relative_to(q) for q in hidden)]
    assert all(not project.is_relative_to(p) and not args.quantum_harbor.resolve().is_relative_to(p) for p in hidden)
    isolated=['bwrap','--bind','/','/','--dev-bind','/dev','/dev']
    for path in hidden:
        if path.exists():isolated+=['--tmpfs',str(path)]
    prefix=[*isolated,'--']
    probe='import sys,json;from pathlib import Path;sys.path.insert(0,'+repr(str(project))+');import harbor,src.execution.adapters.quantum_harbor.process_agent as agent;hidden='+repr([str(p) for p in hidden])+';assert all(not any(Path(p).iterdir()) for p in hidden if Path(p).exists());print(json.dumps({"harbor":harbor.__file__,"adapter":agent.__file__,"hidden":hidden}))'
    proof=json.loads(subprocess.check_output([*prefix,python,'-c',probe],cwd=relocated,env=environment,text=True))
    subprocess.run([*prefix,python,str(project/'run.py'),'--verify'],cwd=relocated,env=environment,check=True,stdout=subprocess.DEVNULL)
    attempt={'originBundleId':origin.manifest['id'],'bundleId':frozen['id'],'candidateSources':frozen['manifest']['sources'],
        'originArtifact':origin.manifest['artifact'],'artifact':frozen['manifest']['artifact'],'originAdapter':origin.manifest['adapter'],'adapter':frozen['manifest']['adapter'],
        'export':export,'isolation':proof,'task':args.task,'startedAt':time.time(),'scope':'separate adapter and real relocation validation'}
    (out/'attempt.json').write_text(json.dumps(attempt,ensure_ascii=False,indent=2))
    with (out/'supervisor.log').open('w') as log:
        completed=subprocess.run([*prefix,python,str(project/'run.py'),'--quantum-harbor',str(args.quantum_harbor),
          '--task',args.task,'--task-image-lock',str(lock),'--output',str(out/'trial'),'--timeout','22000'],cwd=relocated,env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=22500)
    summary=json.loads((out/'trial/summary.json').read_text());assert summary['bundleId']==frozen['id']
    result={'status':'passed' if summary.get('officialReward') is not None else 'failed','bundleId':frozen['id'],
        'originBundleId':origin.manifest['id'],'officialReward':summary.get('officialReward'),'execution':summary.get('execution'),
        'scope':attempt['scope'],'isolation':proof,'archiveSha256':export['archiveSha256']}
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result))
    if result['status']!='passed':raise SystemExit(1)
if __name__=='__main__':main()
