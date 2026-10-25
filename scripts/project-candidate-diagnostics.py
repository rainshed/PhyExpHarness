"""Append derived diagnostic views; never replace official scores or raw archives."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.evidence.diagnostics import candidate_diagnostics
from src.evidence.objects import atomic_json

p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--campaign',required=True);p.add_argument('--write',action='store_true');args=p.parse_args()
file=args.data/'failure-diagnoses.json'
result=json.loads(file.read_text()) if file.exists() else {'trials':{}}
db=sqlite3.connect('file:'+str(args.data/'control.sqlite')+'?mode=ro',uri=True)
count=0
for raw, in db.execute('SELECT data FROM trials WHERE campaign=?',(args.campaign,)):
    t=json.loads(raw)
    if t.get('state') not in ('finished','failed','unknown') or not t.get('output'):continue
    root=Path(t['output']);messages=candidate_diagnostics(root,t.get('summary',{}))
    if not messages:continue
    inputs={d['evidence']:hashlib.sha256((root/d['evidence']).read_bytes()).hexdigest() for d in messages}
    previous=result['trials'].get(t['id'],{})
    result['trials'][t['id']]={**previous,'candidateDiagnostics':messages,
        'diagnosticProjection':{'source':'historical-candidate-events','recordedAt':time.time(),'sourceDigests':inputs,'scoreAuthority':False}}
    count+=1
if args.write:atomic_json(file,result)
print(json.dumps({'campaignId':args.campaign,'trialsWithCandidateErrors':count,'written':args.write}))
