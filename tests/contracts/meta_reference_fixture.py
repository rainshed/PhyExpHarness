"""Model-visible policy for native Meta reference selection and follow-up verification."""
import json
import time
from meta_investigation_fixture import Investigation

class ReferenceInvestigation(Investigation):
    def __init__(self):
        super().__init__();self.reference_phase=0;self.reference_batch=None;self.reference_calls=0
    def reply(self,body):
        if self.reference_phase==4:return super().reply(body)
        self.reference_calls+=1
        assert self.reference_calls<500,'Reference fixture did not converge'
        replies=[m for m in body['messages'] if m['role']=='tool']
        text=replies[-1]['content'] if replies else '{}'
        if isinstance(text,list):text='\n'.join(p.get('text','') for p in text)
        try:last=json.JSONDecoder().raw_decode(text.lstrip())[0]
        except (ValueError,TypeError):last={}
        if self.reference_phase==0:
            self.reference_phase=1;return 'reference_harness_list',{}
        if self.reference_phase==1:
            assert last['policy']['harnessEnabled'] and last['policy']['modelEnabled']
            assert any(r['reference']['mode']=='joint-reference' for r in last['runs']['items'])
            self.reference_phase=2;return 'reference_model_list',{}
        if self.reference_phase==2:
            policy=last['policy'];source=last['runs']['items'][0]
            self.reference_phase=3
            return 'reference_model_submit',{'candidateId':source['candidateId'],'modelRef':policy['modelRefs'][0],
                'tasks':[source['task']],'repeats':1,'researchQuestion':'Hold the execution candidate fixed and inspect the native reference trajectory before proposing a plugin.',
                'expectedPolicyRevision':policy['revision'],'idempotencyKey':'meta-model-reference'}
        if str(last.get('id','')).startswith('reference-batch-'):self.reference_batch=last['id']
        if last.get('batches',{}).get('items') and all(r['state']=='finished' for r in last['batches']['items']):
            assert last['runs']['items'][0]['score']==0
            self.reference_phase=4
            return super().reply(body)
        time.sleep(1)
        return 'reference_model_status',{'batchId':self.reference_batch}
