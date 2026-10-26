import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import meta_native_test as base
from src.control.meta_contracts import binding,version,CONTRACTS
from src.control.meta_native_composition import freeze
from src.control.store import Refused,Conflict,encoded
from src.reporting.tables import plugin_key

class EvolutionTests(unittest.TestCase):
    def setUp(self):
        base.NativeMetaTests.setUp(self)
        c=self.store.get('campaigns',self.c)
        with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):c['config']['metaComposition']=freeze(base.ROOT,self.data,c['config'])
        self.store.put('campaigns',c);self.research=self.service.research
    def tearDown(self):base.NativeMetaTests.tearDown(self)
    def record(self,**extra):return {'kind':'motivation','state':'proposed','summary':'先识别不可恢复错误，减少无效重试。','problem':'命令重复失败','hypothesis':'明确错误类别有助于调整行动','change':'提供可读错误摘要','validation':'检查触发和后续行动；成功不等于机制触发','limitations':['尚无对照'],'nextStep':'验证一般任务','factAt':self.store.clock(),**extra}
    def save(self,**extra):return self.research.save(self.c,self.record(**extra),0,'new')
    def ref(self,r):return {'recordId':r['recordId'],'revision':r['revision']}
    def candidate(self,name,plugins=[]):return self.store.candidate(self.c,{'id':name,'path':str(self.data/name),'plugins':plugins},name,check={'status':'passed'})
    def test_new_and_exact_historical_protocol_resolve_independently(self):
        self.assertEqual(version(self.service,self.c),'meta-tools-v10')
        self.assertNotIn('research_save',CONTRACTS['meta-tools-v3'])
        for name,sha in binding('meta-tools-v3')['files'].items():
            self.assertEqual(hashlib.sha256((base.ROOT/'packages/meta-harness/protocols/meta-tools-v3'/name).read_bytes()).hexdigest(),sha)
        c=self.store.get('campaigns',self.c);ref=c['config']['metaComposition'];path=self.data/'meta-compositions'/ref['id']/'manifest.json';m=json.loads(path.read_text());m.pop('id');m['toolContract']=binding('meta-tools-v3');id=hashlib.sha256(encoded(m).encode()).hexdigest();target=path.parent.parent/id;target.mkdir();(target/'manifest.json').write_text(encoded({**m,'id':id}));c['config']['metaComposition']={**ref,'id':id,'toolContract':binding('meta-tools-v3')};self.store.put('campaigns',c)
        self.assertEqual(version(self.service,self.c),'meta-tools-v3')
        c['config']['metaComposition']['toolContract']['files']['contracts.json']='0'*64;self.store.put('campaigns',c)
        self.assertRaises(Refused,version,self.service,self.c)
    def test_append_only_revisions_conflicts_unfrozen_failed_and_report_snapshot(self):
        record=self.record(state='failed');r=self.research.save(self.c,record,0,'first')
        self.assertEqual(r,self.research.save(self.c,record,0,'first'))
        self.assertRaises(Conflict,self.research.save,self.c,self.record(),0,'first')
        facts=self.service.reports.facts(self.c)
        newer=self.research.save(self.c,self.record(state='abandoned'),1,'second',r['recordId'])
        self.assertEqual(newer['revision'],2);self.assertEqual(self.research.detail(self.c,r['recordId'],1)['record']['state'],'failed')
        analysis={'summary':'完整分析','brief':'没有形成候选，已保留失败过程。','observations':[],'hypotheses':[],'limitations':[],'decision':'放弃','evidenceRefs':[],'researchRefs':[self.ref(r)]}
        report=self.service.reports.save(self.c,analysis,facts=facts)
        self.assertEqual(report['researchRecords'][0]['revision'],1);self.assertEqual(report['reading']['summary'],analysis['brief'])
        self.assertRaises(Refused,self.service.reports.save,self.c,{**analysis,'researchRefs':[self.ref(newer)]},facts=facts)
        self.assertEqual(self.research.overview(self.c)['items'][0]['state'],'abandoned')
        self.assertEqual(self.store.list('candidates',self.c),[])
    def test_character_anchors_scope_missing_corrupt_and_binary(self):
        e=self.service.evidence.add(self.c,None,'test','前🧪证据后',{'archive':'test.txt'})
        a={'evidenceId':e['id'],'sha256':e['sha256'],'start':1,'end':4,'unit':'characters','supports':'只支持记录存在'}
        self.assertEqual(self.service.evidence.excerpt(self.c,a)['text'],'🧪证据')
        self.save(anchors=[a])
        for change,status in [({'start':-1},'invalid_range'),({'sha256':'0'*64},'stale'),({'unit':'bytes'},'unsupported')]:self.assertEqual(self.service.evidence.excerpt(self.c,{**a,**change})['availability'],status)
        self.assertEqual(self.service.evidence.excerpt('foreign',a)['availability'],'unauthorized')
        Path(e['path']).chmod(0o600);Path(e['path']).write_text('damaged')
        self.assertEqual(self.service.evidence.excerpt(self.c,a)['availability'],'stale');Path(e['path']).unlink()
        self.assertEqual(self.service.evidence.excerpt(self.c,a)['availability'],'unavailable')
    def test_frozen_plugin_identity_and_binding_reused_bundle(self):
        r=self.save();p={'name':'same','version':'1','digest':'a'*64};h=self.candidate('one',[p]);other=self.candidate('two',[{**p,'digest':'b'*64}])
        with self.store.connection(True) as db:self.research.bind_candidate(db,self.c,h,[self.ref(r)])
        self.assertEqual(self.research.detail(self.c,r['recordId'],1)['candidateLinks'][0]['plugins'][0]['pluginKey'],plugin_key(p))
        bad=self.record(plugins=[{'candidateId':other['id'],'pluginKey':plugin_key(p)}])
        self.assertRaises(Refused,self.research.save,self.c,bad,0,'bad')
        self.assertEqual(len(self.store.list('research_records',self.c)),1)
    def test_alternatives_freeze_all_attempts_and_rollback_atomically(self):
        r=self.save();h0=self.candidate('zero');h1=self.candidate('one');h2=self.candidate('two')
        ev=self.service.evidence.add(self.c,None,'test','result',{})
        args=dict(tradeoffs='增加了复杂度',limitations=['无重复证据'],reconsiderWhen='复测失败',summary='先保留基线，候选仍需验证。',alternatives=[{'candidateId':h1['id'],'reason':'尚未测试','evidenceRefs':[]}],researchRefs=[self.ref(r)],expectedSelectionRevision=0)
        selected=self.store.retain(self.c,h0['id'],'保持基线',[ev['id']],**args)['selectionDecision']
        self.assertEqual({x['id'] for x in selected['consideredSnapshot']['candidates']},{h0['id'],h1['id']})
        self.assertNotIn(h2['id'],{x['candidateId'] for x in selected['alternatives']})
        self.assertEqual(next(x for x in selected['consideredSnapshot']['candidates'] if x['id']==h1['id'])['snapshotDisplayName'],'H1 · 原始基线')
        before=copy.deepcopy(selected);h1['displayName']='renamed';self.store.put('candidates',h1)
        self.assertEqual(self.store.get('selection_decisions',selected['id']),before)
        self.assertRaises(Conflict,self.store.retain,self.c,h1['id'],'stale',[ev['id']],**args)
        self.assertEqual(self.store.get('campaigns',self.c)['retainedCandidateId'],h0['id'])
    def test_plugin_reading_filters_before_paging_and_keeps_original_development_revision(self):
        p={'name':'same','version':'1','digest':'a'*64};other={**p,'digest':'b'*64}
        h=self.candidate('one',[p]);second=self.candidate('two',[other])
        origin=self.save()
        with self.store.connection(True) as db:self.research.bind_candidate(db,self.c,h,[self.ref(origin)])
        self.research.save(self.c,self.record(kind='turning_point',state='inconclusive'),1,'revision',origin['recordId'])
        batch=self.store.submit(self.c,h['id'],self.store.get('campaigns',self.c)['config']['tasks'],1,'observe')
        trial=next(t for t in self.store.list('trials',self.c) if t['batchId']==batch['id'])
        observed=self.research.save(self.c,self.record(kind='observation',observations=[{
            'plugin':{'candidateId':h['id'],'pluginKey':plugin_key(p)},'trialId':trial['id'],
            'loaded':'yes','applicable':'unknown','triggered':'unknown','behavior':'尚无行为证据','benefit':'未知','anchors':[]
        }]),0,'observed')
        for i in range(22):
            self.research.save(self.c,self.record(plugins=[{'candidateId':second['id'],'pluginKey':plugin_key(other)}]),0,'unrelated-'+str(i))
        first=self.research.overview(self.c,0,1,plugin_key(p));last=self.research.overview(self.c,1,1,plugin_key(p))
        self.assertEqual(first['total'],2);self.assertEqual(first['nextOffset'],1);self.assertIsNone(last['nextOffset'])
        rows=first['items']+last['items']
        self.assertEqual({r['recordId'] for r in rows},{origin['recordId'],observed['recordId']})
        current=next(r for r in rows if r['recordId']==origin['recordId'])
        self.assertEqual(current['revision'],2);self.assertEqual(current['developmentRefs'],[self.ref(origin)])
        observation=next(r for r in rows if r['recordId']==observed['recordId'])
        self.assertEqual(observation['plugins'],[{'candidateId':h['id'],'pluginKey':plugin_key(p)}])
        for i in range(22):
            self.research.save(self.c,self.record(plugins=[{'candidateId':h['id'],'pluginKey':plugin_key(p)}]),0,'related-'+str(i))
        crowded=self.research.overview(self.c,pluginKey=plugin_key(p))
        self.assertEqual(crowded['total'],24)
        self.assertNotIn(origin['recordId'],[r['recordId'] for r in crowded['items']])
        self.assertEqual(crowded['pluginContext']['developmentRef'],self.ref(origin))
        self.assertEqual(crowded['pluginContext']['latestObservation']['recordId'],observed['recordId'])
        self.assertEqual(self.research.overview(self.c,pluginKey='foreign')['total'],0)
    def test_research_categories_cover_all_records_before_paging_and_follow_plugin_binding(self):
        plugin={'name':'sample','version':'1','digest':'a'*64};candidate=self.candidate('categorized',[plugin])
        linked=self.research.save(self.c,self.record(plugins=[{'candidateId':candidate['id'],'pluginKey':plugin_key(plugin)}]),0,'linked')
        attempts=[self.research.save(self.c,self.record(state='failed' if i==0 else 'proposed'),0,'attempt-'+str(i)) for i in range(23)]
        related=self.research.overview(self.c,relation='plugin')
        first=self.research.overview(self.c,relation='unlinked');last=self.research.overview(self.c,20,relation='unlinked')
        self.assertEqual(related['relationCounts'],{'plugin':1,'unlinked':23})
        self.assertEqual([r['recordId'] for r in related['items']],[linked['recordId']])
        self.assertEqual(first['total'],23);self.assertEqual(first['nextOffset'],20);self.assertEqual(len(last['items']),3)
        self.assertEqual({r['recordId'] for r in first['items']+last['items']},{r['recordId'] for r in attempts})
        with self.store.connection(True) as db:self.research.bind_candidate(db,self.c,candidate,[self.ref(attempts[0])])
        updated=self.research.overview(self.c,relation='plugin')
        self.assertEqual(updated['relationCounts'],{'plugin':2,'unlinked':22})
        self.assertNotEqual(updated['revision'],related['revision'])
        self.assertEqual(next(r for r in updated['items'] if r['recordId']==attempts[0]['recordId'])['state'],'failed')
        self.assertEqual(self.research.overview(self.c,pluginKey=plugin_key(plugin),relation='unlinked')['total'],0)
        self.assertRaises(Refused,self.research.overview,self.c,relation='invented')
    def test_meta_write_reconciles_without_duplicate_and_validates_v4(self):
        args={'record':self.record(),'expectedRevision':0,'idempotencyKey':'api'}
        row=self.api.call(self.c,'research_save',args);self.assertEqual(row,self.api.call(self.c,'research_save',args))
        self.assertEqual(len(self.store.list('research_records',self.c)),1)
        files=list((self.data/'campaigns'/self.c/'meta-requests').glob('*.json'));request=json.loads(files[0].read_text());request['state']='outcome_unknown';files[0].write_text(encoded(request))
        self.assertEqual(self.api.call(self.c,'research_save',args)['recordId'],row['recordId'])
        self.assertEqual(len(self.store.list('research_records',self.c)),1)
    def test_history_adoption_access_scope_provenance_and_no_score_import(self):
        source=self.store.create(self.store.get('campaigns',self.c)['config'],'source')['id']
        evidence=self.service.evidence.add(source,None,'trajectory','旧活动中可核对的错误片段',{'archive':'events.json'})
        self.assertEqual(self.service.evidence.excerpt(self.c,{'evidenceId':evidence['id']})['availability'],'unauthorized')
        private=self.service.adoptions.adopt(self.c,source,'evidence',evidence['id'],'用户先阅读','user-only','private')
        self.assertIsNone(private['evidenceId']);self.assertEqual(self.store.list('evidence',self.c),[])
        adopted=self.service.adoptions.adopt(self.c,source,'evidence',evidence['id'],'启发通用错误提示','meta-research','adopt')
        row=self.store.get('evidence',adopted['evidenceId']);self.assertEqual(row['sha256'],evidence['sha256']);self.assertIsNone(row['trialId'])
        self.assertEqual(self.store.list('trials',self.c),[]);self.assertEqual(self.store.usage(self.c)['confirmedTokens'],0)
        self.assertFalse(row['source']['adoption']['feedbackExposure']['unseenEvaluation'])
        items=list(self.service.materials._records(self.c,'evidence'));self.assertEqual(len(items),1)
        self.assertEqual(items[0]['source']['adoption']['sourceCampaignId'],source)
        self.assertRaises(Refused,self.service.adoptions.adopt,self.c,source,'evidence',adopted['evidenceId'],'foreign','meta-research','forged')
        Path(evidence['path']).unlink()
        replay=self.service.adoptions.adopt(self.c,source,'evidence',evidence['id'],'启发通用错误提示','meta-research','adopt')
        self.assertEqual(replay,adopted);self.assertEqual(self.service.adoptions.list(self.c)[0]['availability'],'unavailable')
    def test_history_task_scope_report_classification_and_authored_annotation(self):
        cfg=copy.deepcopy(self.store.get('campaigns',self.c)['config']);cfg['tasks']=['logical_cnot_decoder_calibration']
        source=self.store.create(cfg,'other-task')['id'];e=self.service.evidence.add(source,None,'test','private task data',{})
        self.assertRaises(Refused,self.service.adoptions.adopt,self.c,source,'evidence',e['id'],'outside task','meta-research','bad')
        self.assertEqual(self.store.list('source_adoptions',self.c),[])
        source=self.store.create(self.store.get('campaigns',self.c)['config'],'source-report')['id']
        report=self.service.reports.status_summary(source,'历史未完成，不是新事实');before=encoded(report)
        adopted=self.service.adoptions.adopt(self.c,source,'report',report['id'],'理解过去的限制','meta-research','report-adopt')
        self.assertEqual(adopted['source']['classification'],'historical-analysis');self.assertEqual(adopted['source']['sourceReportRevision'],1)
        self.assertEqual(encoded(self.store.get('reports',report['id'])),before)
        self.store.finalize(self.c)
        annotation=self.record(kind='annotation',anchors=[{'evidenceId':adopted['evidenceId'],'sha256':adopted['sha256'],'start':0,'end':30,'unit':'characters','supports':'引用旧分析，不是官方结果'}])
        r=self.research.save(self.c,annotation,0,'annotation',author='user');self.assertEqual(r['author'],'user')
        self.assertEqual(self.store.list('trials',self.c),[])
        self.assertRaises(Refused,self.research.save,self.c,self.record(kind='annotation'),0,'missing-source',author='user')
    def test_user_routes_and_read_views_never_grant_meta_writes(self):
        from fastapi.testclient import TestClient
        from src.control.server import make_app
        client=TestClient(make_app(self.service,supervise=False));headers={'Authorization':'Bearer '+self.service.user_token}
        r=self.save();status=client.get('/campaigns/'+self.c,headers=headers).json()
        self.assertIn('researchRevision',status);self.assertNotIn('researchRecords',status)
        route='/campaigns/'+self.c+'/research'
        self.assertEqual(client.get(route).status_code,401)
        self.assertEqual(client.get(route,headers=headers).json()['items'][0]['recordId'],r['recordId'])
        _,token=self.service.lease(self.c,'meta',self.store.clock()+60)
        self.assertEqual(client.post('/campaigns/'+self.c+'/sources',headers={'Authorization':'Bearer '+token},json={}).status_code,403)

    def test_round_report_preserves_activity_version_label(self):
        h0=self.candidate('baseline');h1=self.candidate('candidate')
        b=self.store.submit(self.c,h1['id'],self.store.get('campaigns',self.c)['config']['tasks'],1,'round')
        facts=self.service.reports.facts(self.c,b['id'])
        report=self.service.reports.save(self.c,{'summary':'尚无结果','observations':[],'hypotheses':[],'limitations':[],'decision':'等待','evidenceRefs':[]},b['id'],facts=facts)
        self.assertEqual(report['tables']['versions'][0]['label'],'H1')
        self.assertEqual(report['tables']['rounds'][0]['versionLabel'],'H1')
