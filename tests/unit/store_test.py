import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from src.control.store import Store,Conflict,Refused,PUBLIC_TASKS,RETENTION_RULE

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=1000
        self.store=Store(Path(self.temp.name)/'control.sqlite',clock=lambda:self.now)
        self.config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
            'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},'tasks':list(PUBLIC_TASKS),
            'maxRounds':2,'maxTrials':10,'concurrency':1,'wallTimeSeconds':7200,'trialTimeSeconds':3600,
            'softTokenLimit':3000000,'reserveSeconds':900,'reserveTokens':300000,'retries':0}
        self.c=self.store.create(self.config,'create')['id'];self.store.control(self.c,'start','start')
        self.candidate=self.store.candidate(self.c,{'id':'hash','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})['id']
    def tearDown(self):self.temp.cleanup()
    def submit(self,key='batch',tasks=None,repeats=1):return self.store.submit(self.c,self.candidate,tasks or [PUBLIC_TASKS[0]],repeats,key)
    def test_one_candidate_five_tasks_two_repeats_is_one_round_ten_trials(self):
        b=self.submit(tasks=list(PUBLIC_TASKS),repeats=2)
        self.assertEqual(b['plannedTrials'],10);self.assertEqual(self.store.status(self.c)['counts']['rounds'],1)
        t=self.store.claim(self.c);self.assertIsNotNone(t);self.assertIsNone(self.store.claim(self.c))
        self.store.trial_update(t['id'],state='failed',stopReason='startup_failure')
        self.assertIsNotNone(self.store.claim(self.c))
        self.assertEqual(self.store.status(self.c)['counts']['trials'],10)
    def test_idempotent_acceptance_and_conflicting_payload(self):
        first=self.submit();self.assertEqual(first,self.submit())
        self.assertRaises(Conflict,self.submit,'batch',[PUBLIC_TASKS[1]])
        self.assertEqual(self.store.status(self.c)['counts']['rounds'],1)
    def test_task_evaluation_rule_binds_at_creation_and_replays_without_migration(self):
        self.assertEqual(self.store.get('campaigns',self.c)['config']['taskEvaluationRule'],'task-completion-v2')
        old=self.store.create({**self.config,'taskEvaluationRule':'task-completion-v1'},'v1')
        self.assertEqual(self.store.create({**self.config,'taskEvaluationRule':'task-completion-v1'},'v1'),old)
        self.assertEqual(self.store.get('campaigns',old['id'])['config']['taskEvaluationRule'],'task-completion-v1')
        self.assertRaises(Refused,self.store.create,{**self.config,'taskEvaluationRule':'unknown'},'invalid-rule')
    def test_simultaneous_last_round_admission_is_atomic(self):
        self.store.control(self.c,'limits','limit',changes={'maxRounds':1})
        def work(i):
            try:return self.submit(str(i))
            except Refused:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.store.status(self.c)['counts']['rounds'],1)
    def test_pause_time_keeps_running_and_expired_resume_only_closes(self):
        self.submit();self.store.control(self.c,'pause','pause');self.assertIsNone(self.store.claim(self.c))
        self.now+=7201;self.assertEqual(self.store.status(self.c)['elapsedSeconds'],7201)
        self.assertEqual(self.store.control(self.c,'resume','resume')['state'],'closing');self.assertIsNone(self.store.claim(self.c))
    def test_unknown_usage_retains_reservation_and_conflicting_settlement_rejected(self):
        r=self.store.reserve(self.c,'meta','request',300000,'meta');self.assertEqual(r,self.store.reserve(self.c,'meta','request',300000,'meta'))
        self.store.settle(self.c,'meta','request',None,True)
        usage=self.store.usage(self.c);self.assertEqual(usage['unknownReservedTokens'],300000);self.assertEqual(usage['unknownRequests'],1)
        self.assertRaises(Conflict,self.store.settle,self.c,'meta','request',10,False)
        for i in range(8):self.store.reserve(self.c,'solver',str(i),300000,'solver')
        self.assertRaises(Refused,self.store.reserve,self.c,'solver','overflow',300000,'solver')
        self.store.reserve(self.c,'report','closeout',300000,'report')
    def test_cancel_releases_only_unstarted_slots_and_keeps_round(self):
        self.submit(repeats=3);t=self.store.claim(self.c)
        self.store.control(self.c,'stop','stop')
        status=self.store.status(self.c)
        self.assertEqual(status['counts']['rounds'],1);self.assertEqual(status['counts']['trials'],1)
        self.assertEqual(status['counts']['startedTrials'],1)
        self.store.trial_update(t['id'],state='failed',score=None)
        self.assertEqual(self.store.list('batches',self.c)[0]['state'],'finished')
    def test_user_revision_check_and_provider_capability_check(self):
        self.assertRaises(Conflict,self.store.control,self.c,'pause','stale',1)
        self.assertRaises(Refused,self.store.create,{**self.config,'hardTokenLimit':1},'hard')
        self.assertRaises(Refused,self.store.control,self.c,'limits','change-model',changes={'solver':{}})
    def test_retention_compares_each_task_and_refuses_changed_environment_or_regression(self):
        c=self.store.get('campaigns',self.c);c['config']['retentionRule']=RETENTION_RULE;self.store.put('campaigns',c)
        other=self.store.candidate(self.c,{'id':'candidate-hash','path':'/fixture','plugins':[]},'H1',check={'status':'passed'})['id']
        self.store.put('evidence',{'id':'e','campaignId':self.c})
        for candidate in [self.candidate,other]:
            for index,task in enumerate(PUBLIC_TASKS):
                self.store.put('trials',{'id':candidate+str(index),'campaignId':self.c,'candidateId':candidate,
                    'task':task,'score':1,'state':'finished','comparisonContext':{'taskImageIds':['image-'+task],'runnerImageId':'runner'}})
        self.store.retain(self.c,self.candidate,'Baseline',['e'])
        row=self.store.get('trials',other+'0');row['comparisonContext']['runnerImageId']='changed';self.store.put('trials',row)
        self.assertRaisesRegex(Refused,'not comparable',self.store.retain,self.c,other,'Changed',['e'])
        row['comparisonContext']['runnerImageId']='runner';row['score']=None;self.store.put('trials',row)
        self.assertRaisesRegex(Refused,'official result',self.store.retain,self.c,other,'Incomplete',['e'])
        row['score']=0;self.store.put('trials',row)
        self.assertRaisesRegex(Refused,'regression',self.store.retain,self.c,other,'Worse',['e'])
        row['score']=1;self.store.put('trials',row)
        self.assertEqual(self.store.retain(self.c,other,'Matched conditions',['e'])['retainedCandidateId'],other)
