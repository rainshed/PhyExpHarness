import json
import tempfile
import unittest
from pathlib import Path
from src.execution.host.failure import diagnose, failed_result, public_failure
from src.evidence.diagnostics import trial_diagnostics

class FailureTests(unittest.TestCase):
    def test_storage_root_cause_reaches_public_diagnostics_without_becoming_cancellation(self):
        from src.control.meta_status import meta_status
        for code in ['storage_capacity','log_size_limit','log_record_size_limit','storage_write_error']:
            failure={'code':code,'stage':'logging','secondaryCodes':['request_cancelled']}
            self.write({'status':'error','failureContract':'request-failure-v2','failure':failure})
            result=diagnose(self.root)
            self.assertEqual(result['code'],code);self.assertEqual(result['category'],'platform')
            self.assertEqual(result['secondaryCodes'],['request_cancelled'])
            status=meta_status([{'id':'session','state':'needs_attention','summary':{'failure':failure}}])
            self.assertEqual(status['failure']['code'],code)

    def test_observed_layers_and_score_impact_do_not_rewrite_original_records(self):
        rows=[{'id':code,'state':'failed','startedAt':1,'finishedAt':2,'score':None,'failure':{'code':code}}
              for code in ['stream_whitespace','model_service_overloaded','control_database_busy','runtime_failed']]
        rows.append({'id':'official-zero','state':'finished','startedAt':1,'score':0})
        before=json.dumps(rows)
        projected=trial_diagnostics(rows,config={'taskEvaluationRule':'task-completion-v4'})
        self.assertEqual([t['diagnosis']['category'] for t in projected],['model_output','model_service','platform','unknown','task_result'])
        self.assertEqual([t['score'] for t in projected],[None,None,None,None,0])
        self.assertTrue(all(t['taskAssessment']['score']==0 for t in projected))
        self.assertEqual(projected[-1]['diagnosis']['impact'],'official_score_recorded')
        self.assertEqual(json.dumps(rows),before)

    def test_recovered_failures_are_history_and_bridge_receipts_omit_raw_errors(self):
        from src.execution.host.failure import container_transport
        self.runtime.with_name('container-transport.json').write_text(json.dumps({'schemaVersion':1,'verificationBlocked':False,
            'issues':[{'callId':'one','stage':'deliver_response','executionState':'completed','blocksVerification':False,'message':'SECRET','recoveredBy':'two'}]}))
        bridge=container_transport(self.root)
        row={'id':'one','state':'finished','score':1,'failureContract':'request-failure-v2',
             'summary':{'containerTransport':bridge,'requestRecovery':{'failedRequests':1,'recoveredRequests':1,
                 'failures':[{'code':'model_service_overloaded','requestId':'old','recoveredBy':'new'}]}}}
        out=trial_diagnostics([row])[0]
        self.assertEqual(out['diagnosis']['category'],'none')
        self.assertNotIn('failure',out)
        self.assertEqual(out['requestRecovery']['failures'][0]['recoveredBy'],'new')
        self.assertNotIn('未能恢复',out['requestRecovery']['failures'][0]['message'])
        self.assertNotIn('SECRET',str(out));self.assertEqual(out['score'],1)

    def test_database_tool_receipt_survives_unavailable_publication_and_preserves_unknown_writes(self):
        import sqlite3
        from src.control.meta_tool_boundary import ToolBoundary
        boundary=ToolBoundary(None)
        for write in (False,True):
            result=boundary.error('fixture','report_save',sqlite3.OperationalError('database is locked'),write=write)
            self.assertEqual(result['code'],'control_database_busy')
            self.assertEqual(result['status'],'outcome_unknown' if write else 'failed')
            self.assertEqual(result['reconciliationRequired'],write)

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

    def test_environment_timeout_is_not_masked_by_collector_value_error(self):
        result_path = self.root/'harbor/trial/result.json'
        for exception in [{'exception_type':'EnvironmentStartTimeoutError'},
                          {'exception_type':'RuntimeError','exception_message':'Compose containers did not become ready PRIVATE'}]:
            result_path.write_text(json.dumps({'environment_setup':{'started_at':'fixture'}, 'exception_info':exception}))
            original = result_path.read_bytes()
            result = failed_result(self.root, ValueError('missing runtime summary'))
            self.assertEqual(result['failure']['code'], 'environment_start_timeout')
            self.assertEqual(result['failure']['stage'], 'environment')
            self.assertEqual(result['scoringStatus'], 'not_run')
            self.assertNotIn('PRIVATE', str(result['failure']))
            self.assertEqual(result_path.read_bytes(), original)

    def test_environment_receipt_preserves_role_and_never_overrides_scientific_score(self):
        receipt = self.runtime.with_name('environment-startup-verifier.json')
        receipt.write_text(json.dumps({'status':'failed','code':'environment_healthcheck_failed','role':'verifier'}))
        self.write({'status':'completed'})
        failure = diagnose(self.root)
        self.assertEqual(failure['code'], 'environment_healthcheck_failed')
        self.assertEqual(failure['scoringStatus'], 'failed')
        result_path = self.root/'harbor/trial/result.json'
        result_path.write_text(json.dumps({'verifier_result':{'rewards':{'reward':0}}}))
        self.assertEqual(diagnose(self.root)['code'], 'result_collection_failed')
        self.assertEqual(diagnose(self.root)['scoringStatus'], 'completed')

    def test_outer_timeout_explains_cancellation_but_user_stop_keeps_its_cause(self):
        self.runtime.with_name('environment-startup-agent.json').write_text(json.dumps(
            {'status':'failed','code':'environment_start_interrupted','role':'agent'}))
        (self.root/'harbor/trial/result.json').write_text(json.dumps(
            {'exception_info':{'exception_type':'EnvironmentStartTimeoutError'}}))
        self.assertEqual(diagnose(self.root)['code'], 'environment_start_timeout')
        self.assertEqual(diagnose(self.root,'user_stop')['code'], 'user_stop')
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
