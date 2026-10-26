import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from src.control.service import ControlService
from src.control.server import make_app
from src.control.meta_context import activity_state
from src.evidence.outcomes import (task_outcome, outcome_summary, END_TO_END_RULE, RULE, RESOURCE_RULE,
                                   OUTPUT_FAILURES, EXTERNAL_FAILURES)
from src.evidence.diagnostics import trial_diagnostics

ROOT=Path(__file__).resolve().parents[2]
TASK='time_budgeted_hamlearn_10q'
CONFIG={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
        'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
        'tasks':[TASK],'concurrency':1,'wallTimeSeconds':7200}
V4={'taskEvaluationRule':END_TO_END_RULE}


class V4OutcomesTests(unittest.TestCase):
    def trial(self,code=None,**changes):
        return {'id':'trial','task':TASK,'state':'failed','score':None,'startedAt':100,'finishedAt':200,
                'failure':{'code':code} if code else None,**changes}

    def test_every_settled_failure_counts_and_preserves_raw_score(self):
        codes=OUTPUT_FAILURES|EXTERNAL_FAILURES|{'accounting_unavailable','accounting_lease_expired',
            'accounting_auth_failed','accounting_protocol_error','budget_admission_denied','trial_deadline',
            'campaign_deadline','request_timeout','request_cancelled','runtime_failed','unknown_new_error',
            'no_submission','invalid_submission',None}
        for code in codes:
            with self.subTest(code=code):
                row=self.trial(code);before=copy.deepcopy(row)
                shown=trial_diagnostics([row],config=V4)[0];o=shown['taskAssessment']
                self.assertEqual((o['category'],o['score'],o['included']),('failed',0,True))
                self.assertTrue(shown['completionLabel'].startswith('失败 · '))
                self.assertNotIn('官方未评分',shown['completionLabel'])
                self.assertIsNone(shown['score']);self.assertEqual(row,before)
        self.assertEqual(task_outcome(self.trial('request_timeout',failure={'code':'request_timeout','observed':{'responseBytes':0}}),V4)['score'],0)

    def test_live_and_unconfirmed_processes_are_not_premature_failures(self):
        for state in ['reserved','queued','launching','running']:
            for score in [None,1]:
                self.assertEqual(task_outcome(self.trial('stream_whitespace',state=state,score=score),V4)['category'],'pending')
        for end in [None,False,float('nan')]:
            self.assertEqual(task_outcome(self.trial(state='unknown',finishedAt=end),V4)['category'],'unresolved')
        self.assertEqual(task_outcome(self.trial(state='unknown'),V4)['score'],0)
        self.assertEqual(task_outcome(self.trial(state='finished'),V4)['score'],0)

    def test_not_started_and_operator_cancellation_exceptions(self):
        for code in ['budget_admission_denied','startup_failure','campaign_deadline',None]:
            self.assertEqual(task_outcome(self.trial(code,startedAt=None),V4)['category'],'not_started')
        self.assertEqual(task_outcome(self.trial('user_stop',state='cancelled'),V4)['category'],'cancelled')
        self.assertEqual(task_outcome(self.trial('request_cancelled',stopReason='user_stop'),V4)['category'],'cancelled')
        # Generic request cancellation and automatic time cuts are not evidence of an operator action.
        self.assertEqual(task_outcome(self.trial('request_cancelled',state='cancelled'),V4)['score'],0)
        self.assertEqual(task_outcome(self.trial('trial_deadline',deadline=120,taskTimeLimitSeconds=60),V4)['score'],0)
        self.assertEqual(task_outcome(self.trial(startedAt=0),V4)['score'],0)

    def test_stop_cannot_erase_confirmed_failure_but_cleanup_faults_do_not_prove_prior_failure(self):
        for code in OUTPUT_FAILURES:
            self.assertEqual(task_outcome(self.trial(code,stopReason='user_stop',state='cancelled'),V4)['score'],0)
        for detected in [150,'1970-01-01T00:02:30Z']:
            row=self.trial(failure={'code':'verifier_failed','detectedAt':detected},stopReason='user_stop',stopRequestedAt=180)
            self.assertEqual(task_outcome(row,V4)['score'],0)
        for detected in [190,None,'not-a-time']:
            row=self.trial(failure={'code':'model_transport_error','detectedAt':detected},stopReason='user_stop',stopRequestedAt=180)
            self.assertEqual(task_outcome(row,V4)['category'],'cancelled')

    def test_trusted_official_result_wins_and_invalid_values_never_count_as_success(self):
        for score in [0,1]:
            o=task_outcome(self.trial('archive_invalid',score=score,stopReason='user_stop',startedAt=None),V4)
            self.assertEqual(o['score'],score);self.assertEqual(o['basis'],'official_score')
        for score in [True,float('nan'),float('inf'),.5,'1']:
            row=self.trial(score=score)
            self.assertEqual(task_outcome(row,V4)['score'],0)
            self.assertEqual(outcome_summary([row],[TASK],V4)['total']['officialScored'],0)
            self.assertIn('无效',trial_diagnostics([row],config=V4)[0]['resultLabel'])

    def test_macro_rates_include_external_and_unattributed_failures_without_pooling_advantage(self):
        rows=[self.trial(score=1,task='easy') for _ in range(9)]
        rows += [self.trial('verifier_failed',task='hard'),self.trial(task='hard'),self.trial(task='hard',state='unknown',finishedAt=None),
                 self.trial(task='hard',startedAt=None),self.trial('user_stop',task='hard')]
        stats=outcome_summary(rows,['easy','hard'],V4)
        self.assertEqual(stats['macroSuccessRate'],.5)
        self.assertEqual(stats['total']['eligible'],11)
        self.assertEqual(stats['total']['derivedFailures'],2)
        self.assertEqual(stats['total']['not_started'],1)
        self.assertEqual(stats['total']['conservativeSuccessRate'],9/11)
        self.assertEqual(stats['byTask']['hard']['successRate'],0)
        self.assertIsNone(outcome_summary(rows,['easy','hard','untried'],V4)['macroSuccessRate'])

    def test_historical_rules_remain_distinct_and_cached_old_assessment_is_not_reused(self):
        row=self.trial('verifier_failed');row['taskAssessment']=task_outcome(row,{'taskEvaluationRule':RESOURCE_RULE})
        for rule in [None,'task-completion-v1',RULE,RESOURCE_RULE]:
            config={'taskEvaluationRule':rule} if rule else {}
            self.assertEqual(outcome_summary([row],[TASK],config)['total']['eligible'],0)
        self.assertEqual(outcome_summary([row],[TASK],V4)['total']['eligible'],1)


