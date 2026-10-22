import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from src.control.service import ControlService
from src.control.server import make_app
from src.control.result_collection import read_summary
from src.execution.bundle.freeze import freeze
from src.execution.adapters.quantum_harbor.results import archive_manifest

ROOT = Path(__file__).resolve().parents[2]
TASK = 'time_budgeted_hamlearn_10q'


class ResultCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.service = ControlService(ROOT, self.root, ROOT.parent/'Quantum-Harbor', 'http://127.0.0.1:1')
        self.addCleanup(self.service.pool.shutdown)
        self.client = TestClient(make_app(self.service, supervise=False))
        self.addCleanup(self.client.close)
        self.client.headers['Authorization'] = 'Bearer '+self.service.user_token
        self.store = self.service.store
        cfg = {'solver': {'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
               'meta': {'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
               'tasks':[TASK], 'maxRounds':2, 'maxTrials':3, 'concurrency':1, 'wallTimeSeconds':7200,
               'trialTimeSeconds':3600, 'softTokenLimit':3000000, 'reserveSeconds':900, 'reserveTokens':300000}
        self.cid = self.store.create(cfg, 'fixture')['id']
        self.store.control(self.cid, 'start', 'start')
        bundle = freeze(ROOT, self.root/'objects', json.loads((ROOT/'recipes/h0-sol.json').read_text()))
        self.candidate = self.store.candidate(self.cid, bundle, 'Fixture', check={'status':'passed'})
        self.store.submit(self.cid, self.candidate['id'], [TASK], 1, 'one')
        trial = self.store.claim(self.cid)
        self.output = self.root/'trials'/trial['launchId']
        self.base = self.output/'harbor/trial'
        self.write('harbor/result.json', {'stats':{'n_completed_trials':1,'n_errored_trials':0}})
        self.write('harbor/trial/result.json', {'task_name':TASK,'trial_name':'trial',
                   'exception_info':None,'verifier_result':{'rewards':{'reward':0}}})
        self.write('harbor/trial/lock.json', {'task':{'digest':'fixture'}})
        self.write('harbor/trial/phyexp/runtime-summary.json', {'status':'completed','toolCalls':2,
                   'recipe':{'plugins':[]},'bundleId':bundle['id'],'model':'gpt-6-sol','provider':'openai-codex'})
        self.write('harbor/trial/phyexp/events.json', [{'type':'assistant/message','data':{'usage':{
                   'inputTokens':10,'outputTokens':3,'cacheReadTokens':20,'totalTokens':33}}}])
        self.write('harbor/trial/verifier/artifacts/score_report.json',
                   {'task_id':TASK,'reward_binary':0,'result':{'binary_pass':False}})
        self.write('harbor/trial/verifier/artifacts/final_answer.json', {'answer':{}})
        (self.base/'verifier/reward.txt').write_text('0\n')
        (self.base/'verifier/artifacts/experiment_log.jsonl').write_text('{"action":"probe"}\n')
        self.write('provenance.json', {'bundleId':bundle['id'],'task':TASK})
        self.original = {'pipelineStatus':'failed','officialReward':None,'status':'infrastructure_error',
                         'error':"'id'",'stopReason':'runtime_failed','failure':{'code':'runtime_failed'},
                         'usage':{'totalTokens':33},'scoringStatus':'completed','bundleId':bundle['id']}
        self.write('summary.json', self.original)
        archive_manifest(self.output)
        self.trial = self.store.trial_update(trial['id'], output=str(self.output),state='failed',
            score=None,stopReason='runtime_failed',finishedAt=100,usage={'totalTokens':33},summary=self.original)
        self.store.control(self.cid, 'pause', 'pause')

    def write(self, name, value):
        p = self.output/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))

    def recover(self):
        return self.client.post('/trials/'+self.trial['id']+'/recollect')

    def test_score_recovery_is_idempotent_and_preserves_archive_timing_ledger_and_selection(self):
        before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.rglob('*') if p.is_file()}
        campaign = self.store.get('campaigns', self.cid)
        usage = self.store.usage(self.cid)
        response = self.recover();self.assertEqual(response.status_code,200,response.text)
        trial = self.store.get('trials', self.trial['id'])
        self.assertEqual(trial['score'],0);self.assertEqual(trial['state'],'finished')
        self.assertIsNone(trial['failure']);self.assertIsNone(trial['stopReason'])
        self.assertEqual(trial['finishedAt'],100);self.assertEqual(trial['usage'],{'totalTokens':33})
        self.assertEqual(self.store.get('campaigns',self.cid),campaign)
        self.assertEqual(self.store.usage(self.cid),usage)
        after = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(self.recover().json()['status'],'already_recovered')
        self.assertEqual(len(list((self.root/'result-recoveries').iterdir())),1)
        events = [x for x in self.store.events(self.cid) if x['type']=='trial_result_recollected']
        self.assertEqual(len(events),1)
        shown=self.client.get('/campaigns/'+self.cid).json()
        self.assertEqual(shown['taskEvaluation']['total']['officialScored'],1)
        self.assertEqual(shown['trials'][0]['taskAssessment']['category'],'failed')
        evidence=self.store.list('evidence',self.cid)[0]
        self.assertEqual(json.loads(Path(evidence['path']).read_text())['officialReward'],0)

    def test_current_controller_collects_old_frozen_summary_without_relaunch(self):
        trial=self.store.trial_update(self.trial['id'],state='running',score=None)
        self.service._collect(trial)
        self.assertEqual(self.store.get('trials',trial['id'])['score'],0)
        self.assertEqual(json.loads((self.output/'summary.json').read_text()),self.original)

    def test_recovered_official_one_remains_one(self):
        (self.base/'verifier/reward.txt').write_text('1\n')
        self.write('harbor/trial/result.json',{'task_name':TASK,'trial_name':'trial',
            'exception_info':None,'verifier_result':{'rewards':{'reward':1}}})
        self.write('harbor/trial/verifier/artifacts/score_report.json',
            {'task_id':TASK,'reward_binary':1,'result':{'binary_pass':True}})
        archive_manifest(self.output)
        self.assertEqual(self.recover().json()['score'],1)

    def test_missing_or_uncovered_official_evidence_cannot_become_zero(self):
        (self.base/'verifier/reward.txt').unlink()
        archive_manifest(self.output)
        with self.assertRaises(FileNotFoundError):read_summary(self.trial,self.candidate)
        (self.base/'verifier/reward.txt').write_text('0\n')
        with self.assertRaisesRegex(ValueError,'not covered'):read_summary(self.trial,self.candidate)
        self.assertIsNone(self.store.get('trials',self.trial['id'])['score'])

    def test_changed_or_wrong_candidate_archive_is_refused(self):
        (self.base/'verifier/reward.txt').write_text('1\n')
        with self.assertRaisesRegex(ValueError,'mismatch'):read_summary(self.trial,self.candidate)
        (self.base/'verifier/reward.txt').write_text('0\n')
        self.write('provenance.json',{'bundleId':'wrong','task':TASK});archive_manifest(self.output)
        self.assertEqual(self.recover().status_code,400)

    def test_authority_pause_and_inflight_guards(self):
        self.store.control(self.cid,'resume','resume')
        self.assertEqual(self.recover().status_code,403)
        self.store.control(self.cid,'pause','again')
        self.store.trial_update(self.trial['id'],state='running')
        self.assertEqual(self.recover().status_code,403)
        self.store.trial_update(self.trial['id'],state='failed')
        for role in ['meta','solver']:
            _,token=self.service.lease(self.cid,role,time.time()+60)
            self.client.headers['Authorization']='Bearer '+token
            self.assertEqual(self.recover().status_code,403)

    def test_bridge_fault_gets_no_fabricated_score(self):
        self.write('harbor/trial/result.json',{'task_name':TASK,'exception_info':{'exception_type':'RuntimeError',
            'exception_message':'Container transport failed: Only a nonempty command is accepted'},'verifier_result':None})
        self.write('summary.json',{**self.original,'error':'Expected exactly one completed trial and no infrastructure errors'})
        archive_manifest(self.output)
        self.assertEqual(self.recover().status_code,200)
        trial=self.store.get('trials',self.trial['id'])
        self.assertIsNone(trial['score'])
        self.assertEqual(trial['failure']['code'],'container_transport_error')
        self.assertEqual(trial['scoringStatus'],'not_run')
        shown=self.client.get('/campaigns/'+self.cid).json()['trials'][0]
        self.assertEqual(shown['taskAssessment']['category'],'external_failure')
