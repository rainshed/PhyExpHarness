"""Bounded subprocess fixture: no model, task submission or official score."""
import argparse
import hashlib
import json
import os
import signal
import time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--deadline',type=float,required=True);args=p.parse_args()
args.output.mkdir(parents=True);stopped=False

def stop(*_):
    global stopped
    stopped=True
signal.signal(signal.SIGTERM,stop)
(args.output/'supervisor.json').write_text(json.dumps({'pid':os.getpid(),'state':'running','deadline':args.deadline}))
while not stopped and time.time()<args.deadline:time.sleep(.02)
(args.output/'summary.json').write_text(json.dumps({'fixture':True,'status':'infrastructure_error','pipelineStatus':'failed',
    'officialReward':None,'stopReason':'fixture_cancelled' if stopped else 'fixture_deadline','usage':{},'wallTimeSeconds':.3}))
(args.output/'supervisor.json').write_text(json.dumps({'pid':os.getpid(),'state':'finished'}))
files={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in args.output.iterdir() if p.is_file()}
(args.output/'archive-manifest.json').write_text(json.dumps({'algorithm':'sha256','files':files}))
