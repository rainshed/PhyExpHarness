"""Append diagnoses derived from verified terminal archives; never rewrite original trials/reports."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.control.store import Store
from src.execution.host.failure import diagnose
from src.execution.adapters.quantum_harbor.results import verify_manifest
from src.control.paths import data_dir


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-dir',type=Path);args=parser.parse_args()
    data=data_dir(args.data_dir);store=Store(data/'control.sqlite');file=data/'failure-diagnoses.json'
    index=json.loads(file.read_text()) if file.exists() else {'schemaVersion':1,'trials':{}}
    added=[]
    for trial in store.list('trials'):
        if trial.get('score') is not None or trial['state'] not in ['failed','unknown','cancelled'] or trial.get('failure'):continue
        if store.get('campaigns',trial['campaignId'])['state'] not in ['finished','failed']:continue
        if trial['id'] in index['trials']:continue
        if not trial.get('output'):continue
        folder=Path(trial['output']);count=verify_manifest(folder)
        failure=diagnose(folder,trial.get('stopReason'));failure['source']='historical-artifact-analysis'
        index['trials'][trial['id']]={'failure':failure,'campaignId':trial['campaignId'],
            'archiveManifestSha256':hashlib.sha256((folder/'archive-manifest.json').read_bytes()).hexdigest(),'verifiedFiles':count}
        added.append(trial['id'])
    temp=file.with_suffix('.tmp');temp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');temp.replace(file)
    print(json.dumps({'added':added,'total':len(index['trials']),'file':str(file)},ensure_ascii=False))
if __name__=='__main__':main()
