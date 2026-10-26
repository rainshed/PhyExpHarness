from src.execution.host.storage_layout import state_path, lock_path
"""Transactional authority for Campaigns, accepted batches and request accounting."""
import contextlib
import hashlib
import json
import math
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from .stop_policy import CONTROLLED_POLICIES
from .defaults import effective_objective
from src.execution.host.models import supported_model,load_model_config,provider_route,campaign_model_config
from src.evidence.diagnostics import trial_diagnostics
from src.evidence.outcomes import outcome_summary, DEFAULT_RULE, RULES, rule_for, description_for
from . import resource_planning as planning
from .model_access import control_only, check_config, TOKEN_FIELDS
from .database import begin_write, diagnostic
from src.execution.host.task_time import benchmark_time

SCHEMA_VERSION = 9
TABLES = ('campaigns','candidates','batches','trials','usage','evidence','reports','exports','leases','operations','meta_sessions','selection_decisions','stop_reviews','meta_observations','admissions','meta_questions','research_records','research_links','source_adoptions','reference_batches','reference_runs','owned_artifacts','collection_jobs')
PUBLIC_TASKS = ('time_budgeted_hamlearn_10q','time_budgeted_shadow_surrogate_60q','tunable_coupler_cz_netzero',
                'logical_cnot_decoder_calibration','adaptive_clustered_clbcs_h2o')
LEGACY_RETENTION_RULE = 'public-development-v1'
RETENTION_RULE = 'public-development-v2'
META_RETENTION_RULE = 'meta-selection-v1'

class Conflict(ValueError): pass
class Refused(ValueError): pass

