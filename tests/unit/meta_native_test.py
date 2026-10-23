import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.control.service import ControlService
from src.control.store import Refused,Conflict
from src.control.meta import MetaDriver
from src.control.meta_recovery import recovery
from src.control.meta_composition import freeze,verify
ROOT=Path(__file__).resolve().parents[2]

class NativeMetaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)
        self.service=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1');self.store=self.service.store
        model={'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'}
        self.c=self.store.create({'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],'concurrency':1,'wallTimeSeconds':7200},'native-fixture')['id']
        c=self.store.get('campaigns',self.c);c['config']['metaComposition']={'version':'meta-composition-v2','id':'fixture','preset':'native','plugins':json.loads((ROOT/'packages/meta-harness/composition-native.json').read_text())['plugins']};c['config']['stopPolicy']='stop-review-v1';self.store.put('campaigns',c)
        self.store.control(self.c,'start','start');self.api=self.service.meta_api
    def tearDown(self):self.service.pool.shutdown(wait=True);self.temp.cleanup()
    def test_full_unknown_score_fields_events_binary_and_tail_are_accessible(self):
        folder=self.data/'trial';(folder/'harbor/fixture/phyexp').mkdir(parents=True);artifacts=folder/'harbor/fixture/verifier/artifacts';artifacts.mkdir(parents=True)
        for task in ['time_budgeted_hamlearn_10q','shadow','cz']:
            value={'task':task,'new_metric':{'nested':[0,42]},'tail':'末尾'}
            (artifacts/(task+'.json')).write_text(json.dumps(value,ensure_ascii=False))
        (artifacts/'array.bin').write_bytes(bytes(range(256)))
        events=[{'type':'new/unrecognized','data':{'full':'长'*20000+'TAIL_UNIQUE'}}]
        (folder/'harbor/fixture/phyexp/events.json').write_text(json.dumps(events,ensure_ascii=False))
        (folder/'summary.json').write_text(json.dumps({'score':{'unknown_metric':7}}))
        rows=self.service.evidence.ingest({'id':'trial-one','campaignId':self.c,'output':str(folder)}, {'score':{'unknown_metric':7}})
        self.assertEqual(len(rows),6)
        row=next(r for r in rows if r['kind']=='trajectory-original');descriptor=self.api.files.evidence(self.c,row)
        source=self.api.files.directory(self.c)/descriptor['path'].lstrip('/')
        self.assertIn('TAIL_UNIQUE',source.read_text());self.assertEqual(json.loads(source.read_text()),events)
        binary=next(r for r in rows if r['source']['archive'].endswith('array.bin'))
        result=self.api.call(self.c,'evidence_read',{'id':binary['id']})
        self.assertFalse(result['previewAvailable']);self.assertEqual(result['encoding'],'binary')
        self.assertEqual(result['sha256'],hashlib.sha256(bytes(range(256))).hexdigest())
        self.assertTrue(result['path'].startswith('/evidence/trials/trial-one/'))
    def test_evidence_pagination_exposes_more_than_500_files_and_search_tail(self):
        for i in range(507):self.service.evidence.add(self.c,'trial',f'item-{i}',f'content-{i}',{'archive':str(i)},policy='public-development-full-v2')
        result=self.api.call(self.c,'evidence_list',{'offset':500,'limit':100})
        self.assertEqual(result['total'],507);self.assertEqual(len(result['items']),7);self.assertIsNone(result['nextOffset'])
        evidence=self.service.evidence.add(self.c,'trial','long','甲'*40000+'TAIL_MATCH',{'archive':'long.txt'},policy='public-development-full-v2')
        found=self.api.call(self.c,'materials_search',{'kind':'evidence','query':'TAIL_MATCH'})
        self.assertEqual(found['matches'][0]['ref'],'evidence:'+evidence['id']);self.assertEqual(found['matches'][0]['matchOffset'],40000)
    def test_notifications_replay_until_durably_acknowledged(self):
        driver=MetaDriver(self.service);cursor=self.store.last_event(self.c)
        session=self.store.put('meta_sessions',{'id':'native','campaignId':self.c,'state':'waiting','runtimeVersion':'meta-runtime-v2','cursor':cursor})
        with self.store.connection(True) as db:self.store._event(db,self.c,'operation_finished',operationId='fixture')
        with patch.object(self.api.files,'refresh'):
            first=driver.notifications('native',cursor);second=driver.notifications('native',cursor)
            self.assertEqual(first['events'],second['events']);self.assertEqual(self.store.get('meta_sessions','native')['cursor'],cursor)
            with self.assertRaises(Refused):driver.acknowledge('native',first['cursor']+1)
            driver.acknowledge('native',first['cursor'])
            self.assertEqual(driver.notifications('native',first['cursor'])['events'],[])
    def test_idempotency_does_not_repeat_unknown_side_effects(self):
        args={'candidateId':'fixture','idempotencyKey':'one'}
        with patch.object(self.api,'_call',return_value={'operationId':'operation-one'}) as work:
            first=self.api.call(self.c,'export_create',args);self.assertEqual(first,self.api.call(self.c,'export_create',args));self.assertEqual(work.call_count,1)
            with self.assertRaises(Conflict):self.api.call(self.c,'export_create',{**args,'candidateId':'different'})
        with patch.object(self.api,'_call',side_effect=ConnectionError('response lost')) as work:
            with self.assertRaises(ConnectionError):self.api.call(self.c,'export_create',{**args,'idempotencyKey':'unknown'})
            result=self.api.call(self.c,'export_create',{**args,'idempotencyKey':'unknown'});self.assertEqual(result['status'],'outcome_unknown');self.assertEqual(work.call_count,1)
    def test_facts_and_analysis_revisions_remain_independent(self):
        snap=self.api.call(self.c,'report_get_facts',{})
        analysis={'summary':'Research record','observations':[],'hypotheses':[],'limitations':[],'decision':'Continue','evidenceRefs':[]}
        args={'factsId':snap['factsId'],'analysis':analysis,'expectedReportRevision':0,'idempotencyKey':'report-1'}
        report=self.api.call(self.c,'report_save',args);row=self.store.get('reports',report['id'])
        self.assertEqual(row['factsSha256'],snap['factsId']);self.assertEqual(report['analysisRevision'],1)
        self.assertEqual(self.api.call(self.c,'report_save',args)['id'],row['id'])
        with self.assertRaises(Refused):self.api.call(self.c,'report_save',{**args,'idempotencyKey':'report-stale'})
        second=self.api.call(self.c,'report_save',{**args,'analysis':{**analysis,'summary':'New interpretation'},'expectedReportRevision':1,'idempotencyKey':'report-2'})
        self.assertEqual(second['analysisRevision'],2);self.assertEqual(self.store.get('reports',row['id'])['analysis']['summary'],'Research record')
    def test_accepted_batch_is_reconciled_after_response_loss(self):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'bundle'),'plugins':[]},'fixture',check={'status':'passed'})
        args={'candidateId':candidate['id'],'tasks':['time_budgeted_hamlearn_10q'],'repeats':1,'idempotencyKey':'lost-batch'}
        call=self.api._call
        def lost(*a):
            call(*a)
            raise ConnectionError('response lost after commit')
        with patch.object(self.api,'_call',side_effect=lost):
            with self.assertRaises(ConnectionError):self.api.call(self.c,'batch_submit',args)
        result=self.api.call(self.c,'batch_submit',args)
        self.assertEqual(result['id'],self.store.list('batches',self.c)[0]['id'])
        self.assertEqual(len(self.store.list('trials',self.c)),1)
        self.assertTrue(self.api.requests(self.c)[0]['reconciled'])
    def test_user_questions_persist_validate_roles_and_answers(self):
        from src.control.meta_questions import request,answer
        self.store.put('meta_sessions',{'id':'native','campaignId':self.c,'runtimeVersion':'meta-runtime-v2','nativeSessionId':'native-id'})
        questions=[{'id':'scope','question':'Which scope?','options':[{'label':'first'},{'label':'second'}]}]
        with self.assertRaises(Refused):request(self.store,'native','child','call',questions)
        row=request(self.store,'native','native-id','call',questions)
        self.assertEqual(row['id'],request(self.store,'native','native-id','call',questions)['id'])
        with self.assertRaises(Refused):answer(self.store,row['id'],{'answers':[{'id':'scope','selected':['forged']}]})
        response={'answers':[{'id':'scope','selected':['first'],'custom':'Keep original limits'}]}
        answer(self.store,row['id'],response)
        self.assertEqual(request(self.store,'native','native-id','call',questions)['answer'],response)
        self.assertEqual(len(self.store.list('meta_questions',self.c)),1)
        with self.assertRaises(Conflict):answer(self.store,row['id'],{'answers':[{'id':'scope','selected':['second']}]})
    def test_recovery_bounded_without_closing_activity(self):
        summary={'failure':{'code':'model_transport_error'}}
        for attempt,delay in enumerate((2,5,10,20,30,60)):
            with self.subTest(attempt=attempt):
                decision=recovery(summary,attempt,100,1000)
                self.assertEqual(decision['state'],'recovering')
                self.assertTrue(decision['automaticRecovery'])
                self.assertEqual(decision['retryAt'],100+delay)
                self.assertEqual(decision['nextAttempt'],attempt+1)
                # Recovery at or after the original deadline must not be admitted.
                self.assertEqual(recovery(summary,attempt,100,100+delay)['state'],'needs_attention')
        exhausted=recovery(summary,6,100,1000)
        self.assertEqual(exhausted['state'],'needs_attention')
        self.assertEqual(exhausted['reason'],'recovery_exhausted')
        self.assertFalse(exhausted['automaticRecovery'])
        for failure in [{'error':'integrity mismatch'},{'failure':{'code':'budget_exhausted'}},
                        {'failure':{'observed':{'transport':{'httpStatus':401}}}}]:
            with self.subTest(failure=failure):
                decision=recovery(failure,5,100,1000)
                self.assertEqual(decision['state'],'needs_attention')
                self.assertEqual(decision['reason'],'nonrecoverable')
        self.assertEqual(recovery(summary,5,100,1000,stopped=True)['state'],'needs_attention')
        self.assertEqual(self.store.get('campaigns',self.c)['state'],'running')
    def test_native_research_registration_and_accounting_remain_scoped_after_host_replacement(self):
        runtime=self.service.stop_runtime
        for attempt in ['first','restored']:
            self.store.put('meta_sessions',{'id':attempt,'campaignId':self.c,'leaseId':attempt,'state':'running','runtimeVersion':'meta-runtime-v2','nativeSessionId':'main'})
            runtime.dispatch(attempt,'register',{'agentId':'main','preset':'phyexp-meta','isolated':True,'isolationScope':'activity-research','runnerId':'main','tools':['campaign_status']})
            runtime.dispatch(attempt,'register',{'agentId':'research','parentAgentId':'main','preset':'phyexp-researcher','isolated':True,'isolationScope':'activity-research','runnerId':'main','tools':['campaign_status','send_message']})
            with self.assertRaises(Refused):runtime.dispatch(attempt,'call',{'agentId':'research','operation':'batch_submit','input':{}})
            with self.assertRaises(Refused):runtime.dispatch(attempt,'register',{'agentId':'writer','preset':'phyexp-researcher','isolated':True,'tools':['batch_submit']})
            with self.assertRaises(Refused):runtime.dispatch(attempt,'register',{'agentId':'review','preset':'phyexp-stop-reviewer','isolated':True,'tools':[]})
            request='request-'+attempt
            self.store.reserve(self.c,attempt,request,100,'meta')
            runtime.dispatch(attempt,'model_request',{'id':request,'agentId':'research'})
            self.store.settle(self.c,attempt,request,30,False)
            self.assertEqual(self.store.get('usage',request)['metaAgentId'],'research')
            self.assertEqual(self.store.get('usage',request)['metaPreset'],'phyexp-researcher')
        self.assertEqual(self.store.usage(self.c)['confirmedTokens'],60)

    def test_recovered_session_reads_prior_review_without_another_vote(self):
        old=self.store.put('meta_sessions',{'id':'old','campaignId':self.c,'runtimeVersion':'meta-runtime-v2','nativeSessionId':'native','state':'recovering'})
        new=self.store.put('meta_sessions',{'id':'new','campaignId':self.c,'runtimeVersion':'meta-runtime-v2','nativeSessionId':'native','state':'running','previousSessionId':'old'})
        review=self.store.put('stop_reviews',{'id':'review','campaignId':self.c,'sessionId':'old','state':'approved','result':{'verdict':'approve'}})
        self.assertEqual(self.service.stop_runtime.dispatch('new','review_status',{'reviewId':'review'})['result']['verdict'],'approve')
        self.store.put('meta_sessions',{'id':'unrelated','campaignId':self.c,'runtimeVersion':'meta-runtime-v2','nativeSessionId':'different','state':'running'})
        with self.assertRaises(Refused):self.service.stop_runtime.dispatch('unrelated','review_status',{'reviewId':'review'})
        self.assertEqual(len(self.store.list('stop_reviews',self.c)),1)
    def test_concurrent_recovery_admits_one_host(self):
        import threading
        entered=threading.Event();release=threading.Event();calls=[]
        def launch(campaign):calls.append(campaign);entered.set();release.wait(5)
        first,second=MetaDriver(self.service),MetaDriver(self.service)
        with patch.object(MetaDriver,'_start',side_effect=launch):
            thread=threading.Thread(target=first.start,args=(self.c,));thread.start()
            self.assertTrue(entered.wait(2))
            try:second.start(self.c);self.assertEqual(calls,[self.c])
            finally:release.set();thread.join(5)
    def test_direct_resume_reaches_supervisor_once_without_pausing_trials(self):
        self.store.put('meta_sessions',{'id':'blocked','campaignId':self.c,'state':'needs_attention',
            'runtimeVersion':'meta-runtime-v2','nativeSessionId':'native',
            'recovery':{'reason':'recovery_exhausted','failure':{'code':'model_transport_error'}}})
        self.store.control(self.c,'resume','direct-resume')
        driver=MetaDriver(self.service)
        def launch(campaign):
            self.store.put('meta_sessions',{'id':'new','campaignId':campaign,'state':'running','pid':123,
                'output':str(self.data/'new-session'),'runtimeVersion':'meta-runtime-v2','previousSessionId':'blocked'})
        with patch.object(driver,'_start',side_effect=launch) as start,patch.object(self.service,'_process_alive',return_value=True):
            driver.tick(self.c);driver.tick(self.c)
        self.assertEqual(start.call_count,1)
        self.assertEqual(self.store.list('meta_sessions',self.c)[-1]['state'],'running')
        self.assertEqual(self.store.status(self.c)['state'],'running')
    def test_export_operation_publishes_readable_archive_and_replays_receipt(self):
        candidate=self.store.candidate(self.c,{'id':'fixture','path':str(self.data/'bundle'),'plugins':[]},'fixture',check={'status':'passed'})
        archive=self.data/'harness.zip';archive.write_bytes(b'PK\x00\xfffixture')
        result={'id':'fixture-export','campaignId':self.c,'candidateId':candidate['id'],'archive':str(archive),'path':str(self.data),'archiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'staticValidation':'passed'}
        args={'candidateId':candidate['id'],'idempotencyKey':'export'}
        with patch.object(self.service,'export',return_value=result) as export:
            receipt=self.api.call(self.c,'export_create',args)
            self.service.operations[receipt['operationId']].result(timeout=5)
            self.assertEqual(self.api.call(self.c,'export_create',args),receipt)
            status=self.api.call(self.c,'export_status',{'operationId':receipt['operationId']})
            self.assertEqual(status['state'],'finished');self.assertEqual(export.call_count,1)
            file=status['result']['file'];self.assertEqual((self.api.files.directory(self.c)/file['path'].lstrip('/')).read_bytes(),archive.read_bytes())
            self.assertNotIn('archive',status['result'])
    def test_native_compositions_store_refs_and_rebuild_cache_without_framework_copy(self):
        with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):
            first=freeze(ROOT,self.data,{'objective':'first','solver':{'model':'fixture'}})
            count=len(list((self.data/'meta-objects/sha256').iterdir()))
            second=freeze(ROOT,self.data,{'objective':'second','solver':{'model':'fixture'}})
        self.assertNotEqual(first['id'],second['id']);self.assertEqual(count,len(list((self.data/'meta-objects/sha256').iterdir())))
        self.assertEqual([p.name for p in (self.data/'meta-compositions'/first['id']).iterdir()],['manifest.json'])
        folder,doc=verify(self.data,first,ROOT);self.assertEqual(doc['framework']['version'],'0.2.1-rc.2')
        self.assertNotIn('src/execution/adapters/quantum_harbor/worker.mjs',doc['files'])
        import shutil
        shutil.rmtree(folder);rebuilt,_=verify(self.data,first,ROOT)
        self.assertTrue((rebuilt/'src/control/meta_worker_native.mjs').is_file())
        blob=self.data/'meta-objects/sha256'/next(iter(doc['files'].values()));blob.chmod(0o644);blob.write_text('corrupted')
        with self.assertRaises(Refused):verify(self.data,first,ROOT)

if __name__=='__main__':unittest.main()
