"""Historical sequential batch command, backed by the single frozen execution implementation."""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
from src.execution.host.single_run import source_hashes,write_json
from src.execution.adapters.quantum_harbor.results import archive_manifest,verify_manifest
from .paths import data_dir
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',type=Path,default=ROOT/'experiments/h0-public-remaining-sol.json')
    parser.add_argument('--quantum-harbor',type=Path,default=ROOT.parent/'Quantum-Harbor')
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    plan=json.loads(args.experiment.read_text())
    if plan['attempts']!=1 or plan['retries']!=0 or len(set(plan['tasks']))!=len(plan['tasks']):
        raise ValueError('Distinct tasks, one attempt each, no automatic retries required')
    root=data_dir(args.data_dir);recipe=json.loads((ROOT/plan['recipe']).read_text())
    batch_id=plan['id']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=root/'runs/batches'/batch_id;folder.mkdir(parents=True)
    (root/'runs/h0').mkdir(parents=True,exist_ok=True)
    batch={'batchId':batch_id,'status':'running','plan':plan,'recipe':recipe,'runs':[]};started=time.monotonic()
    for index,task in enumerate(plan['tasks'],1):
        experiment={'id':'h0-sol-'+task,'recipe':plan['recipe'],'task':task,'attempts':1,'retries':0,'purpose':plan['purpose']}
        file=folder/f'{index}-experiment.json';write_json(file,experiment)
        before=set((root/'runs/h0').glob(experiment['id']+'-*'));clock=time.monotonic()
        with (folder/f'{index}-console.log').open('w') as log:
            process=subprocess.run([sys.executable,str(ROOT/'src/integrations/quantum_harbor/run.py'),
                '--experiment',str(file),'--quantum-harbor',str(args.quantum_harbor.resolve()),'--data-dir',str(root)],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        entry={'index':index,'task':task,'exitCode':process.returncode,'wallTimeSeconds':time.monotonic()-clock}
        try:
            new=set((root/'runs/h0').glob(experiment['id']+'-*'))-before
            if len(new)!=1:raise ValueError('Expected one archive')
            run=new.pop();summary=json.loads((run/'summary.json').read_text());verify_manifest(run)
            entry.update({k:summary.get(k) for k in ['status','pipelineStatus','taskOutcome','officialReward','sciencePassed','usage','error']})
            entry.update(runId=run.name,archive=str(run),configurationVerified=True)
            actual=json.loads((run/'provenance.json').read_text())['recipe']
            expected={k:v for k,v in recipe.items() if k!='modules'}|{'plugins':[]}
            if actual not in [recipe,expected]:raise ValueError('Recipe changed')
        except Exception as error:entry.update(status='infrastructure_error',error=str(error))
        batch['runs'].append(entry);write_json(folder/'batch.json',batch)
    batch.update(status='completed',wallTimeSeconds=time.monotonic()-started,
        officiallyGradedTasks=sum(e.get('officialReward') is not None for e in batch['runs']),
        passedTasks=sum(e.get('officialReward')==1 for e in batch['runs']),
        infrastructureErrors=sum(e['status']=='infrastructure_error' for e in batch['runs']))
    write_json(folder/'batch.json',batch);archive_manifest(folder)
    report=root/'reports/h0'/f'{batch_id}.json';report.parent.mkdir(parents=True,exist_ok=True);write_json(report,batch)
    print(str(report));return int(bool(batch['infrastructureErrors']))
