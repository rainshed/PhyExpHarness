from src.control.model_access import control_only
"""Append-only authored explanations. Provenance validation never certifies causality."""
import copy
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator,ValidationError
from .store import Refused,Conflict,identity,encoded
from src.reporting.tables import plugin_key,build_tables,read_annotations
from src.evidence.library import EvidenceLibrary
from src.execution.bundle.plugin_reading import candidate_plugins, resolve_reference

SCHEMA=json.loads((Path(__file__).resolve().parents[2]/'packages/meta-harness/research.schema.json').read_text())

def reading_keys(candidates):
    matches={}
    for c in candidates:
        for p in candidate_plugins(c):
            current=plugin_key(p)
            for alias in {current,p.get('storedPluginKey',current)}:
                matches.setdefault((c['id'],alias),set()).add(current)
    return {key:next(iter(values)) for key,values in matches.items() if len(values)==1}


def reading_reference(ref,keys):
    current=keys.get((ref.get('candidateId'),ref.get('pluginKey')))
    return {**ref,'pluginKey':current,'storedPluginKey':ref['pluginKey']} if current and current!=ref['pluginKey'] else ref


def reading_record(row,keys):
    row=copy.deepcopy(row);record=row['record']
    if 'plugins' in record:record['plugins']=[reading_reference(p,keys) for p in record['plugins']]
    for observation in record.get('observations',[]):observation['plugin']=reading_reference(observation['plugin'],keys)
    return row


def reading_links(links,keys):
    return [{**r,'plugins':[reading_reference({**p,'candidateId':r['candidateId']},keys) for p in r['plugins']]} for r in links]


