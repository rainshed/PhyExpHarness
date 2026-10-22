import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import meta_native_test as legacy
from src.control.meta_native_composition import freeze
from src.control.store import Refused,Conflict,encoded,META_RETENTION_RULE
from src.control.meta import MetaDriver
from src.control.meta_context import startup_context
from src.control.meta_contracts import binding

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        legacy.NativeMetaTests.setUp(self)
        c=self.store.get('campaigns',self.c)
        with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64), patch('src.control.meta_contracts.binding',return_value=binding('meta-tools-v3')):c['config']['metaComposition']=freeze(legacy.ROOT,self.data,c['config'])
        c['config']['retentionRule']=META_RETENTION_RULE
        self.store.put('campaigns',c)
    def tearDown(self):legacy.NativeMetaTests.tearDown(self)
    def read(self,result):
        self.assertLessEqual(len(encoded(result).encode()),4096)
        file=result['file'];p=self.api.files.directory(self.c)/file['path'].lstrip('/')
        data=p.read_bytes();self.assertEqual(hashlib.sha256(data).hexdigest(),file['sha256'])
        self.assertNotIn(str(self.data),encoded(result));self.assertNotIn(str(self.data),data.decode())
        return json.loads(data)
    def analysis(self):return {'summary':'原始研究正文尾部','observations':[],'hypotheses':[],'limitations':[],'decision':'继续','evidenceRefs':[]}
    def args(self,**changes):
        facts=self.api.call(self.c,'report_get_facts',{})
        return {'factsId':facts['factsId'],'analysis':self.analysis(),'expectedReportRevision':0,'idempotencyKey':'save',**changes}
    def test_full_catalog_binary_unavailable_empty_and_scope(self):
        for i in range(507):self.service.evidence.add(self.c,'trial',f'item-{i}',f'content-{i}-尾部',{'archive':str(i)},policy='public-development-full-v2')
        e=self.store.list('evidence',self.c)[0];Path(e['path']).unlink()
        result=self.api.call(self.c,'evidence_list',{});data=self.read(result)['data']
        self.assertEqual(result['total'],507);self.assertEqual(result['unavailableCount'],1);self.assertEqual(len(data['items']),507)
        last=data['items'][-1]['file'];self.assertTrue((self.api.files.directory(self.c)/last['path'].lstrip('/')).read_text().endswith('尾部'))
        self.assertEqual(result['file'],self.api.call(self.c,'evidence_list',{})['file'])
        self.store.put('trials',{'id':'empty','campaignId':self.c,'batchId':'batch'})
        self.assertEqual(self.api.call(self.c,'evidence_list',{'trialId':'empty'})['total'],0)
        self.store.put('trials',{'id':'foreign','campaignId':'other'})
        with self.assertRaises(Refused):self.api.call(self.c,'evidence_list',{'trialId':'foreign'})
        with self.assertRaises(Refused):self.api.call(self.c,'evidence_list',{'offset':0})
    def test_sdk_same_frozen_document_and_navigation(self):
        pack=self.service.knowledge_for(self.c);id=next(iter(pack.manifest['documents']))
        result=self.api.call(self.c,'sdk_read',{'id':id});file=result['file']
        self.assertLess(len(encoded(result).encode()),4096)
        self.assertEqual((self.api.files.directory(self.c)/file['path'].lstrip('/')).read_text(),pack._text(id))
        index=json.loads((self.api.files.directory(self.c)/'sdk/index.json').read_text())
        self.assertEqual(index['knowledgePackId'],pack.manifest['id']);self.assertEqual(len(index['documents']),len(pack.manifest['documents']))
    def test_candidate_unavailable_and_stable_status_snapshot(self):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'missing'),'plugins':[]},'fixture',check={'status':'passed','evidence':str(self.data/'missing')})
        result=self.api.call(self.c,'candidate_list',{});rows=self.read(result)['data']['items']
        self.assertEqual(result['total'],1);self.assertEqual(rows[0]['availability'],'unavailable')
        self.assertEqual(rows[0]['id'],candidate['id'])
        result=self.api.call(self.c,'campaign_status',{});snapshot=self.read(result)
        self.assertEqual(result['file'],self.api.call(self.c,'campaign_status',{})['file'])
        self.assertEqual(result['budget']['unknown'],0);self.assertIn('requests',snapshot['data'])
        self.assertNotIn('config',startup_context(self.service,self.c)['state'])
    def test_report_all_errors_direct_file_and_rejected_journal(self):
        bad={'summary':'x','problems':{},'unexpected':'PRIVATE_CONTENT'}
        args=self.args(analysis=bad)
        direct=self.api.call(self.c,'report_save',args)
        self.assertEqual(direct['status'],'rejected');self.assertFalse(direct['committed']);self.assertGreaterEqual(direct['errorCount'],7)
        errors=self.read(direct)['errors'];self.assertNotIn('PRIVATE_CONTENT',encoded(errors))
        self.assertIn('/analysis/observations',[e['pointer'] for e in errors]);self.assertIn('/analysis/unexpected',[e['pointer'] for e in errors])
        self.assertEqual(self.api.call(self.c,'report_save',args),direct)
        self.assertEqual(self.api.requests(self.c)[0]['state'],'rejected')
        self.assertEqual(self.api.call(self.c,'campaign_status',{})['unresolvedOperationCount'],0)
        root=self.data/'campaigns'/self.c/'meta-work/analysis';root.mkdir(parents=True)
        data=encoded(bad).encode();(root/'bad.json').write_bytes(data)
        args.pop('analysis');args.update(idempotencyKey='file',analysisFile={'path':'/work/analysis/bad.json','sha256':hashlib.sha256(data).hexdigest()})
        file=self.api.call(self.c,'report_save',args);self.assertEqual(file['errorCount'],direct['errorCount'])
        self.assertEqual(self.store.list('reports',self.c),[])
    def test_file_commit_replay_after_draft_change_and_lost_journal(self):
        root=self.data/'campaigns'/self.c/'meta-work/analysis';root.mkdir(parents=True)
        data=encoded(self.analysis()).encode();file=root/'draft.json';file.write_bytes(data)
        args=self.args();args.pop('analysis');args['analysisFile']={'path':'/work/analysis/draft.json','sha256':hashlib.sha256(data).hexdigest()}
        publish=self.api.receipts.report
        with patch.object(self.api.receipts,'report',side_effect=OSError('disk')):
            result=self.api.call(self.c,'report_save',args)
        self.assertTrue(result['committed']);self.assertEqual(result['status'],'committed')
        file.write_text('changed draft')
        result=self.api.call(self.c,'report_save',args);row=self.read(result)
        self.assertEqual(result['reportId'],row['id']);self.assertEqual(row['analysisSchema'],'meta-report-analysis-v1')
        self.assertEqual(len(self.store.list('reports',self.c)),1)
        self.assertEqual(result,self.api.call(self.c,'report_save',args))
        with self.assertRaises(Conflict):self.api.call(self.c,'report_save',{**args,'expectedReportRevision':1})
    def test_report_nested_fields_scope_hash_path_and_revision(self):
        analysis={**self.analysis(),'problems':[{'status':'unresolved','description':'待验证'}],'pluginContributions':[{'plugin':'p','expected':'x','observed':'y','comparison':'z','assessment':'unknown'}]}
        args=self.args(analysis=analysis);saved=self.api.call(self.c,'report_save',args);row=self.read(saved)
        self.assertEqual(row['reading']['problems'],['未解决：待验证'])
        stale=self.api.call(self.c,'report_save',{**args,'idempotencyKey':'stale'});self.assertEqual(stale['code'],'revision_conflict')
        bad=self.api.call(self.c,'report_save',{**args,'idempotencyKey':'refs','analysis':{**analysis,'problems':[{'status':'resolved','description':'x','evidenceRefs':['foreign']}]}})
        self.assertEqual(bad['status'],'rejected')
        for i,path in enumerate(['/etc/passwd','/work/analysis/../secret']):
            other={k:v for k,v in args.items() if k!='analysis'};other.update(idempotencyKey='path'+str(i),analysisFile={'path':path,'sha256':'0'*64})
            self.assertEqual(self.api.call(self.c,'report_save',other)['status'],'rejected')
        self.assertEqual(len(self.store.list('reports',self.c)),1)
    def test_retain_committed_once_and_new_receipt_after_publication_failure(self):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'bundle'),'plugins':[]},'fixture',check={'status':'passed'})
        evidence=self.service.evidence.add(self.c,'trial','fixture','evidence',{'archive':'fixture.json'},policy='public-development-full-v2')
        args={'candidateId':candidate['id'],'reason':'Fixture','evidenceRefs':[evidence['id']],'tradeoffs':'fixture','limitations':[],'reconsiderWhen':'later','expectedSelectionRevision':0,'idempotencyKey':'retain'}
        with patch('src.execution.bundle.manifest.verify',return_value={'id':'fixture'}):
            rejected=self.api.call(self.c,'candidate_retain',{**args,'idempotencyKey':'invalid-query-ref','evidenceRefs':[evidence['id'],'query:comparison']})
        self.assertEqual(rejected['status'],'rejected');self.assertNotIn('analysisSchema',rejected)
        self.assertEqual(self.read(rejected)['errors'][0]['pointer'],'/evidenceRefs')
        self.assertEqual(self.store.list('selection_decisions',self.c),[])
        with patch('src.execution.bundle.manifest.verify',return_value={'id':'fixture'}),patch.object(self.api.receipts,'decision',side_effect=OSError('publication unavailable')):
            result=self.api.call(self.c,'candidate_retain',args)
        self.assertEqual(result['status'],'committed')
        result=self.api.call(self.c,'candidate_retain',args);self.read(result)
        self.assertEqual(result['selectionRevision'],1);self.assertEqual(len(self.store.list('selection_decisions',self.c)),1)
        self.assertEqual(self.api.call(self.c,'candidate_retain',args),result)
    def test_large_comparison_same_calculation_and_notification_ack(self):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'bundle'),'plugins':[]},'fixture',check={'status':'passed'})
        batch=self.store.submit(self.c,candidate['id'],['time_budgeted_hamlearn_10q'],1,'batch');trial=self.store.list('trials',self.c)[0]
        for i in range(1001):self.store.put('trials',{**trial,'id':'comparison-'+str(i),'state':['finished','cancelled','failed'][i%3],'score':[0,1,None][i%3]})
        result=self.api.call(self.c,'results_compare',{});full=self.read(result)['data']
        old=self.api._call(self.c,'results_compare',{})
        self.assertEqual(full['evaluation'],old['evaluation']);self.assertEqual(len(full['attempts']),1002)
        cursor=self.store.last_event(self.c);self.store.put('meta_sessions',{'id':'consumer','campaignId':self.c,'runtimeVersion':'meta-runtime-v2','state':'waiting','cursor':cursor})
        with self.store.connection(True) as db:self.store._event(db,self.c,'operation_finished',operationId='fixture',details='large'*10000)
        driver=MetaDriver(self.service)
        with patch.object(self.api.files,'refresh'):
            first=driver.notifications('consumer',cursor);second=driver.notifications('consumer',cursor)
        self.assertEqual(first['events'],second['events']);self.assertLess(len(encoded(first).encode()),4096)
        driver.acknowledge('consumer',first['cursor']);self.assertEqual(self.store.get('meta_sessions','consumer')['cursor'],first['cursor'])
    def test_report_rejects_bad_file_types_hash_symlink_and_both_sources(self):
        root=self.data/'campaigns'/self.c/'meta-work/analysis';root.mkdir(parents=True)
        (root/'ok.json').write_text(encoded(self.analysis()));(root/'escape.json').symlink_to(self.data/'outside.json')
        (self.data/'outside.json').write_text(encoded(self.analysis()))
        args=self.args();args.pop('analysis')
        for i,value in enumerate([{'path':5,'sha256':'0'*64},{'path':'/work/analysis/ok.json','sha256':'0'*64},{'path':'/work/analysis/escape.json','sha256':'0'*64}]):
            result=self.api.call(self.c,'report_save',{**args,'idempotencyKey':'invalid-'+str(i),'analysisFile':value})
            self.assertEqual(result['status'],'rejected');self.assertFalse(result['committed'])
        both=self.api.call(self.c,'report_save',{**args,'idempotencyKey':'both','analysis':self.analysis(),'analysisFile':{'path':'/work/analysis/ok.json','sha256':'0'*64}})
        self.assertEqual(both['status'],'rejected');self.assertEqual(self.store.list('reports',self.c),[])
        self.assertTrue(all(r['state']=='rejected' for r in self.api.requests(self.c)))
    def test_binary_and_intersection_are_complete(self):
        for id in ['a','b']:self.store.put('batches',{'id':id,'campaignId':self.c})
        for id,batch in [('t1','a'),('t2','b')]:self.store.put('trials',{'id':id,'campaignId':self.c,'batchId':batch})
        data=bytes(range(256));p=self.data/'binary.bin';p.write_bytes(data)
        self.store.put('evidence',{'id':'binary','campaignId':self.c,'trialId':'t1','kind':'artifact','path':str(p),'sha256':hashlib.sha256(data).hexdigest(),'source':{'archive':'binary.bin'},'policy':'public-development-full-v2'})
        result=self.api.call(self.c,'evidence_list',{'batchId':'a','trialId':'t1'});row=self.read(result)['data']['items'][0]
        self.assertEqual(row['file']['encoding'],'binary');self.assertEqual((self.api.files.directory(self.c)/row['file']['path'].lstrip('/')).read_bytes(),data)
        self.assertEqual(self.api.call(self.c,'evidence_list',{'batchId':'b','trialId':'t1'})['total'],0)
    def test_explicit_legacy_retention_keeps_rule_and_request_identity(self):
        from src.control.store import LEGACY_RETENTION_RULE
        c=self.store.get('campaigns',self.c);c['config']['retentionRule']=LEGACY_RETENTION_RULE;self.store.put('campaigns',c)
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'bundle'),'plugins':[]},'fixture',check={'status':'passed'})
        batch=self.store.submit(self.c,candidate['id'],['time_budgeted_hamlearn_10q'],1,'baseline')
        trial=self.store.list('trials',self.c)[0];self.store.trial_update(trial['id'],state='finished',score=1,startedAt=1,finishedAt=2)
        evidence=self.service.evidence.add(self.c,trial['id'],'fixture','evidence',{'archive':'fixture.json'},policy='public-development-full-v2')
        args={'candidateId':candidate['id'],'reason':'Fixture','evidenceRefs':[evidence['id']],'tradeoffs':'fixture','limitations':[],'reconsiderWhen':'later','expectedSelectionRevision':0,'idempotencyKey':'retain'}
        with patch('src.execution.bundle.manifest.verify',return_value={'id':'fixture'}):result=self.api.call(self.c,'candidate_retain',args)
        self.assertEqual(result['status'],'completed');self.assertEqual(self.read(result)['rule'],LEGACY_RETENTION_RULE)
        self.assertEqual(result,self.api.call(self.c,'candidate_retain',args));self.assertEqual(len(self.store.list('selection_decisions',self.c)),1)
    def test_closeout_names_missing_round_even_with_final_report(self):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'bundle'),'plugins':[]},'fixture',check={'status':'passed'})
        batch=self.store.submit(self.c,candidate['id'],['time_budgeted_hamlearn_10q'],1,'failed-batch')
        trial=self.store.list('trials',self.c)[0];self.store.trial_update(trial['id'],state='failed',score=None,finishedAt=2)
        # Reproduce final-first reporting without any new model or experiment.
        self.api.call(self.c,'report_save',self.args())
        c=self.store.get('campaigns',self.c);c.update(state='closing',explorationClosed=True,stopReason='round_limit');self.store.put('campaigns',c)
        receipt=self.api.call(self.c,'campaign_status',{})
        self.assertIn(batch['id'],receipt['summary']);self.assertIn('无需再调用 campaign_finish',receipt['summary'])
        full=self.read(receipt)['data']['closeout'];self.assertFalse(full['finalReportRequired']);self.assertEqual(full['missingRoundBatchIds'],[batch['id']])
        facts=self.api.call(self.c,'report_get_facts',{'batchId':batch['id']})
        self.api.call(self.c,'report_save',{'factsId':facts['factsId'],'analysis':self.analysis(),'expectedReportRevision':0,'idempotencyKey':'round'})
        self.assertTrue(self.api.receipts.closeout(self.c)['complete'])
    def test_pause_resume_closeout_never_reopens_exploration_or_changes_budget(self):
        c=self.store.get('campaigns',self.c);c.update(state='closing',explorationClosed=True,stopReason='round_limit');self.store.put('campaigns',c)
        before=self.store.status(self.c)
        self.store.control(self.c,'pause','pause-closeout');self.assertEqual(self.store.status(self.c)['state'],'paused')
        self.service.tick();self.store.close_admission(self.c,'token_threshold')
        self.assertEqual(self.store.status(self.c)['state'],'paused')
        self.store.control(self.c,'resume','resume-closeout');after=self.store.status(self.c)
        self.assertEqual(after['state'],'closing');self.assertTrue(after['explorationClosed']);self.assertEqual(after['stopReason'],'round_limit')
        self.assertEqual(after['deadline'],before['deadline']);self.assertEqual(after['usage'],before['usage']);self.assertEqual(after['config'],before['config'])
    def test_analysis_root_symlink_and_non_regular_file_are_rejected(self):
        import os
        from src.control.meta_receipts import read_analysis_file
        base=self.data/'campaigns'/self.c/'meta-work';base.mkdir(parents=True)
        outside=self.data/'outside';outside.mkdir();(outside/'draft.json').write_text(encoded(self.analysis()))
        root=base/'analysis';root.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):read_analysis_file(root,'draft.json')
        root.unlink();root.mkdir();os.mkfifo(root/'pipe')
        with self.assertRaises(Refused):read_analysis_file(root,'pipe')
        (root/'draft.json').write_text(encoded(self.analysis()))
        self.assertEqual(json.loads(read_analysis_file(root,'draft.json')),self.analysis())
    def test_unknown_exact_protocol_refused(self):
        c=self.store.get('campaigns',self.c);c['config']['metaComposition']['toolContract']['version']='future';self.store.put('campaigns',c)
        with self.assertRaises(Refused):self.api.call(self.c,'campaign_status',{})

if __name__=='__main__':unittest.main()
