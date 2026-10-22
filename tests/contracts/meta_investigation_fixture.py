"""Deterministic provider policy using only model-visible tool replies and paths."""
import json
import time

class Investigation:
    def __init__(self):self.stage=0;self.calls=0;self.operation=None;self.candidate=None;self.batch=None;self.comparison=None
    def reply(self,body):
        self.calls+=1
        if self.calls>200:raise AssertionError('Meta fixture failed to converge')
        replies=[m for m in body['messages'] if m['role']=='tool']
        text=replies[-1]['content'] if replies else '{}'
        if isinstance(text,list):text='\n'.join(p.get('text','') for p in text)
        try:last=json.JSONDecoder().raw_decode(text.lstrip())[0]
        except (ValueError,TypeError):last={}
        if last.get('receiptVersion')=='meta-tool-receipt-v1':
            assert len(text.encode())<=4096,text
            assert 'completeToolResult' not in text,text
            if self.stage in [3,5]:
                script="import json; s=json.load(open("+repr(last['file']['path'])+"))['data']; print(json.dumps({'operations':s['operations'],'config':{'tasks':s['campaign']['config']['tasks']}}))"
                return 'bash',{'command':"python3 - <<'PY'\n"+script+"\nPY"}
            if self.stage==8:
                script="import json; s=json.load(open("+repr(last['file']['path'])+"))['data']; print(json.dumps({'evaluation':s['evaluation']}))"
                return 'bash',{'command':"python3 - <<'PY'\n"+script+"\nPY"}
        if self.stage==0:
            self.stage=1
            script="""import json,hashlib,pathlib
index=json.load(open('/evidence/index.json'))
rows=[r for r in index['items'] if r.get('trialId') and r.get('availability')=='available']
assert rows
proof=[]
for r in rows:
 data=pathlib.Path(r['path']).read_bytes()
 assert hashlib.sha256(data).hexdigest()==r['sha256']
 proof.append({'ref':r['ref'],'bytes':len(data),'scoreFields':b'reward' in data or b'score' in data,'trajectory':b'tool' in data})
assert any(r['scoreFields'] for r in proof) and any(r['trajectory'] for r in proof)
pathlib.Path('/work/analysis').mkdir(exist_ok=True)
pathlib.Path('/work/analysis/investigation.json').write_text(json.dumps(proof))
print('COMPLETE_SCORES_AND_TRAJECTORY_READ',len(proof))
"""
            return 'bash',{'command':"python3 - <<'PY'\n"+script+'PY'}
        if self.stage==1:
            assert 'COMPLETE_SCORES_AND_TRAJECTORY_READ' in text,text
            self.stage=2
            manifest={'schemaVersion':1,'name':'investigation-fixture','version':'1.0.0','entry':'index.mjs','purpose':'Engineering fixture','configSchema':{'type':'object','additionalProperties':False},'dependencies':[],'observes':['public context'],'intervenes':['system context'],'capabilities':['public-context'],'fallbackBehavior':'No scientific behavior change','assets':[]}
            source="export const inject=['systemPrompt']; export function apply(ctx){ctx.systemPrompt.section({name:'fixture:investigation',order:25,text:'Engineering fixture only; use the task tools normally.'});}\n"
            script="from pathlib import Path\np=Path('/work/plugins/investigation');p.mkdir(parents=True,exist_ok=True)\n"+f"(p/'plugin.json').write_text({json.dumps(manifest)!r})\n(p/'index.mjs').write_text({source!r})\nprint('PLUGIN_WRITTEN')\n"
            return 'bash',{'command':"python3 - <<'PY'\n"+script+'PY'}
        if self.stage==2:
            assert 'PLUGIN_WRITTEN' in text,text
            self.stage=3;return 'candidate_check',{'plugins':[{'path':'/work/plugins/investigation','config':{}}],'idempotencyKey':'investigation-check'}
        if self.stage in [3,5]:
            if 'operationId' in last:self.operation=last['operationId']
            row=next((o for o in last.get('operations',[]) if o['id']==self.operation),None)
            if row:
                assert row['state']!='failed',row
                if row['state']=='finished':
                    if self.stage==3:
                        assert row['result']['status']=='passed' and row['result']['trialCreated'] is False,row
                        self.stage=5;self.operation=None
                        return 'candidate_freeze',{'plugins':[{'path':'/work/plugins/investigation','config':{}}],'description':'Full-evidence investigation fixture','idempotencyKey':'investigation-freeze'}
                    self.candidate=row['result']['id'];self.stage=6
                    return 'batch_submit',{'candidateId':self.candidate,'tasks':last['config']['tasks'],'repeats':1,'idempotencyKey':'investigation-batch'}
            time.sleep(.2)
            return 'campaign_status',{}
        if self.stage==6:
            self.batch=last['id'];self.stage=7
        if self.stage==7:
            if last.get('batch',{}).get('state')=='finished':
                assert last['trials']['items'][0]['score']==0,last
                self.stage=8;return 'results_compare',{'candidateIds':[self.candidate]}
            time.sleep(.3)
            return 'batch_status',{'batchId':self.batch}
        if self.stage==8:
            assert last['evaluation']['total']['officialScored']==1,last
            self.comparison=last;self.stage=9
        return None,None
