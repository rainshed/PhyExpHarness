"""Allowlisted derived feedback. Raw official archives remain unchanged and separately verifiable."""
import hashlib
import json
from pathlib import Path
from src.control.store import identity,Refused

HAMLEARN_METRICS = {'linf','relative_l2','relative_l2_within_threshold','level','scored_vector_kind',
    'support_detected_true','support_false_positives','uncertainty_covered','uncertainty_total','uncertainty_median_1sigma',
    'budget_us','budget_used_us','within_budget','accepted_row_count','ran_nonzero_time_probe',
    'verifiable_activity_consistent','evidence_mean_binomial_deviance','evidence_p90_binomial_deviance',
    'evidence_data_compatible','binary_pass','reward_binary','penalties'}

def feedback(task,score):
    if not isinstance(score,dict):return None
    # Unknown report fields are not published by default, even for registered public tasks.
    result={k:score[k] for k in ['task_id','schema_version','reward_binary','reward','passed','disposition'] if k in score}
    if task=='time_budgeted_hamlearn_10q':
        result['penalties']=score.get('penalties',[])
        if isinstance(score.get('result'),dict):result['result']={k:v for k,v in score['result'].items() if k in HAMLEARN_METRICS}
        else:result['result']=None
    result['feedbackPolicy']='public-development-v1'
    return result

class EvidenceLibrary:
    def __init__(self,store,data):self.store=store;self.root=Path(data)/'evidence'
    def add(self,campaign,trial,kind,text,source):
        data=text.encode();sha=hashlib.sha256(data).hexdigest();file=self.root/sha
        file.parent.mkdir(parents=True,exist_ok=True)
        if not file.exists():file.write_bytes(data);file.chmod(0o444)
        with self.store.connection(True) as db:
            existing=[x for x in self.store._list(db,'evidence',campaign) if x['trialId']==trial and x['kind']==kind and x['sha256']==sha]
            if existing:return existing[0]
            row={'id':identity('evidence'),'campaignId':campaign,'trialId':trial,'kind':kind,'sha256':sha,'path':str(file),
                 'bytes':len(data),'source':source,'policy':'public-development-v1'}
            return self.store._save(db,'evidence',row)
    def ingest(self,trial):
        folder=Path(trial['output']);summary=json.loads((folder/'summary.json').read_text());items=[]
        safe={k:summary.get(k) for k in ['fixture','status','pipelineStatus','taskOutcome','officialReward','sciencePassed','submissionPresent',
            'scientificAssessmentPresent','wallTimeSeconds','stopReason','error','usage','bundleId','failure','scoringStatus','accounting','failureContract','requestRecovery']}
        safe['score']=feedback(trial['task'],summary.get('score'))
        items.append(self.add(trial['campaignId'],trial['id'],'official-result',json.dumps(safe,ensure_ascii=False,indent=2),
            {'archive':'summary.json','official':summary.get('evidence',{}).get('officialScore')}))
        for file in folder.glob('harbor/*/phyexp/events.json'):
            events=json.loads(file.read_text());allowed=[]
            for index,event in enumerate(events):
                if event.get('type') in ['request/header','tool/call','tool/result','assistant/message','turn/end','error']:
                    # Presentation includes returned actions/text, not hidden provider internals.
                    if event.get('type')=='assistant/message':
                        event=json.loads(json.dumps(event));message=event.get('data',{}).get('message',{})
                        message['content']=[x for x in message.get('content',[]) if x.get('type')!='reasoning']
                    allowed.append({'eventIndex':index,'event':event})
            text='\n'.join(json.dumps(x,ensure_ascii=False) for x in allowed)
            items.append(self.add(trial['campaignId'],trial['id'],'trajectory',text,{'archive':str(file.relative_to(folder))}))
        for name in ['container-exec.jsonl','mcp-discovery.json','load-receipt.json','bootstrap-receipt.json']:
            for file in folder.glob('harbor/*/phyexp/'+name):
                items.append(self.add(trial['campaignId'],trial['id'],name,file.read_text(),{'archive':str(file.relative_to(folder))}))
        return items
    def read(self,campaign,id,offset=0,limit=16000):
        row=self.store.get('evidence',id)
        if row['campaignId']!=campaign:raise Refused('Evidence belongs to another Campaign')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=32000:raise Refused('Invalid evidence range')
        data=Path(row['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Refused('Evidence integrity mismatch')
        text=data.decode()
        return {k:v for k,v in row.items() if k!='path'}|{'offset':offset,'total':len(text),'text':text[offset:offset+limit]}
