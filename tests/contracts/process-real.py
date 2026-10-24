"""Explicit real Solver/Harbor acceptance. Uses a supplied authorized config and preserves all outputs."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.execution.bundle.project import freeze_project
from src.control.execution_cache import prepare_runtime
from src.execution.host.models import campaign_route


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--quantum-harbor',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--task',required=True)
    p.add_argument('--project',type=Path,default=ROOT/'templates/harness/default');p.add_argument('--cache',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(args.config.read_text());task=args.task
    assert task in cfg['tasks'],'Task is outside supplied scope'
    resources=json.loads((ROOT/'schemas/execution/process-resources.json').read_text())
    recipe={**cfg['solver'],'timePolicy':'benchmark-time-v1','providerConfig':campaign_route(cfg,'solver'),'processResources':resources}
    with (args.output/'build.log').open('w') as log:
        frozen=freeze_project(ROOT,args.output/'objects',args.project,recipe,args.cache/'builds',log,resources['build'])
    runtime=prepare_runtime(frozen['path'],args.cache)
    lock=args.output/'task-lock.json';lock.write_text(json.dumps(cfg['taskImageLocks'][task]))
    trial=args.output/'trial'
    command=[sys.executable,str(runtime/'run.py'),'--bundle',frozen['path'],'--quantum-harbor',str(args.quantum_harbor),
             '--task',task,'--task-image-lock',str(lock),'--output',str(trial),'--deadline',str(time.time()+22000)]
    (args.output/'attempt.json').write_text(json.dumps({'bundleId':frozen['id'],'bundlePath':frozen['path'],'task':task,'command':command,'startedAt':time.time()},indent=2))
    with (args.output/'supervisor.log').open('w') as log: completed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=22500)
    summary=json.loads((trial/'summary.json').read_text())
    result={'status':'passed' if summary.get('officialReward') is not None else 'failed','bundleId':frozen['id'],
            'officialReward':summary.get('officialReward'),'execution':summary.get('execution'),'taskOutcome':summary.get('taskOutcome'),
            'trial':str(trial),'realModel':cfg['solver']}
    (args.output/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    if result['status']!='passed': raise SystemExit(1)
if __name__=='__main__':main()
