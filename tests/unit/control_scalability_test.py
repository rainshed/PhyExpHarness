import json
import unittest
from pathlib import Path
from unittest.mock import patch
from collection_workers_test import CollectionWorkersTests as Fixture
from src.control.store import comparison_diagnostics,comparison_issues,encoded
from src.control.resource_planning import feasibility
from src.evidence.diagnostics import candidate_diagnostics
from src.evidence.objects import POLICY
from src.control.meta_api import MetaAPI

class ScalabilityTests(unittest.TestCase):
    write=Fixture.write
    def setUp(self):Fixture.setUp(self)
    def test_report_row_is_small_and_read_is_exact_and_hash_checked(self):
        report=self.service.reports.status_summary(self.cid,'fixture')
        with self.store.connection() as db:raw=json.loads(db.execute('SELECT data FROM reports WHERE id=?',(report['id'],)).fetchone()[0])
        self.assertNotIn('facts',raw);self.assertEqual(raw['reportRef']['version'],'immutable-report-v1')
        self.assertEqual(self.store.get('reports',report['id']),report)
        heads=self.store.report_heads(self.cid);self.assertEqual(heads[0]['id'],report['id']);self.assertNotIn('facts',heads[0])
        file=Path(report['markdownPath']).with_suffix('.json');file.write_text('{}')
        with self.assertRaisesRegex(ValueError,'integrity'):self.store.get('reports',report['id'])
    def test_legacy_embedded_report_still_reads_without_file(self):
        row={'id':'legacy','campaignId':self.cid,'facts':{'old':True}}
        saved=self.store.put('reports',row);self.assertEqual(self.store.get('reports','legacy'),saved)
    def test_scope_comparison_separates_pending_metadata_and_different_fields(self):
        complete={'id':'a','task':'t','state':'finished','comparisonContext':{'runContract':'harbor-process-v1','taskSourcesDigest':'same','runnerImageId':None}}
        pending={'id':'pending','task':'t','state':'reserved'}
        self.assertEqual(comparison_issues([complete,pending]),[])
        self.assertEqual(comparison_diagnostics([complete,pending])[0]['kind'],'pending')
        changed={**complete,'id':'b','comparisonContext':{**complete['comparisonContext'],'taskSourcesDigest':'changed'}}
        issue=comparison_diagnostics([complete,changed])[0]
        self.assertEqual(issue['fields'],['taskSourcesDigest']);self.assertEqual(issue['trialIds'],['a','b'])
    def test_time_conditions_are_current_and_withdrawal_is_idempotent(self):
        c={'deadline':1000,'config':{'executionTimePolicy':{'version':'benchmark-task-time-v1'},'stopMode':'strict','drainGraceSeconds':0,'reserveSeconds':0,'reserveTokens':0,'taskTimeLimits':{'t':{'requiredTimeSeconds':600,'solverTimeSeconds':400}}}}
        from src.execution.host.task_time import POLICY as TIME
        c['config']['executionTimePolicy']['version']=TIME
        trial={'task':'t','state':'reserved'}
        self.assertEqual(feasibility(c,trial,100)['latestStartAt'],400)
        self.assertEqual(feasibility(c,trial,500)['availableSeconds'],500)
        self.assertEqual(feasibility(c,trial,500)['state'],'currently_infeasible')
        row=self.store.trial_update(self.trial['id'],state='reserved',startedAt=None)
        result=self.store.withdraw_trial(row['id'],'时间不足，撤回','cancel')
        self.assertEqual(result['state'],'cancelled');self.assertIsNone(result['startedAt'])
        self.assertEqual(self.store.withdraw_trial(row['id'],'时间不足，撤回','cancel'),result)
        self.assertEqual(len([e for e in self.store.events(self.cid) if e['type']=='trial_withdrawn']),1)
    def test_candidate_errors_are_labelled_and_do_not_replace_score(self):
        self.write('harbor/trial/phyexp/events.json',[{'type':'error','data':{'code':'PI_AI_ERROR','message':'no healthy upstream'}}])
        found=candidate_diagnostics(self.output,{'officialReward':0})
        self.assertEqual(found[0]['source'],'candidate-reported');self.assertEqual(found[0]['message'],'no healthy upstream')
        self.assertEqual(found[0]['eventIndex'],0)
    def test_page_filters_paths_and_navigation_remain_bounded(self):
        for i in range(110):self.service.evidence.add(self.cid,self.trial['id'],'raw','body '+str(i),{'archive':'files/'+str(i)})
        with patch.object(self.store,'list',side_effect=AssertionError('full table deserialization')):
            page=self.service.evidence.page(self.cid,trialId=self.trial['id'],limit=10,offset=100)
            overview=self.service.evidence.overview(self.cid)
        self.assertEqual(len(page['items']),10);self.assertIsNone(page['nextOffset'])
        self.assertEqual(overview['total'],110);self.assertEqual(len(overview['items']),1)
