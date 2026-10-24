"""Server-owned evidence snapshots and independent stop-review receipts.
Only the authenticated frozen host runtime can register agents and submit native child outcomes.
"""
import hashlib
import math
from pathlib import Path
from .store import Refused, identity, encoded
from .stop_policy import REVIEW_POLICY as POLICY, GOAL_POLICY, CONTROLLED_POLICIES

READ_OPERATIONS={'materials_list','materials_search','materials_read','sdk_search','sdk_read','sdk_inspect','workspace_read','candidate_list','campaign_status','evidence_read','evidence_list'}
TERMINAL={'finished','failed','cancelled'}
def sha(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def required_text(value,label):
    if not isinstance(value,str) or not value.strip() or len(value)>16000:raise Refused(label+' requires nonempty text')
def string_list(value,label,nonempty=False):
    if not isinstance(value,list) or (nonempty and not value) or any(not isinstance(v,str) or not v.strip() for v in value):raise Refused(label+' requires a list of text')
def snapshot(store,db,c):
    campaign=c['id']
    # Revisions, heartbeats, accounting and review receipts are intentionally excluded.
    return {'config':{k:v for k,v in c['config'].items() if k not in ['modelCatalogRevision']},
      'deadline':c['deadline'],'resourcePlan':c.get('resourcePlan'),'retainedCandidateId':c.get('retainedCandidateId'),
      'candidates':[{k:r.get(k) for k in ['id','bundleId','check']} for r in store._list(db,'candidates',campaign)],
      'trials':[{k:r.get(k) for k in ['id','candidateId','state','score','taskAssessment','stopReason','comparisonContext']} for r in store._list(db,'trials',campaign)],
      'evidence':[{k:v for k,v in r.items() if k not in ['revision','schemaVersion','path']} for r in store._list(db,'evidence',campaign)],
      'operations':[{k:r.get(k) for k in ['id','state','kind','result','error']} for r in store._list(db,'operations',campaign)]}
def references(store,db,campaign,refs):
    string_list(refs,'evidenceRefs',True)
    allowed={r['id']:r for r in store._list(db,'evidence',campaign)}
    if set(refs)-allowed.keys():raise Refused('Unknown or cross-Campaign evidence reference')
    for ref in refs:
        row=allowed[ref]
        try:content=Path(row['path']).read_bytes()
        except (OSError,KeyError) as error:raise Refused('Stop evidence unavailable: '+ref) from error
        if hashlib.sha256(content).hexdigest()!=row.get('sha256'):raise Refused('Stop evidence integrity mismatch: '+ref)
def request_valid(store,db,c,request):
    if request.get('condition')!='exhausted':raise Refused('Only exhaustion uses independent review')
    required_text(request.get('reason'),'reason');references(store,db,c['id'],request.get('evidenceRefs'))
    candidate=store._get(db,'candidates',request.get('candidateId',''))
    if candidate['campaignId']!=c['id'] or candidate['check']['status']!='passed':raise Refused('Checked Campaign candidate required')
    attempts=request.get('attempts')
    if not isinstance(attempts,list) or not attempts:raise Refused('Describe substantive attempts and their evidence')
    for item in attempts:
        if not isinstance(item,dict):raise Refused('Invalid attempt')
        required_text(item.get('direction'),'attempt.direction');required_text(item.get('finding'),'attempt.finding');references(store,db,c['id'],item.get('evidenceRefs'))
    for key in ['remainingDirections','unresolved']:string_list(request.get(key),key)
def ready(store,db,c):
    if c['state']!='running' or c['explorationClosed']:raise Refused('Exploration is not open')
    if store.clock()>=c['deadline']-c['config']['reserveSeconds']:raise Refused('Exploration time exhausted; controller owns resource stop')
    usage=store.usage(c['id'],db);cap=c['config'].get('softTokenLimit')
    if cap is not None and usage['confirmedTokens']+usage['inflightReservedTokens']+usage['unknownReservedTokens']>=cap-c['config']['reserveTokens']:raise Refused('Exploration token threshold reached')
def no_pending(store,db,c):
    if any(t['state'] not in TERMINAL for t in store._runs(db,c['id'])) or any(o['state']=='running' for o in store._list(db,'operations',c['id'])):raise Refused('Pending experiments or builds must settle before voluntary stop')

def owns_review(store,db,session,review):
    """A recovered host can read/use its existing judgment, never obtain a new vote."""
    current=session;seen=set()
    while current['id'] not in seen:
        seen.add(current['id'])
        if current['campaignId']!=review['campaignId']:return False
        if current['id']==review['sessionId']:return True
        if current.get('runtimeVersion')!='meta-runtime-v2' or not current.get('previousSessionId'):return False
        current=store._get(db,'meta_sessions',current['previousSessionId'])
    return False

def finish(store,db,c,args):
    """Called inside Store.control's write transaction, including direct finish attempts."""
    ready(store,db,c);no_pending(store,db,c);required_text(args.get('reason'),'reason')
    condition=args.get('condition')
    if condition=='exhausted':
        if c['config'].get('stopPolicy')==GOAL_POLICY:raise Refused('Exploration exhaustion cannot end this activity; continue until the goal is met or the activity budget is reached')
        review=store._get(db,'stop_reviews',args.get('reviewId',''))
        if review['campaignId']!=c['id'] or review['state']!='approved' or review['policy']!=POLICY:raise Refused('Independent approval required')
        references(store,db,c['id'],review['request']['evidenceRefs']);references(store,db,c['id'],review['result']['evidenceRefs'])
        if review['snapshotSha256']!=sha(snapshot(store,db,c)):raise Refused('Stop approval stale; evidence or policy changed')
        if any(args.get(k)!=v for k,v in review['request'].items()):raise Refused('Finish request differs from reviewed request')
        review.update(state='consumed',consumedAt=store.clock());store._save(db,'stop_reviews',review)
        return {'source':'independent-stop-review','condition':condition,'reason':args['reason'],'reviewId':review['id'],'recordedAt':store.clock()}
    if condition=='stable':
        rule=c['config'].get('stabilityRule')
        if not rule:raise Refused('No pre-agreed machine-checkable stabilityRule; cannot claim stable')
        candidate=store._get(db,'candidates',args.get('candidateId',''))
        if candidate['campaignId']!=c['id'] or candidate['check']['status']!='passed':raise Refused('Checked candidate required')
        if candidate['id']!=c.get('retainedCandidateId'):raise Refused('Stable candidate must be the selected final candidate')
        trials=store._list(db,'trials',c['id'])
        for task in c['config']['tasks']:
            rows=[t for t in trials if t['candidateId']==candidate['id'] and t['task']==task and t.get('startedAt') is not None]
            if len(rows)<rule['minTrialsPerTask'] or any(t['state']!='finished' or type(t.get('score')) not in [int,float] or not math.isfinite(t['score']) or t['score']<rule['minimumOfficialScore'] for t in rows):raise Refused('Candidate has not met agreed stabilityRule on all attempts')
        references(store,db,c['id'],args.get('evidenceRefs'))
        return {'source':'controller-verified-stability','condition':'stable','candidateId':candidate['id'],'rule':rule,'reason':args['reason'],'recordedAt':store.clock()}
    raise Refused('A supported stop condition is required')

class StopRuntime:
    def __init__(self,service):self.service=service;self.store=service.store
    def dispatch(self,session_id,action,data):
        store=self.store
        with store.connection(True) as db:
            session=store._get(db,'meta_sessions',session_id);campaign=session['campaignId'];c=store._get(db,'campaigns',campaign)
            if c['config'].get('stopPolicy') not in CONTROLLED_POLICIES or session['state'] not in ['starting','running','waiting']:raise Refused('Active composed Meta session required')
            agents=session.get('agents',{})
            native=c['config'].get('metaComposition',{}).get('version')=='meta-composition-v2'
            main=session.get('nativeSessionId',session_id)
            if action=='register':
                agent=data.get('agentId');preset=data.get('preset')
                if not isinstance(agent,str) or not agent:raise Refused('Native agent identity required')
                if preset not in (['phyexp-meta','phyexp-stop-reviewer','phyexp-researcher'] if native else ['phyexp-meta','phyexp-stop-reviewer']):raise Refused('Unknown native preset')
                if native and not data.get('isolated'):raise Refused('Isolated host binding required')
                if preset=='phyexp-meta' and agent!=main:raise Refused('Main session identity mismatch')
                if preset=='phyexp-stop-reviewer':
                    pending=[r for r in store._list(db,'stop_reviews',campaign) if r['sessionId']==session_id and r['state']=='pending']
                    if len(pending)!=1:raise Refused('Reviewer requires exactly one pending request')
                    if any(a.get('reviewId')==pending[0]['id'] for a in agents.values()):raise Refused('Review already owns a child')
                    data={**data,'reviewId':pending[0]['id']}
                    if not native and any(t not in READ_OPERATIONS|{'cordis_inspect_list','cordis_inspect_query','structured_output'} for t in data.get('tools',[])):raise Refused('Reviewer acquired unexpected capability')
                if native and preset!='phyexp-meta':
                    from .reference.plugins import frozen_contracts
                    operations={**self.service.meta_api.contract,**frozen_contracts(self.service,campaign)}
                    if any(t in operations and operations[t]['write'] for t in data.get('tools',[])):raise Refused('Child acquired business writes')
                agents[agent]={**data,'registeredAt':store.clock()};session['agents']=agents;store._save(db,'meta_sessions',session)
                return {'ok':True}
            if action=='call':
                actor=agents.get(data.get('agentId'))
                if not actor:raise Refused('Unregistered native caller')
                if actor['preset']!='phyexp-meta' and data.get('operation') not in READ_OPERATIONS|{'research_list','research_read','evidence_excerpt'}:raise Refused('Child is read-only')
                if data.get('operation')=='campaign_finish' and data.get('input',{}).get('condition')=='exhausted':
                    if c['config'].get('stopPolicy')==GOAL_POLICY:raise Refused('Exploration exhaustion cannot end this activity')
                    review=store._get(db,'stop_reviews',data['input'].get('reviewId',''))
                    if not owns_review(store,db,session,review):raise Refused('Stop approval belongs to a different main session')
                # Dispatch outside this transaction; its own writes are transactional.
            elif action=='model_request':
                actor=agents.get(data.get('agentId'))
                if not actor:raise Refused('Unregistered model caller')
                usage=store._get(db,'usage',data.get('id',''))
                if usage['campaignId']!=campaign or usage['leaseId']!=session['leaseId']:raise Refused('Model accounting owner mismatch')
                usage.update(metaAgentId=data['agentId'],metaPreset=actor['preset'],metaCompositionId=c['config']['metaComposition']['id'])
                return store._save(db,'usage',usage)
            elif action=='observe':
                actor=agents.get(data.get('agentId'))
                if not actor:raise Refused('Unknown agent')
                plugins=c['config']['metaComposition']['plugins'];scope='meta' if actor['preset']=='phyexp-meta' else 'reviewer'
                scope='research' if actor['preset']=='phyexp-researcher' else scope
                if not any(p['id']==data.get('pluginId') and (scope in p.get('roles',[]) if native else p['scope']==scope) and p['enabled'] for p in plugins):raise Refused('Plugin not in frozen composition')
                key=sha([session_id,data.get('agentId'),data.get('pluginId'),data.get('callId'),data.get('event')])
                return store._save(db,'meta_observations',{'id':key,'campaignId':campaign,'sessionId':session_id,**data,'recordedAt':store.clock()})
            elif action=='review_request':
                if c['config'].get('stopPolicy')==GOAL_POLICY:raise Refused('This activity does not support exhaustion reviews')
                if data.get('agentId')!=main or agents.get(main,{}).get('preset')!='phyexp-meta':raise Refused('Only main Meta may request review')
                ready(store,db,c);no_pending(store,db,c);request=data.get('request',{});request_valid(store,db,c,request)
                snapshot_data=snapshot(store,db,c);fingerprint=sha(snapshot_data);key=sha([campaign,POLICY,fingerprint,request])
                reviews=store._list(db,'stop_reviews',campaign)
                # A snapshot gets one independent judgment, not repeated votes with reworded reasons.
                for old in reviews:
                    if old['snapshotSha256']==fingerprint:
                        if old['sessionId']!=session_id and old['state']=='pending':old.update(state='failed',failure='Owner session ended before completion');store._save(db,'stop_reviews',old)
                        return {**old,'replayed':True}
                row={'id':identity('review'),'campaignId':campaign,'sessionId':session_id,'parentAgentId':main,'policy':POLICY,'requestKey':key,'request':request,'snapshot':snapshot_data,'snapshotSha256':fingerprint,'state':'pending','createdAt':store.clock(),'compositionId':c['config']['metaComposition']['id']}
                return store._save(db,'stop_reviews',row)
            elif action=='review_status' and native:
                row=store._get(db,'stop_reviews',data.get('reviewId',''))
                if not owns_review(store,db,session,row):raise Refused('Review owner mismatch')
                return row
            elif action in ['review_attach','review_result','review_failed']:
                row=store._get(db,'stop_reviews',data.get('reviewId',''))
                if row['sessionId']!=session_id or row['campaignId']!=campaign:raise Refused('Review owner mismatch')
                if row['state']!='pending':return row
                if action=='review_failed':row.update(state='failed',failure=str(data.get('error','Review failed'))[:16000],finishedAt=store.clock())
                else:
                    child=agents.get(data.get('childId'),{})
                    if child.get('preset')!='phyexp-stop-reviewer' or child.get('reviewId')!=row['id']:raise Refused('Native reviewer identity mismatch')
                    if action=='review_attach':row['childId']=data['childId']
                    else:
                        if row.get('childId')!=data['childId']:raise Refused('Review child differs from published activation')
                        result=data.get('result');valid=isinstance(result,dict) and result.get('verdict') in ['approve','continue','insufficient_evidence']
                        try:
                            if not valid or data.get('stopReason')!='completed':raise Refused('Incomplete native review')
                            required_text(result.get('reason'),'Review reason');references(store,db,campaign,result.get('evidenceRefs'))
                            for key in ['missingEvidence','nextDirections']:string_list(result.get(key),key)
                            if result['verdict']=='approve':
                                ready(store,db,c);no_pending(store,db,c)
                                if result['missingEvidence'] or result['nextDirections']:raise Refused('Approval conflicts with missing evidence or feasible directions')
                                if sha(snapshot(store,db,c))!=row['snapshotSha256']:raise Refused('Review evidence became stale')
                            row.update(state={'approve':'approved','continue':'continue','insufficient_evidence':'insufficient_evidence'}[result['verdict']],result=result,finishedAt=store.clock())
                        except (ValueError,TypeError) as error:row.update(state='failed',failure=str(error),result=result,finishedAt=store.clock())
                requests=[u for u in store._list(db,'usage',campaign) if u.get('metaAgentId')==row.get('childId') and u['leaseId']==session['leaseId']] if row.get('childId') else []
                row['usage']={'requestIds':[u['id'] for u in requests],'confirmedTokens':sum(u.get('confirmedTokens') or 0 for u in requests),'unknownReservedTokens':sum(u['reservedTokens'] for u in requests if u['status']=='unknown'),'includedInMetaTotal':True}
                store._event(db,campaign,'stop_review',reviewId=row['id'],state=row['state'])
                return store._save(db,'stop_reviews',row)
            else:raise Refused('Unknown runtime operation')
        return (self.service.meta_api.call if native else self.service.meta_call)(campaign,data['operation'],data.get('input',{}))
