"""Transactional authority for Campaigns, accepted batches and request accounting."""
import contextlib
import hashlib
import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
from .defaults import effective_objective

SCHEMA_VERSION = 1
TABLES = ('campaigns','candidates','batches','trials','usage','evidence','reports','exports','leases','operations','meta_sessions')
PUBLIC_TASKS = ('time_budgeted_hamlearn_10q','time_budgeted_shadow_surrogate_60q','tunable_coupler_cz_netzero',
                'logical_cnot_decoder_calibration','adaptive_clustered_clbcs_h2o')
LEGACY_RETENTION_RULE = 'public-development-v1'
RETENTION_RULE = 'public-development-v2'

class Conflict(ValueError): pass
class Refused(ValueError): pass

def identity(prefix): return prefix+'-'+str(uuid.uuid4())
def encoded(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def comparison_issues(trials):
    issues=[]
    for task in sorted({t['task'] for t in trials}):
        contexts=[t.get('comparisonContext') for t in trials if t['task']==task]
        # Build attestations can change the OCI index while executable config and all
        # layers remain byte-identical. Use this identity only with proofs for every run.
        if contexts and all(c and c.get('runnerExecutionManifest') for c in contexts):
            contexts=[{**{k:v for k,v in c.items() if k!='runnerImageId'}} for c in contexts]
        else:
            contexts=[{k:v for k,v in c.items() if k!='runnerExecutionManifest'} if c else c for c in contexts]
        if any(contexts) and (not all(contexts) or any(x!=contexts[0] for x in contexts[1:])):
            issues.append(task+': task sources or runtime image identities differ or are missing')
    return issues

def retention_rule_description(config):
    rule=config.get('retentionRule',LEGACY_RETENTION_RULE)
    if rule==RETENTION_RULE:
        return rule+'：逐任务比较全部已结束且有官方评分的结果；均分与有效评分完成率均不得退步；未评分不填零，失败与取消单独保留；参与比较的版本有待完成试验时暂缓选择。此规则不证明统计显著性或泛化。'
    return rule+'：旧活动沿用完整结果规则；任一任务缺分时不能替换保留版本；全部尝试保留，缺失分数不填零。'

def retention_assessment(config,previous,trials):
    """V2: separate scientific scores from completion reliability, without picking runs."""
    summaries={};scored=[];issues=[]
    for label,rows in [('reference',previous),('candidate',trials)]:
        summaries[label]={}
        for task in config['tasks']:
            selected=[t for t in rows if t['task']==task]
            pending=[t for t in selected if t['state'] not in ['finished','failed','cancelled']]
            cancelled=[t for t in selected if t['state']=='cancelled' and t.get('startedAt') is None]
            completed=[t for t in selected if t not in pending and t not in cancelled]
            valid=[t for t in completed if t['state']=='finished' and type(t.get('score')) in [int,float] and math.isfinite(t['score'])]
            unscored=[t for t in completed if t not in valid]
            scored.extend(valid)
            summaries[label][task]={
                'scoredTrialIds':[t['id'] for t in valid],
                'unscoredTrials':[{'id':t['id'],'state':t['state'],'reason':t.get('stopReason')} for t in unscored],
                'pendingTrialIds':[t['id'] for t in pending],
                'cancelledBeforeStartIds':[t['id'] for t in cancelled],
                'completedAttempts':len(completed),'scoredCount':len(valid),
                'meanScore':sum(t['score'] for t in valid)/len(valid) if valid else None,
                'scoredFraction':len(valid)/len(completed) if completed else None}
            if pending:issues.append(f'{label}/{task}: pending Trials must finish before comparison')
            if not valid:issues.append(f'{label}/{task}: at least one completed official result is required')
    # Failed attempts may have no environment receipt; they remain in reliability
    # accounting. Every score used for scientific comparison must have provenance.
    if any(not t.get('comparisonContext') for t in scored):
        issues.append('Scored results are not comparable: missing comparison provenance')
    if comparison_issues(scored):issues.append('Task sources or runtime images changed; scored results are not comparable')
    for task in config['tasks']:
        old,new=summaries['reference'][task],summaries['candidate'][task]
        if old['meanScore'] is not None and new['meanScore'] is not None:
            if new['meanScore']<old['meanScore']:
                issues.append(f'{task}: score regression ({new["meanScore"]:g} < {old["meanScore"]:g})')
            # Exact integer comparison avoids rounding the completion fractions.
            if new['scoredCount']*old['completedAttempts']<old['scoredCount']*new['completedAttempts']:
                issues.append(f'{task}: scored completion rate regression ({new["scoredCount"]}/{new["completedAttempts"]} < {old["scoredCount"]}/{old["completedAttempts"]})')
    return {'rule':RETENTION_RULE,'eligible':not issues,'issues':issues,**summaries}

def validate_config(config):
    config=dict(config)
    for key in ['objective','stabilityCriteria']:
        if key in config and config[key] is not None and (not isinstance(config[key],str) or len(config[key])>16000):
            raise Refused(key+' must be text of at most 16000 characters')
    if 'retentionRule' in config and config['retentionRule'] not in [LEGACY_RETENTION_RULE,RETENTION_RULE]:
        raise Refused('Unknown retention rule')
    # None is a genuine absent cap, never a large sentinel. Wall time stays finite.
    for key in ['maxRounds','maxTrials','trialTimeSeconds','softTokenLimit']:
        config.setdefault(key,None)
        if config[key] is not None and (type(config[key]) is not int or config[key]<=0):
            raise Refused(key+' must be null or a positive integer')
    for key in ['concurrency','wallTimeSeconds']:
        if type(config.get(key)) is not int or config[key]<=0:raise Refused(key+' must be a positive integer')
    for key,total in [('reserveSeconds','wallTimeSeconds'),('reserveTokens','softTokenLimit')]:
        if config.get(key) is None:
            config[key]=min(900,max(0,config[total]//10)) if key=='reserveSeconds' else (min(800000,config[total]//10) if config[total] else 0)
        if type(config[key]) is not int or config[key]<0 or (config[total] is not None and config[key]>=config[total]):raise Refused('Invalid '+key)
    if config['softTokenLimit'] is None:config['reserveTokens']=0
    if 'authorizationDeadline' in config:
        import math
        if type(config['authorizationDeadline']) not in [int,float] or not math.isfinite(config['authorizationDeadline']) or config['authorizationDeadline']<=0:raise Refused('Invalid authorization deadline')
    if config.get('retries',0)!=0 or config.get('hardTokenLimit') or config.get('dollarLimit'):
        raise Refused('This provider supports a soft token threshold, no verified hard token/dollar limit or automatic retries')
    if config['maxTrials'] is not None and config['concurrency']>config['maxTrials']:raise Refused('Concurrency exceeds Trial limit')
    if not config.get('tasks') or len(set(config['tasks']))!=len(config['tasks']) or any(t not in PUBLIC_TASKS for t in config['tasks']):
        raise Refused('Only registered public development tasks are available')
    if config['maxTrials'] is not None and len(config['tasks'])>config['maxTrials']:raise Refused('Trial limit cannot cover the baseline task set')
    for role in ['solver','meta']:
        model=config.get(role,{})
        if model.get('provider')!='openai-codex' or model.get('model') not in ['gpt-6-sol','gpt-6-astra','gpt-6-luna'] or model.get('reasoningEffort') not in ['low','medium','high','xhigh']:
            raise Refused('Unsupported model configuration')
    if type(config.get('drainGraceSeconds',300)) is not int or not 0<=config.get('drainGraceSeconds',300)<=900:raise Refused('Drain grace must be 0–900 seconds')
    if config.get('stopMode','strict') not in ['strict','drain']:raise Refused('Unknown stop mode')
    return {**config,'retries':0,'taskPurpose':'development','stopMode':config.get('stopMode','strict'),'limitKind':'soft',
            'drainGraceSeconds':config.get('drainGraceSeconds',300),'weights':{t:1/len(config['tasks']) for t in config['tasks']}}

class Store:
    def __init__(self,path,clock=time.time):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.clock=clock
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY)')
            db.execute('INSERT OR IGNORE INTO migrations VALUES (?)',(SCHEMA_VERSION,))
            for table in TABLES:
                db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,campaign TEXT NOT NULL,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,campaign TEXT NOT NULL,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS commands(campaign TEXT,kind TEXT,key TEXT,payload TEXT,result TEXT,PRIMARY KEY(campaign,kind,key))')
    @contextlib.contextmanager
    def connection(self,write=False):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        try:
            if write:db.execute('BEGIN IMMEDIATE')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()
    def _get(self,db,table,id):
        if table not in TABLES:raise ValueError('Unknown table')
        row=db.execute(f'SELECT data FROM {table} WHERE id=?',(id,)).fetchone()
        if row is None:raise KeyError(id)
        return json.loads(row['data'])
    def get(self,table,id):
        with self.connection() as db:return self._get(db,table,id)
    def _list(self,db,table,campaign=None):
        if table not in TABLES:raise ValueError('Unknown table')
        rows=db.execute(f'SELECT data FROM {table}'+(' WHERE campaign=?' if campaign else ''),(campaign,) if campaign else ()).fetchall()
        return [json.loads(row['data']) for row in rows]
    def list(self,table,campaign=None):
        with self.connection() as db:return self._list(db,table,campaign)
    def _save(self,db,table,value):
        value={**value,'schemaVersion':1,'revision':value.get('revision',0)+1}
        db.execute(f'INSERT INTO {table} VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
            (value['id'],value.get('campaignId',value['id']),encoded(value)))
        return value
    def _event(self,db,campaign,kind,**data):
        event={'type':kind,'time':self.clock(),**data};db.execute('INSERT INTO events(campaign,data) VALUES(?,?)',(campaign,encoded(event)))
    def events(self,campaign,after=0):
        with self.connection() as db:return [{**json.loads(r['data']),'seq':r['seq']} for r in db.execute(
            'SELECT * FROM events WHERE campaign=? AND seq>? ORDER BY seq LIMIT 200',(campaign,after))]
    def last_event(self,campaign):
        with self.connection() as db:return db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE campaign=?',(campaign,)).fetchone()[0]
    def _idem(self,db,campaign,kind,key,payload):
        if not isinstance(key,str) or not 1<=len(key)<=200:raise Refused('Idempotency key required')
        row=db.execute('SELECT * FROM commands WHERE campaign=? AND kind=? AND key=?',(campaign,kind,key)).fetchone()
        if row:
            if row['payload']!=encoded(payload):raise Conflict('Idempotency key reused with different input')
            return json.loads(row['result'])
    def _remember(self,db,campaign,kind,key,payload,result):
        db.execute('INSERT INTO commands VALUES(?,?,?,?,?)',(campaign,kind,key,encoded(payload),encoded(result)))
        return result
    def create(self,config,key,defaults=None):
        config=validate_config(config)
        with self.connection(True) as db:
            prior=self._idem(db,'global','create',key,config)
            if prior:return prior
            c={'id':identity('campaign'),'config':{**config,**(defaults or {}),'objective':effective_objective(config),'retentionRule':config.get('retentionRule',RETENTION_RULE)},'state':'draft','createdAt':self.clock(),'startedAt':None,
               'deadline':None,'stopReason':None,'retainedCandidateId':None,'finalCandidateId':None,'explorationClosed':False}
            c=self._save(db,'campaigns',c);self._event(db,c['id'],'created')
            return self._remember(db,'global','create',key,config,c)
    def usage(self,campaign,db=None):
        rows=self._list(db,'usage',campaign) if db else self.list('usage',campaign)
        return {'confirmedTokens':sum(r.get('confirmedTokens') or 0 for r in rows),
            'inflightReservedTokens':sum(r['reservedTokens'] for r in rows if r['status']=='inflight'),
            'unknownReservedTokens':sum(r['reservedTokens'] for r in rows if r['status']=='unknown'),
            'unknownRequests':sum(r['status']=='unknown' for r in rows),'requests':len(rows),'limitKind':'soft'}
    def _counts(self,db,campaign):
        trials=self._list(db,'trials',campaign)
        return {'rounds':len(self._list(db,'batches',campaign)),
            'trials':sum(t['state']!='cancelled' for t in trials),
            'startedTrials':sum(t.get('startedAt') is not None for t in trials),
            'activeTrials':sum(t['state'] in ['launching','running'] for t in trials),
            'reservedTrials':sum(t['state']=='reserved' for t in trials)}
    def status(self,id):
        with self.connection() as db:
            c=self._get(db,'campaigns',id);c['counts']=self._counts(db,id);c['usage']=self.usage(id,db)
            c['elapsedSeconds']=max(0,(c.get('finishedAt') or self.clock())-c['startedAt']) if c['startedAt'] else 0
            c['remainingSeconds']=max(0,c['deadline']-self.clock()) if c['deadline'] else c['config']['wallTimeSeconds']
            return c
    def control(self,id,action,key,expected_revision=None,changes=None):
        payload={'action':action,'expectedRevision':expected_revision,'changes':changes}
        with self.connection(True) as db:
            prior=self._idem(db,id,'control',key,payload)
            if prior:return prior
            c=self._get(db,'campaigns',id)
            if expected_revision is not None and c['revision']!=expected_revision:raise Conflict('Campaign revision changed')
            if action=='start':
                if c['state']!='draft':raise Refused('Campaign already started')
                c.update(state='running',startedAt=self.clock(),deadline=min(self.clock()+c['config']['wallTimeSeconds'],c['config'].get('authorizationDeadline',float('inf'))))
            elif action=='pause':
                if c['state']!='running':raise Refused('Only a running Campaign can pause')
                c['state']='paused'
            elif action=='resume':
                if c['state']!='paused':raise Refused('Campaign is not paused')
                if self.clock()>=c['deadline']-c['config']['reserveSeconds']:
                    c.update(state='closing',explorationClosed=True,stopReason='time_limit')
                else:c['state']='running'
            elif action in ['stop','finish']:
                if c['state'] in ['finished','failed']:raise Refused('Campaign already finalized')
                if action=='finish' and changes and changes.get('reason'):
                    c['finishAssessment']={'source':'meta-analysis','reason':changes['reason'],'recordedAt':self.clock()}
                c.update(state='closing',explorationClosed=True,stopReason='user_stop' if action=='stop' else (c['stopReason'] or 'meta_finished'))
                for t in self._list(db,'trials',id):
                    if t['state']=='reserved':t.update(state='cancelled',stopReason=c['stopReason']);self._save(db,'trials',t)
            elif action=='limits':
                if c['state'] in ['finished','failed']:raise Refused('Finalized Campaign is immutable')
                allowed={'maxRounds','maxTrials','concurrency','wallTimeSeconds','trialTimeSeconds','softTokenLimit','reserveSeconds','reserveTokens','stopMode','drainGraceSeconds'}
                if not changes or set(changes)-allowed:raise Refused('Only user limits may change')
                c['config']=validate_config({**c['config'],**changes})
                if c['startedAt']:c['deadline']=min(c['startedAt']+c['config']['wallTimeSeconds'],c['config'].get('authorizationDeadline',float('inf')))
            else:raise Refused('Unknown control action')
            self._finish_batches(db,id)
            c=self._save(db,'campaigns',c);self._event(db,id,action,changes=changes)
            return self._remember(db,id,'control',key,payload,c)
    def candidate(self,campaign,bundle,description,parent=None,check=None):
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            if c['explorationClosed'] or c['state'] not in ['draft','running']:raise Refused('Search writes are closed')
            if parent and self._get(db,'candidates',parent)['campaignId']!=campaign:raise Refused('Candidate belongs to another Campaign')
            existing=[x for x in self._list(db,'candidates',campaign) if x['bundleId']==bundle['id']]
            if existing:return existing[0]
            row=self._save(db,'candidates',{'id':identity('candidate'),'campaignId':campaign,'bundleId':bundle['id'],
                'bundlePath':bundle['path'],'plugins':bundle['plugins'],'parentId':parent,'description':description,
                'check':check or {'status':'pending'},'createdAt':self.clock()})
            self._event(db,campaign,'candidate_frozen',candidateId=row['id']);return row
    def submit(self,campaign,candidate,tasks,repeats,key):
        payload={'candidateId':candidate,'tasks':tasks,'repeats':repeats}
        with self.connection(True) as db:
            prior=self._idem(db,campaign,'batch',key,payload)
            if prior:return prior
            c=self._get(db,'campaigns',campaign);cfg=c['config'];counts=self._counts(db,campaign)
            if c['state']!='running' or c['explorationClosed']:raise Refused('Exploration admission closed')
            if self.clock()>=c['deadline']-cfg['reserveSeconds']:raise Refused('Exploration time exhausted')
            selected=self._get(db,'candidates',candidate)
            if selected['campaignId']!=campaign or selected['check']['status']!='passed':raise Refused('Candidate is not checked for this Campaign')
            if not tasks or len(set(tasks))!=len(tasks) or any(t not in cfg['tasks'] for t in tasks) or type(repeats) is not int or repeats<1:
                raise Refused('Invalid task/repeat plan')
            planned=len(tasks)*repeats
            if planned>100:raise Refused('A batch may contain at most 100 Trials; split submissions within the same total limits')
            if (cfg['maxRounds'] is not None and counts['rounds']>=cfg['maxRounds']) or (cfg['maxTrials'] is not None and counts['trials']+planned>cfg['maxTrials']):raise Refused('Round or Trial limit reached')
            u=self.usage(campaign,db)
            if cfg['softTokenLimit'] is not None and u['confirmedTokens']+u['inflightReservedTokens']+u['unknownReservedTokens']>=cfg['softTokenLimit']-cfg['reserveTokens']:
                raise Refused('Exploration token threshold reached')
            batch=self._save(db,'batches',{'id':identity('batch'),'campaignId':campaign,'candidateId':candidate,'round':counts['rounds']+1,
                'tasks':tasks,'repeats':repeats,'testSettings':{k:cfg[k] for k in ['solver','trialTimeSeconds']},'plannedTrials':planned,'state':'accepted','acceptedAt':self.clock()})
            for task in tasks:
                for repeat in range(repeats):
                    self._save(db,'trials',{'id':identity('trial'),'campaignId':campaign,'batchId':batch['id'],'candidateId':candidate,
                        'launchId':identity('launch'),'task':task,'repeat':repeat,'state':'reserved','startedAt':None,
                        'score':None,'usage':{},'stopReason':None})
            round_full=cfg['maxRounds'] is not None and counts['rounds']+1>=cfg['maxRounds']
            trial_full=cfg['maxTrials'] is not None and counts['trials']+planned>=cfg['maxTrials']
            if round_full or trial_full:
                c.update(explorationClosed=True,stopReason='round_limit' if round_full else 'trial_limit')
                self._save(db,'campaigns',c)
            self._event(db,campaign,'batch_accepted',batchId=batch['id'],round=batch['round'],plannedTrials=planned)
            return self._remember(db,campaign,'batch',key,payload,batch)
    def claim(self,campaign):
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign);counts=self._counts(db,campaign)
            if c['state']!='running' or counts['activeTrials']>=c['config']['concurrency'] or self.clock()>=c['deadline']-c['config']['reserveSeconds']:return None
            u=self.usage(campaign,db)
            if c['config']['softTokenLimit'] is not None and u['confirmedTokens']+u['unknownReservedTokens']+u['inflightReservedTokens']>=c['config']['softTokenLimit']-c['config']['reserveTokens']:return None
            t=next((t for t in self._list(db,'trials',campaign) if t['state']=='reserved'),None)
            if t is None:return None
            t.update(state='launching',startedAt=self.clock(),deadline=min(c['deadline']+(c['config']['drainGraceSeconds'] if c['config']['stopMode']=='drain' else 0),self.clock()+(c['config']['trialTimeSeconds'] or 3600),c['deadline']-c['config']['reserveSeconds']))
            t=self._save(db,'trials',t);self._event(db,campaign,'trial_claimed',trialId=t['id'],launchId=t['launchId']);return t
    def trial_update(self,id,**changes):
        with self.connection(True) as db:
            t=self._get(db,'trials',id);t.update(changes);t=self._save(db,'trials',t)
            self._finish_batches(db,t['campaignId'])
            return t
    def _finish_batches(self,db,campaign):
        trials=self._list(db,'trials',campaign)
        for batch in self._list(db,'batches',campaign):
            members=[t for t in trials if t['batchId']==batch['id']]
            if batch['state']!='finished' and members and all(t['state'] in ['finished','failed','cancelled','unknown'] for t in members):
                batch.update(state='finished',finishedAt=self.clock());self._save(db,'batches',batch)
                self._event(db,campaign,'batch_finished',batchId=batch['id'])
    def reserve(self,campaign,lease,id,reserved_tokens,purpose):
        with self.connection(True) as db:
            try:
                row=self._get(db,'usage',id)
                if row['campaignId']!=campaign or row['leaseId']!=lease:raise Conflict('Request identity conflict')
                return row
            except KeyError:pass
            c=self._get(db,'campaigns',campaign);cfg=c['config'];u=self.usage(campaign,db)
            effective_deadline=c['deadline']
            if purpose=='solver' and cfg['stopMode']=='drain':
                try:effective_deadline=min(self._get(db,'leases',lease)['deadline'],c['deadline']+cfg['drainGraceSeconds'])
                except KeyError:pass
            if c['state'] in ['draft','finished','failed'] or (purpose=='meta' and c['state']=='paused') or self.clock()>=effective_deadline:
                raise Refused('Model admission stopped')
            if purpose not in ['solver','meta','report'] or type(reserved_tokens) is not int or reserved_tokens<1:raise Refused('Invalid request reservation')
            closing=purpose=='report' or (purpose=='meta' and (c['state']=='closing' or c['explorationClosed']))
            ceiling=cfg['softTokenLimit']-(0 if closing else cfg['reserveTokens']) if cfg['softTokenLimit'] is not None else None
            if ceiling is not None and sum(u[k] for k in ['confirmedTokens','unknownReservedTokens','inflightReservedTokens'])+reserved_tokens>ceiling:
                raise Refused('Soft token threshold reached')
            row=self._save(db,'usage',{'id':id,'campaignId':campaign,'leaseId':lease,'purpose':'report' if closing else purpose,
                'status':'inflight','reservedTokens':reserved_tokens,'confirmedTokens':None,'startedAt':self.clock()})
            self._event(db,campaign,'request_reserved',requestId=id,purpose=row['purpose']);return row
    def settle(self,campaign,lease,id,confirmed,unknown,*,host_audit=False):
        with self.connection(True) as db:
            row=self._get(db,'usage',id)
            if row['campaignId']!=campaign or row['leaseId']!=lease:raise Refused('Request belongs to another lease')
            if confirmed is not None and (type(confirmed) is not int or confirmed<0):raise Refused('Invalid usage')
            update={'confirmedTokens':confirmed,'status':'unknown' if unknown or confirmed is None else 'reported'}
            if row['status']!='inflight':
                if not any(row[k]!=v for k,v in update.items()):return row
                if not (host_audit and ((row['status']=='unknown' and update['status']=='reported') or (row['status']=='reported' and update['status']=='unknown' and confirmed==row['confirmedTokens']))):
                    raise Conflict('Conflicting usage settlement')
                row['reconciledFromHostAudit']=True
            row.update(update,finishedAt=self.clock());row=self._save(db,'usage',row)
            self._event(db,campaign,'request_settled',requestId=id,status=row['status'],confirmedTokens=confirmed);return row
    def put(self,table,value):
        with self.connection(True) as db:return self._save(db,table,value)
    def mark_unknown(self,lease):
        with self.connection(True) as db:
            for row in self._list(db,'usage'):
                if row['leaseId']==lease and row['status']=='inflight':
                    row.update(status='unknown',finishedAt=self.clock());self._save(db,'usage',row)
                    self._event(db,row['campaignId'],'request_unknown',requestId=row['id'])
    def close_admission(self,campaign,reason,cancel_reserved=True):
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            if c['state'] in ['draft','finished','failed']:return c
            if c['state']!='closing':
                c.update(state='closing',explorationClosed=True,stopReason=reason);c=self._save(db,'campaigns',c)
                self._event(db,campaign,'closing',reason=reason)
            if cancel_reserved:
                for t in self._list(db,'trials',campaign):
                    if t['state']=='reserved':t.update(state='cancelled',stopReason=reason);self._save(db,'trials',t)
            self._finish_batches(db,campaign)
            return c
    def finalize(self,campaign,reason=None):
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            if self._counts(db,campaign)['activeTrials']:raise Refused('Cannot finalize while a Trial is active')
            if c['state']=='finished':return c
            c.update(state='finished',explorationClosed=True,finishedAt=self.clock(),
                stopReason=reason or c['stopReason'] or 'completed',finalCandidateId=c['retainedCandidateId'])
            c=self._save(db,'campaigns',c);self._event(db,campaign,'finished',reason=c['stopReason']);return c
    def retain(self,campaign,candidate,reason,refs):
        rejection=None
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            if c['state']=='finished':raise Refused('Final candidate selection is frozen')
            selected=self._get(db,'candidates',candidate)
            if selected['campaignId']!=campaign:raise Refused('Candidate unavailable')
            trials=[t for t in self._list(db,'trials',campaign) if t['candidateId']==candidate]
            rule=c['config'].get('retentionRule',LEGACY_RETENTION_RULE)
            has_result=any(t['score'] is not None for t in trials) if rule==LEGACY_RETENTION_RULE else any(
                t['state']=='finished' and type(t.get('score')) in [int,float] and math.isfinite(t['score']) for t in trials)
            if not has_result:raise Refused('Retaining a candidate requires a completed official result')
            allowed={e['id'] for e in self._list(db,'evidence',campaign)}
            if not reason or not refs or set(refs)-allowed:raise Refused('Retain requires a reason and allowed evidence IDs')
            assessment=None
            if c['retainedCandidateId'] and c['retainedCandidateId']!=candidate:
                previous=[t for t in self._list(db,'trials',campaign) if t['candidateId']==c['retainedCandidateId']]
                if rule==RETENTION_RULE:
                    assessment=retention_assessment(c['config'],previous,trials)
                    if not assessment['eligible']:
                        rejection='Retention refused: '+'; '.join(assessment['issues'])
                        self._event(db,campaign,'candidate_retention_rejected',candidateId=candidate,
                            reason=reason,evidenceRefs=refs,rule=rule,assessment=assessment)
                else:
                    def scores(rows):
                        result={}
                        for task in c['config']['tasks']:
                            values=[t['score'] for t in rows if t['task']==task]
                            if not values or any(x is None for x in values):return None
                            result[task]=sum(values)/len(values)
                        return result
                    if comparison_issues(previous+trials):
                        raise Refused('Task sources or runtime images changed; results are not comparable')
                    old,new=scores(previous),scores(trials)
                    if old is None or new is None or any(new[t]<old[t] for t in old):raise Refused('Retention rule requires comparable complete results without a task score regression')
            if rejection is None:
                c['retainedCandidateId']=candidate;c=self._save(db,'campaigns',c)
                self._event(db,campaign,'candidate_retained',candidateId=candidate,reason=reason,evidenceRefs=refs,rule=rule,assessment=assessment)
                return c
        # Commit the rejected assessment for audit, without changing the selection.
        raise Refused(rejection)
