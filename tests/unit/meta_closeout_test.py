import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.control.meta import MetaDriver
from src.control.service import ControlService

ROOT=Path(__file__).resolve().parents[2]


class MetaCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)
        self.service=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.store=self.service.store;self.driver=MetaDriver(self.service)
        model={'provider':'openai-codex','model':'gpt-6-luna','reasoningEffort':'medium'}
        self.c=self.store.create({'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],
            'concurrency':1,'wallTimeSeconds':7200,'softTokenLimit':3000000},'closeout')['id']
        c=self.store.get('campaigns',self.c);c['config']['metaComposition']={'version':'meta-composition-v2','id':'fixture','preset':'native','plugins':[]}
        self.store.put('campaigns',c);self.store.control(self.c,'start','start')
        candidate=self.store.candidate(self.c,{'id':'fixture','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})
        self.batch=self.store.submit(self.c,candidate['id'],['time_budgeted_hamlearn_10q'],1,'baseline')
        self.trial=self.store.claim(self.c)
        self.store.trial_update(self.trial['id'],state='finished',score=0,scoringStatus='completed',finishedAt=time.time())
        self.store.close_admission(self.c,'round_limit')
        self.evidence=self.service.evidence.add(self.c,self.trial['id'],'fixture','Official zero',{'archive':'fixture.txt'})
        self.analysis={'summary':'Official zero was collected','observations':['Fixture evidence'],
            'hypotheses':[],'limitations':['No real model'],'decision':'Close out','evidenceRefs':[self.evidence['id']]}
        self.output=self.data/'meta';self.output.mkdir()
        self.summary={'status':'error','turns':2,'failure':{'code':'budget_admission_denied'}}
        self.session=self.store.put('meta_sessions',{'id':'meta-fixture','campaignId':self.c,'leaseId':'meta-lease',
            'runtimeVersion':'meta-runtime-v2','state':'needs_attention','output':str(self.output),
            'summary':self.summary,'recovery':{'automaticRecovery':False}})

    def tearDown(self):
        self.service.pool.shutdown(wait=True);self.temp.cleanup()

    def reports(self):
        self.service.reports.save(self.c,self.analysis,self.batch['id'])
        self.service.reports.save(self.c,self.analysis)

    def tick_without_model(self):
        with patch.object(self.driver,'start',side_effect=AssertionError('Must not start another model session')):
            self.driver.tick(self.c)

    def test_reports_complete_after_budget_denial_finish_without_changing_evidence(self):
        self.reports()
        self.store.reserve(self.c,'old-lease','unknown-request',300000,'meta');self.store.mark_unknown('old-lease')
        before={table:self.store.list(table,self.c) for table in ['reports','trials','usage','meta_sessions']}
        files={r['markdownPath']:Path(r['markdownPath']).read_bytes() for r in before['reports']}
        self.tick_without_model()
        self.assertEqual(self.store.status(self.c)['state'],'finished')
        self.assertEqual(self.store.status(self.c)['stopReason'],'round_limit')
        for table,rows in before.items():self.assertEqual(self.store.list(table,self.c),rows)
        for path,content in files.items():self.assertEqual(Path(path).read_bytes(),content)
        self.assertEqual(self.store.usage(self.c)['unknownReservedTokens'],300000)
        revision=self.store.get('campaigns',self.c)['revision'];self.tick_without_model()
        self.assertEqual(self.store.get('campaigns',self.c)['revision'],revision)

    def test_newly_exited_failed_worker_is_reconciled_then_finalized(self):
        self.reports();(self.output/'summary.json').write_text(json.dumps(self.summary))
        self.store.put('meta_sessions',{**self.session,'state':'running'})
        with patch.object(self.service,'_process_alive',return_value=False):self.tick_without_model()
        self.assertEqual(self.store.status(self.c)['state'],'finished')
        session=self.store.get('meta_sessions',self.session['id'])
        self.assertEqual(session['state'],'needs_attention')
        self.assertEqual(session['summary']['failure']['code'],'budget_admission_denied')

    def test_missing_round_or_final_analysis_remains_incomplete(self):
        self.service.reports.status_summary(self.c,'Facts only')
        self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'closing')
        self.service.reports.save(self.c,self.analysis)
        self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'closing')
        self.service.reports.save(self.c,self.analysis,self.batch['id'])
        self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'finished')

    def test_unfinished_trials_prevent_closeout(self):
        self.reports()
        for state in ['reserved','launching','running']:
            with self.subTest(state=state):
                self.store.trial_update(self.trial['id'],state=state)
                self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'closing')

    def test_pending_operation_prevents_closeout(self):
        self.reports();self.store.put('operations',{'id':'build','campaignId':self.c,'state':'running'})
        self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'closing')

    def test_live_worker_is_not_interrupted_after_reports_commit(self):
        self.reports();self.store.put('meta_sessions',{**self.session,'state':'running'})
        self.driver.children[self.session['id']]=SimpleNamespace(poll=lambda:None)
        self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'closing')

    def test_paused_and_open_exploration_are_not_finalized_by_reports(self):
        self.reports()
        for state in ['paused','running']:
            with self.subTest(state=state):
                c=self.store.get('campaigns',self.c);c.update(state=state,explorationClosed=state=='paused');self.store.put('campaigns',c)
                self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],state)

    def test_completed_reports_do_not_trigger_technical_recovery(self):
        self.reports();self.store.put('meta_sessions',{**self.session,'state':'recovering','recovery':{'retryAt':time.time()-1}})
        self.tick_without_model();self.assertEqual(self.store.status(self.c)['state'],'finished')


if __name__=='__main__':unittest.main()