class V4IntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.fixtures.benchmark_tasks import make_tasks
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        quantum=make_tasks(Path(self.temp.name)/'synthetic-quantum', CONFIG['tasks'])
        self.service=ControlService(ROOT,Path(self.temp.name),quantum,'http://127.0.0.1:1')
        self.addCleanup(self.service.pool.shutdown,wait=True)
        self.client=TestClient(make_app(self.service,supervise=False));self.addCleanup(self.client.close)
        self.client.headers['Authorization']='Bearer '+self.service.user_token
        self.store=self.service.store

    def test_new_default_and_service_create_replay_preserve_original_versions(self):
        # This verifies version/idempotency semantics; image construction belongs
        # to the Docker contracts and must not make the unit suite build an image.
        with patch.object(self.service,'_operation',return_value={}), \
             patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):
            first=self.service.create(CONFIG,'new')
            self.assertEqual(first['config']['taskEvaluationRule'],END_TO_END_RULE)
            self.assertEqual(self.service.create(CONFIG,'new')['config'],first['config'])
            old=self.service.create({**CONFIG,'taskEvaluationRule':RESOURCE_RULE},'old')
            # Before this change the service injected v3 into an otherwise versionless create.
            self.assertEqual(self.service.create(CONFIG,'old')['config'],old['config'])
            self.assertEqual(self.store.get('campaigns',old['id'])['config']['taskEvaluationRule'],RESOURCE_RULE)
        for rule in ['task-completion-v1',RULE,RESOURCE_RULE]:
            cfg={**CONFIG,'taskEvaluationRule':rule}
            old=self.store.create(cfg,rule)
            self.assertEqual(self.store.create(cfg,rule),old)
        legacy=self.store.create(CONFIG,'legacy-no-default')
        # Original Store creates had the default in their result, not their request payload.
        with self.store.connection(True) as db:
            result=copy.deepcopy(legacy);result['config']['taskEvaluationRule']=RULE
            db.execute("UPDATE commands SET result=? WHERE kind='create' AND key='legacy-no-default'",(json.dumps(result),))
        self.assertEqual(self.store.create(CONFIG,'legacy-no-default')['config']['taskEvaluationRule'],RULE)

    def test_api_meta_reports_comparison_selection_and_historical_snapshots_agree(self):
        cid=self.store.create(CONFIG,'fixture')['id'];self.store.control(cid,'start','start')
        candidate=self.store.candidate(cid,{'id':'fixture','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})
        self.store.submit(cid,candidate['id'],[TASK],5,'batch')
        trials=self.store.list('trials',cid)
        for t,(score,code,state,start) in zip(trials,[(1,None,'finished',100),(None,'verifier_failed','failed',100),
                (None,None,'unknown',100),(None,'user_stop','cancelled',100),(None,'budget_admission_denied','cancelled',None)]):
            self.store.trial_update(t['id'],state=state,score=score,failure={'code':code} if code else None,
                                    startedAt=start,finishedAt=200,stopReason=code)
        before=copy.deepcopy(self.store.list('trials',cid))
        status=self.client.get('/campaigns/'+cid).json();expected=status['taskEvaluation']
        self.assertEqual(expected['rule'],END_TO_END_RULE)
        self.assertEqual((expected['total']['passed'],expected['total']['eligible']),(1,3))
        self.assertEqual(expected['total']['not_started'],1)
        self.assertEqual(activity_state(self.service,cid)['taskEvaluation'],expected)
        self.assertEqual(self.service.meta_call(cid,'candidate_list',{})[0]['taskEvaluation'],expected['byCandidate'][candidate['id']])
        compare=self.service.meta_api.call(cid,'results_compare',{})
        self.assertEqual(compare['evaluation'],expected)
        report=self.service.reports.status_summary(cid,'fixture')
        self.assertEqual(report['facts']['taskEvaluation'],expected)
        evidence=self.service.evidence.add(cid,trials[0]['id'],'fixture','{}',{})
        decision=self.store.retain(cid,candidate['id'],'fixture',[evidence['id']],tradeoffs='fixture',limitations=[],reconsiderWhen='new evidence')['selectionDecision']
        self.assertEqual(decision['assessment']['taskEvaluation']['candidate'],expected['byCandidate'][candidate['id']])
        self.assertEqual(self.store.list('trials',cid),before)
        original=copy.deepcopy(report);raw=Path(report['markdownPath']).read_bytes()
        self.assertIn('失败 · 评分器异常',raw.decode())
        self.assertIn('未执行 1',raw.decode())
        self.store.trial_update(trials[1]['id'],score=1,state='finished')
        self.assertEqual(self.service.reports.view(report)['taskEvaluation'],expected)
        self.assertEqual(report,original);self.assertEqual(Path(report['markdownPath']).read_bytes(),raw)
        schema=json.loads((ROOT/'schemas/contracts.schema.json').read_text())
        for t in status['trials']:Draft202012Validator(schema['$defs']['TaskAssessment']).validate(t['taskAssessment'])
        Draft202012Validator(schema['$defs']['TaskEvaluation']).validate(expected)


if __name__=='__main__':unittest.main()
