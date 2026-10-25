"""Explicit user grants for historical inspiration; never imports trials or scores."""
import hashlib
import os
from pathlib import Path
from src.control.store import Refused,identity,encoded
from .objects import Objects, enabled

POLICIES={'public-development-v1','public-development-full-v2'}
class Adoptions:
    def __init__(self,service):self.service=service;self.store=service.store;self.data=service.data
    def _source(self,target,sourceCampaignId,sourceKind,sourceId):
        self.store.writable(sourceCampaignId);self.store.writable(target)
        if sourceCampaignId==target:raise Refused('Use current Campaign evidence directly')
        source=self.store.get('campaigns',sourceCampaignId);c=self.store.get('campaigns',target)
        if sourceKind not in ['evidence','report']:raise Refused('Only archived evidence or an exact report revision can be adopted')
        row=self.store.get('evidence' if sourceKind=='evidence' else 'reports',sourceId)
        if row['campaignId']!=sourceCampaignId:raise Refused('Source identity mismatch')
        trial=None
        if sourceKind=='evidence':
            if row['policy'] not in POLICIES:raise Refused('Source policy does not allow further adoption')
            if row.get('trialId'):
                trial=self.store.get('trials',row['trialId'])
                if trial['campaignId']!=sourceCampaignId:raise Refused('Source Trial identity mismatch')
            tasks=[trial['task']] if trial else source['config']['tasks']
            data=self.service.evidence.body(row)
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Refused('Historical evidence integrity mismatch')
        else:
            tasks=source['config']['tasks']
            # Preserve authored analysis with exact report/facts identity. No host paths or runtime config.
            data=encoded({'classification':'historical-analysis','reportId':row['id'],'analysisRevision':row['analysisRevision'],
                'author':row['author'],'createdAt':row['createdAt'],'factsSha256':row['factsSha256'],'analysis':row['analysis']}).encode()
        if set(tasks)-set(c['config']['tasks']):raise Refused('Historical source tasks are outside target development scope')
        return data,{'sourceProject':'PhyExpHarness','sourceCampaignId':sourceCampaignId,'sourceCampaignName':source['config'].get('name') or sourceCampaignId,
            'sourceKind':sourceKind,'sourceId':sourceId,'sourceReportRevision':row.get('analysisRevision'),
            'sourceTrialId':trial['id'] if trial else None,'sourceCandidateId':trial.get('candidateId') if trial else None,
            'tasks':tasks,'sha256':hashlib.sha256(data).hexdigest(),'sourcePolicy':row.get('policy','authored-report'),
            'classification':'historical-analysis' if sourceKind=='report' else 'historical-execution-evidence'}
    def adopt(self,campaign,sourceCampaignId,sourceKind,sourceId,reason,access,idempotencyKey):
        if not isinstance(reason,str) or not reason.strip() or len(reason)>4000:raise Refused('An adoption reason of 1–4000 characters is required')
        if access not in ['user-only','meta-research']:raise Refused('Explicit access scope required')
        payload={'sourceCampaignId':sourceCampaignId,'sourceKind':sourceKind,'sourceId':sourceId,'reason':reason,'access':access}
        # Replay precedes re-reading a source that might since have disappeared.
        with self.store.connection(True) as db:
            prior=self.store._idem(db,campaign,'source-adopt',idempotencyKey,payload)
            if prior:return prior
        data,origin=self._source(campaign,sourceCampaignId,sourceKind,sourceId)
        objects=Objects(self.data)
        # Keep publication and reference registration in GC-safe lock order.
        with objects.locked():
            file=self.data/'evidence'/origin['sha256'];file.parent.mkdir(parents=True,exist_ok=True)
            canonical=objects._publish([data]) if enabled(self.store.get('campaigns',campaign)['config']) else file
            if not file.exists():
                if canonical!=file:os.link(canonical,file)
                else:file.write_bytes(data);file.chmod(0o444)
            if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=origin['sha256']:raise Refused('Adopted copy integrity mismatch')
            with self.store.connection(True) as db:
                prior=self.store._idem(db,campaign,'source-adopt',idempotencyKey,payload)
                if prior:return prior
                self.store.writable(sourceCampaignId,db)
                self.store._get(db,'campaigns',campaign)
                id=identity('adoption');now=self.store.clock()
                provenance={**origin,'targetCampaignId':campaign,'adoptionId':id,'adoptedAt':now,'access':access,
                    'purpose':'design-inspiration','feedbackExposure':{'tasks':origin['tasks'],'purpose':'development','recordedAt':now,'unseenEvaluation':False}}
                evidence=None
                if access=='meta-research':
                    evidence=self.store._save(db,'evidence',{'id':identity('evidence'),'campaignId':campaign,'trialId':None,
                        'kind':'historical-inspiration','sha256':origin['sha256'],'path':str(canonical),'bytes':len(data),
                        'policy':'explicit-history-adoption-v1','source':{'archive':'historical-source.txt','adoption':provenance}})
                row=self.store._save(db,'source_adoptions',{'id':id,'campaignId':campaign,'source':provenance,'reason':reason,
                    'access':access,'evidenceId':evidence['id'] if evidence else None,'recordedAt':now,'author':'user','sha256':origin['sha256']})
                self.store._event(db,campaign,'source_adopted',adoptionId=id,access=access)
                return self.store._remember(db,campaign,'source-adopt',idempotencyKey,payload,row)
    def list(self,campaign):
        self.store.get('campaigns',campaign);rows=[]
        for r in self.store.list('source_adoptions',campaign):
            path=self.data/'evidence'/r['sha256']
            try:available=not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256']
            except OSError:available=False
            rows.append({**r,'availability':'available' if available else 'unavailable','reasonUnavailable':None if available else '受控副本缺失或内容摘要不匹配；来源身份仍保留'})
        return rows

    def read(self,campaign,id,offset=0,limit=16000):
        row=self.store.get('source_adoptions',id)
        if row['campaignId']!=campaign:raise Refused('Source adoption outside Campaign')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=32000:raise Refused('Invalid source range')
        path=self.data/'evidence'/row['sha256']
        try:data=path.read_bytes()
        except OSError:return {**row,'availability':'unavailable','reason':'受控副本缺失，来源身份保留'}
        if path.is_symlink() or hashlib.sha256(data).hexdigest()!=row['sha256']:return {**row,'availability':'stale','reason':'受控副本摘要不匹配'}
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:return {**row,'availability':'unsupported','reason':'二进制材料没有文字预览'}
        return {**row,'availability':'available','offset':offset,'offsetUnit':'characters','total':len(text),'text':text[offset:offset+limit],'nextOffset':offset+limit if offset+limit<len(text) else None}
