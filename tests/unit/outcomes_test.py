import copy
import json
import tempfile
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from src.evidence.outcomes import task_outcome, outcome_summary, OUTPUT_FAILURES, EXTERNAL_FAILURES, RULE, LEGACY_RULE, RESOURCE_RULE, CONNECTION_FAILURES
from src.evidence.diagnostics import trial_diagnostics
from src.control.service import ControlService
from src.control.meta_context import activity_state

ROOT=Path(__file__).resolve().parents[2]


class OutcomeTests(unittest.TestCase):
    def trial(self,code=None,**kw):
        return {'id':'trial','task':'a','state':'failed','score':None,
                'failure':{'code':code} if code else None,**kw}

    def test_final_transport_failures_are_zero_in_current_rules_with_official_null_preserved(self):
        for rule in [RULE, RESOURCE_RULE]:
            config={'taskEvaluationRule':rule}
            for code in CONNECTION_FAILURES:
                original=self.trial(code,requestRecovery={'failedRequests':2,'recoveredRequests':0})
                before=copy.deepcopy(original)
                view=trial_diagnostics([original],config=config)[0]
                self.assertEqual(view['taskAssessment']['score'],0)
                self.assertTrue(view['taskAssessment']['included'])
                self.assertIsNone(view['score'])
                self.assertIn('任务完成分 0；官方未评分',view['completionLabel'])
                self.assertEqual(original,before)
                recovered={**original,'state':'finished','score':1,'failure':None,
                           'requestRecovery':{'failedRequests':2,'recoveredRequests':2}}
                self.assertEqual(task_outcome(recovered,config)['score'],1)
                self.assertIsNone(task_outcome({**original,'state':'running'},config)['score'])
            for code in ['startup_failure','verifier_failed','archive_invalid']:
                self.assertEqual(task_outcome(self.trial(code),config)['category'],'external_failure')
        for code in ['accounting_unavailable','accounting_protocol_error','accounting_auth_failed']:
            self.assertEqual(task_outcome(self.trial(code),{'taskEvaluationRule':RESOURCE_RULE})['category'],'external_failure')

    def test_failures_and_external_causes_are_separate_and_official_scores_unchanged(self):
        for code in OUTPUT_FAILURES | {'request_timeout'}:
            t=self.trial(code);before=copy.deepcopy(t)
            self.assertEqual(task_outcome(t)['score'],0,code);self.assertEqual(t,before)
        for code in EXTERNAL_FAILURES:
            self.assertEqual(task_outcome(self.trial(code))['category'],'external_failure',code)
        self.assertEqual(task_outcome(self.trial('archive_invalid',score=1))['score'],1)
        self.assertEqual(task_outcome(self.trial(score=0))['basis'],'official_score')
        for value in [True,float('nan'),float('inf')]:self.assertIsNone(task_outcome(self.trial(score=value))['score'])

    def test_v2_counts_only_confirmed_terminal_connection_faults_and_keeps_v1(self):
        config={'taskEvaluationRule':RULE}
        for code in CONNECTION_FAILURES:
            trial=self.trial(code);original=copy.deepcopy(trial)
            self.assertEqual(task_outcome(trial,config)['score'],0)
            self.assertEqual(task_outcome(trial,{'taskEvaluationRule':LEGACY_RULE})['category'],'external_failure')
            self.assertEqual(task_outcome(trial)['rule'],LEGACY_RULE)
            self.assertEqual(task_outcome({**trial,'state':'running'},config)['category'],'pending')
            self.assertEqual(task_outcome({**trial,'state':'unknown'},config)['category'],'unresolved')
            self.assertEqual(task_outcome({**trial,'state':'cancelled'},config)['category'],'cancelled')
            self.assertEqual(task_outcome({**trial,'stopReason':'user_stop'},config)['category'],'cancelled')
            self.assertEqual(task_outcome({**trial,'score':1},config)['score'],1)
            self.assertEqual(trial,original)
        for code in EXTERNAL_FAILURES-CONNECTION_FAILURES:
            self.assertEqual(task_outcome(self.trial(code),config)['category'],'external_failure')
        self.assertEqual(task_outcome(self.trial('model_response_error',failure={'code':'model_response_error','observed':{'providerCode':'CONTEXT_WINDOW_EXCEEDED'}}),config)['category'],'external_failure')

    def test_cached_assessment_must_match_activity_rule(self):
        trial=self.trial('model_transport_error');trial['taskAssessment']=task_outcome(trial)
        original=copy.deepcopy(trial)
        self.assertEqual(outcome_summary([trial],['a'],{'taskEvaluationRule':RULE})['total']['eligible'],1)
        self.assertEqual(outcome_summary([trial],['a'],{})['total']['eligible'],0)
        self.assertEqual(trial,original)

    def test_missing_submission_requires_evidence_and_pending_is_never_zero(self):
        for outcome in ['no_submission','invalid_submission']:
            t=self.trial(summary={'taskOutcome':outcome})
            self.assertEqual(task_outcome(t)['score'],0)
            # Stored Trial/report snapshots use outcome and can omit the raw summary.
            self.assertEqual(trial_diagnostics([self.trial(outcome=outcome)])[0]['taskAssessment']['score'],0)
        self.assertEqual(task_outcome(self.trial(summary={'submissionPresent':False}))['category'],'unresolved')
        self.assertIsNone(task_outcome(self.trial('stream_whitespace',state='running'))['score'])
        self.assertIsNone(task_outcome(self.trial('runtime_failed'))['score'])
        self.assertIsNone(task_outcome(self.trial('user_stop'))['score'])
        # A confirmed abnormal stream followed by operator cancellation retains its cause.
        self.assertEqual(task_outcome(self.trial('stream_whitespace',stopReason='user_stop'))['score'],0)
        self.assertEqual(task_outcome(self.trial('verifier_failed',summary={'submissionPresent':False,'pipelineStatus':'completed'}))['category'],'external_failure')

    def test_deadlines_distinguish_full_budget_from_shortened_campaign_window(self):
        full=self.trial('trial_deadline',startedAt=100,deadline=160,taskTimeLimitSeconds=60)
        self.assertEqual(task_outcome(full,{'trialTimeSeconds':600})['score'],0)
        self.assertEqual(task_outcome({**full,'deadline':130})['category'],'cancelled')
        self.assertEqual(task_outcome(self.trial('campaign_deadline'))['category'],'cancelled')
        t=self.trial(failure={'code':'request_timeout','observed':{'responseBytes':0}})
        self.assertEqual(task_outcome(t)['category'],'unresolved')

    def test_all_attempts_count_without_oversampling_easy_tasks_or_hiding_unknowns(self):
        rows=[self.trial(score=1,state='finished') for _ in range(9)]
        rows += [self.trial('stream_whitespace',task='b'),self.trial('model_transport_error',task='b'),self.trial(task='b')]
        s=outcome_summary(rows,['a','b'])
        self.assertEqual(s['macroSuccessRate'],.5)
        self.assertEqual(s['total']['successRate'],.9)
        self.assertEqual(s['total']['conservativeSuccessRate'],9/11)
        self.assertEqual(s['total']['external_failure'],1)
        self.assertIsNone(outcome_summary(rows,['a','b','untried'])['macroSuccessRate'])

    def test_historical_diagnosis_is_shared_and_has_no_source_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            rows=[self.trial()];before=copy.deepcopy(rows)
            Path(temp,'failure-diagnoses.json').write_text(json.dumps({'trials':{'trial':{'failure':{'code':'stream_whitespace'}}}}))
            projected=trial_diagnostics(rows,temp)
            self.assertEqual(projected[0]['taskAssessment']['score'],0)
            self.assertIn('官方未评分',projected[0]['completionLabel'])
            self.assertEqual(rows,before)


