import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from src.control.store import Store, Refused, Conflict
from src.control.resource_planning import POLICY
from src.evidence.outcomes import task_outcome, RESOURCE_RULE, RULE
from src.execution.host.failure import diagnose
from src.evidence.library import EvidenceLibrary

MODEL = {'provider':'openai-codex','model':'gpt-6-luna','reasoningEffort':'xhigh'}
TASK = 'time_budgeted_hamlearn_10q'


class ResourcePlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=1000
        self.store=Store(self.root/'ledger',clock=lambda:self.now)
        bundle=self.root/'bundle';bundle.mkdir();(bundle/'recipe.json').write_text(json.dumps({'agentTimeoutSec':7200}))
        self.bundle={'id':'fixture','path':str(bundle),'plugins':[]}

    def activity(self,plan=True,**overrides):
        cfg={'solver':MODEL,'meta':MODEL,'tasks':[TASK],'concurrency':3,'wallTimeSeconds':7200,
             'resourcePolicy':POLICY,**overrides}
        c=self.store.create(cfg,str(len(self.store.list('campaigns'))))['id']
        self.store.control(c,'start','start')
        candidate=self.store.candidate(c,self.bundle,'H0',check={'status':'passed'})['id']
        if plan:self.plan(c)
        self.store.put('leases',{'id':c+'-lease','campaignId':c,'role':'solver','deadline':20000,'revoked':False})
        return c,candidate

    def plan(self,c,revision=0,**changes):
        value={'parallelism':2,'defaultTrialTimeSeconds':3600,'closeoutReserveSeconds':0,'closeoutReserveTokens':0,**changes}
        return self.store.update_plan(c,value,'Test resource allocation','plan-'+str(revision),revision)

    def test_no_hidden_cap_no_automatic_reserve_and_plan_required(self):
        c,candidate=self.activity(plan=False)
        cfg=self.store.get('campaigns',c)['config']
        self.assertIsNone(cfg['softTokenLimit']);self.assertIsNone(cfg['maxTrials'])
        self.assertEqual((cfg['reserveSeconds'],cfg['reserveTokens']),(0,0))
        self.assertIsNone(self.store.claim(c))
        with self.assertRaisesRegex(Refused,'resource plan'):self.store.submit(c,candidate,[TASK],1,'b')
        self.plan(c);self.store.submit(c,candidate,[TASK],1,'b')
        self.assertEqual(self.store.claim(c)['taskTimeLimitSeconds'],3600)

    def test_plan_idempotency_ownership_and_revision(self):
        c,_=self.activity(plan=False)
        first=self.plan(c);self.assertEqual(first,self.plan(c))
        with self.assertRaises(Conflict):self.plan(c,revision=0,parallelism=1)
        with self.assertRaises(Refused):self.plan(c,revision=1,parallelism=4)
        with self.assertRaises(Refused):self.plan(c,revision=1,softTokenLimit=1)
        self.assertEqual(self.store.get('campaigns',c)['resourcePlan']['revision'],1)

    def test_accepted_batches_keep_plan_snapshot_future_batches_change(self):
        c,candidate=self.activity()
        self.store.submit(c,candidate,[TASK],1,'a')
        self.plan(c,revision=1,defaultTrialTimeSeconds=1800,parallelism=1)
        self.store.submit(c,candidate,[TASK],1,'b')
        a=self.store.claim(c);self.assertEqual(a['taskTimeLimitSeconds'],3600)
        self.assertEqual(a['effectiveConditions']['resourcePlanRevision'],1)
        self.assertIsNone(self.store.claim(c))
        self.store.trial_update(a['id'],state='finished')
        b=self.store.claim(c);self.assertEqual(b['taskTimeLimitSeconds'],1800)

    def test_shortened_trial_waits_for_explicit_conditions(self):
        c,candidate=self.activity()
        self.store.submit(c,candidate,[TASK],1,'batch')
        self.now=7800;self.assertIsNone(self.store.claim(c))
        t=self.store.list('trials',c)[0];self.assertEqual(t['conditionsRequired']['availableSeconds'],400)
        self.store.accept_trial_conditions(c,t['id'],400,'accept','Accept remaining time for diagnosis')
        self.now+=1;t=self.store.claim(c)
        self.assertEqual(t['effectiveConditions']['actualTimeSeconds'],399)
        self.assertIn('conditionAdjustment',t)

    def test_infeasible_time_is_rejected_before_a_trial_can_start(self):
        c,candidate=self.activity(plan=False)
        with self.assertRaisesRegex(Refused,'verification/cleanup'):self.plan(c,defaultTrialTimeSeconds=330)
        self.plan(c)
        with self.assertRaisesRegex(Refused,'verification/cleanup'):
            self.store.submit(c,candidate,[TASK],1,'short',execution={'trialTimeSeconds':300})
        self.assertEqual(self.store.list('trials',c),[])
        self.store.submit(c,candidate,[TASK],1,'valid')
        self.now=7800;self.assertIsNone(self.store.claim(c))
        trial=self.store.list('trials',c)[0]
        with self.assertRaisesRegex(Refused,'verification/cleanup'):
            self.store.accept_trial_conditions(c,trial['id'],300,'too-short','Too short')
        self.store.accept_trial_conditions(c,trial['id'],400,'accept','Accept shorter trial')
        self.now=8000;self.assertIsNone(self.store.claim(c))
        self.assertEqual(self.store.list('trials',c)[0]['conditionsRequired']['minimumTrialTimeSeconds'],331)

    def test_effective_conditions_distinguish_solver_and_whole_trial_deadlines(self):
        c,candidate=self.activity()
        self.store.submit(c,candidate,[TASK],1,'batch')
        trial=self.store.claim(c)
        self.assertEqual(trial['effectiveConditions']['trialCloseoutReserveSeconds'],330)
        self.assertEqual(trial['effectiveConditions']['solverDeadline'],trial['deadline']-330)
        self.assertEqual(self.store.status(c)['resourcePlanning']['executionTimePolicy']['minimumTrialTimeSeconds'],331)

    def test_drain_does_not_intersect_earlier_admission_deadline(self):
        c,candidate=self.activity(plan=False,wallTimeSeconds=1200,stopMode='drain',drainGraceSeconds=300)
        self.plan(c,defaultTrialTimeSeconds=1400,closeoutReserveSeconds=100)
        self.store.submit(c,candidate,[TASK],1,'batch')
        t=self.store.claim(c)
        self.assertEqual(t['deadline'],2400)
        self.assertGreater(t['deadline'],self.store.get('campaigns',c)['deadline'])

    def test_plan_reserve_is_reversible_not_an_activity_stop(self):
        c,candidate=self.activity()
        self.store.submit(c,candidate,[TASK],1,'batch')
        self.plan(c,revision=1,closeoutReserveSeconds=7100)
        self.now=1200;self.assertIsNone(self.store.claim(c))
        self.assertIsNone(self.store.claim(c))
        self.assertEqual(self.store.status(c)['resourcePlanning']['schedulingWait']['reason'],'closeout_time')
        self.assertEqual(len([e for e in self.store.events(c,0) if e['type']=='resource_plan_waiting']),1)
        self.assertEqual(self.store.get('campaigns',c)['state'],'running')
        self.plan(c,revision=2,closeoutReserveSeconds=0)
        self.assertIsNone(self.store.status(c)['resourcePlanning']['schedulingWait'])
        self.assertIsNotNone(self.store.claim(c))

    def test_user_increase_reports_existing_deadline_and_startup_cap(self):
        c,candidate=self.activity(softTokenLimit=1000000)
        self.store.submit(c,candidate,[TASK],1,'batch')
        trial=self.store.claim(c)
        self.store.control(c,'limits','extend',changes={'wallTimeSeconds':14400,'softTokenLimit':None})
        current=self.store.status(c)
        self.assertEqual(current['resourcePlanning']['runningConditions'][0]['deadline'],trial['deadline'])
        self.assertEqual(current['resourcePlanning']['runningConditions'][0]['launchLimits']['softTokenLimit'],1000000)
        self.assertEqual(current['resourcePlanning']['configurationSources']['softTokenLimit']['source'],'user')

    def test_plan_remains_adjustable_for_accepted_trials_at_batch_limit(self):
        c,candidate=self.activity(maxRounds=1)
        self.store.submit(c,candidate,[TASK],1,'batch')
        self.assertTrue(self.store.get('campaigns',c)['explorationClosed'])
        self.plan(c,revision=1,closeoutReserveSeconds=7100)
        self.now=1200;self.assertIsNone(self.store.claim(c))
        self.plan(c,revision=2,closeoutReserveSeconds=0)
        trial=self.store.claim(c);self.assertIsNotNone(trial)
        self.plan(c,revision=3,parallelism=1)
        with self.assertRaises(Refused):self.store.submit(c,candidate,[TASK],1,'extra')
        self.store.trial_update(trial['id'],state='finished')
        with self.assertRaisesRegex(Refused,'planning closed'):self.plan(c,revision=4)

    def test_claim_uses_one_clock_snapshot_for_comparable_actual_duration(self):
        c,candidate=self.activity()
        self.store.submit(c,candidate,[TASK],1,'batch')
        def advancing():
            self.now+=0.001
            return self.now
        self.store.clock=advancing
        trial=self.store.claim(c)
        self.assertEqual(trial['effectiveConditions']['actualTimeSeconds'],3600)
        self.assertEqual(trial['deadline']-trial['startedAt'],3600)

    def test_central_waits_are_atomic_idempotent_and_resume_after_settlement(self):
        c,_=self.activity(softTokenLimit=1000000,reserveTokens=0);lease=c+'-lease'
        with ThreadPoolExecutor(4) as pool:
            rows=list(pool.map(lambda i:self.store.admit(c,lease,str(i),300000,'solver'),range(4)))
        self.assertEqual(sum(r['status']=='granted' for r in rows),3)
        waiting=next(r for r in rows if r['status']=='waiting')
        self.assertEqual(self.store.usage(c)['confirmedTokens'],0)
        self.assertEqual(self.store.usage(c)['inflightReservedTokens'],900000)
        for r in rows:
            if r['status']=='granted':self.store.settle(c,lease,r['requestId'],1000,False)
        decision=self.store.admit(c,lease,waiting['requestId'],300000,'solver')
        self.assertEqual(decision['status'],'granted')
        self.store.admit(c,lease,waiting['requestId'],300000,'solver')
        self.assertEqual(self.store.usage(c)['requests'],4)
        self.assertEqual(self.store.usage(c)['confirmedTokens'],3000)

    def test_terminal_denial_persists_without_model_request_and_unknown_not_zeroed(self):
        c,_=self.activity(softTokenLimit=400000,reserveTokens=0);lease=c+'-lease'
        self.store.admit(c,lease,'a',300000,'solver')
        self.store.settle(c,lease,'a',None,True)
        denial=self.store.admit(c,lease,'b',300000,'solver')
        self.assertEqual(denial['code'],'budget_admission_denied')
        self.assertEqual(self.store.get('admissions','b')['decision']['status'],'denied')
        self.assertEqual(self.store.usage(c)['unknownReservedTokens'],300000)
        self.assertEqual(self.store.usage(c)['requests'],1)

    def test_admission_wait_survives_ledger_reopen_without_duplicate_reservation(self):
        c,_=self.activity(softTokenLimit=1000000,reserveTokens=0);lease=c+'-lease'
        for request in ('a','b','c'):self.store.admit(c,lease,request,300000,'solver')
        self.assertEqual(self.store.admit(c,lease,'waiting',300000,'solver')['status'],'waiting')
        restored=Store(self.root/'ledger',clock=lambda:self.now)
        self.assertEqual(restored.admit(c,lease,'waiting',300000,'solver')['status'],'waiting')
        restored.settle(c,lease,'a',1000,False)
        self.assertEqual(restored.admit(c,lease,'waiting',300000,'solver')['status'],'granted')
        self.assertEqual(restored.admit(c,lease,'waiting',300000,'solver')['status'],'granted')
        self.assertEqual(restored.usage(c)['requests'],4)
        events=[e for e in restored.events(c,0) if e['type']=='admission_waiting' and e.get('requestId')=='waiting']
        self.assertEqual(len(events),1)

    def test_meta_can_revise_plan_when_solver_waits_on_its_reserve(self):
        c,_=self.activity(softTokenLimit=1000000,reserveTokens=0)
        self.plan(c,revision=1,closeoutReserveTokens=800000)
        self.assertEqual(self.store.admit(c,c+'-lease','solver',300000,'solver')['code'],'budget_plan_wait')
        self.store.put('leases',{'id':c+'-meta','campaignId':c,'role':'meta','deadline':10000})
        self.assertEqual(self.store.admit(c,c+'-meta','meta',300000,'meta')['status'],'granted')
        self.store.settle(c,c+'-meta','meta',100,False)
        self.plan(c,revision=2,closeoutReserveTokens=0)
        self.assertEqual(self.store.admit(c,c+'-lease','solver',300000,'solver')['status'],'granted')

    def test_wait_can_end_by_cancellation_and_deadline(self):
        c,_=self.activity(softTokenLimit=1000000,reserveTokens=0)
        lease=self.store.get('leases',c+'-lease');lease['revoked']=True;self.store.put('leases',lease)
        self.assertEqual(self.store.admit(c,lease['id'],'cancel',300000,'solver')['code'],'request_cancelled')
        lease['revoked']=False;self.store.put('leases',lease);self.now=9000
        self.assertEqual(self.store.admit(c,lease['id'],'late',300000,'solver')['code'],'trial_deadline')

    def test_legacy_keeps_original_deadlines_and_reserves(self):
        c,candidate=self.activity(plan=False,resourcePolicy=None)
        self.assertEqual(self.store.get('campaigns',c)['config']['reserveSeconds'],720)
        self.store.submit(c,candidate,[TASK],1,'b')
        self.assertEqual(self.store.claim(c)['taskTimeLimitSeconds'],3600)
        with self.assertRaises(Refused):self.plan(c)

    def test_diagnosis_and_rule_version_preserve_budget_censoring(self):
        run=self.root/'run';runtime=run/'harbor/t/phyexp';runtime.mkdir(parents=True)
        (runtime/'runtime-summary.json').write_text(json.dumps({'status':'error','failureContract':'request-failure-v2',
            'failure':{'code':'budget_admission_denied','stage':'admission','source':'host-admission'}}))
        failure=diagnose(run);self.assertEqual(failure['code'],'budget_admission_denied')
        trial={'state':'failed','score':None,'failure':failure}
        self.assertEqual(task_outcome(trial,{'taskEvaluationRule':RESOURCE_RULE})['category'],'cancelled')
        self.assertEqual(task_outcome(trial,{'taskEvaluationRule':RULE})['category'],'unresolved')

    def test_recovery_projection_keeps_successful_recovery(self):
        c,_=self.activity();folder=self.root/'result';folder.mkdir()
        recovery={'failedRequests':1,'recoveredRequests':1,'failures':[]}
        (folder/'summary.json').write_text(json.dumps({'officialReward':1,'failureContract':'request-failure-v2','requestRecovery':recovery}))
        library=EvidenceLibrary(self.store,self.root)
        row=library.ingest({'id':'fixture-trial','campaignId':c,'task':TASK,'output':str(folder)})[0]
        self.assertEqual(json.loads(Path(row['path']).read_text())['requestRecovery'],recovery)


if __name__=='__main__':unittest.main()
