import concurrent.futures
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from src.control.store import Store,Refused,Conflict,PUBLIC_TASKS,encoded
from src.control.reference.policy import DEFAULT,validate
from src.control.reference.service import References
from src.control.reference.runtime import freeze_runtime,verify_runtime
from src.reporting.reports import Reports
ROOT=Path(__file__).resolve().parents[2]

class ReferencesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name);self.store=Store(self.data/'db',clock=lambda:1000)
        self.stopped=[]
        self.service=SimpleNamespace(store=self.store,data=self.data,source=ROOT,meta_driver=None,stop_trial=lambda t,r:self.stopped.append(t['id']))
        self.ref=self.service.references=References(self.service)
        frozen={'adapter':'deepseek-api-key','pluginVersion':'0.2.1-rc.2','config':{'baseURL':'https://example.test/anthropic','apiKeyEnv':'TEST_KEY'},
          'call':{'provider':'deepseek-official','model':'test-model','reasoningEffort':'high','maxTokens':8192},'info':{},'credentialRef':'TEST_KEY'}
        self.ref.catalog.sync({'version':'native-reference-catalog-v1','bindings':[{'id':'native-'+'a'*64,'label':'Test','provider':'deepseek-official','model':'test-model','frozen':frozen,'credential':{'ref':'TEST_KEY','value':'secret-marker'}}]})
        row=self.ref.catalog.read()['models'][0];self.model=row['id']
        self.policy={**DEFAULT,'modelEnabled':True,'harnessEnabled':True,'modelRefs':[self.model],'harnessRefs':['dsh-standard','claude-code'],'limits':{'model':{'maxTrials':4,'softTokenLimit':400},'harness':{'maxTrials':4,'softTokenLimit':500}},'catalogRevision':self.ref.catalog.read()['revision']}
        config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},'tasks':[PUBLIC_TASKS[0]],'maxRounds':None,'maxTrials':20,'concurrency':2,'wallTimeSeconds':7200,'trialTimeSeconds':3600,'softTokenLimit':3000000,'reserveSeconds':100,'reserveTokens':100,'retries':0,'referencePolicy':self.policy}
        self.c=self.store.create(config,'create',defaults={'referenceBindings':{'models':{self.model:row},'harnesses':{'dsh-standard':{},'claude-code':{}},'runtime':'a'*64}})['id']
        self.store.control(self.c,'start','start')
        self.candidate=self.store.candidate(self.c,{'id':'bundle','path':str(self.data),'plugins':[]},'H0',check={'status':'passed'})['id']
    def tearDown(self):self.temp.cleanup()
    def h0(self):return self.store.submit(self.c,self.candidate,[PUBLIC_TASKS[0]],1,'h0')
    def submit(self,key='ref',mode='joint',repeats=1,**extra):
        axis='model' if mode=='model' else 'harness'
        args={'tasks':[PUBLIC_TASKS[0]],'repeats':repeats,'researchQuestion':'Compare trajectory','idempotencyKey':key,'expectedPolicyRevision':1,**extra}
        if mode in ('model','joint'):args['modelRef']=self.model
        if mode=='model':args['candidateId']=self.candidate
        else:args['harnessRef']='dsh-standard'
        return self.ref.call(self.c,'reference_'+axis+'_submit',args)
    def test_h0_reserves_first_and_one_pair_is_one_round(self):
        with self.assertRaisesRegex(Refused,'H0'):self.submit()
        self.h0();b=self.submit(repeats=2)
        self.assertEqual(self.store.status(self.c)['counts']['rounds'],2)
        self.assertEqual(len(self.store.list('batches',self.c)),1)
        self.assertEqual(len(self.store.list('trials',self.c)),1)
        self.assertEqual(len(self.store.list('reference_runs',self.c)),2)
        self.assertEqual(b['reference']['requiredCapabilities'],['model','harness'])
    def test_idempotent_after_restart_and_payload_conflict(self):
        self.h0();before=self.submit()
        self.store=self.service.store=Store(self.data/'db',clock=lambda:1000);self.ref=self.service.references=References(self.service)
        self.assertEqual(self.submit(),before)
        with self.assertRaises(Conflict):self.submit(repeats=2)
    def test_independent_disable_joint_cancellation_and_original_capability_bound(self):
        self.h0();self.submit('model','model');self.submit('harness','harness');self.submit()
        updated=self.ref.update(self.c,{**self.policy,'modelEnabled':False},'disable',1)
        states={t['reference']['mode']:t['state'] for t in self.store.list('reference_runs',self.c)}
        self.assertEqual(states,{'model-reference':'cancelled','harness-reference':'reserved','joint-reference':'cancelled'})
        self.assertEqual(updated['revision'],2)
        self.ref.update(self.c,self.policy,'enable',2)
        self.assertEqual(len([t for t in self.store.list('reference_runs',self.c) if t['state']=='cancelled']),2)
        self.assertEqual(self.store.status(self.c)['counts']['rounds'],4)
    def test_same_global_limits_and_concurrency_with_reference_subcaps(self):
        self.h0();self.store.control(self.c,'limits','lim',changes={'maxTrials':3})
        def submit(i):
            try:return self.submit(str(i))
            except Refused:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:rows=list(pool.map(submit,range(5)))
        self.assertEqual(sum(r is not None for r in rows),2)
        self.assertIsNotNone(self.store.claim(self.c));self.assertIsNotNone(self.store.claim(self.c));self.assertIsNone(self.store.claim(self.c))
    def test_joint_tokens_charged_once_and_overlapping_caps_apply(self):
        self.h0();self.submit();run=self.store.list('reference_runs',self.c)[0]
        self.store.put('leases',{'id':'lease','campaignId':self.c,'trialId':run['id'],'role':'solver','deadline':8000})
        self.assertEqual(self.store.admit(self.c,'lease','a',250,'solver')['status'],'granted')
        self.assertEqual(self.store.admit(self.c,'lease','b',250,'solver')['status'],'waiting')
        self.store.settle(self.c,'lease','a',150,False)
        self.assertEqual(self.store.admit(self.c,'lease','b',250,'solver')['status'],'granted')
        self.store.settle(self.c,'lease','b',250,False)
        denied=self.store.admit(self.c,'lease','c',1,'solver')
        self.assertEqual(denied['boundary'],'reference_model')
        self.assertEqual(self.store.usage(self.c)['confirmedTokens'],400)
    def test_reference_token_caps_still_apply_without_global_token_limit(self):
        self.store.control(self.c,'limits','unlimited',changes={'softTokenLimit':None})
        self.test_joint_tokens_charged_once_and_overlapping_caps_apply()
    def test_drain_and_cancelled_started_run_is_still_charged(self):
        self.h0();self.submit();self.store.claim(self.c);run=self.store.claim(self.c)
        self.assertTrue(run['id'].startswith('reference-run-'))
        self.ref.update(self.c,{**self.policy,'modelEnabled':False},'disable',1)
        self.assertEqual(self.store.run(run['id'])['state'],'launching');self.assertEqual(self.stopped,[])
        self.store.trial_update(run['id'],state='cancelled')
        self.assertEqual(self.store.status(self.c)['counts']['trials'],2)
    def test_explicit_stop_revokes_lease_and_survives_idempotent_retry(self):
        self.h0();self.submit();self.store.claim(self.c);run=self.store.claim(self.c)
        self.store.put('leases',{'id':'active-lease','campaignId':self.c,'trialId':run['id'],'role':'solver','deadline':8000})
        self.store.trial_update(run['id'],leaseId='active-lease',state='running')
        policy={**self.policy,'harnessEnabled':False}
        result=self.ref.update(self.c,policy,'stop',1,True)
        self.assertEqual(self.ref.update(self.c,policy,'stop',1,True),result)
        self.assertEqual(self.stopped,[run['id']]);self.assertTrue(self.store.get('leases','active-lease')['revoked'])
        self.assertTrue(self.store.run(run['id'])['referenceStopPending'])
    def test_queued_cancel_releases_trials_but_never_rounds_or_old_runs(self):
        self.h0();self.store.control(self.c,'limits','cap',changes={'maxTrials':2});batch=self.submit()
        self.assertEqual(self.store.status(self.c)['counts']['trials'],2)
        self.ref.cancel(self.c,{'batchId':batch['id'],'expectedPolicyRevision':1,'idempotencyKey':'cancel'})
        counts=self.store.status(self.c)['counts'];self.assertEqual(counts['trials'],1);self.assertEqual(counts['rounds'],2)
        self.submit('replacement');self.assertEqual(self.store.status(self.c)['counts']['rounds'],3)
    def test_policy_cannot_add_unfrozen_capability_or_expand_allowlist(self):
        with self.assertRaisesRegex(Refused,'widen'):self.ref.update(self.c,{**self.policy,'harnessRefs':['codex']},'widen',1)
        c=self.store.get('campaigns',self.c);c['config']['referencePolicy']={**self.policy,'modelEnabled':False};self.store.put('campaigns',c)
        with self.assertRaisesRegex(Refused,'not frozen'):self.ref.update(self.c,self.policy,'enable',1)
    def test_external_non_equivalent_settings_remain_unverified(self):
        from src.control.reference.compatibility import external_settings_issue
        snapshot={'adapter':'pi-ai','call':{'provider':'p','model':'m','reasoningEffort':'high'},'config':{'providers':{'p':{'api':'anthropic-messages'}}}}
        self.assertIsNotNone(external_settings_issue(snapshot,{},None))
        snapshot['call'].pop('reasoningEffort');self.assertIsNone(external_settings_issue(snapshot,{},None))
        snapshot['config']['providers']['p']['thinkingBudgets']={};self.assertIsNone(external_settings_issue(snapshot,{},None))
        snapshot['config']['providers']['p']['thinkingBudgets']={'high':3000};self.assertIsNotNone(external_settings_issue(snapshot,{},None))
    def test_allowlists_pinned_pairs_and_native_integrity(self):
        self.h0()
        with self.assertRaisesRegex(Refused,'Pinned pair'):self.ref.update(self.c,{**self.policy,'pairs':[{'modelRef':'no','harnessRef':'dsh-standard'}]},'bad',1)
        self.ref.update(self.c,{**self.policy,'selectionMode':'pinned-pairs','pairs':[{'modelRef':self.model,'harnessRef':'claude-code'}]},'pin',1)
        with self.assertRaisesRegex(Refused,'Pair'):self.submit(expectedPolicyRevision=2)
        binding=self.ref.catalog.root/'bindings'/(self.model+'.json');value=json.loads(binding.read_text());value['call']['model']='changed';binding.write_text(json.dumps(value))
        with self.assertRaisesRegex(Refused,'integrity'):self.submit('changed',expectedPolicyRevision=2)
    def test_protocol_mismatch_is_refused_and_public_metadata_hides_credentials(self):
        c=self.store.get('campaigns',self.c)
        self.assertEqual(self.ref.compatibility(c,self.model,'claude-code')['state'],'supported')
        self.assertEqual(self.ref.compatibility(c,self.model,'codex')['state'],'unsupported')
        self.assertNotIn('secret-marker',encoded(self.ref.catalog.public()))
        self.assertNotIn('baseURL',encoded(self.ref.catalog.public()))
    def test_fixed_solver_codex_subscription_keeps_its_native_harness(self):
        c={'config':{'solver':{'provider':'openai-codex','model':'gpt-6-luna','reasoningEffort':'low'}}}
        self.assertEqual(self.ref.compatibility(c,None,'codex')['state'],'supported')
        self.assertEqual(self.ref.compatibility(c,None,'claude-code')['state'],'unsupported')
    def test_native_codex_host_handle_compatibility_and_private_credential_boundary(self):
        frozen={'adapter':'pi-ai','pluginVersion':'0.2.1-rc.2','nativeAuth':'codex-host','credentialRef':None,
                'config':{'providers':{'openai-codex':{'models':[{'id':'gpt-6-sol'}],'reasoning':'medium','headers':{},'thinkingBudgets':{}}}},
                'call':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},'info':{}}
        row={'id':'native-'+'b'*64,'provider':'openai-codex','model':'gpt-6-sol','label':'GPT','frozen':frozen}
        document={'version':'native-reference-catalog-v1','bindings':[row]}
        self.ref.catalog.sync(document);public=self.ref.catalog.read()['models'][0];model=public['id']
        self.assertFalse((self.ref.catalog.root/'credentials'/(model+'.json')).exists())
        for harness,state in [('codex','supported'),('dsh-standard','supported'),('claude-code','unsupported')]:
            self.assertEqual(self.ref.compatibility({'config':{}},model,harness)['state'],state)
        from src.control.reference.runtime import preflight
        c=self.store.get('campaigns',self.c);c['config']['referencePolicy'].update(modelRefs=[model],harnessEnabled=False)
        c['config']['referenceBindings']['models']={model:public};self.store.put('campaigns',c)
        with patch('src.control.reference.runtime.verify_runtime'),patch('src.control.reference.runtime.subprocess.run') as run:
            run.return_value.returncode=0;preflight(self.service,self.c)
            self.assertIn('createChatGPTCredentials',run.call_args.args[0][-1])
            run.return_value.returncode=1
            with self.assertRaisesRegex(Refused,'login'):preflight(self.service,self.c)
        frozen['config']['providers']['openai-codex']['cacheRetention']='long'
        self.ref.catalog.sync(document);model=self.ref.catalog.read()['models'][0]['id']
        self.assertEqual(self.ref.compatibility({'config':{}},model,'codex')['state'],'unverified')
        for key,value in [('baseURL','https://other.test'),('api','openai-responses'),('headers',{'Authorization':'other'}),('apiKeyEnv','OTHER')]:
            frozen['config']['providers']['openai-codex'][key]=value
            with self.assertRaisesRegex(Refused,'Invalid'):self.ref.catalog.sync(document)
            del frozen['config']['providers']['openai-codex'][key]
        row['credential']={'ref':'OTHER','value':'must-not-store'}
        with self.assertRaisesRegex(Refused,'copy'):self.ref.catalog.sync(document)
    def test_finalization_and_stop_cover_both_tables(self):
        self.h0();self.submit(repeats=2);self.store.claim(self.c);run=self.store.claim(self.c)
        with self.assertRaises(Refused):self.store.finalize(self.c)
        self.store.control(self.c,'stop','stop')
        self.assertEqual(sum(t['state']=='cancelled' for t in self.store.list('reference_runs',self.c)),1)
        for t in self.store.runs(self.c):
            if t['state']=='launching':self.store.trial_update(t['id'],state='failed')
        self.assertEqual(self.store.list('reference_batches',self.c)[0]['state'],'finished')
        self.store.finalize(self.c)
    def test_frozen_adapter_runtime_tamper_detected(self):
        id=freeze_runtime(ROOT,self.data);root=verify_runtime(self.data,id)
        (root/'src/execution/reference/cli.mjs').write_text('changed')
        with self.assertRaisesRegex(Refused,'changed'):verify_runtime(self.data,id)
    def test_primary_scores_exclude_reference_and_report_keeps_separate_evidence(self):
        self.h0();self.submit();run=self.store.list('reference_runs',self.c)[0]
        self.store.trial_update(run['id'],state='finished',score=1)
        facts=Reports(self.store,self.data).facts(self.c)
        self.assertEqual(len(facts['trials']),1)
        self.assertIsNone(facts['trials'][0]['score'])
        self.assertEqual(facts['referenceExperiments']['runs'][0]['score'],1)
        self.assertIsNone(self.store.get('campaigns',self.c)['retainedCandidateId'])

if __name__=='__main__':unittest.main()
