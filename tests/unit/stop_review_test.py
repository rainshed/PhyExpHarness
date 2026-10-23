import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from src.control.store import Store,Refused
from src.control.stop_review import StopRuntime

class Service:
    def __init__(self,store):self.store=store;self.calls=[]
    def meta_call(self,campaign,operation,args):self.calls.append((campaign,operation,args));return {'ok':True}

class StopReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=1000
        self.store=Store(Path(self.temp.name)/'control.sqlite',clock=lambda:self.now)
        config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},'tasks':['time_budgeted_hamlearn_10q'],'concurrency':1,'wallTimeSeconds':7200,'reserveSeconds':900,'stopPolicy':'stop-review-v1','metaComposition':{'id':'fixture','plugins':[{'id':'queries','scope':'meta','enabled':True}]}}
        self.c=self.store.create(config,'fixture')['id'];self.store.control(self.c,'start','start')
        self.candidate=self.store.candidate(self.c,{'id':'bundle','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})
        evidence=Path(self.temp.name)/'evidence.txt';evidence.write_text('one')
        self.e=self.store.put('evidence',{'id':'e1','campaignId':self.c,'trialId':'t1','sha256':hashlib.sha256(b'one').hexdigest(),'path':str(evidence)})
        self.store.put('meta_sessions',{'id':'main','campaignId':self.c,'leaseId':'lease','state':'running'})
        self.service=Service(self.store);self.runtime=StopRuntime(self.service)
        self.dispatch('register',{'agentId':'main','preset':'phyexp-meta','tools':['campaign_finish']})
        self.request={'condition':'exhausted','candidateId':self.candidate['id'],'reason':'Substantive attempts exhausted feasible paths','evidenceRefs':['e1'],'attempts':[{'direction':'Mechanism one','finding':'Observed failure','evidenceRefs':['e1']}],'remainingDirections':[],'unresolved':[]}
    def tearDown(self):self.temp.cleanup()
    def dispatch(self,action,data):return self.runtime.dispatch('main',action,data)
    def begin(self):
        r=self.dispatch('review_request',{'agentId':'main','request':self.request})
        self.dispatch('register',{'agentId':'child','preset':'phyexp-stop-reviewer','tools':['campaign_status','structured_output']})
        self.dispatch('review_attach',{'reviewId':r['id'],'childId':'child'});return r
    def result(self,r,verdict='approve',**changes):
        result={'verdict':verdict,'reason':'Independent evidence checked','evidenceRefs':['e1'],'missingEvidence':[],'nextDirections':[]};result.update(changes)
        return self.dispatch('review_result',{'reviewId':r['id'],'childId':'child','result':result,'stopReason':'completed'})
    def finish(self,r,**changes):return self.store.control(self.c,'finish','finish',changes={**self.request,'reviewId':r['id'],**changes})
    def test_reason_and_model_approval_cannot_bypass_backend(self):
        for args in [{'reason':'done'},{**self.request,'approved':True,'reviewId':'fake'}]:
            with self.assertRaises((Refused,KeyError)):self.store.control(self.c,'finish','bad',changes=args)
        self.assertEqual(self.store.status(self.c)['state'],'running')
    def test_approval_stops_early_and_accounting_does_not_make_it_stale(self):
        r=self.begin();self.result(r)
        self.store.reserve(self.c,'lease','req',10,'meta');self.store.settle(self.c,'lease','req',4,False)
        result=self.finish(r);self.assertEqual(result['state'],'closing');self.assertEqual(result['finishAssessment']['source'],'independent-stop-review')
        self.assertEqual(self.store.get('stop_reviews',r['id'])['state'],'consumed')
    def test_evidence_change_invalidates_approval(self):
        r=self.begin();self.result(r);self.store.put('evidence',{**self.e,'sha256':'changed'})
        with self.assertRaisesRegex(Refused,'integrity|stale'):self.finish(r)
    def test_pending_experiment_cannot_be_cancelled_by_voluntary_stop(self):
        r=self.begin();self.result(r)
        self.store.submit(self.c,self.candidate['id'],['time_budgeted_hamlearn_10q'],1,'batch')
        with self.assertRaisesRegex(Refused,'Pending'):self.finish(r)
        self.assertEqual(self.store.status(self.c)['counts']['reservedTrials'],1)
    def test_reviewer_cannot_write_or_self_register_as_main(self):
        r=self.begin()
        with self.assertRaises(Refused):self.dispatch('call',{'agentId':'child','operation':'batch_submit','input':{'role':'meta'}})
        with self.assertRaises(Refused):self.dispatch('register',{'agentId':'child2','preset':'phyexp-meta'})
        with self.assertRaises(Refused):self.dispatch('review_request',{'agentId':'child','request':self.request})
        self.dispatch('call',{'agentId':'child','operation':'campaign_status','input':{}});self.assertEqual(len(self.service.calls),1)
    def test_decline_and_duplicate_rewording_do_not_launch_another_vote(self):
        r=self.begin();self.result(r,'continue',nextDirections=['Test a different tool exposure'])
        replay=self.dispatch('review_request',{'agentId':'main','request':{**self.request,'reason':'try again'}})
        self.assertTrue(replay['replayed']);self.assertEqual(replay['id'],r['id'])
        with self.assertRaises(Refused):self.finish(r)
    def test_forged_child_cross_session_and_invalid_result_fail_closed(self):
        r=self.begin()
        with self.assertRaises(Refused):self.dispatch('review_result',{'reviewId':r['id'],'childId':'forged','result':{'verdict':'approve'},'stopReason':'completed'})
        self.store.put('meta_sessions',{'id':'other','campaignId':self.c,'leaseId':'other','state':'running'})
        with self.assertRaises(Refused):self.runtime.dispatch('other','review_attach',{'reviewId':r['id'],'childId':'child'})
        result=self.dispatch('review_result',{'reviewId':r['id'],'childId':'child','result':None,'stopReason':'completed'})
        self.assertEqual(result['state'],'failed')
        with self.assertRaises(Refused):self.finish(r)
    def test_deadline_does_not_wait_for_reviewer_and_user_stop_works(self):
        r=self.begin();self.now+=7200
        self.assertEqual(self.result(r)['state'],'failed')
        self.assertEqual(self.store.control(self.c,'stop','stop')['stopReason'],'user_stop')
    def test_no_implicit_stability_threshold(self):
        with self.assertRaisesRegex(Refused,'pre-agreed'):self.store.control(self.c,'finish','stable',changes={**self.request,'condition':'stable'})
    def test_goal_policy_rejects_exhaustion_at_runtime_and_store_even_with_approval(self):
        review=self.begin();self.result(review)
        c=self.store.get('campaigns',self.c);c['config']['stopPolicy']='goal-or-budget-v1';self.store.put('campaigns',c)
        with self.assertRaisesRegex(Refused,'exhaustion'):self.finish(review)
        with self.assertRaisesRegex(Refused,'exhaustion'):self.dispatch('review_request',{'agentId':'main','request':self.request})
        with self.assertRaisesRegex(Refused,'exhaustion'):self.dispatch('call',{'agentId':'main','operation':'campaign_finish','input':{**self.request,'reviewId':review['id']}})
        with self.assertRaisesRegex(Refused,'pre-agreed'):self.store.control(self.c,'finish','stable',changes={**self.request,'condition':'stable'})
        self.assertEqual(self.store.status(self.c)['state'],'running')
        self.assertEqual(self.store.control(self.c,'stop','user-stop')['stopReason'],'user_stop')
    def test_goal_policy_uses_user_threshold_and_keeps_failures_in_completion_check(self):
        c=self.store.get('campaigns',self.c);c['config'].update(stopPolicy='goal-or-budget-v1',stabilityRule={'minTrialsPerTask':3,'minimumOfficialScore':0.9});c['retainedCandidateId']=self.candidate['id'];self.store.put('campaigns',c)
        trial={'campaignId':self.c,'candidateId':self.candidate['id'],'task':'time_budgeted_hamlearn_10q','state':'finished','score':1,'startedAt':1000}
        for i in range(3):self.store.put('trials',{**trial,'id':str(i)})
        self.store.put('trials',{**trial,'id':'failed','state':'failed','score':None})
        with self.assertRaisesRegex(Refused,'all attempts'):self.store.control(self.c,'finish','stable',changes={**self.request,'condition':'stable'})
        # A genuinely different candidate has its own complete evidence history.
        candidate=self.store.candidate(self.c,{'id':'improved','path':'/improved','plugins':[]},'Improved',check={'status':'passed'})
        c=self.store.get('campaigns',self.c);c['retainedCandidateId']=candidate['id'];self.store.put('campaigns',c)
        for i in range(3):self.store.put('trials',{**trial,'id':'new-'+str(i),'candidateId':candidate['id']})
        result=self.store.control(self.c,'finish','stable',changes={**self.request,'condition':'stable','candidateId':candidate['id']})
        self.assertEqual(result['finishAssessment']['rule'],{'minTrialsPerTask':3,'minimumOfficialScore':0.9})
    def test_user_stability_rule_can_be_set_when_creating_an_activity(self):
        config=self.store.get('campaigns',self.c)['config']
        rule={'minTrialsPerTask':3,'minimumOfficialScore':1}
        created=self.store.create({**config,'stopPolicy':'goal-or-budget-v1','stabilityRule':rule},'configured-goal')
        self.assertEqual(created['config']['stabilityRule'],rule)
    def test_relevant_policy_changes_invalidate_approval(self):
        r=self.begin();self.result(r);self.store.control(self.c,'limits','limits',changes={'concurrency':2})
        with self.assertRaisesRegex(Refused,'stale'):self.finish(r)
    def test_reviewer_with_recursive_or_write_tools_is_rejected(self):
        self.dispatch('review_request',{'agentId':'main','request':self.request})
        with self.assertRaises(Refused):self.dispatch('register',{'agentId':'child','preset':'phyexp-stop-reviewer','tools':['workspace_write']})
    def test_recovery_keeps_failed_request_and_does_not_rerun_it(self):
        r=self.begin();other=self.store.get('meta_sessions','main');other['state']='failed';self.store.put('meta_sessions',other)
        self.store.put('meta_sessions',{'id':'new','campaignId':self.c,'leaseId':'new','state':'running'})
        self.runtime.dispatch('new','register',{'agentId':'new','preset':'phyexp-meta'})
        replay=self.runtime.dispatch('new','review_request',{'agentId':'new','request':self.request})
        self.assertEqual(replay['state'],'failed');self.assertTrue(replay['replayed'])

    def test_stability_is_checked_on_all_attempts_of_the_selected_candidate(self):
        c=self.store.get('campaigns',self.c);c['config']['stabilityRule']={'minTrialsPerTask':2,'minimumOfficialScore':0.8};c['retainedCandidateId']=self.candidate['id'];self.store.put('campaigns',c)
        trial={'campaignId':self.c,'candidateId':self.candidate['id'],'task':'time_budgeted_hamlearn_10q','state':'finished','score':0.9,'startedAt':1000}
        self.store.put('trials',{**trial,'id':'a'})
        with self.assertRaises(Refused):self.store.control(self.c,'finish','stable',changes={**self.request,'condition':'stable'})
        self.store.put('trials',{**trial,'id':'b'})
        result=self.store.control(self.c,'finish','stable',changes={**self.request,'condition':'stable'})
        self.assertEqual(result['finishAssessment']['source'],'controller-verified-stability')
    def test_review_accounting_is_subset_of_shared_ledger(self):
        r=self.begin();self.store.reserve(self.c,'lease','child-call',100,'meta')
        self.dispatch('model_request',{'id':'child-call','agentId':'child'});self.store.settle(self.c,'lease','child-call',30,False)
        result=self.result(r);self.assertEqual(result['usage']['confirmedTokens'],30)
        self.assertEqual(self.store.usage(self.c)['confirmedTokens'],30)
    def test_campaign_and_session_identity_cannot_cross(self):
        r=self.begin();other=self.store.create(self.store.get('campaigns',self.c)['config'],'other')['id'];self.store.control(other,'start','start')
        self.store.put('meta_sessions',{'id':'other','campaignId':other,'leaseId':'other','state':'running'})
        with self.assertRaises(Refused):self.runtime.dispatch('other','review_result',{'reviewId':r['id'],'childId':'child','result':{},'stopReason':'completed'})
        with self.assertRaises(Refused):self.runtime.dispatch('other','call',{'agentId':'child','operation':'workspace_write','input':{}})

if __name__=='__main__':unittest.main()