class UnifiedProjectionTests(unittest.TestCase):
    def test_ui_report_meta_and_comparison_share_results_and_preserve_report_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            service=ControlService(ROOT,Path(temp),ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
            self.addCleanup(service.pool.shutdown,wait=True)
            config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
                    'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
                    'tasks':['time_budgeted_hamlearn_10q'],'wallTimeSeconds':7200,'concurrency':1}
            cid=service.store.create(config,'fixture')['id'];service.store.control(cid,'start','start')
            candidate=service.store.candidate(cid,{'id':'bundle','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})
            batch=service.store.submit(cid,candidate['id'],config['tasks'],4,'batch')
            trials=service.store.list('trials',cid)
            for t,(score,code) in zip(trials,[(1,None),(None,'stream_whitespace'),(None,'model_transport_error'),(None,'request_timeout')]):
                service.store.trial_update(t['id'],state='finished' if score is not None else 'failed',score=score,
                    failure={'code':code} if code else None,startedAt=100,finishedAt=200)
            before=copy.deepcopy(service.store.list('trials',cid))
            status=service.status(cid);expected=status['taskEvaluation']
            self.assertEqual(expected['rule'],RULE)
            self.assertEqual(expected['total']['eligible'],4);self.assertEqual(expected['total']['passed'],1)
            self.assertEqual(expected['total']['external_failure'],0)
            self.assertEqual(activity_state(service,cid)['taskEvaluation'],expected)
            self.assertEqual(service.meta_call(cid,'candidate_list',{})[0]['taskEvaluation'],expected['byCandidate'][candidate['id']])
            report=service.reports.status_summary(cid,'fixture')
            self.assertEqual(report['facts']['taskEvaluation'],expected)
            evidence=service.evidence.add(cid,trials[0]['id'],'fixture','{}',{})
            decision=service.store.retain(cid,candidate['id'],'fixture',[evidence['id']],tradeoffs='fixture',limitations=[],reconsiderWhen='more evidence')['selectionDecision']
            self.assertEqual(decision['assessment']['taskEvaluation']['candidate'],expected['byCandidate'][candidate['id']])
            self.assertEqual(service.store.list('trials',cid),before)
            original=copy.deepcopy(report);markdown=Path(report['markdownPath']).read_bytes()
            # Simulate an old report lacking the new projection; do not write it back.
            legacy=copy.deepcopy(report);legacy['facts'].pop('taskEvaluation')
            for t in legacy['facts']['trials']:
                t.pop('taskAssessment',None);t.pop('completionLabel',None)
            for r in legacy['tables']['rounds']:r.pop('versionName',None)
            for v in legacy['tables']['versions']:v.pop('displayName',None)
            view=service.reports.view(legacy)
            self.assertEqual(view['taskEvaluation'],expected)
            self.assertIn('按规则计 0：3 次',view['markdown'])
            self.assertIn('官方未评分',view['markdown'])
            # Later results must not leak into an older report's derived statistics.
            service.store.trial_update(trials[1]['id'],state='finished',score=1)
            self.assertEqual(service.reports.view(legacy)['taskEvaluation'],expected)
            self.assertEqual(report,original);self.assertEqual(Path(report['markdownPath']).read_bytes(),markdown)
            # Reports created before version binding remain v1 even on the new reader.
            old=copy.deepcopy(legacy);old['facts']['campaign']['config'].pop('taskEvaluationRule')
            old_view=service.reports.view(old)
            self.assertEqual(old_view['taskEvaluation']['rule'],LEGACY_RULE)
            self.assertEqual(old_view['taskEvaluation']['total']['eligible'],3)
            self.assertEqual(old_view['taskEvaluation']['total']['external_failure'],1)
            schema=json.loads((ROOT/'schemas/contracts.schema.json').read_text())
            for t in status['trials']:Draft202012Validator(schema['$defs']['TaskAssessment']).validate(t['taskAssessment'])
            Draft202012Validator(schema['$defs']['TaskEvaluation']).validate(expected)
