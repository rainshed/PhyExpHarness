import copy
import json
import tempfile
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator

from src.control.store import Store,Refused,META_RETENTION_RULE,RETENTION_RULE
from src.control.meta_context import system_prompt
from src.evidence.library import EvidenceLibrary
from src.reporting.reports import Reports

ROOT=Path(__file__).resolve().parents[2]


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.store=Store(self.data/'control.sqlite',clock=lambda:1000)
        self.tasks=['adaptive_clustered_clbcs_h2o','logical_cnot_decoder_calibration']
        self.config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
            'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
            'tasks':self.tasks,'wallTimeSeconds':7200,'concurrency':4}
        self.c=self.store.create(self.config,'setup')['id'];self.store.control(self.c,'start','start')
        self.h0=self.candidate('H0');self.h3=self.candidate('H3',self.h0)
        self.evidence=EvidenceLibrary(self.store,self.data).add(self.c,'fixture','official-result','{"fixture":true}',{})
        self.n=0

    def candidate(self,name,parent=None):
        return self.store.candidate(self.c,{'id':name,'path':'/fixture','plugins':[]},name,parent,{'status':'passed'})['id']

    def add(self,candidate,task,score,**changes):
        self.n+=1
        return self.store.put('trials',{'id':str(self.n),'campaignId':self.c,'candidateId':candidate,'batchId':'fixture',
            'task':task,'score':score,'state':'finished' if score is not None else 'failed','startedAt':100,
            'stopReason':None if score is not None else 'stream_whitespace',
            'comparisonContext':{'taskSourcesDigest':'source','taskImageIds':['image'],'runnerImageId':'runner'},**changes})

    def select(self,candidate,**changes):
        args={'reason':'Prefer this frozen version based on all attempts','refs':[self.evidence['id']],
            'tradeoffs':'Accept limited evidence for better observed completion','limitations':['Small sample'],
            'reconsiderWhen':'Revisit if further repetitions fail',**changes}
        return self.store.retain(self.c,candidate,**args)

    def decisions(self):return self.store.list('selection_decisions',self.c)

    def test_missing_reference_scores_and_changed_environment_are_advisory_and_audited(self):
        self.assertEqual(self.store.status(self.c)['config']['retentionRule'],META_RETENTION_RULE)
        self.add(self.h0,self.tasks[0],None);self.add(self.h0,self.tasks[1],1)
        self.select(self.h0)
        for task in self.tasks:
            for i in range(2):self.add(self.h3,task,1,comparisonContext={'taskImageIds':[str(i)]})
        before=copy.deepcopy(self.store.list('trials',self.c));old=copy.deepcopy(self.decisions())
        result=self.select(self.h3);d=self.decisions()[-1]
        self.assertEqual(result['retainedCandidateId'],self.h3)
        self.assertEqual(d['previousCandidateId'],self.h0);self.assertEqual(d['previousDecisionId'],old[0]['id'])
        self.assertEqual(d['bundleId'],'H3');self.assertEqual(d['verifiedEvidence'][0]['sha256'],self.evidence['sha256'])
        self.assertIn('缺少有效官方评分',';'.join(d['assessment']['comparisonLimitations']))
        self.assertIn('运行镜像',';'.join(d['assessment']['comparisonLimitations']))
        self.assertEqual(len(d['assessment']['trials']),6)
        self.assertIsNone(d['assessment']['reference'][self.tasks[0]]['meanScore'])
        self.assertEqual(self.store.list('trials',self.c),before);self.assertEqual(self.decisions()[:-1],old)
        schema=json.loads((ROOT/'schemas/contracts.schema.json').read_text())['$defs']['SelectionDecision']
        Draft202012Validator(schema).validate(d)

    def test_regressions_pending_results_and_rollback_do_not_block_choice(self):
        for task in self.tasks:self.add(self.h0,task,1);self.add(self.h3,task,0)
        self.select(self.h0)
        self.add(self.h3,self.tasks[0],None);self.add(self.h3,self.tasks[1],None,state='running')
        self.select(self.h3);d=copy.deepcopy(self.decisions()[-1])
        warnings=';'.join(d['assessment']['comparisonLimitations'])
        for text in ['官方均分','任务成功率','未结束试验']:self.assertIn(text,warnings)
        self.select(self.h0)
        self.assertEqual(self.decisions()[-1]['previousCandidateId'],self.h3)
        self.store.trial_update(str(self.n),state='finished',score=1)
        self.assertEqual(self.decisions()[-2],d) # Later results cannot rewrite decision-time evidence.

    def test_unscored_baseline_can_be_selected_and_reaffirmed_without_platform_auto_selection(self):
        self.assertIsNone(self.store.status(self.c)['retainedCandidateId'])
        self.select(self.h0);self.select(self.h0)
        self.assertEqual(len(self.decisions()),2)
        self.assertEqual(self.decisions()[-1]['previousCandidateId'],self.h0)
        self.assertFalse(any('首次选择' in x for x in self.decisions()[-1]['assessment']['comparisonLimitations']))

    def test_invalid_decision_evidence_and_candidate_leave_selection_unchanged(self):
        self.select(self.h0);before=copy.deepcopy(self.store.get('campaigns',self.c))
        other=self.store.create(self.config,'other')['id']
        foreign=EvidenceLibrary(self.store,self.data).add(other,'foreign','official-result','{}',{})
        for changes in [{'reason':' '},{'refs':[]},{'refs':[foreign['id']]},{'refs':['missing']},
                        {'refs':[self.evidence['id']]*2},{'tradeoffs':''},{'limitations':'none'},{'reconsiderWhen':None}]:
            with self.subTest(changes=changes),self.assertRaises(Refused):self.select(self.h3,**changes)
        Path(self.evidence['path']).chmod(0o644);Path(self.evidence['path']).write_text('changed')
        with self.assertRaisesRegex(Refused,'integrity'):self.select(self.h3)
        Path(self.evidence['path']).unlink()
        with self.assertRaisesRegex(Refused,'unavailable'):self.select(self.h3)
        unchecked=self.store.candidate(self.c,{'id':'bad','path':'/fixture','plugins':[]},'Bad')['id']
        with self.assertRaisesRegex(Refused,'checked'):self.select(unchecked)
        foreign_candidate=self.store.candidate(other,{'id':'other','path':'/fixture','plugins':[]},'Other',check={'status':'passed'})['id']
        with self.assertRaisesRegex(Refused,'unavailable'):self.select(foreign_candidate)
        self.assertEqual(len(self.decisions()),1);self.assertEqual(self.store.get('campaigns',self.c),before)

    def test_decision_survives_restart_reports_and_finalization_without_upgrading_old_campaigns(self):
        self.select(self.h3);self.store.finalize(self.c)
        restart=Store(self.data/'control.sqlite')
        self.assertEqual(restart.status(self.c)['selectionDecision']['candidateId'],self.h3)
        self.assertEqual(restart.status(self.c)['finalCandidateId'],self.h3)
        with self.assertRaisesRegex(Refused,'frozen'):self.select(self.h0)
        reports=Reports(restart,self.data);r=reports.status_summary(self.c,'Fixture report')
        self.assertEqual(r['facts']['selectionDecisions'],self.decisions())
        self.assertIn(self.evidence['id'],[e['id'] for e in r['facts']['evidence']])
        self.assertIn('Meta 版本选择记录',Path(r['markdownPath']).read_text())
        self.assertIn('重新考虑的条件',Path(r['markdownPath']).read_text())
        old=restart.create({**self.config,'retentionRule':RETENTION_RULE},'old')
        self.assertEqual(old['config']['retentionRule'],RETENTION_RULE)
        self.assertNotIn('selectionDecision',old)
        self.assertIn(META_RETENTION_RULE,system_prompt(restart.status(self.c)['config'])['text'])


if __name__=='__main__':unittest.main()
