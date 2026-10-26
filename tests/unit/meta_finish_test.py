import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.control.service import ControlService
from src.control.meta import MetaDriver
from src.control.meta_native_composition import freeze
from src.control.stop_policy import META_POLICY
from src.control.stop_review import StopRuntime
from src.control.store import Refused

ROOT=Path(__file__).resolve().parents[2]
TASK='time_budgeted_hamlearn_10q'


class MetaFinishTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)
        self.service=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.store=self.service.store;self.api=self.service.meta_api;self.driver=MetaDriver(self.service)
        model={'provider':'openai-codex','model':'gpt-6-luna','reasoningEffort':'medium'}
        self.c=self.store.create({'solver':model,'meta':model,'tasks':[TASK],'concurrency':1,
            'wallTimeSeconds':7200,'stopPolicy':META_POLICY,'objective':'比较失败原因并说明差异'},'fixture')['id']
        c=self.store.get('campaigns',self.c)
        with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):
            c['config']['metaComposition']=freeze(ROOT,self.data,c['config'])
        self.store.put('campaigns',c);self.store.control(self.c,'start','start')
        self.args={'reason':'比较已完成，不需要新的实验。','summary':'两种方法均未通过。\n已比较失败原因，仍不能证明改善。','idempotencyKey':'finish'}

    def tearDown(self):
        self.service.pool.shutdown(wait=True);self.temp.cleanup()

    def finish(self):return self.api.call(self.c,'campaign_finish',self.args)

    def tick(self):
        with patch.object(self.driver,'start',side_effect=AssertionError('Must not restart Meta')):
            self.driver.tick(self.c)

    def session(self,state='running'):
        output=self.data/'session';output.mkdir(exist_ok=True)
        (output/'summary.json').write_text(json.dumps({'status':'error','failure':{'code':'model_authentication'}}))
        return self.store.put('meta_sessions',{'id':'main','nativeSessionId':'main','campaignId':self.c,'leaseId':'fixture-lease',
            'runtimeVersion':'meta-runtime-v2','state':state,'output':str(output),'cursor':0,
            'agents':{'main':{'preset':'phyexp-meta'},'child':{'preset':'phyexp-researcher'}}})

    def batch(self,repeats=1):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':'/fixture','plugins':[]},'Fixture',check={'status':'passed'})
        return self.store.submit(self.c,candidate['id'],[TASK],repeats,'batch')

    def test_custom_goal_without_rule_candidate_experiment_or_reports_closes(self):
        result=self.finish();self.assertEqual(result['state'],'closing')
        decision=self.store.status(self.c)['finishAssessment']
        self.assertEqual(decision['source'],'meta-decision');self.assertEqual(decision['summary'],self.args['summary'])
        self.assertIsNone(self.store.status(self.c)['retainedCandidateId'])
        self.assertEqual(self.store.report_heads(self.c),[])
        self.tick();c=self.store.status(self.c)
        self.assertEqual(c['state'],'finished');self.assertEqual(c['finishAssessment'],decision)
        before=c['revision'];self.tick();self.assertEqual(self.store.status(self.c)['revision'],before)

    def test_required_text_rejections_leave_activity_open(self):
        for key in ('reason','summary'):
            for value in (None,'',' \n ',42):
                with self.subTest(key=key,value=value):
                    result=self.api.call(self.c,'campaign_finish',{**self.args,key:value})
                    self.assertEqual(result['status'],'rejected')
                    self.assertEqual(self.store.status(self.c)['state'],'running')
                    self.assertFalse(self.store.status(self.c).get('finishAssessment'))
        # Store validates independently of the public tool schema.
        with self.assertRaises(Refused):self.store.control(self.c,'finish','direct',changes={'reason':'why'})

    def test_failed_attempts_and_stability_rule_do_not_gate_closeout(self):
        self.batch();trial=self.store.claim(self.c)
        self.store.trial_update(trial['id'],state='failed',score=None,finishedAt=time.time())
        c=self.store.get('campaigns',self.c);c['config']['stabilityRule']={'minTrialsPerTask':9,'minimumOfficialScore':1};self.store.put('campaigns',c)
        self.finish();self.tick();self.assertEqual(self.store.status(self.c)['state'],'finished')

    def test_pending_main_reference_build_and_collection_settle_after_acceptance(self):
        batch=self.batch(2);trial=self.store.claim(self.c);deadline=trial['deadline']
        self.store.put('reference_runs',{'id':'reference-run-fixture','campaignId':self.c,'state':'running','startedAt':time.time()})
        self.store.put('operations',{'id':'build','campaignId':self.c,'state':'running'})
        self.finish()
        self.assertEqual(self.store.get('trials',trial['id'])['deadline'],deadline)
        rows=self.store.list('trials',self.c)
        self.assertEqual(sum(t['state']=='cancelled' for t in rows),1)
        self.assertIsNone(self.store.claim(self.c))
        for state in ('running','collecting','finished'):
            self.store.trial_update(trial['id'],state=state)
            self.tick();self.assertEqual(self.store.status(self.c)['state'],'closing')
        self.store.put('reference_runs',{'id':'reference-run-fixture','campaignId':self.c,'state':'finished','score':0})
        self.tick();self.assertEqual(self.store.status(self.c)['state'],'closing')
        self.store.put('operations',{'id':'build','campaignId':self.c,'state':'failed'})
        self.tick();self.assertEqual(self.store.status(self.c)['state'],'finished')
        self.assertFalse(self.store.report_heads(self.c))

    def test_committed_closeout_stops_live_worker_without_waiting_for_reply(self):
        self.session();self.finish()
        notice=self.driver.notifications('main',0)
        self.assertTrue(notice['finish']);self.assertFalse(notice['continue'])
        with patch.object(self.service,'_process_alive',return_value=True),patch.object(self.driver,'interrupt') as interrupt:
            self.tick();interrupt.assert_called_once_with(self.c,'activity_closed')
        self.assertEqual(self.store.status(self.c)['state'],'finished')

    def test_crashed_or_recovering_worker_cannot_restart_after_commit(self):
        self.session('recovering');self.finish();self.tick()
        self.assertEqual(self.store.status(self.c)['state'],'finished')
        with patch.object(self.service,'knowledge_for',side_effect=AssertionError('No new session')):
            self.driver._start(self.c)

    def test_unknown_receipt_reconciles_after_restart_and_cannot_overwrite(self):
        call=self.api._call
        def lost(*args):
            call(*args)
            raise ConnectionError('response lost after commit')
        with patch.object(self.api,'_call',side_effect=lost):
            result=self.finish();self.assertEqual(result['status'],'outcome_unknown')
        decision=self.store.status(self.c)['finishAssessment'];self.tick()
        from src.control.meta_api import MetaAPI
        self.service.meta_api=MetaAPI(self.service);self.api=self.service.meta_api
        with patch.object(self.api,'_call',side_effect=AssertionError('Must not repeat side effect')):
            first=self.finish();self.assertEqual(first,self.finish());self.assertEqual(first['state'],'closing')
        conflict=self.api.call(self.c,'campaign_finish',{**self.args,'summary':'changed'})
        self.assertEqual(conflict['status'],'rejected')
        self.assertEqual(self.store.status(self.c)['finishAssessment'],decision)

    def test_new_identity_does_not_replace_saved_decision(self):
        self.finish();decision=self.store.status(self.c)['finishAssessment']
        result=self.api.call(self.c,'campaign_finish',{**self.args,'idempotencyKey':'again','summary':'different'})
        self.assertEqual(result['status'],'rejected');self.assertEqual(self.store.status(self.c)['finishAssessment'],decision)

    def test_read_only_child_cannot_finish_or_request_review(self):
        self.session();runtime=StopRuntime(self.service)
        with self.assertRaisesRegex(Refused,'authenticated main Meta'):
            self.service.control(self.c,'finish','user-pretending-meta',changes=self.args)
        with self.assertRaisesRegex(Refused,'read-only'):
            runtime.dispatch('main','call',{'agentId':'child','operation':'campaign_finish','input':self.args})
        with self.assertRaisesRegex(Refused,'does not support'):
            runtime.dispatch('main','review_request',{'agentId':'main','request':{}})
        runtime.dispatch('main','call',{'agentId':'main','operation':'campaign_finish','input':self.args})
        self.assertEqual(self.store.status(self.c)['state'],'closing')

    def test_external_stop_without_meta_summary_finishes_and_marks_missing(self):
        self.session('needs_attention');self.store.control(self.c,'stop','user-stop');self.tick()
        self.assertEqual(self.store.status(self.c)['state'],'finished')
        report=self.service.reports.status_summary(self.c,'系统事实')
        self.assertEqual(report['author'],'system');self.assertFalse(report.get('closeoutSubmitted'))
        self.assertIn('尚未收到 Meta 提交的收尾理由与实验总结',Path(report['markdownPath']).read_text())

    def test_closeout_during_resource_closing_saves_meta_text_and_report_source(self):
        self.store.close_admission(self.c,'round_limit');self.finish();self.tick()
        self.assertEqual(self.store.status(self.c)['stopReason'],'round_limit')
        report=self.service.reports.status_summary(self.c,'系统最终事实')
        self.assertEqual(report['author'],'system');self.assertTrue(report['closeoutSubmitted'])
        self.assertTrue(self.store.report_heads(self.c)[0]['closeoutSubmitted'])
        text=Path(report['markdownPath']).read_text()
        self.assertIn(self.args['reason'],text);self.assertIn(self.args['summary'],text)
        self.assertIn('活动结束不表示平台认证目标已经达成',text)
        self.assertNotIn('尚未收到 Meta 提交',text)

    def test_status_does_not_demand_reports_or_default_stability_criteria(self):
        self.session();self.store.close_admission(self.c,'round_limit')
        with patch.object(self.api.files,'refresh'):
            notice=self.driver.notifications('main',0)
        self.assertIn('separate reports are optional',notice['instruction'])
        self.finish();result=self.api.receipts.status(self.c)
        self.assertIn('无需再次提交',result['summary'])
        view=self.api.receipts.closeout(self.c)
        self.assertFalse(view['reportsRequired']);self.assertIsNone(view['nextReport'])
        from src.control.meta_context import activity_state
        state=activity_state(self.service,self.c)
        self.assertNotIn('stabilityCriteria',state);self.assertFalse(state['completion']['certifiesGoal'])

    def test_finalize_never_bypasses_open_admission_or_running_build(self):
        with self.assertRaises(Refused):self.store.finalize(self.c)
        self.finish();self.store.put('operations',{'id':'build','campaignId':self.c,'state':'running'})
        with self.assertRaises(Refused):self.store.finalize(self.c)
        with patch.object(self.service.storage,'permit',return_value=True):
            for kind in ('candidate_check','freeze'):
                with self.assertRaisesRegex(Refused,'Search writes closed'):
                    self.service._operation(self.c,kind,{},lambda:self.fail('Must not launch new work'))

    def test_deadline_and_crash_can_finish_without_a_summary(self):
        self.session();self.store.close_admission(self.c,'time_limit')
        c=self.store.get('campaigns',self.c);c['deadline']=time.time()-1;self.store.put('campaigns',c)
        with patch.object(self.service,'_process_alive',return_value=False):self.tick()
        c=self.store.status(self.c)
        self.assertEqual(c['state'],'finished');self.assertEqual(c['stopReason'],'time_limit')
        self.assertFalse(c.get('finishAssessment'))


if __name__=='__main__':unittest.main()
