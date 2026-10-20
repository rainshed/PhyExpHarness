import copy
import math
import tempfile
import unittest
from pathlib import Path

from src.control.store import Store,Refused,RETENTION_RULE,LEGACY_RETENTION_RULE,retention_assessment
from src.reporting.reports import Reports


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'control.sqlite',clock=lambda:1000)
        self.task='adaptive_clustered_clbcs_h2o'
        self.config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
            'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
            'retentionRule':RETENTION_RULE,'tasks':[self.task],'wallTimeSeconds':12600,'concurrency':3}
        self.c=self.store.create(self.config,'setup')['id'];self.store.control(self.c,'start','start')
        self.h0=self.store.candidate(self.c,{'id':'h0','path':'/fixture','plugins':[]},'H0')['id']
        self.h1=self.store.candidate(self.c,{'id':'h1','path':'/fixture','plugins':[]},'H1')['id']
        self.store.put('evidence',{'id':'e','campaignId':self.c})
        self.n=0;self.add(self.h0,0);self.select(self.h0)

    def add(self,candidate,score,**changes):
        self.n+=1
        return self.store.put('trials',{'id':str(self.n),'campaignId':self.c,'candidateId':candidate,'batchId':'fixture',
            'task':self.task,'score':score,'state':'finished' if score is not None else 'failed',
            'startedAt':100,'stopReason':None if score is not None else 'max-tokens',
            'comparisonContext':{'taskSourcesDigest':'source','taskImageIds':['image'],'runnerImageId':'runner'},**changes})

    def select(self,candidate):return self.store.retain(self.c,candidate,'Evidence based development selection',['e'])

    def test_baseline_missing_score_no_longer_poison_comparison_and_all_records_survive(self):
        self.add(self.h0,0);self.add(self.h0,0);self.add(self.h0,None,comparisonContext=None)
        for score in [0,0,1]:self.add(self.h1,score)
        before=self.store.list('trials',self.c)
        self.assertEqual(self.select(self.h1)['retainedCandidateId'],self.h1)
        self.assertEqual(self.store.list('trials',self.c),before)
        event=self.store.events(self.c)[-1];a=event['assessment']
        self.assertEqual(event['rule'],RETENTION_RULE)
        self.assertEqual(a['reference'][self.task]['scoredFraction'],3/4)
        self.assertEqual(a['candidate'][self.task]['meanScore'],1/3)
        self.assertEqual(len(a['reference'][self.task]['unscoredTrials']),1)

    def test_additional_official_result_can_recover_without_deleting_failed_attempt(self):
        self.add(self.h0,None);failed=self.add(self.h1,None)
        with self.assertRaisesRegex(Refused,'official result'):self.select(self.h1)
        self.add(self.h1,1)
        self.assertEqual(self.select(self.h1)['retainedCandidateId'],self.h1)
        self.assertEqual(self.store.get('trials',failed['id']),failed)

    def test_ignoring_failed_candidate_attempts_cannot_hide_completion_regression(self):
        self.add(self.h1,1);self.add(self.h1,None)
        with self.assertRaisesRegex(Refused,'completion rate regression'):self.select(self.h1)
        self.assertEqual(self.store.status(self.c)['retainedCandidateId'],self.h0)
        event=self.store.events(self.c)[-1]
        self.assertEqual(event['type'],'candidate_retention_rejected')
        self.assertEqual(event['assessment']['candidate'][self.task]['scoredFraction'],.5)

    def test_pending_results_block_early_selection_even_when_already_scored(self):
        self.add(self.h1,1)
        for state in ['reserved','launching','running','reconciling']:
            with self.subTest(state=state):
                row=self.add(self.h1,1,state=state)
                with self.assertRaisesRegex(Refused,'pending Trials'):self.select(self.h1)
                self.store.trial_update(row['id'],state='finished')
        self.assertEqual(self.select(self.h1)['retainedCandidateId'],self.h1)

    def test_unstarted_cancelled_trial_not_an_attempt_but_started_cancellation_counts(self):
        self.add(self.h1,1)
        row=self.add(self.h1,None,state='cancelled',startedAt=None)
        a=retention_assessment(self.config,self.rows(self.h0),self.rows(self.h1))
        self.assertTrue(a['eligible']);self.assertEqual(a['candidate'][self.task]['cancelledBeforeStartIds'],[row['id']])
        self.store.trial_update(row['id'],startedAt=100)
        with self.assertRaisesRegex(Refused,'completion rate regression'):self.select(self.h1)

    def rows(self,candidate):return [t for t in self.store.list('trials',self.c) if t['candidateId']==candidate]

    def test_every_task_requires_coverage_and_cannot_hide_regression_in_average(self):
        cfg={**self.config,'tasks':[self.task,'another-task']}
        old=self.rows(self.h0);new=[{**old[0],'id':'new','score':1}]
        self.assertFalse(retention_assessment(cfg,old,new)['eligible'])
        old.append({**old[0],'id':'old-other','task':'another-task','score':1})
        new.append({**new[0],'id':'new-other','task':'another-task','score':0})
        self.assertIn('score regression',';'.join(retention_assessment(cfg,old,new)['issues']))

    def test_scored_result_missing_or_changed_provenance_still_refused(self):
        row=self.add(self.h1,1)
        for context in [None,{},{'runnerImageId':'different'}]:
            self.store.trial_update(row['id'],comparisonContext=context)
            with self.assertRaisesRegex(Refused,'not comparable'):self.select(self.h1)

    def test_nonfinite_and_boolean_scores_are_not_official_measurements(self):
        for score in [math.nan,math.inf,True]:
            row={**self.rows(self.h0)[0],'score':score}
            a=retention_assessment(self.config,self.rows(self.h0),[row])
            self.assertFalse(a['eligible']);self.assertIsNone(a['candidate'][self.task]['meanScore'])

    def test_legacy_rule_survives_limit_edits_and_new_defaults_are_versioned(self):
        self.assertEqual(self.store.status(self.c)['config']['retentionRule'],RETENTION_RULE)
        c=self.store.get('campaigns',self.c);del c['config']['retentionRule'];self.store.put('campaigns',c)
        self.store.control(self.c,'limits','edit',changes={'wallTimeSeconds':13000})
        self.assertNotIn('retentionRule',self.store.status(self.c)['config'])
        self.add(self.h0,None);self.add(self.h1,1)
        with self.assertRaisesRegex(Refused,'complete results'):self.select(self.h1)
        old=self.store.create({**self.config,'retentionRule':LEGACY_RETENTION_RULE},'legacy')
        self.assertEqual(old['config']['retentionRule'],LEGACY_RETENTION_RULE)
        with self.assertRaises(Refused):self.store.control(self.c,'limits','change-rule',changes={'retentionRule':RETENTION_RULE})
        with self.assertRaises(Refused):self.store.create({**self.config,'retentionRule':'unknown'},'bad')

    def test_create_retry_is_idempotent_and_finished_selection_stays_frozen(self):
        self.assertEqual(self.store.create(self.config,'setup')['id'],self.c)
        self.add(self.h1,1);self.store.finalize(self.c)
        before=copy.deepcopy(self.store.get('campaigns',self.c))
        with self.assertRaisesRegex(Refused,'frozen'):self.select(self.h1)
        self.assertEqual(self.store.get('campaigns',self.c),before)

    def test_report_facts_name_the_actual_rule_without_upgrading_history(self):
        reports=Reports(self.store,Path(self.temp.name))
        self.assertIn(RETENTION_RULE,reports.facts(self.c)['comparisonRule'])
        c=self.store.get('campaigns',self.c);del c['config']['retentionRule'];self.store.put('campaigns',c)
        self.assertIn(LEGACY_RETENTION_RULE,reports.facts(self.c)['comparisonRule'])


if __name__=='__main__':unittest.main()