def identity(prefix): return prefix+'-'+str(uuid.uuid4())
def encoded(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def comparison_diagnostics(trials):
    result=[]
    for task in sorted({t['task'] for t in trials}):
        rows=[t for t in trials if t['task']==task]
        pending=[t.get('id','unknown') for t in rows if t.get('state') in ('reserved','queued','launching','running','collecting')]
        if pending:result.append({'task':task,'kind':'pending','trialIds':pending,'fields':[]})
        rows=[t for t in rows if t.get('state') not in ('reserved','queued','launching','running','collecting') and not(t.get('state')=='cancelled' and not t.get('startedAt'))]
        missing=[t.get('id','unknown') for t in rows if not t.get('comparisonContext')]
        if missing:result.append({'task':task,'kind':'missing_metadata','trialIds':missing,'fields':['comparisonContext']})
        rows=[t for t in rows if t.get('comparisonContext')]
        contexts=[dict(t['comparisonContext']) for t in rows]
        proofs=bool(contexts) and all(c.get('runnerExecutionManifest') for c in contexts)
        for c in contexts:
            c.pop('runnerImageId' if proofs else 'runnerExecutionManifest',None)
            if c.get('runContract')=='harbor-process-v1':c.pop('runnerImageId',None);c.pop('runnerExecutionManifest',None)
        fields=sorted({k for c in contexts for k in c if any(x.get(k)!=c.get(k) for x in contexts)})
        if fields:result.append({'task':task,'kind':'different','trialIds':[t.get('id','unknown') for t in rows],
            'fields':fields,'values':[{ 'trialId':t.get('id','unknown'), 'fields':{k:c.get(k) for k in fields}} for t,c in zip(rows,contexts)]})
    return result


def comparison_issues(trials):
    labels={'missing_metadata':'comparison metadata missing','different':'comparison fields differ'}
    return [f"{d['task']}: {labels[d['kind']]} ({', '.join(d['fields'])}); trials: {', '.join(d['trialIds'])}"
        for d in comparison_diagnostics(trials) if d['kind'] in labels]

def retention_rule_description(config):
    rule=config.get('retentionRule',LEGACY_RETENTION_RULE)
    if rule==META_RETENTION_RULE:
        return rule+'：由 Meta 自主选择、维持或回退冻结版本；平台核验候选与证据，记录全部尝试、比较限制及完整决策。缺分、在途试验、环境差异和指标退步只提示，不否决选择；选定不代表稳定性或因果提升认证。'+description_for(config)
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

def selection_assessment(config,previous,trials,has_reference):
    """Descriptive evidence only: the platform does not rank or veto Meta's choice."""
    summary=retention_assessment(config,previous,trials)
    completion={label:outcome_summary(rows,config['tasks'],config) for label,rows in [('reference',previous),('candidate',trials)]}
    limits=[]
    if not has_reference:limits.append('尚无先前保留版本；本次为 Meta 首次选择。')
    for label,title in [('reference','参考版本'),('candidate','选定版本')]:
        if label=='reference' and not has_reference:continue
        for task,row in summary[label].items():
            row['taskCompletion']=completion[label]['byTask'][task]
            counted=row['taskCompletion']
            for key,category_title in [('external_failure','外部故障'),('unresolved','待归因'),('cancelled','取消'),('not_started','未执行')]:
                if counted.get(key):limits.append(f'{title}/{task}：{counted[key]} 次{category_title}，单列且不计入任务成功率。')
            if row['scoredCount']==0:limits.append(f'{title}/{task}：缺少有效官方评分，均分未知。')
            elif row['scoredCount']<2:limits.append(f'{title}/{task}：仅有一次有效评分，重复证据不足。')
            if row['pendingTrialIds']:limits.append(f'{title}/{task}：仍有未结束试验，后续结果可能改变判断。')
            if row['unscoredTrials']:limits.append(f'{title}/{task}：有 {len(row["unscoredTrials"])} 次已结束但未评分的尝试，原因和执行记录保留。')
    scored=[t for t in previous+trials if (t.get('taskAssessment') or {}).get('included') or (t['state']=='finished' and type(t.get('score')) in [int,float] and math.isfinite(t['score']))]
    for issue in comparison_issues(scored):
        limits.append(issue.split(':',1)[0]+'：任务来源或运行镜像身份存在差异或缺失，尚未证明环境一致。')
    if any(not t.get('comparisonContext') for t in scored):limits.append('部分计入任务成功率的尝试缺少比较环境记录。')
    for task in config['tasks']:
        old,new=summary['reference'][task],summary['candidate'][task]
        for key,title in [('meanScore','官方均分')]:
            if old[key] is not None and new[key] is not None and new[key]<old[key]:
                limits.append(f'{task}：选定版本的{title}低于参考版本（{new[key]:g} < {old[key]:g}）。')
        old_rate=completion['reference']['byTask'][task]['successRate'];new_rate=completion['candidate']['byTask'][task]['successRate']
        if old_rate is not None and new_rate is not None and new_rate<old_rate:
            limits.append(f'{task}：选定版本的任务成功率低于参考版本（{new_rate:g} < {old_rate:g}），包含按规则计 0 的失败。')
    limits.append('开发样本与版本选择不能自动证明稳定性、因果收益或跨任务泛化。')
    keys=['id','candidateId','batchId','task','state','score','scoringStatus','stopReason','failure','startedAt','finishedAt','comparisonContext','usage','taskAssessment']
    return {'rule':META_RETENTION_RULE,'source':'platform-evidence-check','certification':'not_certified',
        'reference':summary['reference'],'candidate':summary['candidate'],'comparisonLimitations':limits,'taskEvaluation':{'rule':rule_for(config),**completion},
        'trials':[{k:t[k] for k in keys if k in t} for t in {t['id']:t for t in previous+trials}.values()]}

def validate_config(config,model_config=None):
    model_config=load_model_config() if model_config is None else model_config
    config=dict(config)
    if control_only(config):check_config(config)
    if config.get('resourcePolicy') not in (None, planning.POLICY):raise Refused('Unknown resource policy')
    if config.get('taskEvaluationRule',DEFAULT_RULE) not in RULES:raise Refused('Unknown task evaluation rule')
    for key in ['objective','stabilityCriteria']:
        if key in config and config[key] is not None and (not isinstance(config[key],str) or len(config[key])>16000):
            raise Refused(key+' must be text of at most 16000 characters')
    if config.get('stabilityRule') is not None:
        rule=config['stabilityRule']
        if not isinstance(rule,dict) or set(rule)!={'minTrialsPerTask','minimumOfficialScore'} or type(rule.get('minTrialsPerTask')) is not int or rule['minTrialsPerTask']<2 or type(rule.get('minimumOfficialScore')) not in [int,float] or not math.isfinite(rule['minimumOfficialScore']):raise Refused('stabilityRule requires minTrialsPerTask >= 2 and a finite minimumOfficialScore')
    if 'retentionRule' in config and config['retentionRule'] not in [LEGACY_RETENTION_RULE,RETENTION_RULE,META_RETENTION_RULE]:
        raise Refused('Unknown retention rule')
    # None is a genuine absent cap, never a large sentinel. Wall time stays finite.
    for key in ['maxRounds','maxTrials','trialTimeSeconds','softTokenLimit']:
        config.setdefault(key,None)
        if config[key] is not None and (type(config[key]) is not int or config[key]<=0):
            raise Refused(key+' must be null or a positive integer')
    if benchmark_time(config) and config['trialTimeSeconds'] is not None:
        raise Refused('Benchmark owns task time; single-trial time overrides are unavailable')
    for key in ['concurrency','wallTimeSeconds']:
        if type(config.get(key)) is not int or config[key]<=0:raise Refused(key+' must be a positive integer')
    for key,total in [('reserveSeconds','wallTimeSeconds'),('reserveTokens','softTokenLimit')]:
        if config.get(key) is None:
            config[key]=0 if planning.enabled(config) else (min(900,max(0,config[total]//10)) if key=='reserveSeconds' else (min(800000,config[total]//10) if config[total] else 0))
        if type(config[key]) is not int or config[key]<0 or (config[total] is not None and config[key]>=config[total]):raise Refused('Invalid '+key)
    if config['softTokenLimit'] is None:config['reserveTokens']=0
    if 'authorizationDeadline' in config:
        if type(config['authorizationDeadline']) not in [int,float] or not math.isfinite(config['authorizationDeadline']) or config['authorizationDeadline']<=0:raise Refused('Invalid authorization deadline')
    if config.get('retries',0)!=0 or config.get('hardTokenLimit') or config.get('dollarLimit'):
        raise Refused('This provider supports a soft token threshold, no verified hard token/dollar limit or automatic retries')
    if config['maxTrials'] is not None and config['concurrency']>config['maxTrials']:raise Refused('Concurrency exceeds Trial limit')
    if not config.get('tasks') or len(set(config['tasks']))!=len(config['tasks']) or any(t not in PUBLIC_TASKS for t in config['tasks']):
        raise Refused('Only registered public development tasks are available')
    if config.get('executionContract')!='harbor-process-v1' and config['maxTrials'] is not None and len(config['tasks'])>config['maxTrials']:raise Refused('Trial limit cannot cover the baseline task set')
    for role in ['solver','meta']:
        model=config.get(role,{})
        if not supported_model(model,model_config):
            raise Refused('Unsupported model configuration')
        config[role]={k:model[k] for k in ['provider','model','reasoningEffort'] if k in model and model[k] is not None}
    config['modelRoutes']={role:provider_route(config[role],model_config) for role in ['solver','meta']}
    if type(config.get('drainGraceSeconds',300)) is not int or not 0<=config.get('drainGraceSeconds',300)<=900:raise Refused('Drain grace must be 0–900 seconds')
    if config.get('stopMode','strict') not in ['strict','drain']:raise Refused('Unknown stop mode')
    if control_only(config):
        for key in TOKEN_FIELDS:config.pop(key,None)
    return {**config,'retries':0,'taskPurpose':'development','stopMode':config.get('stopMode','strict'),**({} if control_only(config) else {'limitKind':'soft'}),
            'drainGraceSeconds':config.get('drainGraceSeconds',300),'weights':{t:1/len(config['tasks']) for t in config['tasks']}}

class Store:
    def __init__(self,path,clock=time.time,model_config=None):
        self.model_config=load_model_config() if model_config is None else model_config
        self._read_local=threading.local();self.data=Path(path).parent;self.path=state_path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.clock=clock
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY)')
            db.execute('INSERT OR IGNORE INTO migrations VALUES (?)',(SCHEMA_VERSION,))
            for table in TABLES:
                db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,campaign TEXT NOT NULL,data TEXT NOT NULL)')
                db.execute(f'CREATE INDEX IF NOT EXISTS {table}_campaign ON {table}(campaign)')
            db.execute('CREATE TABLE IF NOT EXISTS evidence_versions(campaign TEXT PRIMARY KEY, version INTEGER NOT NULL)')
            for event in ('INSERT','UPDATE','DELETE'):
                row='old' if event=='DELETE' else 'new'
                db.execute(f"CREATE TRIGGER IF NOT EXISTS evidence_version_{event.lower()} AFTER {event} ON evidence BEGIN INSERT INTO evidence_versions VALUES({row}.campaign,1) ON CONFLICT(campaign) DO UPDATE SET version=version+1; END")
            db.execute("CREATE INDEX IF NOT EXISTS evidence_identity ON evidence(campaign,json_extract(data,'$.trialId'),json_extract(data,'$.kind'),json_extract(data,'$.sha256'))")
            # Archive deletion checks other campaigns by digest for every body.
            # Campaign-first indexes otherwise scan all historical evidence.
            for table in ('evidence','source_adoptions'):
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_digest_campaign ON {table}(json_extract(data,'$.sha256'),campaign)")
            db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,campaign TEXT NOT NULL,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS commands(campaign TEXT,kind TEXT,key TEXT,payload TEXT,result TEXT,PRIMARY KEY(campaign,kind,key))')
            db.execute('CREATE TABLE IF NOT EXISTS deletions(campaign TEXT PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS deleted_create_keys(digest TEXT PRIMARY KEY)')
            db.execute("CREATE INDEX IF NOT EXISTS reports_scope ON reports(campaign,json_extract(data,'$.batchId'),json_extract(data,'$.kind'))")
            db.execute("CREATE INDEX IF NOT EXISTS reports_request ON reports(campaign,json_extract(data,'$.metaRequest.requestId'))")
    @contextlib.contextmanager
    def read_snapshot(self):
        if not hasattr(self, '_read_local'): self._read_local=threading.local()
        if getattr(self._read_local, 'db', None) is not None:
            yield
            return
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        self._read_local.db=db
        try: yield
        finally:
            self._read_local.db=None;db.rollback();db.close()

    @contextlib.contextmanager
    def connection(self,write=False,*,operation=None):
        active=getattr(getattr(self,'_read_local',None),'db',None)
        if active is not None:
            if write:raise RuntimeError('Writes are not allowed inside a query snapshot')
            yield active
            return
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        caller=sys._getframe(2)
        operation=operation or f'{Path(caller.f_code.co_filename).name}:{caller.f_code.co_name}:{caller.f_lineno}'
        started=time.monotonic();acquired=None;attempts=0;error=None;transaction=uuid.uuid4().hex
        try:
            if write:attempts=begin_write(db)
            acquired=time.monotonic()
            yield db;db.commit()
        except BaseException as exc:
            error=exc;db.rollback();raise
        finally:
            db.close()
            diagnostic(transaction=transaction,operation=operation,write=write,started=started,
                       acquired=acquired,attempts=attempts,error=error)
    def _get(self,db,table,id):
        if table not in TABLES:raise ValueError('Unknown table')
        row=db.execute(f'SELECT data FROM {table} WHERE id=?',(id,)).fetchone()
        if row is None:raise KeyError(id)
        return self._decode(table,row['data'])
    def _decode(self,table,data):
        value=json.loads(data)
        if table=='reports' and value.get('reportRef'):
            ref=value['reportRef'];path=self.data/'reports'/value['id']/'report.json'
            body=path.read_bytes()
            if hashlib.sha256(body).hexdigest()!=ref['sha256']:raise Refused('Report snapshot integrity mismatch')
            return json.loads(body)
        return value
    def report_heads(self,campaign):
        fields=('id','campaignId','kind','batchId','createdAt','analysisRevision','status','factsSha256','author','analysis','metaRequest','reportRef','tasks','candidateIds','revision')
        projection=','.join("'%s',json_extract(data,'$.%s')"%(key,key) for key in fields)
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT json_object('+projection+') FROM reports WHERE campaign=? ORDER BY rowid',(campaign,))]
    def get(self,table,id):
        with self.connection() as db:return self._get(db,table,id)
    def _list(self,db,table,campaign=None):
        if table not in TABLES:raise ValueError('Unknown table')
        rows=db.execute(f'SELECT data FROM {table}'+(' WHERE campaign=?' if campaign else ''),(campaign,) if campaign else ()).fetchall()
        return [self._decode(table,row['data']) for row in rows]
    def list(self,table,campaign=None):
        with self.connection() as db:return self._list(db,table,campaign)
    def _save(self,db,table,value):
        self.writable(value.get('campaignId',value['id']),db)
        value={**value,'schemaVersion':1,'revision':value.get('revision',0)+1}
        db.execute(f'INSERT INTO {table} VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
            (value['id'],value.get('campaignId',value['id']),encoded(value)))
        return value
    def _event(self,db,campaign,kind,**data):
        self.writable(campaign,db)
        event={'type':kind,'time':self.clock(),**data};db.execute('INSERT INTO events(campaign,data) VALUES(?,?)',(campaign,encoded(event)))
    def events(self,campaign,after=0):
        with self.connection() as db:return [{**json.loads(r['data']),'seq':r['seq']} for r in db.execute(
            'SELECT * FROM events WHERE campaign=? AND seq>? ORDER BY seq LIMIT 200',(campaign,after))]
    def last_event(self,campaign):
        with self.connection() as db:return db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE campaign=?',(campaign,)).fetchone()[0]
    def _idem(self,db,campaign,kind,key,payload):
        self.writable(campaign,db)
        if not isinstance(key,str) or not 1<=len(key)<=200:raise Refused('Idempotency key required')
        row=db.execute('SELECT * FROM commands WHERE campaign=? AND kind=? AND key=?',(campaign,kind,key)).fetchone()
        if row:
            if row['payload']!=encoded(payload):raise Conflict('Idempotency key reused with different input')
            return json.loads(row['result'])
    def _remember(self,db,campaign,kind,key,payload,result):
        self.writable(campaign,db)
        db.execute('INSERT INTO commands VALUES(?,?,?,?,?)',(campaign,kind,key,encoded(payload),encoded(result)))
        return result
    def create(self,config,key,defaults=None):
        if not isinstance(key,str) or not 1<=len(key)<=200:raise Refused('Idempotency key required')
        with self.connection(True) as db:
            self.check_create_key(key,db)
            saved=db.execute("SELECT payload,result FROM commands WHERE campaign='global' AND kind='create' AND key=?",(key,)).fetchone()
            catalog=campaign_model_config(json.loads(saved['result'])['config']) if saved else self.model_config
            config=validate_config(config,catalog)
            if saved and 'modelRoutes' not in json.loads(saved['payload']):config.pop('modelRoutes',None)
            prior=self._idem(db,'global','create',key,config)
            if prior:return prior
            c={'id':identity('campaign'),'config':{**config,**(defaults or {}),'taskEvaluationRule':config.get('taskEvaluationRule',DEFAULT_RULE),'objective':effective_objective(config),'retentionRule':config.get('retentionRule',META_RETENTION_RULE)},'state':'draft','createdAt':self.clock(),'startedAt':None,
               'deadline':None,'stopReason':None,'retainedCandidateId':None,'finalCandidateId':None,'explorationClosed':False}
            c=self._save(db,'campaigns',c);self._event(db,c['id'],'created')
            return self._remember(db,'global','create',key,config,c)

    def deletion(self,campaign,db=None):
        if db is None:
            with self.connection() as connection:return self.deletion(campaign,connection)
        row=db.execute('SELECT data FROM deletions WHERE campaign=?',(campaign,)).fetchone()
        return json.loads(row['data']) if row else None

    def writable(self,campaign,db=None):
        if self.deletion(campaign,db):raise Conflict('活动正在删除或已经删除，不能继续写入。')

    def check_create_key(self,key,db=None):
        if db is None:
            with self.connection() as connection:return self.check_create_key(key,connection)
        if isinstance(key,str) and db.execute('SELECT 1 FROM deleted_create_keys WHERE digest=?',(hashlib.sha256(key.encode()).hexdigest(),)).fetchone():
            raise Conflict('原创建请求对应的活动已删除；如需新活动，请重新创建。')

    def track_artifact(self,campaign,path,kind):
        # An already admitted build can finish after deletion was requested. Its
        # files must still enter the inventory before the cleaner acquires exclusivity.
        with self.connection(True) as db:
            job=self.deletion(campaign,db)
            if job and job['phase']!='stopping':raise Conflict('Activity artifact publication is closed')
            self._get(db,'campaigns',campaign)
            id=hashlib.sha256((campaign+'\0'+str(path)).encode()).hexdigest()
            row={'id':id,'campaignId':campaign,'path':str(path),'kind':kind}
            db.execute('INSERT OR REPLACE INTO owned_artifacts VALUES(?,?,?)',(id,campaign,encoded(row)))
    def usage(self,campaign,db=None):
        c=self._get(db,'campaigns',campaign) if db else self.get('campaigns',campaign)
        if control_only(c['config']):return {'status':'not_collected'}
        rows=self._list(db,'usage',campaign) if db else self.list('usage',campaign)
        return {'confirmedTokens':sum(r.get('confirmedTokens') or 0 for r in rows),
            'inflightReservedTokens':sum(r['reservedTokens'] for r in rows if r['status']=='inflight'),
            'unknownReservedTokens':sum(r['reservedTokens'] for r in rows if r['status']=='unknown'),
            'unknownRequests':sum(r['status']=='unknown' for r in rows),'requests':len(rows),'limitKind':'soft'}
    @staticmethod
    def run_table(id):
        return 'reference_runs' if id.startswith('reference-run-') else 'trials'
    def _runs(self,db,campaign=None):
        return self._list(db,'trials',campaign)+self._list(db,'reference_runs',campaign)
    def runs(self,campaign=None):
        with self.connection() as db:return self._runs(db,campaign)
    def run(self,id):return self.get(self.run_table(id),id)
    def _save_run(self,db,row):return self._save(db,self.run_table(row['id']),row)
    def _counts(self,db,campaign):
        trials=self._runs(db,campaign)
        return {'rounds':len(self._list(db,'batches',campaign))+len(self._list(db,'reference_batches',campaign)),
            'referenceTrials':sum(t['id'].startswith('reference-run-') for t in trials),
            'trials':sum(t['state']!='cancelled' or t.get('startedAt') is not None for t in trials),
            'startedTrials':sum(t.get('startedAt') is not None for t in trials),
            'activeTrials':sum(t['state'] in ['launching','running'] for t in trials),
            'collectingTrials':sum(t['state']=='collecting' for t in trials),
            'reservedTrials':sum(t['state']=='reserved' for t in trials)}
    def status(self,id):
        with self.connection() as db:
            c=self._get(db,'campaigns',id);c['counts']=self._counts(db,id);c['usage']=self.usage(id,db)
            c['elapsedSeconds']=max(0,(c.get('finishedAt') or self.clock())-c['startedAt']) if c['startedAt'] else 0
            c['remainingSeconds']=max(0,c['deadline']-self.clock()) if c['deadline'] else c['config']['wallTimeSeconds']
            c['resourcePlanning']=planning.view(c,self._runs(db,id),self.clock())
            if c.get('selectionDecisionId'):
                c['selectionDecision']=self._get(db,'selection_decisions',c['selectionDecisionId'])
            return c
    def control(self,id,action,key,expected_revision=None,changes=None):
        if action=='finish':
            from src.evidence.cold import ColdArchive
            payload=changes or {}
            if payload.get('reviewId'):
                review=self.get('stop_reviews',payload['reviewId'])
                if review['campaignId']==id:payload={**payload,'review':review}
            ColdArchive(self.data).prepare_references(self,id,payload)
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
                if c['state'] not in ['running','closing']:raise Refused('Only a running or closing Campaign can pause')
                c['state']='paused'
            elif action=='resume':
                sessions=self._list(db,'meta_sessions',id)
                latest=sessions[-1] if sessions else None
                needs_attention=bool(latest and latest['state']=='needs_attention')
                if c['state']!='paused':
                    if c['state'] not in ['running','closing'] or not needs_attention:
                        raise Refused('活动未暂停，且当前 Meta 无需恢复；请刷新状态。')
                    if self.clock()>=c['deadline']:raise Refused('活动已到截止时间，无法恢复。')
                if c['explorationClosed']:
                    c['state']='closing'
                elif self.clock()>=c['deadline']-(0 if planning.enabled(c['config']) else c['config']['reserveSeconds']):
                    c.update(state='closing',explorationClosed=True,stopReason='time_limit')
                else:c['state']='running'
                # Commit the explicit recovery intent with its idempotency receipt.
                # Replaying this command must not clear a later session's failure.
                if needs_attention and self.clock()<c['deadline']:
                    latest.update(state='recovering',recovery={**(latest.get('recovery') or {}),
                        'state':'recovering','userResumedAt':self.clock(),'automaticRecovery':False,'retryAt':self.clock(),'nextAttempt':0})
                    self._save(db,'meta_sessions',latest)
            elif action in ['stop','finish']:
                if c['state'] in ['finished','failed']:raise Refused('Campaign already finalized')
                if action=='finish' and c['config'].get('stopPolicy') in CONTROLLED_POLICIES:
                    from .stop_review import finish
                    c['finishAssessment']=finish(self,db,c,changes or {})
                elif action=='finish' and changes and changes.get('reason'):
                    c['finishAssessment']={'source':'meta-analysis','reason':changes['reason'],'recordedAt':self.clock()}
                c.update(state='closing',explorationClosed=True,stopReason='user_stop' if action=='stop' else (c['stopReason'] or 'meta_finished'))
                for t in self._runs(db,id):
                    if t['state']=='reserved':t.update(state='cancelled',stopReason=c['stopReason']);self._save_run(db,t)
            elif action=='limits':
                if c['state'] in ['finished','failed']:raise Refused('Finalized Campaign is immutable')
                allowed={'maxRounds','maxTrials','concurrency','wallTimeSeconds','trialTimeSeconds','softTokenLimit','reserveSeconds','reserveTokens','stopMode','drainGraceSeconds'}
                if control_only(c['config']):allowed-=set(TOKEN_FIELDS)
                if not changes or set(changes)-allowed:raise Refused('Only user limits may change')
                previous={k:c['config'].get(k) for k in changes}
                c['config']=validate_config({**c['config'],**changes},campaign_model_config(c['config']))
                if planning.enabled(c['config']):
                    c['userLimitsRevision']=c.get('userLimitsRevision',1)+1
                    for k in changes:
                        c['config'].setdefault('configurationSources',{})[k]={'source':'user','decidedAt':self.clock(),'operation':'limits'}
                    self._event(db,id,'limits_changed',previous=previous,current=changes,userLimitsRevision=c['userLimitsRevision'],
                                scope='Future launches; running workers retain startup ceilings; tightened overall ceilings still apply')
                if c['startedAt']:c['deadline']=min(c['startedAt']+c['config']['wallTimeSeconds'],c['config'].get('authorizationDeadline',float('inf')))
            else:raise Refused('Unknown control action')
            self._finish_batches(db,id)
            c=self._save(db,'campaigns',c);self._event(db,id,action,changes=changes)
            return self._remember(db,id,'control',key,payload,c)
    def candidate(self,campaign,bundle,description,parent=None,check=None,research_refs=None):
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            if c['explorationClosed'] or c['state'] not in ['draft','running']:raise Refused('Search writes are closed')
            if parent and self._get(db,'candidates',parent)['campaignId']!=campaign:raise Refused('Candidate belongs to another Campaign')
            existing=[x for x in self._list(db,'candidates',campaign) if x['bundleId']==bundle['id']]
            if research_refs is not None:
                from .research import Research
                research=Research(self,self.data);research.resolve(db,campaign,research_refs)
            if existing:
                if research_refs is not None:research.bind_candidate(db,campaign,existing[0],research_refs)
                return existing[0]
            row=self._save(db,'candidates',{'id':identity('candidate'),'campaignId':campaign,'bundleId':bundle['id'],
                'bundlePath':bundle['path'],'plugins':bundle['plugins'],'metaCompositionId':c['config'].get('metaComposition',{}).get('id'),'parentId':parent,'description':description,
                'check':check or {'status':'pending'},'createdAt':self.clock()})
            if research_refs is not None:research.bind_candidate(db,campaign,row,research_refs)
            self._event(db,campaign,'candidate_frozen',candidateId=row['id']);return row
    def update_plan(self,campaign,changes,reason,key,expected_revision,source='meta'):
        if source not in ('meta','user','operator','developer'):raise Refused('Unknown plan source')
        payload={'changes':changes,'reason':reason,'expectedPlanRevision':expected_revision,'source':source}
        with self.connection(True) as db:
            prior=self._idem(db,campaign,'resource-plan',key,payload)
            if prior:return prior
            c=self._get(db,'campaigns',campaign)
            if not planning.enabled(c['config']):raise Refused('Legacy activity has no resource planning interface')
            if c['state'] not in ('draft','running','paused'):raise Refused('Resource planning closed')
            if c['explorationClosed'] and not any(t['state'] in ('reserved','launching','running') for t in self._runs(db,campaign)):
                raise Refused('Resource planning closed')
            if type(expected_revision) is not int or expected_revision!=(c.get('resourcePlan') or {}).get('revision',0):raise Conflict('Resource plan revision changed')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>16000:raise Refused('Plan reason required')
            values=planning.validate_plan(c,changes)
            c.pop('resourcePlanWait',None)
            c['resourcePlan']={**values,'revision':expected_revision+1,'source':source,'reason':reason,'updatedAt':self.clock()}
            c=self._save(db,'campaigns',c)
            self._event(db,campaign,'resource_plan_updated',plan=c['resourcePlan'])
            return self._remember(db,campaign,'resource-plan',key,payload,planning.view(c,self._runs(db,campaign)))
    def accept_trial_conditions(self,campaign,trial_id,seconds,key,reason):
        payload={'trialId':trial_id,'trialTimeSeconds':seconds,'reason':reason}
        with self.connection(True) as db:
            prior=self._idem(db,campaign,'trial-conditions',key,payload)
            if prior:return prior
            c=self._get(db,'campaigns',campaign);t=self._get(db,self.run_table(trial_id),trial_id)
            if benchmark_time(c['config']):raise Refused('Benchmark task time cannot be shortened')
            if not planning.enabled(c['config']) or c['state']!='running' or t['campaignId']!=campaign or t['state']!='reserved':raise Refused('Only pending activity trials may change conditions')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>16000:raise Refused('Condition adjustment reason required')
            if type(seconds) is not int or not 0<seconds<=t['executionSettings']['trialTimeSeconds']:raise Refused('Only explicit shortening of pending conditions is supported')
            if seconds<=t['executionSettings'].get('trialCloseoutReserveSeconds',planning.trial_closeout(c)):
                raise Refused('Shortened time cannot fit fixed verification/cleanup reserve')
            previous=t['executionSettings']
            t['executionSettings']={**previous,'trialTimeSeconds':seconds,'allowShortened':True}
            t['conditionAdjustment']={'previous':previous,'reason':reason,'time':self.clock()}
            t.pop('conditionsRequired',None);t=self._save_run(db,t)
            self._event(db,campaign,'trial_conditions_accepted',trialId=t['id'],**t['conditionAdjustment'])
            return self._remember(db,campaign,'trial-conditions',key,payload,t)
    def submit(self,campaign,candidate,tasks,repeats,key,execution=None,*,reference=None):
        payload={'candidateId':candidate,'tasks':tasks,'repeats':repeats}
        if execution is not None:payload['execution']=execution
        if reference is not None:payload['reference']=reference
        kind='reference-batch' if reference is not None else 'batch'
        with self.connection(True) as db:
            prior=self._idem(db,campaign,kind,key,payload)
            if prior:return prior
            c=self._get(db,'campaigns',campaign);cfg=c['config'];counts=self._counts(db,campaign)
            if c['state']!='running' or c['explorationClosed']:raise Refused('Exploration admission closed')
            if self.clock()>=c['deadline']-planning.reserves(c)[0]:raise Refused('Exploration time unavailable; inspect user deadline and adjustable plan reserve')
            selected=self._get(db,'candidates',candidate)
            if selected['campaignId']!=campaign or selected['check']['status']!='passed':raise Refused('Candidate is not checked for this Campaign')
            if reference is not None:
                from .reference.policy import admit_reference
                admit_reference(self,db,c,reference,len(tasks)*repeats)
            settings=planning.trial_settings(c,selected,execution) if planning.enabled(cfg) else {k:cfg[k] for k in ['solver','trialTimeSeconds']}
            if not tasks or len(set(tasks))!=len(tasks) or any(t not in cfg['tasks'] for t in tasks) or type(repeats) is not int or repeats<1:
                raise Refused('Invalid task/repeat plan')
            planned=len(tasks)*repeats
            if planned>100:raise Refused('A batch may contain at most 100 Trials; split submissions within the same total limits')
            if (cfg['maxRounds'] is not None and counts['rounds']>=cfg['maxRounds']) or (cfg['maxTrials'] is not None and counts['trials']+planned>cfg['maxTrials']):raise Refused('Round or Trial limit reached')
            u=self.usage(campaign,db)
            if cfg.get('softTokenLimit') is not None and u['confirmedTokens']+u['inflightReservedTokens']+u['unknownReservedTokens']>=cfg.get('softTokenLimit')-planning.reserves(c)[1]:
                raise Refused('Exploration token threshold reached')
            extra={'reference':reference} if reference is not None else {}
            batch=self._save(db,'reference_batches' if reference is not None else 'batches',{'id':identity('reference-batch' if reference is not None else 'batch'),'campaignId':campaign,'candidateId':candidate,'round':counts['rounds']+1,
                'tasks':tasks,'repeats':repeats,'admissionFeasibility':{task:planning.feasibility(c,{'task':task,'state':'reserved'},self.clock()) for task in tasks} if benchmark_time(cfg) else {},'testSettings':settings,'plannedTrials':planned,'state':'accepted','acceptedAt':self.clock(),**extra})
            for task in tasks:
                task_settings={**settings,'benchmarkTime':cfg['taskTimeLimits'][task]} if benchmark_time(cfg) else settings
                for repeat in range(repeats):
                    self._save(db,'reference_runs' if reference is not None else 'trials',{'id':identity('reference-run' if reference is not None else 'trial'),'campaignId':campaign,'batchId':batch['id'],'candidateId':candidate,
                        'launchId':identity('launch'),'task':task,'repeat':repeat,'state':'reserved','startedAt':None,
                        'score':None,'usage':{},'stopReason':None,**extra,**({'executionSettings':task_settings} if planning.enabled(cfg) else {})})
            round_full=cfg['maxRounds'] is not None and counts['rounds']+1>=cfg['maxRounds']
            trial_full=cfg['maxTrials'] is not None and counts['trials']+planned>=cfg['maxTrials']
            if round_full or trial_full:
                c.update(explorationClosed=True,stopReason='round_limit' if round_full else 'trial_limit')
                self._save(db,'campaigns',c)
            self._event(db,campaign,'reference_batch_accepted' if reference is not None else 'batch_accepted',batchId=batch['id'],round=batch['round'],plannedTrials=planned)
            return self._remember(db,campaign,kind,key,payload,batch)
    def claim(self,campaign):
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign);counts=self._counts(db,campaign);now=self.clock()
            cfg=c['config'];plan=c.get('resourcePlan')
            parallelism=min(cfg['concurrency'],plan['parallelism']) if planning.enabled(cfg) and plan else cfg['concurrency']
            if planning.enabled(cfg) and not plan:return None
            if c['state']!='running' or counts['activeTrials']>=parallelism:return None
            pending=[t for t in self._runs(db,campaign) if t['state']=='reserved']
            if not pending:return None
            u=self.usage(campaign,db)
            reason='closeout_time' if now>=c['deadline']-planning.reserves(c)[0] else None
            if not reason and cfg.get('softTokenLimit') is not None and u['confirmedTokens']+u['unknownReservedTokens']+u['inflightReservedTokens']>=cfg.get('softTokenLimit')-planning.reserves(c)[1]:
                reason='token_capacity'
            if reason:
                if planning.enabled(cfg):
                    waiting={'reason':reason,'resourcePlanRevision':plan['revision'],'userLimitsRevision':c.get('userLimitsRevision',1)}
                    if c.get('resourcePlanWait')!=waiting:
                        c['resourcePlanWait']=waiting;self._save(db,'campaigns',c)
                        self._event(db,campaign,'resource_plan_waiting',**waiting)
                return None
            if c.pop('resourcePlanWait',None):self._save(db,'campaigns',c)
            t=None
            for item in pending:
                if benchmark_time(cfg):
                    timing=item['executionSettings']['benchmarkTime'];required=timing['requiredTimeSeconds']
                    available=max(0,planning.end_time(c)-now)
                    if required is None or available<required:
                        waiting={'reason':'benchmark_time_unavailable','requiredSeconds':required,'availableSeconds':available,
                                 'solverTimeSeconds':timing['solverTimeSeconds'],'canShorten':False}
                        if item.get('conditionsRequired',{}).get('reason')!=waiting['reason']:
                            item['conditionsRequired']=waiting;self._save_run(db,item)
                            self._event(db,campaign,'trial_conditions_required',trialId=item['id'],**waiting)
                        continue
                    item.pop('conditionsRequired',None)
                elif planning.enabled(cfg):
                    settings=item['executionSettings'];seconds=settings['trialTimeSeconds']
                    available=max(0,planning.end_time(c)-now)
                    if cfg['trialTimeSeconds'] is not None:available=min(available,cfg['trialTimeSeconds'])
                    closeout=settings.get('trialCloseoutReserveSeconds',planning.trial_closeout(c))
                    if available<=closeout or (available<seconds and not settings['allowShortened']):
                        if not item.get('conditionsRequired'):
                            item['conditionsRequired']={'requestedSeconds':seconds,'availableSeconds':available,'minimumTrialTimeSeconds':closeout+1}
                            self._save_run(db,item);self._event(db,campaign,'trial_conditions_required',trialId=item['id'],**item['conditionsRequired'])
                        continue
                t=item;break
            if t is None:return None
            if benchmark_time(cfg):
                timing=t['executionSettings']['benchmarkTime'];seconds=timing['solverTimeSeconds']
                deadline=planning.end_time(c)
                t['effectiveConditions']={**t['executionSettings'],'solverTimeSeconds':seconds,
                    'solverDeadline':None,'availableTimeSeconds':deadline-now,
                    'userLimitsRevision':c.get('userLimitsRevision',1),'resourcePlanRevisionAtLaunch':plan['revision']}
                t['launchLimits']={'campaignDeadline':c['deadline'],**({} if control_only(cfg) else {'softTokenLimit':cfg.get('softTokenLimit')})}
            elif planning.enabled(cfg):
                seconds=t['executionSettings']['trialTimeSeconds']
                deadline=min(planning.end_time(c),now+seconds,now+(cfg['trialTimeSeconds'] or seconds))
                t['effectiveConditions']={**t['executionSettings'],'actualTimeSeconds':deadline-now,
                    'solverDeadline':deadline-t['executionSettings'].get('trialCloseoutReserveSeconds',planning.trial_closeout(c)),
                    'userLimitsRevision':c.get('userLimitsRevision',1),'resourcePlanRevisionAtLaunch':plan['revision'],
                    'configurationSources':cfg.get('configurationSources',{})}
                t['launchLimits']={'campaignDeadline':c['deadline'],**({} if control_only(cfg) else {'softTokenLimit':cfg.get('softTokenLimit')})}
            else:
                seconds=cfg['trialTimeSeconds'] or 3600
                deadline=min(planning.end_time(c),now+seconds,c['deadline']-cfg['reserveSeconds'])
            t.update(state='launching',startedAt=now,deadline=deadline)
            t['taskTimeLimitSeconds']=seconds
            t=self._save_run(db,t);self._event(db,campaign,'trial_claimed',trialId=t['id'],launchId=t['launchId']);return t
    def withdraw_trial(self,id,reason,key):
        if not isinstance(reason,str) or not reason.strip() or len(reason)>4000:raise Refused('Withdrawal reason required')
        with self.connection(True) as db:
            t=self._get(db,self.run_table(id),id);campaign=t['campaignId'];payload={'trialId':id,'reason':reason}
            prior=self._idem(db,campaign,'trial-withdraw',key,payload)
            if prior:return prior
            if t['state']!='reserved' or t.get('startedAt') is not None:raise Refused('Only unstarted reserved trials can be withdrawn')
            t.update(state='cancelled',stopReason='withdrawn_before_start',withdrawal={'reason':reason,'time':self.clock(),'source':'user'})
            t=self._save_run(db,t);self._finish_batches(db,campaign)
            self._event(db,campaign,'trial_withdrawn',trialId=id,reason=reason)
            return self._remember(db,campaign,'trial-withdraw',key,payload,t)
    def trial_update(self,id,**changes):
        with self.connection(True) as db:
            t=self._get(db,self.run_table(id),id);previous=t['state'];t.update(changes);t=self._save_run(db,t)
            if previous not in ['finished','failed','cancelled','unknown'] and t['state'] in ['finished','failed','cancelled','unknown']:
                self._event(db,t['campaignId'],'reference_run_finished' if t.get('reference') else 'trial_finished',trialId=id,batchId=t['batchId'],state=t['state'],failure=t.get('failure'))
            self._finish_batches(db,t['campaignId'])
            return t
    def _finish_batches(self,db,campaign):
        for table,runs in [('batches','trials'),('reference_batches','reference_runs')]:
            trials=self._list(db,runs,campaign)
            for batch in self._list(db,table,campaign):
                members=[t for t in trials if t['batchId']==batch['id']]
                if batch['state']!='finished' and members and all(t['state'] in ['finished','failed','cancelled','unknown'] for t in members):
                    batch.update(state='finished',finishedAt=self.clock());self._save(db,table,batch)
                    self._event(db,campaign,'reference_batch_finished' if table=='reference_batches' else 'batch_finished',batchId=batch['id'])
    def reserve(self,campaign,lease,id,reserved_tokens,purpose):
        if control_only(self.get('campaigns',campaign)['config']):raise Refused('Usage accounting is unavailable for this activity')
        with self.connection(True) as db:
            try:
                row=self._get(db,'usage',id)
                if row['campaignId']!=campaign or row['leaseId']!=lease:raise Conflict('Request identity conflict')
                return row
            except KeyError:pass
            c=self._get(db,'campaigns',campaign);cfg=c['config']
            effective_deadline=c['deadline']
            if purpose=='solver' and cfg['stopMode']=='drain':
                try:effective_deadline=min(self._get(db,'leases',lease)['deadline'],c['deadline']+cfg['drainGraceSeconds'])
                except KeyError:pass
            if c['state'] in ['draft','finished','failed'] or (purpose=='meta' and c['state']=='paused') or self.clock()>=effective_deadline:
                raise Refused('Model admission stopped')
            if purpose not in ['solver','meta','report'] or type(reserved_tokens) is not int or reserved_tokens<1:raise Refused('Invalid request reservation')
            closing=purpose=='report' or (purpose=='meta' and (c['state']=='closing' or c['explorationClosed']))
            ceiling=cfg.get('softTokenLimit')-(0 if closing else cfg['reserveTokens']) if cfg.get('softTokenLimit') is not None else None
            if ceiling is not None:
                u=self.usage(campaign,db)
                if sum(u[k] for k in ['confirmedTokens','unknownReservedTokens','inflightReservedTokens'])+reserved_tokens>ceiling:
                    raise Refused('Soft token threshold reached')
            from .reference.policy import token_admission
            decision=token_admission(self,db,c,next((l for l in self._list(db,'leases',campaign) if l['id']==lease),{}),reserved_tokens)
            if decision.get('status') in ('waiting','denied'):raise Refused('Reference token threshold reached')
            row=self._save(db,'usage',{'id':id,'campaignId':campaign,'leaseId':lease,'purpose':'report' if closing else purpose,
                'status':'inflight','reservedTokens':reserved_tokens,'confirmedTokens':None,'startedAt':self.clock()})
            self._event(db,campaign,'request_reserved',requestId=id,purpose=row['purpose']);return row
    def admit(self,campaign,lease,id,reserved_tokens,purpose):
        """Structured admission commits denials and waits as well as successful reservations."""
        if control_only(self.get('campaigns',campaign)['config']):raise Refused('Usage accounting is unavailable for this activity')
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign);cfg=c['config'];now=self.clock()
            if purpose not in ('solver','meta','report') or type(reserved_tokens) is not int or reserved_tokens<1:raise Refused('Invalid request reservation')
            if not isinstance(id,str) or not id or len(id)>200:raise Refused('Invalid request identity')
            try:existing=self._get(db,'admissions',id)
            except KeyError:existing=None
            if existing and (existing['campaignId']!=campaign or existing['leaseId']!=lease or existing['reservedTokens']!=reserved_tokens or existing['purpose']!=purpose):raise Conflict('Admission identity conflict')
            try:
                row=self._get(db,'usage',id)
                if row['campaignId']!=campaign or row['leaseId']!=lease:raise Conflict('Request identity conflict')
                return {'status':'granted','requestId':id}
            except KeyError:pass
            owner=self._get(db,'leases',lease)
            if owner['campaignId']!=campaign or owner['role']!=purpose:raise Refused('Lease role mismatch')
            # Unlimited requests need no total-history scan. Keep cheap receipts;
            # aggregate usage only for actual limits, status queries and reports.
            usage=self.usage(campaign,db) if cfg.get('softTokenLimit') is not None else {}
            committed=usage.get('confirmedTokens',0)+usage.get('unknownReservedTokens',0)
            hard_end=planning.end_time(c) if purpose=='solver' else c['deadline']
            decision={'status':'granted','requestId':id}
            if owner.get('revoked') or c['state'] in ('draft','finished','failed') or (purpose=='meta' and c['state']=='paused'):
                decision.update(status='denied',code='request_cancelled',boundary='controller')
            elif now>=min(owner['deadline'],hard_end):
                decision.update(status='denied',code='trial_deadline' if purpose=='solver' else 'campaign_deadline',boundary='deadline')
            else:
                cap=cfg.get('softTokenLimit')
                closing=purpose=='report' or (purpose=='meta' and (c['state']=='closing' or c['explorationClosed']))
                # Meta must remain able to revise its own plan and prepare reports.
                user_reserve=0 if closing or (planning.enabled(cfg) and purpose=='meta') else cfg['reserveTokens']
                ceiling=cap-user_reserve if cap is not None else None
                if ceiling is not None and committed+reserved_tokens>ceiling:
                    decision.update(status='denied',code='budget_admission_denied',boundary='configured_limit')
                elif ceiling is not None and committed+usage['inflightReservedTokens']+reserved_tokens>ceiling:
                    decision.update(status='waiting',code='budget_inflight_wait',boundary='inflight',retryAfterMs=500)
                elif cap is not None and purpose=='solver' and planning.enabled(cfg) and committed+usage['inflightReservedTokens']+reserved_tokens>cap-planning.reserves(c)[1]:
                    decision.update(status='waiting',code='budget_plan_wait',boundary='meta_plan',retryAfterMs=500)
            from .reference.policy import token_admission
            if decision['status']=='granted':
                decision.update(token_admission(self,db,c,owner,reserved_tokens))
            if decision['status']=='granted':
                row=self._save(db,'usage',{'id':id,'campaignId':campaign,'leaseId':lease,'purpose':purpose,
                    'status':'inflight','reservedTokens':reserved_tokens,'confirmedTokens':None,'startedAt':now})
                self._event(db,campaign,'request_reserved',requestId=id,purpose=purpose)
            decision.update(userLimitsRevision=c.get('userLimitsRevision',1),
                            resourcePlanRevision=(c.get('resourcePlan') or {}).get('revision',0),
                            observed={**usage,'requestReservedTokens':reserved_tokens,'softTokenLimit':cfg.get('softTokenLimit')})
            record={'id':id,'campaignId':campaign,'leaseId':lease,'purpose':purpose,'reservedTokens':reserved_tokens,
                    'startedAt':(existing or {}).get('startedAt',now),'updatedAt':now,'decision':decision}
            self._save(db,'admissions',record)
            if not existing or existing['decision']['status']!=decision['status'] or existing['decision'].get('code')!=decision.get('code'):
                self._event(db,campaign,'admission_'+decision['status'],requestId=id,decision=decision)
            return decision
    def settle(self,campaign,lease,id,confirmed,unknown,*,host_audit=False):
        if control_only(self.get('campaigns',campaign)['config']):raise Refused('Usage accounting is unavailable for this activity')
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
            if c['state'] not in ['closing','paused'] or not c['explorationClosed']:
                c.update(state='paused' if c['state']=='paused' else 'closing',explorationClosed=True,stopReason=c.get('stopReason') or reason);c=self._save(db,'campaigns',c)
                self._event(db,campaign,'closing',reason=reason)
            if cancel_reserved:
                for t in self._runs(db,campaign):
                    if t['state']=='reserved':t.update(state='cancelled',stopReason=reason);self._save_run(db,t)
            self._finish_batches(db,campaign)
            return c
    def finalize(self,campaign,reason=None,summary_reason=None):
        job=None
        if summary_reason:
            directory=self.data/'campaigns'/campaign/'collections';directory.mkdir(parents=True,exist_ok=True)
            key='collection-report-'+hashlib.sha256(campaign.encode()).hexdigest()
            job={'id':key,'campaignId':campaign,'kind':'report-summary','stage':'report','state':'queued','attempts':0,
                'reason':summary_reason,'createdAt':self.clock(),'lockPath':str(lock_path(directory/(key+'.lock')))}
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            counts=self._counts(db,campaign)
            if counts['activeTrials'] or counts['collectingTrials']:raise Refused('Cannot finalize while a Trial is active or collecting results')
            if c['state']=='finished':return c
            c.update(state='finished',explorationClosed=True,finishedAt=self.clock(),
                stopReason=reason or c['stopReason'] or 'completed',finalCandidateId=c['retainedCandidateId'])
            c=self._save(db,'campaigns',c)
            if job:self._save(db,'collection_jobs',job)
            self._event(db,campaign,'finished',reason=c['stopReason']);return c
    def retain(self,campaign,candidate,reason,refs,*,tradeoffs=None,limitations=None,reconsiderWhen=None,expectedSelectionRevision=None,meta_request=None,summary=None,alternatives=None,researchRefs=None):
        from src.evidence.cold import ColdArchive
        ColdArchive(self.data).prepare_references(self,campaign,{'evidenceRefs':refs,'alternatives':alternatives})
        rejection=None
        with self.connection(True) as db:
            c=self._get(db,'campaigns',campaign)
            if meta_request:
                previous=next((r for r in self._list(db,'selection_decisions',campaign) if r.get('metaRequest',{}).get('requestId')==meta_request['requestId']),None)
                if previous:
                    if previous['metaRequest']['payload']!=meta_request['payload']:raise Conflict('Selection request payload changed')
                    return {**c,'selectionDecision':previous}
            if expectedSelectionRevision is not None and expectedSelectionRevision!=len(self._list(db,'selection_decisions',campaign)):raise Conflict('Selection revision changed')
            if c['state'] in ['finished','failed']:raise Refused('Final candidate selection is frozen')
            selected=self._get(db,'candidates',candidate)
            if selected['campaignId']!=campaign:raise Refused('Candidate unavailable')
            trials=[t for t in self._list(db,'trials',campaign) if t['candidateId']==candidate]
            rule=c['config'].get('retentionRule',LEGACY_RETENTION_RULE)
            if rule==META_RETENTION_RULE:
                return self._meta_select(db,c,selected,trials,reason,refs,tradeoffs,limitations,reconsiderWhen,meta_request,summary,alternatives,researchRefs)
            has_result=any(t['score'] is not None for t in trials) if rule==LEGACY_RETENTION_RULE else any(
                t['state']=='finished' and type(t.get('score')) in [int,float] and math.isfinite(t['score']) for t in trials)
            if not has_result:raise Refused('Retaining a candidate requires a completed official result')
            allowed={r[0] for r in db.execute('SELECT id FROM evidence WHERE campaign=?',(campaign,))}
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
                # v3 journals also bind explicitly configured historical selection rules.
                # Their eligibility checks above remain unchanged.
                if meta_request:
                    previous_id=c.get('retainedCandidateId')
                    previous=[t for t in self._list(db,'trials',campaign) if t['candidateId']==previous_id] if previous_id else []
                    extra={}
                    if summary is not None:
                        from .research import Research
                        extra=Research(self,self.data).selection(db,c,selected,summary,alternatives,researchRefs)
                    audit=selection_assessment(c['config'],trial_diagnostics(previous,self.data,c['config']),trial_diagnostics(trials,self.data,c['config']),bool(previous_id))
                    decision=self._save(db,'selection_decisions',{'id':identity('selection'),'campaignId':campaign,
                        'candidateId':candidate,'bundleId':selected['bundleId'],'previousCandidateId':previous_id,
                        'previousDecisionId':c.get('selectionDecisionId'),'createdAt':self.clock(),'source':'meta-analysis','rule':rule,
                        'reason':reason,'evidenceRefs':refs,'tradeoffs':tradeoffs,'limitations':limitations,'reconsiderWhen':reconsiderWhen,
                        **extra,'assessment':audit,'legacyEligibilityAssessment':assessment,'metaRequest':meta_request,
                        'selectionRevision':len(self._list(db,'selection_decisions',campaign))+1})
                    c['selectionDecisionId']=decision['id']
                c['retainedCandidateId']=candidate;c=self._save(db,'campaigns',c)
                self._event(db,campaign,'candidate_retained',candidateId=candidate,reason=reason,evidenceRefs=refs,rule=rule,assessment=assessment)
                return c
        # Commit the rejected assessment for audit, without changing the selection.
        raise Refused(rejection)

    def _meta_select(self,db,c,selected,trials,reason,refs,tradeoffs,limitations,reconsider_when,meta_request=None,summary=None,alternatives=None,research_refs=None):
        if selected.get('check',{}).get('status')!='passed':raise Refused('Selection requires a checked frozen candidate')
        for key,value in [('reason',reason),('tradeoffs',tradeoffs),('reconsiderWhen',reconsider_when)]:
            if not isinstance(value,str) or not value.strip() or len(value)>16000:raise Refused(key+' must be non-empty text of at most 16000 characters')
        if not isinstance(limitations,list) or len(limitations)>100 or any(not isinstance(x,str) or not x.strip() or len(x)>16000 for x in limitations):
            raise Refused('limitations must be an array of non-empty text (may be empty)')
        if not isinstance(refs,list) or not refs or len(refs)>200 or any(not isinstance(x,str) for x in refs) or len(set(refs))!=len(refs):
            raise Refused('Selection requires unique allowed evidence IDs')
        allowed={row['id']:json.loads(row['data']) for row in db.execute('SELECT id,data FROM evidence WHERE campaign=? AND id IN ('+','.join('?' for _ in refs)+')',[c['id'],*refs])}
        if set(refs)-allowed.keys():raise Refused('Selection requires allowed evidence IDs from this Campaign')
        checks=[]
        for ref in refs:
            e=allowed[ref]
            try:data=Path(e['path']).read_bytes()
            except (KeyError,OSError) as error:raise Refused('Selection evidence unavailable: '+ref) from error
            if hashlib.sha256(data).hexdigest()!=e.get('sha256'):raise Refused('Selection evidence integrity mismatch: '+ref)
            checks.append({'id':ref,'sha256':e['sha256'],'trialId':e.get('trialId'),'kind':e.get('kind')})
        extra={}
        if summary is not None:
            from .research import Research
            extra=Research(self,self.data).selection(db,c,selected,summary,alternatives,research_refs)
        previous_id=c.get('retainedCandidateId')
        previous=[t for t in self._list(db,'trials',c['id']) if t['candidateId']==previous_id] if previous_id else []
        assessment=selection_assessment(c['config'],trial_diagnostics(previous,self.data,c['config']),trial_diagnostics(trials,self.data,c['config']),bool(previous_id))
        decision=self._save(db,'selection_decisions',{'id':identity('selection'),'campaignId':c['id'],
            'candidateId':selected['id'],'bundleId':selected['bundleId'],'previousCandidateId':previous_id,
            **({'metaRequest':meta_request,'selectionRevision':len(self._list(db,'selection_decisions',c['id']))+1} if meta_request else {}),
            'previousDecisionId':c.get('selectionDecisionId'),'createdAt':self.clock(),'source':'meta-analysis',
            'rule':META_RETENTION_RULE,'reason':reason,'tradeoffs':tradeoffs,'limitations':limitations,
            **extra,'reconsiderWhen':reconsider_when,'evidenceRefs':refs,'verifiedEvidence':checks,'assessment':assessment,
            **({} if control_only(c['config']) else {'usage':self.usage(c['id'],db)}),'counts':self._counts(db,c['id']),
            'context':{'campaignRevision':c['revision'],'state':c['state'],'deadline':c.get('deadline'),
                'remainingSeconds':max(0,c['deadline']-self.clock()) if c.get('deadline') else c['config']['wallTimeSeconds'],
                'limits':{k:c['config'].get(k) for k in ['maxRounds','maxTrials','concurrency','wallTimeSeconds',
                    'trialTimeSeconds','softTokenLimit','reserveSeconds','reserveTokens','stopMode','drainGraceSeconds'] if k in c['config']}}})
        c.update(retainedCandidateId=selected['id'],selectionDecisionId=decision['id'])
        c=self._save(db,'campaigns',c)
        self._event(db,c['id'],'candidate_retained',candidateId=selected['id'],previousCandidateId=previous_id,
            decisionId=decision['id'],reason=reason,evidenceRefs=refs,rule=META_RETENTION_RULE,assessment=assessment)
        return {**c,'selectionDecision':decision}
