import json
import tempfile
import unittest
from pathlib import Path
from src.execution.host.failure import diagnose, failed_result, public_failure
from src.evidence.diagnostics import trial_diagnostics

class FailureTests(unittest.TestCase):
    def test_context_overflow_has_specific_safe_message_without_changing_failure_category(self):
        value={'code':'model_response_error','observed':{'providerCode':'CONTEXT_WINDOW_EXCEEDED'},'message':'PRIVATE raw error'}
        result=public_failure(value)
        self.assertEqual(result['code'],'model_response_error')
        self.assertIn('上下文',result['message']);self.assertNotIn('PRIVATE',str(result))
        self.assertEqual(public_failure({'code':'model_response_error'})['message'],'模型提供方返回错误')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.runtime=self.root/'harbor/trial/phyexp/runtime-summary.json';self.runtime.parent.mkdir(parents=True)
    def write(self,value):self.runtime.write_text(json.dumps(value))
    def test_limit_transport_and_unknown_have_distinct_safe_causes(self):
        self.write({'turnEnd':{'kind':'max-tokens'},'usage':{'totalTokens':164648}})
        self.assertEqual(diagnose(self.root)['code'],'model_output_limit')
        self.assertEqual(failed_result(self.root,ValueError('wrapper'))['usage']['totalTokens'],164648)
        self.write({'turnEnd':{'kind':'error','error':{'code':'TRANSPORT','message':'fetch failed SECRET'}}})
        d=diagnose(self.root);self.assertEqual(d['code'],'model_transport_error');self.assertNotIn('SECRET',str(d))
        self.write({'error':'Runtime exited: 137'})
        self.assertEqual(diagnose(self.root)['code'],'runtime_failed')
    def test_protection_cause_survives_cleanup_and_user_stop(self):
        self.write({'status':'error','error':'exit 137'})
        self.runtime.with_name('failure.json').write_text(json.dumps({'code':'stream_whitespace','stage':'model','requestId':'r','observed':{'bytes':5000}}))
        result=failed_result(self.root,ValueError('collector'),'user_stop')
        self.assertEqual(result['failure']['code'],'stream_whitespace');self.assertEqual(result['failure']['termination'],'user_stop')
        self.assertEqual(result['officialReward'],None);self.assertEqual(result['failure']['scoringStatus'],'not_run')
    def test_verifier_failure_and_corruption_are_not_model_errors(self):
        self.write({'status':'completed'})
        (self.root/'harbor/trial/result.json').write_text(json.dumps({'exception_info':{'exception_type':'VerifierTimeoutError'}}))
        self.assertEqual(diagnose(self.root)['code'],'verifier_failed')
        self.assertEqual(diagnose(self.root)['scoringStatus'],'failed')
    def test_collection_and_bridge_errors_are_platform_failures(self):
        from src.evidence.outcomes import task_outcome
        self.write({'status':'completed','failureContract':'request-failure-v2','failure':None})
        result_path=self.root/'harbor/trial/result.json'
        result_path.write_text(json.dumps({'verifier_result':{'rewards':{'reward':0}}}))
        d=failed_result(self.root,KeyError('id'))
        self.assertEqual(d['failure']['code'],'result_collection_failed')
        self.assertEqual(d['failure']['stage'],'collection')
        result_path.write_text(json.dumps({'exception_info':{'exception_type':'RuntimeError',
            'exception_message':'Container transport failed: Only a nonempty command is accepted'}}))
        d=failed_result(self.root,ValueError('collector'))
        self.assertEqual(d['failure']['code'],'container_transport_error')
        self.assertEqual(d['scoringStatus'],'not_run')
        self.assertIsNone(d['officialReward'])
        self.assertEqual(task_outcome({'state':'failed','summary':d})['category'],'external_failure')
    def test_cancelled_request_uses_known_stop_and_missing_scoring_stays_unknown(self):
        self.write({'status':'completed'})
        self.assertEqual(diagnose(self.root)['scoringStatus'],'unknown')
        self.runtime.with_name('failure.json').write_text(json.dumps({'code':'request_cancelled','stage':'model'}))
        self.assertEqual(diagnose(self.root,'user_stop')['code'],'user_stop')
    def test_history_projection_preserves_source_and_distinguishes_running_zero_missing(self):
        rows=[{'id':'running','state':'running','score':None},{'id':'zero','state':'finished','score':0},{'id':'old','state':'failed','score':None}]
        original=json.dumps(rows)
        (self.root/'failure-diagnoses.json').write_text(json.dumps({'trials':{'old':{'failure':{'code':'model_output_limit','source':'historical-artifact-analysis'}}}}))
        out=trial_diagnostics(rows,self.root)
        self.assertEqual(out[0]['scoringStatus'],'pending');self.assertEqual(out[1]['resultLabel'],'评分 0')
        self.assertIn('输出达到',out[2]['resultLabel']);self.assertEqual(json.dumps(rows),original)

    def test_recovered_request_history_does_not_override_final_runtime_or_verifier_failure(self):
        recovered={'code':'model_transport_error','requestId':'old','recoveredBy':'new'}
        self.runtime.with_name('failure.json').write_text(json.dumps({'failureContract':'request-failure-v2','failure':None,'requestRecovery':{'failures':[recovered]}}))
        self.write({'status':'completed','failureContract':'request-failure-v2','failure':None,'turnEnd':{'kind':'completed'},'requestRecovery':{'failures':[recovered]}})
        (self.root/'harbor/trial/result.json').write_text(json.dumps({'exception_info':{'exception_type':'VerifierTimeoutError'}}))
        self.assertEqual(diagnose(self.root)['code'],'verifier_failed')
        latest={'code':'model_service_overloaded','requestId':'last','stage':'model'}
        self.write({'status':'error','failureContract':'request-failure-v2','failure':latest})
        self.assertEqual(diagnose(self.root)['requestId'],'last')

    def test_v2_completed_record_ignores_obsolete_historical_failure_projection(self):
        (self.root/'failure-diagnoses.json').write_text(json.dumps({'trials':{'recovered':{'failure':{'code':'model_transport_error'}}}}))
        rows=[{'id':'recovered','state':'finished','score':1,'failureContract':'request-failure-v2','failure':None}]
        projected=trial_diagnostics(rows,self.root,{'taskEvaluationRule':'task-completion-v2'})[0]
        self.assertIsNone(projected['failure']);self.assertEqual(projected['completionLabel'],'任务完成分 1；官方评分 1')
