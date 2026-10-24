"""New model requests never reserve/settle usage; run controls remain authoritative."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.control.service import ControlService
from src.control.server import make_app
from src.control.store import Refused
from src.control.model_access import POLICY, check_access
from src.control.meta_contracts import CONTRACTS, binding

ROOT=Path(__file__).resolve().parents[2]
TASK='time_budgeted_hamlearn_10q'
MODEL={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}


class ModelAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.service=ControlService(ROOT,Path(self.temp.name),ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.addCleanup(self.service.pool.shutdown,wait=True)
        self.client=TestClient(make_app(self.service,supervise=False));self.addCleanup(self.client.close)
        self.store=self.service.store
        self.config={'solver':MODEL,'meta':MODEL,'tasks':[TASK],'wallTimeSeconds':7200,'concurrency':1,
            'maxTrials':2,'modelAccessPolicy':POLICY,'resourcePolicy':'meta-resource-planning-v1'}
        self.c=self.store.create(self.config,'new')['id'];self.store.control(self.c,'start','start')
        self.lease,self.token=self.service.lease(self.c,'solver',time.time()+3600)
        self.client.headers['Authorization']='Bearer '+self.token
        self.route='/model-access/'+self.lease['id']

    def test_read_only_requests_survive_writer_and_never_touch_accounting(self):
        before=self.store.last_event(self.c)
        with self.store.connection(True) as writer, patch.object(self.store,'reserve',side_effect=AssertionError('reserve')),patch.object(self.store,'settle',side_effect=AssertionError('settle')):
            for _ in range(3):self.assertEqual(self.client.post(self.route,json={}).json(),{'status':'granted'})
        self.assertEqual(self.store.last_event(self.c),before)
        self.assertEqual(self.store.list('usage',self.c),[]);self.assertEqual(self.store.list('admissions',self.c),[])
        self.assertEqual(self.store.status(self.c)['usage'],{'status':'not_collected'})
        with self.assertRaisesRegex(Refused,'unavailable'):self.store.admit(self.c,self.lease['id'],'r',300000,'solver')

    def test_authority_deadline_cancel_and_storage_are_independent_of_usage(self):
        with patch.object(self.service.storage,'permit',return_value=False):
            result=self.client.post(self.route,json={});self.assertEqual(result.status_code,429)
            self.assertEqual(result.json()['code'],'storage_capacity_wait')
        self.assertEqual(self.client.post(self.route,json={}).status_code,200)
        self.assertEqual(self.client.post('/model-access/not-owned',json={}).status_code,403)
        self.client.headers['Authorization']='Bearer wrong'
        self.assertEqual(self.client.post(self.route,json={}).json()['code'],'request_auth_failed')
        self.client.headers['Authorization']='Bearer '+self.token
        with patch.object(self.store,'clock',return_value=time.time()+8000):
            self.assertEqual(self.client.post(self.route,json={}).json()['code'],'trial_deadline')
        self.store.control(self.c,'stop','stop')
        self.store.put('leases',{**self.lease,'revoked':True})
        self.assertEqual(self.client.post(self.route,json={}).json()['code'],'request_lease_expired')

    def test_registered_meta_and_pause_resume_keep_the_same_authority(self):
        lease,token=self.service.lease(self.c,'meta',time.time()+3600)
        self.client.headers['Authorization']='Bearer '+token;route='/model-access/'+lease['id']
        self.assertEqual(self.client.post(route,json={'agentId':'child'}).status_code,403)
        self.store.put('meta_sessions',{'id':'session','campaignId':self.c,'leaseId':lease['id'],'state':'running','agents':{'child':{'preset':'phyexp-researcher'}}})
        self.assertEqual(self.client.post(route,json={'agentId':'child'}).status_code,200)
        self.store.control(self.c,'pause','pause')
        self.assertEqual(self.client.post(route,json={'agentId':'child'}).json()['code'],'request_cancelled')
        # An already-started Solver continues under the documented pause semantics.
        self.assertEqual(check_access(self.store,self.lease['id'])['status'],'granted')
        self.store.control(self.c,'resume','resume')
        self.assertEqual(self.client.post(route,json={'agentId':'child'}).status_code,200)

    def test_plan_counts_concurrency_reports_and_restart_without_usage(self):
        cfg=self.store.get('campaigns',self.c)['config']
        for key in ['softTokenLimit','reserveTokens','limitKind']:self.assertNotIn(key,cfg)
        plan={'parallelism':1,'defaultTrialTimeSeconds':3600,'closeoutReserveSeconds':0}
        self.store.update_plan(self.c,plan,'time and concurrency','plan',0)
        candidate=self.store.candidate(self.c,{'id':'fixture','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})['id']
        batch=self.store.submit(self.c,candidate,[TASK],2,'batch')
        first=self.store.claim(self.c);self.assertIsNotNone(first);self.assertIsNone(self.store.claim(self.c))
        self.store.trial_update(first['id'],state='failed',stopReason='model_transport_error',finishedAt=time.time())
        self.assertIsNotNone(self.store.claim(self.c))
        with self.assertRaises(Refused):self.store.submit(self.c,candidate,[TASK],1,'extra')
        facts=self.service.reports.facts(self.c)
        self.assertNotIn('usageByRole',facts)
        report=self.service.reports.status_summary(self.c,'offline check')
        from src.reporting.reading import render_reading
        self.assertNotIn('token',render_reading(report))
        self.assertTrue(all('accountedUsage' not in t for t in facts['trials']))
        from src.control.store import Store
        restored=Store(self.store.path)
        self.assertEqual(restored.status(self.c)['counts']['startedTrials'],2)
        self.assertEqual(restored.list('usage',self.c),[])
        for changes in [{'softTokenLimit':10},{'reserveTokens':0}]:
            with self.assertRaises(Refused):self.store.control(self.c,'limits',str(changes),changes=changes)
        with self.assertRaises(Refused):self.store.update_plan(self.c,{**plan,'closeoutReserveTokens':0},'obsolete','bad',1)

    def test_current_contract_omits_tokens_and_historical_v7_is_exact(self):
        current=CONTRACTS['meta-tools-v8']['campaign_plan_update']['input']['properties']['changes']
        self.assertEqual(set(current['required']),{'parallelism','closeoutReserveSeconds'})
        self.assertNotIn('closeoutReserveTokens',current['properties'])
        self.assertIn('closeoutReserveTokens',CONTRACTS['meta-tools-v7']['campaign_plan_update']['input']['properties']['changes']['required'])
        # The old binding continues to match the bytes previously frozen in activities.
        import hashlib
        from src.control.store import encoded
        self.assertEqual(hashlib.sha256(encoded(binding('meta-tools-v7')).encode()).hexdigest(),
                         '8857acf860ae99983057cac5da6fabef3e2f243ba4e633a39b386cddefff9a69')
