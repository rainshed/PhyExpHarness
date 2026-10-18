"""Compatibility CLI for historical H0 commands; delegates all execution to frozen single_run."""
import argparse
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from src.execution.bundle.freeze import freeze
from src.execution.host.single_run import run,source_hashes,write_json
from src.execution.adapters.quantum_harbor.results import collect,verify_manifest
from .paths import data_dir

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quantum-harbor',type=Path,default=ROOT.parent/'Quantum-Harbor')
    parser.add_argument('--experiment',type=Path,default=ROOT/'experiments/h0-hamlearn-sol.json')
    parser.add_argument('--collect',type=Path)
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    if args.collect:
        verify_manifest(args.collect);print(json.dumps(collect(args.collect),ensure_ascii=False,indent=2));return 0
    plan=json.loads(args.experiment.read_text());recipe=json.loads((ROOT/plan['recipe']).read_text())
    if plan['attempts']!=1 or plan['retries']!=0:raise ValueError('One trial, no automatic retries required')
    data=data_dir(args.data_dir)
    knowledge=json.loads((ROOT/'knowledge/plugin-sdk/reference/manifest.json').read_text())
    bundle=freeze(ROOT,data/'bundles',recipe,knowledge=knowledge)
    folder=Path(bundle['path'])
    subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=folder,check=True)
    subprocess.run(['node','install-runner.mjs'],cwd=folder,check=True)
    run_id=plan['id']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    import time
    result=run(folder,args.quantum_harbor,plan['task'],data/'runs/h0'/run_id,time.time()+recipe['agentTimeoutSec'])
    report=data/'reports/h0'/f'{run_id}.json';report.parent.mkdir(parents=True,exist_ok=True);write_json(report,result)
    print(json.dumps({k:result.get(k) for k in ['runId','status','officialReward']},ensure_ascii=False))
    return 0 if result['status']=='completed' else 1
