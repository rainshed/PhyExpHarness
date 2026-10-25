import json
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
import sqlite3
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from src.control.service import ControlService
from src.control.server import make_app
from src.control.store import Refused,RETENTION_RULE
from src.evidence.library import feedback

ROOT=Path(__file__).resolve().parents[2]
class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)
        self.service=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.client=TestClient(make_app(self.service,supervise=False))
        self.client.headers['Authorization']='Bearer '+self.service.user_token
        # Store setup deliberately bypasses resource provisioning; no real models or task containers.
        self.config={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
            'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},'tasks':['time_budgeted_hamlearn_10q'],
            'maxRounds':2,'maxTrials':2,'concurrency':1,'wallTimeSeconds':7200,'trialTimeSeconds':3600,
            'softTokenLimit':3000000,'reserveSeconds':900,'reserveTokens':300000}
        self.c=self.service.store.create(self.config,'setup')['id'];self.service.store.control(self.c,'start','start')
    def tearDown(self):
        self.service.pool.shutdown(wait=True);self.client.close();self.temp.cleanup()
    def test_busy_accounting_returns_retryable_response_and_same_receipt_can_recover(self):
        lease,token=self.service.lease(self.c,'meta',time.time()+60)
        self.client.headers['Authorization']='Bearer '+token
        route='/accounting/'+lease['id']
        body={'id':'request','reservedTokens':300000,'admissionVersion':1}
        self.assertEqual(self.client.post(route+'/reserve',json=body).status_code,200)
        # Obtain a real SQLITE_BUSY error without delaying a production-size timeout.
        first=sqlite3.connect(self.data/'busy.sqlite');second=sqlite3.connect(self.data/'busy.sqlite',timeout=0)
        try:
            first.execute('BEGIN IMMEDIATE')
            try:second.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:busy=error
        finally:first.close();second.close()
        receipt={'id':'request','confirmedTokens':12,'unknown':False}
        with patch.object(self.service.store,'settle',side_effect=busy):
            response=self.client.post(route+'/settle',json=receipt)
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['code'],'accounting_unavailable')
        self.assertEqual(self.service.store.get('usage','request')['status'],'inflight')
        for _ in range(2):self.assertEqual(self.client.post(route+'/settle',json=receipt).status_code,200)
        self.assertEqual(self.service.store.usage(self.c)['confirmedTokens'],12)
        with patch.object(self.service,'authenticate',side_effect=busy):
            response=self.client.get('/health')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json()['code'],'control_database_busy')
            self.assertNotIn('ledger',response.text)
            self.assertEqual(response.json()['retryAfterMs'],500)
    def test_database_fault_response_does_not_leak_internal_details(self):
        with patch.object(self.service.store,'list',side_effect=sqlite3.OperationalError('private database path')):
            response=self.client.get('/health')
        self.assertEqual(response.status_code,500)
        self.assertNotIn('private',response.text)
    def test_list_and_detail_expose_latest_meta_health_without_raw_logs_or_state_changes(self):
        store=self.service.store
        before=store.get('campaigns',self.c)
        store.put('meta_sessions',{'id':'meta-old','campaignId':self.c,'state':'needs_attention',
            'recovery':{'reason':'recovery_exhausted','failure':{'code':'model_transport_error',
                'message':'RAW SECRET','observed':{'transport':{'errorCode':'ETIMEDOUT'},'private':'SECRET'}}},
            'summary':{'error':'RAW STACK SECRET'}})
        listing=self.client.get('/campaigns').json()[0]
        detail=self.client.get('/campaigns/'+self.c).json()
        self.assertEqual(listing['state'],'running')
        self.assertEqual(listing['metaStatus'],detail['metaStatus'])
        self.assertEqual(listing['metaStatus']['state'],'needs_attention')
        self.assertTrue(listing['metaStatus']['connectionTimedOut'])
        self.assertNotIn('SECRET',json.dumps(listing))
        self.assertEqual(store.get('campaigns',self.c),before)
        store.put('meta_sessions',{'id':'meta-new','campaignId':self.c,'state':'running'})
        for result in [self.client.get('/campaigns').json()[0],self.client.get('/campaigns/'+self.c).json()]:
            self.assertEqual(result['metaStatus']['state'],'running')
            self.assertIsNone(result['metaStatus']['failure'])
            self.assertEqual(result['metaStatus']['sessionId'],'meta-new')

    def test_model_catalog_is_available_to_user_and_denied_to_meta(self):
        response=self.client.get('/models')
        self.assertEqual(response.status_code,200)
        catalog=response.json()['models']
        self.assertEqual(catalog[-1]['model'],'deepseek-flash')
        self.assertEqual(catalog[-1]['reasoningEfforts'],['off','low','high','max'])
        _,token=self.service.lease(self.c,'meta',time.time()+60)
        self.client.headers['Authorization']='Bearer '+token
        self.assertEqual(self.client.get('/models').status_code,403)

    def test_direct_resume_is_atomic_and_replays_do_not_clear_later_failures(self):
        store=self.service.store;before=store.get('campaigns',self.c)
        failure={'reason':'recovery_exhausted','failure':{'code':'model_transport_error'}}
        store.put('meta_sessions',{'id':'blocked','campaignId':self.c,'state':'needs_attention','recovery':failure})
        store.put('trials',{'id':'in-flight','campaignId':self.c,'state':'running','startedAt':time.time()})
        trial=store.get('trials','in-flight');usage=store.usage(self.c)
        body={'action':'resume','idempotencyKey':'direct-resume','expectedRevision':before['revision']}
        response=self.client.post('/campaigns/'+self.c+'/control',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'running')
        self.assertEqual(response.json()['deadline'],before['deadline'])
        self.assertEqual(response.json()['config'],before['config'])
        session=store.get('meta_sessions','blocked')
        self.assertEqual(session['state'],'recovering');self.assertEqual(session['recovery']['nextAttempt'],0)
        self.assertEqual(session['recovery']['state'],'recovering')
        self.assertEqual(session['recovery']['failure'],failure['failure'])
        self.assertIn('userResumedAt',session['recovery'])
        self.assertEqual(store.get('trials','in-flight'),trial);self.assertEqual(store.usage(self.c),usage)
        self.assertEqual(self.client.post('/campaigns/'+self.c+'/control',json={**body,'idempotencyKey':'double-click'}).status_code,409)
        store.put('meta_sessions',{'id':'later-failure','campaignId':self.c,'state':'needs_attention','recovery':failure})
        later=store.get('meta_sessions','later-failure')
        replay=self.client.post('/campaigns/'+self.c+'/control',json=body)
        self.assertEqual(replay.json(),response.json())
        self.assertEqual(store.get('meta_sessions','later-failure'),later)
        self.assertEqual([e['type'] for e in store.events(self.c) if e['type'] in ['pause','resume']],['resume'])

    def test_direct_resume_rejects_healthy_expired_or_unauthorized_requests(self):
        store=self.service.store;url='/campaigns/'+self.c+'/control'
        body={'action':'resume','idempotencyKey':'not-blocked'}
        self.assertEqual(self.client.post(url,json=body).status_code,403)
        store.put('meta_sessions',{'id':'blocked','campaignId':self.c,'state':'needs_attention'})
        _,token=self.service.lease(self.c,'meta',time.time()+60)
        self.client.headers['Authorization']='Bearer '+token
        self.assertEqual(self.client.post(url,json=body).status_code,403)
        self.client.headers['Authorization']='Bearer '+self.service.user_token
        c=store.get('campaigns',self.c);c['deadline']=time.time()-1;store.put('campaigns',c)
        self.assertEqual(self.client.post(url,json=body).status_code,403)
        self.assertEqual(store.get('meta_sessions','blocked')['state'],'needs_attention')

    def test_direct_resume_preserves_closeout_and_validation_failure_keeps_attention(self):
        from unittest.mock import patch
        store=self.service.store
        store.control(self.c,'stop','close')
        store.put('meta_sessions',{'id':'blocked','campaignId':self.c,'state':'needs_attention'})
        body={'action':'resume','idempotencyKey':'resume-closeout'};url='/campaigns/'+self.c+'/control'
        with patch('src.control.service.verify_meta',side_effect=Refused('Restore matching Meta dependency lock first')):
            c=store.get('campaigns',self.c);c['config']['metaComposition']={'id':'fixture'};store.put('campaigns',c)
            response=self.client.post(url,json=body)
            self.assertEqual(response.status_code,403)
            self.assertEqual(store.get('meta_sessions','blocked')['state'],'needs_attention')
        with patch('src.control.service.verify_meta'):
            response=self.client.post(url,json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'closing');self.assertTrue(response.json()['explorationClosed'])
        self.assertEqual(response.json()['stopReason'],'user_stop')

    def test_user_meta_and_solver_identities_cannot_cross_authority(self):
        self.assertEqual(self.client.get('/health').status_code,200)
        lease,token=self.service.lease(self.c,'meta',time.time()+60)
        self.client.headers['Authorization']='Bearer '+token
        self.assertEqual(self.client.get('/campaigns').status_code,403)
        self.assertEqual(self.client.get('/candidates/unknown/plugins/unknown').status_code,403)
        self.assertEqual(self.client.post('/candidates/unknown/plugins/unknown/open').status_code,403)
        self.assertEqual(self.client.post('/exports/unknown/open').status_code,403)
        response=self.client.post('/meta/'+self.c,json={'operation':'sdk_inspect','input':{'name':'ctx.credentials.resolve'}})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['availability'],'unavailable')
        self.assertEqual(self.client.post('/meta/'+self.c,json={'operation':'limits','input':{}}).status_code,403)
        other=self.service.store.create(self.config,'other')['id']
        self.assertEqual(self.client.post('/meta/'+other,json={'operation':'campaign_status'}).status_code,403)
        for operation in ['materials_list','materials_search','materials_read']:
            self.assertEqual(self.client.post('/meta/'+other,json={'operation':operation,'input':{}}).status_code,403)
        for input in [{'ref':'../../user-token'},{'ref':'guide:reporting','path':'/etc/passwd'}]:
            self.assertEqual(self.client.post('/meta/'+self.c,json={'operation':'materials_read','input':input}).status_code,403)
        self.assertEqual(self.client.post('/meta/'+self.c,json={'operation':'materials_read','input':{'ref':'guide:reporting'}}).status_code,200)
        self.assertEqual(self.client.post('/accounting/'+lease['id']+'/reserve',json={'id':'request','reservedTokens':300000,'purpose':'report'}).json()['purpose'],'meta')
        solver,token=self.service.lease(self.c,'solver',time.time()+60)
        self.client.headers['Authorization']='Bearer '+token
        self.assertEqual(self.client.post('/meta/'+self.c,json={'operation':'sdk_search','input':{'query':'tools'}}).status_code,403)
        self.assertEqual(self.client.post('/meta/'+self.c,json={'operation':'materials_list','input':{}}).status_code,403)
        self.assertEqual(self.client.post('/accounting/'+lease['id']+'/settle',json={'id':'request','confirmedTokens':0,'unknown':False}).status_code,403)
    def test_meta_retention_api_compares_scored_results_and_explains_failures(self):
        c=self.service.store.get('campaigns',self.c);c['config']['retentionRule']=RETENTION_RULE;self.service.store.put('campaigns',c)
        store=self.service.store;task=self.config['tasks'][0]
        ids=[store.candidate(self.c,{'id':name,'path':'/fixture','plugins':[]},name)['id'] for name in ['H0','H1','H2']]
        e=self.service.evidence.add(self.c,'fixture','official-result','{}',{'fixture':True})
        for i,(candidate,scores) in enumerate(zip(ids,[[0,None],[0,1],[1,None,None]])):
            for j,score in enumerate(scores):
                store.put('trials',{'id':f'{i}-{j}','campaignId':self.c,'candidateId':candidate,'task':task,
                    'state':'finished' if score is not None else 'failed','score':score,'startedAt':1,
                    'comparisonContext':{'taskImageIds':['image'],'runnerImageId':'runner'}})
        store.retain(self.c,ids[0],'Reference',[e['id']])
        lease,token=self.service.lease(self.c,'meta',time.time()+60)
        self.client.headers['Authorization']='Bearer '+token
        body={'operation':'candidate_retain','input':{'candidateId':ids[1],'reason':'Compare all attempts','evidenceRefs':[e['id']]}}
        response=self.client.post('/meta/'+self.c,json=body)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['retainedCandidateId'],ids[1])
        body['input']['candidateId']=ids[2]
        response=self.client.post('/meta/'+self.c,json=body)
        self.assertEqual(response.status_code,403);self.assertIn('completion rate regression',response.text)
        self.assertEqual(store.status(self.c)['retainedCandidateId'],ids[1])

    def test_meta_selects_without_score_veto_and_checks_bundle_evidence_and_authority(self):
        from src.execution.bundle.freeze import canonical,digest
        store=self.service.store;folder=self.data/'frozen';folder.mkdir()
        (folder/'plugin.mjs').write_text('export const fixture=true;')
        manifest={'files':{'plugin.mjs':digest((folder/'plugin.mjs').read_bytes())}}
        manifest['id']=digest(canonical(manifest));(folder/'bundle.json').write_text(json.dumps(manifest))
        candidate=store.candidate(self.c,{'id':manifest['id'],'path':str(folder),'plugins':[]},'Fixture',check={'status':'passed'})
        e=self.service.evidence.add(self.c,'fixture','official-result','{}',{})
        body={'operation':'candidate_retain','input':{'candidateId':candidate['id'],'reason':'Choose baseline pending evidence',
            'evidenceRefs':[e['id']],'tradeoffs':'No scientific result yet','limitations':['Unscored'],
            'reconsiderWhen':'Reassess after the pending experiment'}}
        _,solver=self.service.lease(self.c,'solver',time.time()+60)
        self.client.headers['Authorization']='Bearer '+solver
        self.assertEqual(self.client.post('/meta/'+self.c,json=body).status_code,403)
        _,meta=self.service.lease(self.c,'meta',time.time()+60)
        self.client.headers['Authorization']='Bearer '+meta
        response=self.client.post('/meta/'+self.c,json=body)
        self.assertEqual(response.status_code,200,response.text)
        status=self.client.post('/meta/'+self.c,json={'operation':'campaign_status','input':{'view':'full'}}).json()
        self.assertEqual(status['retainedCandidateId'],candidate['id'])
        self.assertEqual(len(status['selectionDecisions']),1)
        self.assertIn('缺少有效官方评分',';'.join(status['selectionDecision']['assessment']['comparisonLimitations']))
        navigation=self.service.status(self.c)['selectionDecision']
        self.assertNotIn('assessment',navigation);self.assertTrue(navigation['detailsAvailable'])
        summary=self.client.post('/meta/'+self.c,json={'operation':'campaign_status','input':{}}).json()
        self.assertEqual(summary['selectionDecision']['reason'],body['input']['reason'])
        self.assertIn('comparisonLimitations',summary['selectionDecision'])
        before=store.get('campaigns',self.c)
        (folder/'plugin.mjs').write_text('tampered')
        r=self.client.post('/meta/'+self.c,json=body)
        self.assertEqual(r.status_code,403);self.assertIn('integrity',r.text)
        (folder/'plugin.mjs').write_text('export const fixture=true;')
        Path(e['path']).chmod(0o644);Path(e['path']).write_text('tampered')
        r=self.client.post('/meta/'+self.c,json=body)
        self.assertEqual(r.status_code,403);self.assertIn('integrity',r.text)
        self.assertEqual(store.get('campaigns',self.c),before)
        self.assertEqual(len(store.list('selection_decisions',self.c)),1)

    def test_collecting_official_result_does_not_automatically_select_for_new_rule(self):
        store=self.service.store
        candidate=store.candidate(self.c,{'id':'fixture','path':'/fixture','plugins':[]},'Fixture',check={'status':'passed'})
        batch=store.submit(self.c,candidate['id'],self.config['tasks'],1,'fixture');trial=store.claim(self.c)
        folder=self.data/'trial';folder.mkdir()
        text=json.dumps({'pipelineStatus':'completed','officialReward':1,'usage':{},'bundleId':'fixture'})
        (folder/'summary.json').write_text(text)
        (folder/'archive-manifest.json').write_text(json.dumps({'files':{'summary.json':{
            'bytes':len(text.encode()),'sha256':hashlib.sha256(text.encode()).hexdigest()}}}))
        trial=store.trial_update(trial['id'],output=str(folder))
        self.service._collect(trial)
        self.assertEqual(store.get('trials',trial['id'])['score'],1)
        self.assertIsNone(store.status(self.c)['retainedCandidateId'])
        self.assertEqual(store.list('selection_decisions',self.c),[])
        c=store.get('campaigns',self.c);c['config']['retentionRule']=RETENTION_RULE;store.put('campaigns',c)
        self.service._collect(trial)
        self.assertEqual(store.status(self.c)['retainedCandidateId'],candidate['id'])

    def test_filtered_evidence_and_reports_never_publish_unknown_score_fields(self):
        score={'reward_binary':0,'secret':'hidden','result':{'linf':.3,'coefficients_true':[1,2,3]}}
        public=feedback('time_budgeted_hamlearn_10q',score)
        self.assertNotIn('secret',str(public));self.assertNotIn('coefficients_true',str(public))
        self.assertNotIn('result',feedback('unknown',score))
        e=self.service.evidence.add(self.c,'trial-fixture','official-result',json.dumps(public),{'fixture':True})
        self.assertEqual(self.service.evidence.read(self.c,e['id'])['sha256'],e['sha256'])
        analysis={'summary':'A fixture result','observations':['No scientific conclusion'],'hypotheses':[],
            'limitations':['Fixture only'],'decision':'No candidate decision','evidenceRefs':[e['id']]}
        self.assertRaises(Refused,self.service.reports.save,self.c,analysis) # No Trial links this evidence to report facts.
        self.assertRaises(Refused,self.service.evidence.read,'other',e['id'])
        Path(e['path']).chmod(0o644);Path(e['path']).write_text('changed')
        self.assertRaises(Refused,self.service.evidence.read,self.c,e['id'])
    def test_workspace_cannot_escape_or_write_after_exploration_closes(self):
        self.assertRaises(Refused,self.service.meta_call,self.c,'workspace_write',{'path':'../outside','content':'x'})
        result=self.service.meta_call(self.c,'workspace_write',{'path':'plugin/index.mjs','content':'export const name="test";'})
        self.assertGreater(result['bytes'],0)
        self.service.store.close_admission(self.c,'round_limit')
        self.assertRaises(Refused,self.service.meta_call,self.c,'workspace_write',{'path':'plugin/index.mjs','content':'changed'})
        self.assertEqual(self.service.meta_call(self.c,'sdk_inspect',{'name':'ctx.tools.register'})['availability'],'declared-in-execution-sdk')
    def test_report_costs_attribute_closeout_to_meta_and_keep_unknown_solver_reserve(self):
        solver,_=self.service.lease(self.c,'solver',time.time()+60)
        meta,_=self.service.lease(self.c,'meta',time.time()+60)
        self.service.store.reserve(self.c,solver['id'],'solver-unknown',300000,'solver')
        self.service.store.settle(self.c,solver['id'],'solver-unknown',13,True)
        self.service.store.close_admission(self.c,'round_limit')
        request=self.service.store.reserve(self.c,meta['id'],'meta-closeout',300000,'meta')
        self.assertEqual(request['purpose'],'report')
        self.service.store.settle(self.c,meta['id'],'meta-closeout',21,False)
        facts=self.service.reports.facts(self.c)
        self.assertEqual(facts['usageByRole']['solver'],{'confirmedTokens':13,'unknownReservedTokens':300000})
        self.assertEqual(facts['usageByRole']['meta'],{'confirmedTokens':21,'unknownReservedTokens':0})
    def test_user_stop_keeps_meta_available_for_closeout_reports(self):
        from unittest.mock import Mock
        self.service.meta_driver=Mock()
        result=self.service.control(self.c,'stop','stop-for-report')
        self.assertEqual(result['state'],'closing')
        self.service.meta_driver.interrupt.assert_not_called()
        lease,_=self.service.lease(self.c,'meta',time.time()+60)
        self.assertEqual(self.service.store.reserve(self.c,lease['id'],'closeout',300000,'meta')['purpose'],'report')
    def test_restart_does_not_relaunch_an_uncertain_claim(self):
        b={'id':'hash','path':'/fixture','plugins':[]};candidate=self.service.store.candidate(self.c,b,'H0',check={'status':'passed'})
        self.service.store.submit(self.c,candidate['id'],self.config['tasks'],1,'one')
        trial=self.service.store.claim(self.c)
        restarted=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        try:
            restarted.tick();row=restarted.store.get('trials',trial['id'])
            self.assertEqual(row['state'],'unknown');self.assertEqual(row['score'],None)
            self.assertEqual(restarted.store.status(self.c)['counts']['startedTrials'],1)
            self.assertEqual(len(restarted.store.list('trials',self.c)),1)
        finally:restarted.pool.shutdown(wait=True)
    def test_supervisor_survives_client_exit_and_service_reconnect_without_duplicate_start(self):
        from src.execution.bundle.freeze import freeze
        bundle=freeze(ROOT,self.data/'bundles',json.loads((ROOT/'recipes/h0-sol.json').read_text()))
        candidate=self.service.store.candidate(self.c,bundle,'H0',check={'status':'passed'})
        self.service.store.submit(self.c,candidate['id'],self.config['tasks'],1,'once')
        started=[]
        def launch(trial):
            proc=subprocess.Popen([sys.executable,str(ROOT/'tests/fixtures/trial_supervisor.py'),'--output',trial['output'],'--deadline',str(time.time()+.4)])
            started.append(proc);return proc
        self.service.launch_trial_override=launch;self.service.tick()
        trial=self.service.store.list('trials',self.c)[0]
        self.assertEqual(trial['state'],'running')
        self.service.store.reserve(self.c,trial['leaseId'],'lost-response',300000,'solver')
        self.client.close() # The client has no process-lifecycle ownership.
        restarted=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1',launch_trial=lambda _:self.fail('duplicate launch'))
        try:
            restarted.tick();self.assertEqual(restarted.store.list('trials',self.c)[0]['state'],'running')
            started[0].wait(timeout=3);restarted.tick()
            row=restarted.store.list('trials',self.c)[0];self.assertEqual(row['state'],'failed');self.assertIsNone(row['score'])
            self.assertEqual(len(started),1);self.assertEqual(restarted.store.status(self.c)['usage']['unknownRequests'],1)
            self.assertTrue(restarted.store.list('evidence',self.c))
        finally:
            restarted.pool.shutdown(wait=True)
            for proc in started:
                if proc.poll() is None:proc.terminate();proc.wait(timeout=3)
    def test_single_trial_stop_requires_user_and_does_not_close_campaign(self):
        from unittest.mock import patch
        candidate=self.service.store.candidate(self.c,{'id':'stop-fixture','path':'/fixture','plugins':[]},'H0',check={'status':'passed'})
        self.service.store.submit(self.c,candidate['id'],self.config['tasks'],1,'stop-fixture')
        trial=self.service.store.claim(self.c)
        trial=self.service.store.trial_update(trial['id'],state='running',pid=123,output='/fixture')
        lease,token=self.service.lease(self.c,'meta',time.time()+60)
        user=self.client.headers['Authorization'];self.client.headers['Authorization']='Bearer '+token
        self.assertEqual(self.client.post('/trials/'+trial['id']+'/stop').status_code,403)
        self.client.headers['Authorization']=user
        with patch.object(self.service,'_process_alive',return_value=False):
            first=self.client.post('/trials/'+trial['id']+'/stop').json();second=self.client.post('/trials/'+trial['id']+'/stop').json()
        self.assertEqual(first['stopRequestedAt'],second['stopRequestedAt'])
        self.assertEqual(self.service.store.get('campaigns',self.c)['state'],'running')
        self.assertEqual(first['stopReason'],'user_stop')
