"""Deletion UI with real API/persistence and one injected unlink failure; no models."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.service import ControlService
from src.control.server import make_app
from src.execution.bundle.freeze import freeze
import src.control.deletion as deletion
import uvicorn


def seed(service):
    model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
    config={'fixture':True,'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],
            'concurrency':1,'wallTimeSeconds':3600,'maxRounds':2,'maxTrials':2}
    ids={}
    for key,name in [('remove','删除演示 · 合成活动'),('source','被引用的历史 · 合成活动'),('keep','保留活动 · 引用历史')]:
        ids[key]=service.store.create({**config,'name':name},key)['id']
    campaign=ids['remove']
    if not service.store.list('candidates',campaign):
        bundle=freeze(ROOT,service.data/'objects/sha256',json.loads((ROOT/'recipes/h0-sol.json').read_text()),[])
        service.store.candidate(campaign,bundle,'合成基线',check={'status':'passed'})
        service.store.control(campaign,'start','start');service.store.control(campaign,'pause','pause')
        service.evidence.add(campaign,None,'trace','合成历史用于删除检查。',{})
        service.reports.status_summary(campaign,'合成报告；不含科学实验结果。')
        source=service.evidence.add(ids['source'],None,'trace','合成历史来源。',{})
        service.adoptions.adopt(ids['keep'],ids['source'],'evidence',source['id'],'验证引用阻塞','user-only','adopt')
    return ids


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=18572)
    args=parser.parse_args();service=ControlService(ROOT,args.data_dir,ROOT.parent/'Quantum-Harbor',f'http://127.0.0.1:{args.port}')
    ids=seed(service);remove=deletion.remove_path;failed=False
    def fail_once(data,path):
        global failed
        if not failed and path=='campaigns/'+ids['remove']:
            failed=True;raise PermissionError('合成故障：首次清理失败，请点击重试删除。')
        return remove(data,path)
    deletion.remove_path=fail_once
    print(json.dumps({'fixture':True,'campaigns':ids,'modelCalls':0}),flush=True)
    uvicorn.run(make_app(service),host='127.0.0.1',port=args.port,log_level='warning')
