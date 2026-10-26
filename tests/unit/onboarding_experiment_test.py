"""First-activity commands retain one identity across uncertain network results."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.onboarding import experiment as exp
from src.onboarding.common import Problem, read_json


class FakeAPI:
    def __init__(self):
        self.calls=[]; self.creates={}; self.lose_create=False; self.lose_start=False; self.credential='configured'
        self.detail={'id':'campaign-test', 'state':'draft', 'startedAt':None, 'revision':3,
                     'operations':[{'kind':'prepare_h0','state':'finished','startedAt':1}], 'candidates':[{'id':'h0'}],
                     'trials':[], 'backgroundWork':[], 'metaStatus':None}
    def request(self, route, body=None):
        self.calls.append((route,copy.deepcopy(body)))
        if route=='/models':return {'revision':1,'models':[{'provider':'test','model':'solver','reasoningEfforts':[],'defaultReasoningEffort':None}, {'provider':'test','model':'meta','reasoningEfforts':['medium'],'defaultReasoningEffort':'medium'}]}
        if route=='/tasks':return {'tasks':[{'id':'task','requiredTimeSeconds':5000}]}
        if route=='/providers':return {'providers':[{'id':'test','credential':{'state':self.credential}}]}
        if route=='/campaigns':
            key=body['idempotencyKey']
            if key in self.creates:assert self.creates[key]==body
            self.creates[key]=copy.deepcopy(body)
            if self.lose_create:self.lose_create=False;raise Problem('request_unknown','timeout',exit_code=3)
            return {'id':self.detail['id']}
        if route.endswith('/control'):
            self.detail.update(state='running',startedAt=100,revision=4)
            if self.lose_start:self.lose_start=False;raise Problem('request_unknown','timeout',exit_code=3)
            return copy.deepcopy(self.detail)
        return copy.deepcopy(self.detail)


class FirstExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.config={'data_dir':self.temp.name,'ui_url':'http://127.0.0.1:18401'}
        self.api=FakeAPI()
        self.patch=patch.object(exp,'client',return_value=self.api);self.patch.start();self.addCleanup(self.patch.stop)
    def init(self, **extra):
        return exp.initialize(self.config,'first',solver=['test','solver'],meta=['test','meta'],task='task',**extra)

    def test_init_is_bounded_no_model_and_same_inputs_reuse(self):
        result=self.init();cfg=result['config']
        self.assertEqual((cfg['maxTrials'],cfg['maxRounds'],cfg['concurrency']),(1,1,1))
        self.assertEqual(cfg['wallTimeSeconds'],6800);self.assertNotIn('reasoningEffort',cfg['solver'])
        self.assertEqual(cfg['meta']['reasoningEffort'],'medium')
        before=read_json(exp.session_path(self.config,'first'));self.api.calls.clear()
        self.assertTrue(self.init()['reused']);self.assertEqual(self.api.calls,[])
        self.assertEqual(read_json(exp.session_path(self.config,'first')),before)
        with self.assertRaises(Problem) as error:self.init(wall_time=9000)
        self.assertEqual(error.exception.code,'session_config_changed')
        self.assertFalse(any(route=='/campaigns' for route,_ in self.api.calls))

    def test_explicit_short_window_is_allowed_without_changing_benchmark(self):
        result=self.init(wall_time=100)
        self.assertEqual(result['config']['wallTimeSeconds'],100)
        self.assertEqual(result['benchmarkReservationSeconds'],5000)
        self.assertNotIn('trialTimeSeconds',result['config'])

    def test_nonpositive_activity_time_is_rejected(self):
        with self.assertRaises(Problem) as error:self.init(wall_time=0)
        self.assertEqual(error.exception.code,'invalid_time')

    def test_create_timeout_replays_identical_body_after_command_restart(self):
        self.init();self.api.lose_create=True
        with self.assertRaises(Problem):exp.prepare(self.config,'first')
        self.assertNotIn('campaignId',read_json(exp.session_path(self.config,'first')))
        result=exp.prepare(self.config,'first')
        self.assertEqual(result['preparation'],'ready');self.assertEqual(len(self.api.creates),1)
        bodies=[body for route,body in self.api.calls if route=='/campaigns']
        self.assertEqual(bodies[0],bodies[1])
        exp.prepare(self.config,'first');self.assertEqual(len([r for r,_ in self.api.calls if r=='/campaigns']),2)

    def test_unknown_start_does_not_start_again_when_backend_committed(self):
        self.init();exp.prepare(self.config,'first');self.api.lose_start=True
        with self.assertRaises(Problem):exp.start_experiment(self.config,'first')
        request=read_json(exp.session_path(self.config,'first'))['startRequest']
        result=exp.start_experiment(self.config,'first')
        self.assertTrue(result['reused']);self.assertEqual(len([r for r,_ in self.api.calls if r.endswith('/control')]),1)
        self.assertEqual(read_json(exp.session_path(self.config,'first'))['startRequest'],request)

    def test_missing_credentials_do_not_send_start(self):
        self.init();exp.prepare(self.config,'first');self.api.credential='missing'
        with self.assertRaises(Problem) as error:exp.start_experiment(self.config,'first')
        self.assertEqual(error.exception.code,'credential_missing');self.assertFalse(any(r.endswith('/control') for r,_ in self.api.calls))

    def test_preparation_failure_and_null_meta_health_have_explicit_result(self):
        self.init();self.api.detail['operations'][0]['state']='failed'
        self.assertEqual(exp.prepare(self.config,'first')['status'],'failed')
        self.assertEqual(exp.experiment_status(self.config,'first')['status'],'failed')

    def test_zero_score_passes_only_with_official_digests_and_indexed_evidence(self):
        root=Path(self.temp.name)/'trials/test';sources={}
        for name,value in [('harbor/t/verifier/reward.txt','0'),('harbor/t/verifier/artifacts/score_report.json','{"reward_binary":0}')]:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
            sources[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        trial={'id':'trial-test','state':'finished','score':0,'scoringStatus':'completed','output':str(root),
               'officialResult':{'status':'available','sources':sources},'evidenceIndex':{'state':'complete'},'evidenceStatus':{'status':'complete'}}
        detail={**self.api.detail,'state':'finished','trials':[trial]}
        self.assertEqual(exp.assessment(detail,self.config)['status'],'passed')
        trial['evidenceIndex']['state']='pending'
        self.assertEqual(exp.assessment(detail,self.config)['status'],'failed')
        trial['evidenceIndex']['state']='complete';trial['score']=None
        self.assertEqual(exp.assessment(detail,self.config)['status'],'failed')
        trial['score']=0;(root/'harbor/t/verifier/reward.txt').write_text('1')
        self.assertEqual(exp.assessment(detail,self.config)['status'],'failed')

    def test_pending_status_and_session_path_escape(self):
        self.init();self.assertEqual(exp.experiment_status(self.config,'first')['status'],'pending')
        with self.assertRaises(Problem):exp.session_path(self.config,'../other')
        with self.assertRaises(Problem):exp.wait(self.config,'first',120)


if __name__=='__main__':unittest.main()
