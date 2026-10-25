"""Local engineering load only: no model calls or user activity mutations.

Run: python tests/performance/control_scale.py --count 50000 --readers 15 --report PATH
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import resource
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from src.control.store import Store
from src.evidence.library import EvidenceLibrary
from src.evidence.objects import POLICY
import src.control.store as store_module


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--count',type=int,default=50000);parser.add_argument('--readers',type=int,default=15);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--delete',action='store_true')
    args=parser.parse_args();timings=[];errors=[];writes=[];stop=threading.Event();barrier=threading.Barrier(args.readers+1)
    original=store_module.diagnostic
    def diagnostic(**kw):
        if kw['write'] and kw['acquired']:writes.append((kw['acquired']-kw['started'],time.monotonic()-kw['acquired']))
        original(**kw)
    store_module.diagnostic=diagnostic
    with tempfile.TemporaryDirectory(prefix='phyexp-scale-') as temp:
        data=Path(temp);store=Store(data/'control.sqlite');library=EvidenceLibrary(store,data)
        model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
        c=store.create({'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],'storagePolicy':POLICY,'concurrency':15,'maxTrials':None,'maxRounds':None,'wallTimeSeconds':86400,'trialTimeSeconds':3600,'softTokenLimit':None,'reserveSeconds':900,'reserveTokens':0},'load')['id']
        store.control(c,'start','start')
        def reader(number):
            barrier.wait();iteration=0
            while not stop.is_set():
                started=time.monotonic()
                try:
                    if number%3==0:store.status(c)
                    elif number%3==1:library.page(c,offset=0,limit=20)
                    else:
                        with store.connection(True,operation='scale.control-event') as db:store._event(db,c,'load_probe',worker=number)
                    timings.append(time.monotonic()-started);iteration+=1
                except Exception as error:errors.append(repr(error));stop.set()
                stop.wait(.2)
            return iteration
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.readers) as pool:
            readers=[pool.submit(reader,i) for i in range(args.readers)]
            barrier.wait();started=time.monotonic()
            for i in range(args.count):
                if errors:break
                library.add(c,'trial-'+str(i%15),'raw-artifact',('evidence '+str(i)+' '+('x'*256)),{'archive':'files/'+str(i)})
                if i and i%10000==0:print(json.dumps({'indexed':i,'seconds':round(time.monotonic()-started,2)}),flush=True)
            duration=time.monotonic()-started;stop.set();operations=sum(r.result() for r in readers)
        ordered=sorted(timings)
        stats={'evidenceCount':library.page(c,limit=1)['total'],'concurrentClients':args.readers,'operations':operations,
            'seconds':duration,'evidencePerSecond':args.count/duration,
            'responseP50Ms':ordered[len(ordered)//2]*1000,'responseP99Ms':ordered[min(len(ordered)-1,int(len(ordered)*.99))]*1000,
            'responseMaxMs':max(ordered)*1000,'writerWaitMaxMs':max(w[0] for w in writes)*1000,
            'writerHeldMaxMs':max(w[1] for w in writes)*1000,
            'maxRssPlatformUnits':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'platform':sys.platform,'errors':errors}
        stats['passed']=not errors and stats['evidenceCount']==args.count and stats['responseP99Ms']<2000 and stats['responseMaxMs']<5000
        if args.delete:
            from types import SimpleNamespace
            from src.control.deletion import ActivityAccess,Deletions
            original_campaign=c
            config=store.get('campaigns',c)['config'];c=store.create(config,'other')['id'];store.control(c,'start','start')
            service=SimpleNamespace(data=data,store=store,tick_lock=threading.Lock(),operations={},children={},meta_driver=None,
                access=ActivityAccess(),collections=SimpleNamespace(stop=lambda _:True),
                storage=SimpleNamespace(lock=threading.RLock(),maintenance_lock=threading.Lock(),waiting={},metrics={'campaigns':{}},errors=[],last_scan=0))
            deletion=Deletions(service);timings.clear();stop.clear();barrier=threading.Barrier(args.readers+1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.readers) as pool:
                readers=[pool.submit(reader,i) for i in range(args.readers)];barrier.wait();start=time.monotonic()
                preview=deletion.preview(original_campaign)
                deletion.request(original_campaign,preview['expectedRevision'],'delete')
                for attempt in range(10):
                    deletion.advance(original_campaign)
                    if store.deletion(original_campaign)['state'] in ('deleted','failed'):break
                elapsed=time.monotonic()-start;stop.set();ops=sum(r.result() for r in readers)
            ordered=sorted(timings);deleted=store.deletion(original_campaign)
            stats['deletion']={'state':deleted['state'],'error':deleted.get('error'),'seconds':elapsed,'otherActivityOperations':ops,
                'responseP99Ms':ordered[min(len(ordered)-1,int(len(ordered)*.99))]*1000,'responseMaxMs':max(ordered)*1000,'errors':errors}
            stats['passed'] &= deleted['state']=='deleted' and not errors and stats['deletion']['responseMaxMs']<5000
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(stats,indent=2)+'\n');print(json.dumps(stats),flush=True)
        if not stats['passed']:raise SystemExit(1)
if __name__=='__main__':main()
