"""Native UI exercise server. All experiment processes are explicitly labeled fixtures; no provider exists."""
import argparse,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from src.control.service import ControlService
from src.control.server import make_app
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--port',type=int,default=18402);args=p.parse_args()
def launch(trial):
    return subprocess.Popen([sys.executable,str(ROOT/'tests/fixtures/trial_supervisor.py'),'--output',trial['output'],'--deadline',str(time.time()+45)])
service=ControlService(ROOT,args.data_dir,ROOT.parent/'Quantum-Harbor',f'http://127.0.0.1:{args.port}',launch_trial=launch)
def build(campaign,selections,description,parent=None):
    return service.store.candidate(campaign,{'id':'ui-fixture','path':'/fixture','plugins':[]},'UI 检查夹具 H0',check={'status':'passed','fixture':True})
service.build_candidate=build
# The normal launch validates a frozen bundle; replace only this test server's launch implementation.
def start(trial):
    output=args.data_dir/'trials'/trial['launchId'];trial=service.store.trial_update(trial['id'],output=str(output))
    child=launch(trial);service.children[trial['id']]=child
    return service.store.trial_update(trial['id'],state='running',pid=child.pid)
service._launch=start
import uvicorn
uvicorn.run(make_app(service),host='127.0.0.1',port=args.port,log_level='warning')
