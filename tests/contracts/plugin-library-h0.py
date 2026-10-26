"""Synthetic isolated H0 builds and exported loading, without model requests."""
import argparse,json,subprocess,sys,tarfile,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.service import ControlService
from src.control.h0 import defaults,materialize
from src.execution.bundle.project import freeze_project
from src.execution.bundle.manifest import resolve
from src.exporting.project import export_project
from tests.fixtures.benchmark_tasks import make_tasks

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    service=ControlService(ROOT,out/'data',make_tasks(out/'tasks',['time_budgeted_hamlearn_10q']),'http://127.0.0.1:1')
    try:
        preset=defaults(service);base={k:preset[k] for k in ('version','templateId','plugins')};results=[]
        for name,selection in [('with-recovery',base),('minimal',{**base,'plugins':[]})]:
            work=out/name;work.mkdir();resolved=materialize(service,selection,work/'source')
            recipe={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium','timePolicy':'benchmark-time-v2',
                    'processResources':json.loads((ROOT/'schemas/execution/process-resources.json').read_text())}
            with (work/'build.log').open('w') as log:
                frozen=freeze_project(ROOT,out/'data/objects/sha256',work/'source',recipe,out/'cache',log,recipe['processResources']['build'])
            export=export_project(frozen['path'],work/'exports')
            assert export['sourceCompositionId']==resolved['compositionId']
            # Only files from the resulting ZIP are available to the container.
            relocated=work/'relocated'
            with zipfile.ZipFile(export['archive']) as archive:archive.extractall(relocated)
            exported=resolve(relocated/'harness')
            plugin_paths=[n for n in exported.assets if n.startswith('candidate/plugins/')]
            assert bool(plugin_paths)==bool(selection['plugins'])
            artifact=exported.asset('candidate.tar')
            runtime=work/'runtime';runtime.mkdir()
            with tarfile.open(artifact) as archive:archive.extractall(runtime,filter='data')
            image=frozen['manifest']['buildReceipt']['inputs']['image']
            command=['docker','run','--rm','--network','none','--mount','type=bind,src='+str(runtime)+',dst=/candidate','-w','/candidate','--entrypoint','/candidate/runtime/node',image,'check-assembly.mjs']
            with (work/'relocated-load.log').open('w') as log:subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=80)
            receipt=json.loads((runtime/'assembly-check.json').read_text())
            assert len(receipt['plugins'])==len(selection['plugins'])
            # Delete the catalog copy. The export and immutable source are independent.
            for chosen in selection['plugins']:
                lib=service.plugin_library;lib.change(chosen['id'],'delete',lib.preview(chosen['id'])['versions'],'delete-'+chosen['id']);lib.prune(lib.store.clock()+1)
                assert not (lib.root/chosen['id']).exists()
            assert resolve(relocated/'harness').manifest['id']==frozen['id']
            results.append({'name':name,'compositionId':resolved['compositionId'],'bundleId':frozen['id'],'export':export,'nativeLoad':receipt})
            print(name+' passed',flush=True)
            # Keep receipts/logs, remove only this contract's bulky synthetic assets.
            for folder in (work/'source',work/'exports',work/'relocated',work/'runtime',out/'cache'):
                if folder.exists():shutil.rmtree(folder)
            from src.control.plugin_library import KIND
            from src.control.h0 import TEMPLATE_KIND
            for folder in (out/'data/objects/sha256').iterdir():
                descriptor=folder/'object.json'
                if descriptor.is_file() and json.loads(descriptor.read_text()).get('kind') in (KIND,TEMPLATE_KIND):continue
                if folder.is_dir():shutil.rmtree(folder)
        (out/'validation.json').write_text(json.dumps({'status':'passed','realModelCalls':0,'scope':'isolated builds and exported native loading; no scientific task or score','results':results},ensure_ascii=False,indent=2))
    finally:service.pool.shutdown()
if __name__=='__main__':main()