class Research:
    def __init__(self,store,data):self.store=store;self.data=Path(data);self.evidence=EvidenceLibrary(store,data)
    def resolve(self,db,campaign,refs):
        if not isinstance(refs,list):raise Refused('Research references must be an array')
        rows=self.store._list(db,'research_records',campaign);result=[]
        for ref in refs:
            if not isinstance(ref,dict) or set(ref)!={'recordId','revision'}:raise Refused('Exact research revision required')
            row=next((r for r in rows if r['recordId']==ref['recordId'] and r['revision']==ref['revision']),None)
            if row is None:raise Refused('Research revision unavailable in this Campaign')
            result.append(row)
        return result
    def _links(self,db,campaign,record):
        for field,table in [('candidateIds','candidates'),('batchIds','batches'),('trialIds','trials'),('reportIds','reports'),('decisionIds','selection_decisions')]:
            allowed={r['id'] for r in self.store._list(db,table,campaign)}
            if table in ('trials','batches'):allowed|={r['id'] for r in self.store._list(db,'reference_runs' if table=='trials' else 'reference_batches',campaign)}
            if set(record.get(field,[]))-allowed:raise Refused('Research link outside Campaign: '+field)
        self.resolve(db,campaign,record.get('relatedRecords',[]))
        for p in record.get('plugins',[])+[o['plugin'] for o in record.get('observations',[])]:
            candidate=self.store._get(db,'candidates',p['candidateId'])
            if candidate['campaignId']!=campaign or resolve_reference(candidate,p['pluginKey']) is None:raise Refused('Exact frozen plugin identity required')
        for o in record.get('observations',[]):
            t=self.store._get(db,self.store.run_table(o['trialId']),o['trialId'])
            if t['campaignId']!=campaign or t['candidateId']!=o['plugin']['candidateId']:raise Refused('Observation must reference an actual use of this plugin')
        anchors=record.get('anchors',[])+[a for o in record.get('observations',[]) for a in o['anchors']]
        for anchor in anchors:
            if self.evidence.excerpt(campaign,anchor)['availability']!='available':raise Refused('Research evidence anchor unavailable or invalid')
    def save(self,campaign,record,expectedRevision,idempotencyKey,recordId=None,author='meta'):
        try:Draft202012Validator(SCHEMA).validate(record)
        except ValidationError as error:raise Refused('Research record: '+error.message) from error
        if type(expectedRevision) is not int or expectedRevision<0:raise Refused('Expected research revision required')
        if recordId is not None and (not isinstance(recordId,str) or len(recordId)>100):raise Refused('Invalid research identity')
        payload={'record':record,'expectedRevision':expectedRevision,'recordId':recordId,'author':author}
        from src.evidence.cold import ColdArchive
        ColdArchive(self.data).prepare_references(self.store,campaign,record)
        with self.store.connection(True) as db:
            previous=self.store._idem(db,campaign,'research-save',idempotencyKey,payload)
            if previous:return previous
            c=self.store._get(db,'campaigns',campaign)
            if author=='meta' and c['state'] not in ['running','paused','closing']:raise Refused('Meta session is not active')
            prior=[r for r in self.store._list(db,'research_records',campaign) if recordId and r['recordId']==recordId]
            if expectedRevision!=len(prior) or (recordId and not prior):raise Conflict('Research revision changed or unavailable')
            if record['factAt']>self.store.clock()+1:raise Refused('Fact time cannot be in the future')
            if author=='user' and record['kind']=='annotation' and not (record.get('anchors') or record.get('reportIds') or record.get('relatedRecords')):raise Refused('Historical annotation requires recorded sources')
            self._links(db,campaign,record)
            row=self.store._save(db,'research_records',{'id':identity('research-revision'),'campaignId':campaign,
                'recordId':recordId or identity('research'),'revision':expectedRevision,'recordSchema':'evolution-research-v1',
                'author':author,'recordedAt':self.store.clock(),'record':copy.deepcopy(record),
                'previousRevisionId':prior[-1]['id'] if prior else None})
            self.store._event(db,campaign,'research_recorded',recordId=row['recordId'],revision=row['revision'])
            return self.store._remember(db,campaign,'research-save',idempotencyKey,payload,row)
    def bind_candidate(self,db,campaign,candidate,refs):
        # Same transaction as candidate persistence, including reuse of an existing bundle.
        for row in self.resolve(db,campaign,refs):
            key=hashlib.sha256(encoded([campaign,candidate['id'],row['id']]).encode()).hexdigest()
            if any(r['id']==key for r in self.store._list(db,'research_links',campaign)):continue
            self.store._save(db,'research_links',{'id':key,'campaignId':campaign,'candidateId':candidate['id'],
                'bundleId':candidate['bundleId'],'plugins':[{'pluginKey':plugin_key(p),'name':p['name'],'version':p['version'],'digest':p.get('digest')} for p in candidate_plugins(candidate)],
                'recordId':row['recordId'],'recordRevision':row['revision'],'relationship':'development-or-adoption','recordedAt':self.store.clock()})
    def detail(self,campaign,recordId,revision):
        with self.store.connection() as db:row=self.resolve(db,campaign,[{'recordId':recordId,'revision':revision}])[0]
        keys=reading_keys(self.store.list('candidates',campaign));row=reading_record(row,keys)
        anchors=row['record'].get('anchors',[])+[a for o in row['record'].get('observations',[]) for a in o['anchors']]
        return {**row,'revisions':[{k:r[k] for k in ['revision','recordedAt','author']} for r in self.store.list('research_records',campaign) if r['recordId']==recordId],'excerpts':[self.evidence.excerpt(campaign,a) for a in anchors],
            'candidateLinks':reading_links([r for r in self.store.list('research_links',campaign) if r['recordId']==recordId and r['recordRevision']==revision],keys)}
    def overview(self,campaign,offset=0,limit=20,pluginKey=None,relation=None):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:raise Refused('Invalid research page')
        if relation not in (None,'','plugin','unlinked'):raise Refused('Invalid research relation')
        with self.store.connection() as db:
            c=self.store._get(db,'campaigns',campaign);all_rows=self.store._list(db,'research_records',campaign)
            keys=reading_keys(self.store._list(db,'candidates',campaign))
            all_rows=[reading_record(r,keys) for r in all_rows]
            latest={r['recordId']:r for r in sorted(all_rows,key=lambda r:r['revision'])}
            rows=sorted(latest.values(),key=lambda r:r['recordedAt'],reverse=True)
            links=reading_links(self.store._list(db,'research_links',campaign),keys)
            def brief(row):
                record=row['record']
                linked=[r for r in links if r['recordId']==row['recordId']]
                plugins=record.get('plugins',[])+[o['plugin'] for o in record.get('observations',[])]+[{'candidateId':r['candidateId'],'pluginKey':p['pluginKey']} for r in linked for p in r['plugins']]
                return {k:row[k] for k in ['recordId','revision','author','recordedAt']}|{k:record[k] for k in ['kind','state','summary','limitations','nextStep','factAt']}|{
                    'candidateIds':list(dict.fromkeys(record.get('candidateIds',[])+[p['candidateId'] for p in plugins])),
                    'plugins':list({(p['candidateId'],p['pluginKey']):p for p in plugins}.values()),
                    'developmentRefs':list({(r['recordId'],r['recordRevision']):{'recordId':r['recordId'],'revision':r['recordRevision']} for r in linked if not pluginKey or any(p['pluginKey']==pluginKey for p in r['plugins'])}.values())}
            rows=[brief(row) for row in rows]
            if pluginKey:rows=[r for r in rows if any(p['pluginKey']==pluginKey for p in r['plugins'])]
            plugin_context={}
            if pluginKey:
                development=next((r for r in sorted(links,key=lambda r:r['recordedAt']) if any(p['pluginKey']==pluginKey for p in r['plugins'])),None)
                plugin_context={'pluginContext':{'developmentRef':{'recordId':development['recordId'],'revision':development['recordRevision']} if development else None,
                    'latestObservation':next((r for r in rows if r['kind'] in ('observation','turning_point')),None)}}
            relation_counts={'plugin':sum(bool(r['plugins']) for r in rows),'unlinked':sum(not r['plugins'] for r in rows)}
            if relation:rows=[r for r in rows if bool(r['plugins'])==(relation=='plugin')]
            # Limits/next plan may be long; main polling carries only a fingerprint, this view is fetched on changes.
            fingerprint=hashlib.sha256(encoded([all_rows,links,c.get('selectionDecisionId')]).encode()).hexdigest()
            return {'schemaVersion':'evolution-view-v1','revision':fingerprint,'observedAt':self.store.clock(),
                'availability':'available' if rows else 'not_recorded','total':len(rows),'items':rows[offset:offset+limit],
                'nextOffset':offset+limit if offset+limit<len(rows) else None,'offset':offset,'relationCounts':relation_counts,**plugin_context}

    def selection(self,db,c,selected,summary,alternatives,refs):
        """Freeze all explicitly considered alternatives in the selection transaction."""
        if not isinstance(summary,str) or not summary.strip() or len(summary)>600:raise Refused('Selection summary requires 1–600 characters')
        if not isinstance(alternatives,list) or len(alternatives)>100:raise Refused('Explicit alternatives required')
        research=self.resolve(db,c['id'],refs or [])
        seen=set();choices=[];evidence={e['id']:e for e in self.store._list(db,'evidence',c['id'])}
        for a in alternatives:
            if not isinstance(a,dict) or set(a)!={'candidateId','reason','evidenceRefs'} or not isinstance(a['reason'],str) or not a['reason'].strip() or len(a['reason'])>4000:raise Refused('Alternative requires candidate, reason and evidence')
            cid=a['candidateId']
            if cid==selected['id'] or cid in seen:raise Refused('Alternative must be a distinct candidate')
            seen.add(cid)
            candidate=self.store._get(db,'candidates',cid)
            if candidate['campaignId']!=c['id']:raise Refused('Alternative outside Campaign')
            if not isinstance(a['evidenceRefs'],list):raise Refused('Alternative evidence must be a list')
            for ref in a['evidenceRefs']:
                e=evidence.get(ref)
                if not e or hashlib.sha256(Path(e['path']).read_bytes()).hexdigest()!=e['sha256']:raise Refused('Alternative evidence unavailable')
            choices.append(copy.deepcopy(a))
        ids=seen|{selected['id']}
        if c.get('retainedCandidateId'):ids.add(c['retainedCandidateId'])
        trials=[t for t in self.store._list(db,'trials',c['id']) if t['candidateId'] in ids]
        usage=[] if control_only(c['config']) else self.store._list(db,'usage',c['id'])
        for t in trials:
            requests=[r for r in usage if r['leaseId']==t.get('leaseId')]
            if not control_only(c['config']):t['accountedUsage']={'confirmedTokens':sum(r.get('confirmedTokens') or 0 for r in requests),'unknownRequests':sum(r['status']=='unknown' for r in requests),'unknownReservedTokens':sum(r['reservedTokens'] for r in requests if r['status']=='unknown')}
        from src.evidence.diagnostics import trial_diagnostics
        from src.evidence.outcomes import evaluation
        from .store import comparison_issues
        trials=trial_diagnostics(trials,self.data,c['config'])
        all_candidates=self.store._list(db,'candidates',c['id'])
        names={v['id']:v['displayName'] for v in build_tables(all_candidates,[],[],c,read_annotations(self.data))['versions']}
        candidates=[{**r,'snapshotDisplayName':names[r['id']]} for r in all_candidates if r['id'] in ids]
        return {'summary':summary,'alternatives':choices,'researchRefs':refs,'researchRecords':research,
            'consideredSnapshot':{'factAt':self.store.clock(),'candidates':candidates,'trials':trials,
                'taskEvaluation':evaluation(trials,c['config']['tasks'],candidates,c['config']),
                'comparisonIssues':comparison_issues(trials),'scope':'selected, previous and explicitly considered alternatives'}}
