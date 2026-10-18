import json
import tempfile
import time
import unittest
from pathlib import Path
from src.control.service import ControlService
from src.control.meta import MetaDriver
from src.control.store import Refused,Conflict
ROOT=Path(__file__).resolve().parents[2]
class MetaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=ControlService(ROOT,Path(self.temp.name),ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.store=self.service.store;self.driver=MetaDriver(self.service)
        config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},'tasks':['time_budgeted_hamlearn_10q'],'maxRounds':1,'maxTrials':1,'concurrency':1,'wallTimeSeconds':7200,'trialTimeSeconds':3600,'softTokenLimit':3000000,'reserveSeconds':900,'reserveTokens':300000}
        self.c=self.store.create(config,'fixture')['id'];self.store.control(self.c,'start','start')
        candidate=self.store.candidate(self.c,{'id':'fixture','path':'/fixture','plugins':[]},'Fixture H0',check={'status':'passed'})
        self.batch=self.store.submit(self.c,candidate['id'],config['tasks'],1,'fixture');self.trial=self.store.claim(self.c)
    def tearDown(self):self.service.pool.shutdown(wait=True);self.temp.cleanup()
    def test_unknown_only_trusted_host_audit_can_reconcile(self):
        self.store.reserve(self.c,'lease','request',300000,'solver');self.store.mark_unknown('lease')
        with self.assertRaises(Conflict):self.store.settle(self.c,'lease','request',120,False)
        self.store.settle(self.c,'lease','request',120,False,host_audit=True)
        u=self.store.usage(self.c);self.assertEqual(u['confirmedTokens'],120);self.assertEqual(u['unknownRequests'],0)
        with self.assertRaises(Conflict):self.store.settle(self.c,'lease','request',0,False,host_audit=True)
    def test_closeout_requires_each_round_and_final_analysis(self):
        self.service._failed_trial(self.trial,'fixture_failure')
        self.store.close_admission(self.c,'round_limit');lease,_=self.service.lease(self.c,'meta',time.time()+60)
        session=self.store.put('meta_sessions',{'id':'meta-fixture','campaignId':self.c,'leaseId':lease['id'],'state':'waiting'})
        self.assertFalse(self.driver.notifications(session['id'],0)['finish'])
        evidence=self.store.list('evidence',self.c)[0]
        a={'summary':'Fixture failure, not a scientific outcome','observations':['No experiment ran'],'hypotheses':[],'limitations':['fixture'],'decision':'No selection','evidenceRefs':[evidence['id']]}
        self.service.reports.save(self.c,a);self.assertFalse(self.driver.notifications(session['id'],0)['finish'])
        self.service.reports.save(self.c,a,self.batch['id']);self.assertTrue(self.driver.notifications(session['id'],0)['finish'])
        self.assertRaises(Refused,self.service.meta_call,self.c,'workspace_write',{'path':'new.mjs','content':'x'})
    def test_crashed_build_is_marked_failed_without_retry_or_charge(self):
        self.store.put('operations',{'id':'operation-fixture','campaignId':self.c,'kind':'freeze','state':'running','payload':{}})
        restart=ControlService(ROOT,self.service.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        try:
            self.assertEqual(restart.store.get('operations','operation-fixture')['state'],'failed')
            self.assertEqual(restart.store.status(self.c)['counts']['rounds'],1)
        finally:restart.pool.shutdown(wait=True)
    def test_error_finish_zero_usage_is_conservatively_unknown(self):
        self.store.reserve(self.c,'lease','request',300000,'solver');self.store.settle(self.c,'lease','request',0,False)
        self.store.settle(self.c,'lease','request',0,True,host_audit=True)
        self.assertEqual(self.store.usage(self.c)['unknownReservedTokens'],300000)
    def test_host_proxy_policy_preserves_loopback_and_is_explicit(self):
        from src.execution.host.network import provider_environment
        env=provider_environment({'HTTPS_PROXY':'http://127.0.0.1:7897','NO_PROXY':'internal.example'})
        self.assertEqual(env['NODE_USE_ENV_PROXY'],'1');self.assertIn('127.0.0.1',env['NO_PROXY']);self.assertIn('internal.example',env['NO_PROXY'])
        self.assertNotIn('NODE_USE_ENV_PROXY',provider_environment({}))
