"""v3 boundary projections; raw evidence and existing user APIs remain unchanged."""
import hashlib
import json
import re
import os
import stat
from pathlib import Path
from jsonschema import Draft202012Validator
from .store import Refused,Conflict,encoded
from .meta_contracts import ANALYSIS,CONTRACTS,ROOT,analysis_for,version
from src.evidence.files import atomic_json
from src.evidence.objects import enabled
from src.evidence.snapshots import Snapshots
from src.execution.bundle.plugin_reading import candidate_view

RECEIPT_SCHEMA=json.loads((ROOT/'receipt.schema.json').read_text())
TOOLS={'campaign_status','candidate_list','evidence_list','sdk_read','results_compare','candidate_retain','report_save'}
FILE_KEYS=('ref','path','mediaType','bytes','sha256','completeness')

def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ['observedAt','remainingSeconds','elapsedSeconds','heartbeat']}
    if isinstance(value,list):return [stable(v) for v in value]
    return value

def public(value):
    """Project host-only locations out of derived metadata, never rewrite originals."""
    if isinstance(value,dict):return {k:(v if k=='pointer' else public(v)) for k,v in value.items() if k not in ['_load']}
    if isinstance(value,list):return [public(v) for v in value]
    if isinstance(value,str):
        # Container paths are the only absolute locations exposed by this protocol.
        if value.startswith('/') and not value.startswith(('/materials/','/evidence/','/sdk/','/versions/','/outputs/','/work/')):
            return {'availability':'unavailable','reason':'host-only metadata; use the associated file reference'}
        return re.sub(r'(?:/Users/|/private/|/tmp/|/var/folders/)[^\n\"\']*','[host location; see file reference]',value)
    return value

def read_analysis_file(root,relative):
    """Read one immutable byte snapshot through directory FDs; reject symlink races."""
    path=Path(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts:raise Refused('Workspace-relative path required')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    directory=os.open(root,flags)
    try:
        for part in path.parts[:-1]:
            child=os.open(part,flags,dir_fd=directory);os.close(directory);directory=child
        fd=os.open(path.parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise Refused('Analysis must be a regular file')
            with os.fdopen(fd,'rb',closefd=False) as stream:return stream.read()
        finally:os.close(fd)
    finally:os.close(directory)

def compact(file):return {k:file[k] for k in FILE_KEYS if k in file}

def receipt(summary,file=None,**fields):
    result={'receiptVersion':'meta-tool-receipt-v1','status':'completed','summary':summary,**fields}
    if file is not None:result['file']=compact(file)
    Draft202012Validator(RECEIPT_SCHEMA).validate(result)
    if len(encoded(result).encode())>4096:raise Refused('Receipt contract exceeds 4096 bytes')
    return result

class Receipts:
    def __init__(self,api):self.api=api;self.service=api.service;self.store=api.store;self.files=api.files
    def publish(self,campaign,ref,value):
        return self.files.publish(campaign,ref,encoded(public(value)),kind='query',source={'archive':'query.json'})
    def snapshot(self,campaign,op,filters,value):
        value=stable(public(value))
        if enabled(self.store.get('campaigns',campaign)['config']):
            return Snapshots(self.files,campaign).publish(op,filters,value)
        digest=hashlib.sha256(encoded([filters,value]).encode()).hexdigest()
        key=hashlib.sha256(encoded([op,filters]).encode()).hexdigest()
        index=self.service.data/'campaigns'/campaign/'meta-snapshots'/(key+'.json')
        if index.exists():
            cached=json.loads(index.read_text())
            if cached['digest']==digest:
                file=cached['file'];path=self.files.directory(campaign)/file['path'].lstrip('/')
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==file['sha256']:return file
        file=self.publish(campaign,'query:'+op+':'+digest,{'operation':op,'filters':filters,'revision':digest,
            'observedAt':self.store.clock(),'observation':'Sequential ledger reads; writes recheck their revisions.',
            'source':'controller-derived-index','data':value})
        atomic_json(index,{'digest':digest,'file':file});return file
    def evidence(self,campaign,row):
        base={k:v for k,v in row.items() if k!='path'}
        try:return public({**base,'file':stable(self.files.evidence(campaign,row)),'availability':'available'})
        except (OSError,ValueError):return public({**base,'availability':'unavailable','reason':'Original missing or integrity validation failed'})
    def evidence_catalog(self,campaign,filters=None):
        from src.evidence.catalog import EvidenceCatalog
        return EvidenceCatalog(self).tree(campaign,filters)
    def closeout(self,campaign):
        from .stop_policy import META_POLICY
        c=self.store.get('campaigns',campaign)
        if c['config'].get('stopPolicy')==META_POLICY:
            submitted=bool(c.get('finishAssessment'))
            return {'complete':submitted,'summaryStatus':'submitted' if submitted else 'missing',
                'requiredFields':['reason','summary'],'reportsRequired':False,'nextReport':None,
                'rule':'Meta decides when to end and submits a reason and activity summary. No stability, candidate, evidence or report prerequisite; ending does not certify success.'}
        reports=self.store.report_heads(campaign);batches=self.store.list('batches',campaign)
        missing=[b['id'] for b in batches if not any(r['batchId']==b['id'] and r['status']=='analysis' for r in reports)]
        final=not any(r['kind']=='final' and r['status']=='analysis' for r in reports)
        return {'missingRoundBatchIds':missing,'finalReportRequired':final,'complete':not missing and not final,
            'nextReport':{'batchId':missing[0] if missing else None,'expectedReportRevision':0} if missing or final else None,
            'rule':'Every accepted batch requires its own analysis, including failed/cancelled trials; a final report does not replace round reports.'}
    def status(self,campaign):
        with self.store.read_snapshot():return self._status(campaign)
    def _status(self,campaign):
        from .meta_context import activity_state
        c=self.store.status(campaign);state=activity_state(self.service,campaign)
        requests=self.api.requests(campaign);operations=self.store.list('operations',campaign)
        closeout=self.closeout(campaign)
        full={'closeout':closeout,'state':state,'campaign':c,'operations':operations,'requests':requests,
            'candidates':self.candidates(campaign),'batches':self.store.list('batches',campaign),
            'trials':[{**{k:t.get(k) for k in ['id','revision','batchId','candidateId','task','state','score']},'file':compact(self.publish(campaign,'trial:'+t['id'],t))} for t in self.store.list('trials',campaign)],
            'reports':[{**{k:r.get(k) for k in ['id','batchId','kind','analysisRevision','factsSha256']},'file':compact(self.publish(campaign,'report-index:'+r['id'],{**r,'reading':'Use report_get with reportId to read the complete immutable report.'}))} for r in self.store.report_heads(campaign)],
            'evidence':{'scope':'navigation-only',**self.service.evidence.overview(campaign),
                'completeDirectory':{'operation':'evidence_list','arguments':{},'reading':'完整不可变证据目录由 evidence_list 返回；这里每次实验只提供一个阅读入口。'}}}
        file=self.snapshot(campaign,'campaign_status',{},full)
        usage=c['usage'];plan=c.get('resourcePlanning') or {}
        unresolved=sum(r['state'] not in ['completed','rejected'] for r in requests)+sum(o['state'] in ['running','outcome_unknown'] for o in operations)
        summary='当前活动状态与待处理事项；文件为完整快照或分层索引，按 reading 和 file.path 遍历。'
        if c['state']=='closing' and 'summaryStatus' in closeout:
            summary=('收尾理由和实验总结已保存；后台正在处理在途工作，无需再次提交或继续研究。' if closeout['complete'] else '活动已关闭探索，可调用 campaign_finish 提交结束理由和实验总结；不要求补齐单独报告。')
        if c['state']=='closing' and closeout['nextReport'] and not (c['counts']['activeTrials'] or c['counts']['reservedTrials']):
            target=closeout['nextReport']['batchId']
            summary='活动已关闭探索，无需再调用 campaign_finish。尚缺 '+str(len(closeout['missingRoundBatchIds']))+' 份每轮报告'+('及总报告' if closeout['finalReportRequired'] else '')+'。下一份：report_get_facts('+encoded({'batchId':target} if target else {})+')，然后 report_save（expectedReportRevision=0）。失败实验也须单独报告；总报告不能代替每轮报告。完整清单见快照 data.closeout。'
        return receipt(summary,file,campaignId=campaign,state=c['state'],revision=c['revision'],
            selectionRevision=len(self.store.list('selection_decisions',campaign)),planRevision=plan.get('revision',plan.get('planRevision',0)),
            remainingSeconds=c['remainingSeconds'],activeTrials=c['counts']['activeTrials'],reservedTrials=c['counts']['reservedTrials'],
            explorationClosed=c['explorationClosed'],stopReason=c.get('stopReason'),unresolvedOperationCount=unresolved,
            pendingQuestionCount=sum(q['state']=='pending' for q in self.store.list('meta_questions',campaign)),
            **({'budget':{'confirmed':usage['confirmedTokens'],'inflight':usage['inflightReservedTokens'],'unknown':usage['unknownReservedTokens'],'limit':c['config']['softTokenLimit']}} if 'confirmedTokens' in usage else {}))
    def candidates(self,campaign):
        items=[];assets={}
        for kind in ['version','plugin']:
            for row in self.service.materials._records(campaign,kind):
                try:file=public(stable(self.files.material(campaign,row)))
                except (OSError,ValueError):file={'ref':row['ref'],'availability':'unavailable','reason':'Frozen version asset unavailable'}
                assets.setdefault(row['candidateId'],[]).append(file)
        trials=self.store.list('trials',campaign)
        for row in self.store.list('candidates',campaign):
            row=candidate_view(row)
            checks=dict(row.get('check',{}));files=assets.get(row['id'],[])
            logs=Path(checks.get('evidence',''))
            allowed=self.service.data/'campaigns'/campaign/'checks'
            if logs.is_dir() and logs.resolve().is_relative_to(allowed.resolve()):
                checks['files']=[stable(self.files.publish(campaign,'check-log:'+row['id']+':'+p.name,p.read_bytes(),kind='check',source={'archive':p.name})) for p in sorted(logs.rglob('*')) if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(allowed.resolve())]
            checkfile=self.publish(campaign,'check:'+row['id'],checks)
            items.append(public({**{k:row.get(k) for k in ['id','displayName','description','parentId','bundleId','plugins','createdAt']},
                'check':{'status':checks.get('status'),'file':compact(checkfile)},'files':files,
                'availability':'available' if files and all(f.get('availability')=='available' for f in files) else 'unavailable',
                'trialCount':sum(t['candidateId']==row['id'] for t in trials)}))
        return items
    def report_navigation(self,campaign):
        ANALYSIS=analysis_for(self.service,campaign)
        schema=self.files.publish(campaign,'schema:'+ANALYSIS['$id'],encoded(ANALYSIS),kind='query',source={'archive':'report-analysis.schema.json'})
        template=self.files.publish(campaign,'template:'+ANALYSIS['$id'],encoded(ANALYSIS['examples'][0]),kind='query',source={'archive':'report-analysis.json'})
        return {'analysisSchema':compact(schema),'analysisTemplate':compact(template)}
    def research(self,campaign,row):
        return receipt(row['record']['summary'],self.publish(campaign,'research:'+row['id'],row),recordId=row['recordId'],revision=row['revision'])
    def report(self,campaign,row):
        return receipt('分析报告已保存。',self.publish(campaign,'report:'+row['id'],row),reportId=row['id'],analysisRevision=row['analysisRevision'],factsId=row['factsSha256'])
    def decision(self,campaign,row):
        return receipt('候选保留决定已记录。',self.publish(campaign,'decision:'+row['id'],row),candidateId=row['candidateId'],decisionId=row['id'],selectionRevision=row['selectionRevision'])
    def reconciled(self,campaign,op,request):
        table={'report_save':'reports','candidate_retain':'selection_decisions'}.get(op)
        if not table:return None
        row=next((r for r in self.store.list(table,campaign) if r.get('metaRequest',{}).get('requestId')==request['requestId']),None)
        if row is None:return None
        if row['metaRequest']['payload']!=request['payload']:raise Conflict('Committed request payload mismatch')
        try:return self.report(campaign,row) if op=='report_save' else self.decision(campaign,row)
        except (OSError,ValueError):
            return receipt('操作已提交，文件发布待修复；使用相同参数与键重试。',status='committed',committed=True,requestId=request['requestId'],
                **({'reportId':row['id'],'analysisRevision':row['analysisRevision']} if op=='report_save' else {'decisionId':row['id'],'selectionRevision':row['selectionRevision']}))
    def rejected(self,campaign,errors,code='validation_failed',operation='report_save'):
        file=self.publish(campaign,'diagnostic:'+hashlib.sha256(encoded(errors).encode()).hexdigest(),{'errors':errors,'operation':operation,'schemaVersion':ANALYSIS['$id'] if operation=='report_save' else 'meta-tools-v3'})
        return receipt('提交未生效；按诊断文件修正后使用新的幂等键。',file,status='rejected',committed=False,code=code,errorCount=len(errors),**(self.report_navigation(campaign) if operation=='report_save' else {}))
    def save_report(self,campaign,args,request):
        ANALYSIS=analysis_for(self.service,campaign)
        schema=CONTRACTS[version(self.service,campaign)]['report_save']['input'];errors=[]
        def add(pointer,expected,actual,hint):errors.append({'pointer':pointer,'expected':expected,'actual':actual,'hint':hint})
        def validate(value,schema,prefix=''):
            for error in Draft202012Validator(schema).iter_errors(value):
                escape=lambda value:str(value).replace('~','~0').replace('/','~1')
                pointer=prefix+''.join('/'+escape(p) for p in error.absolute_path)
                if error.validator=='required':
                    missing=next((key for key in error.validator_value if error.message==repr(key)+' is a required property'),None)
                    if missing is not None:
                        add(pointer+'/'+escape(missing),'required field','missing','Add this field using its declared type.');continue
                if error.validator=='additionalProperties' and isinstance(error.instance,dict):
                    for key in sorted(set(error.instance)-set(error.schema.get('properties',{}))):
                        add(pointer+'/'+escape(key),'declared field',type(error.instance[key]).__name__,'Remove this undeclared field or include its information in an allowed field.')
                    continue
                add(pointer,{'constraint':error.validator,'value':error.validator_value},type(error.instance).__name__,'Match the published schema; no content is copied into this diagnostic.')
        validate({k:v for k,v in args.items() if k!='reviewId'},schema)
        analysis=args.get('analysis');analysis_sha=None
        if 'analysisFile' in args and isinstance(args['analysisFile'],dict):
            try:
                value=args['analysisFile'];path=value['path']
                if not isinstance(path,str):raise Refused('Analysis path must be a string')
                if not path.startswith('/work/analysis/'):raise Refused('Use an absolute /work/analysis/ path')
                data=read_analysis_file(self.service.data/'campaigns'/campaign/'meta-work/analysis',path.removeprefix('/work/analysis/'))
                analysis_sha=hashlib.sha256(data).hexdigest()
                if analysis_sha!=value['sha256']:raise Refused('Analysis hash mismatch')
                analysis=json.loads(data.decode('utf-8'));validate(analysis,ANALYSIS,'/analysis')
            except (OSError,ValueError,KeyError,TypeError) as error:add('/analysisFile','readable authorized UTF-8 JSON with matching SHA-256',type(error).__name__,'Check path, bytes, encoding and digest.')
        snapshot=None;id=args.get('factsId','')
        try:
            if not isinstance(id,str) or not re.fullmatch('[0-9a-f]{64}',id):raise Refused('Invalid facts ID')
            snapshot=json.loads((self.service.data/'campaigns'/campaign/'report-facts'/(id+'.json')).read_text())
            if hashlib.sha256(encoded(snapshot['facts']).encode()).hexdigest()!=id:raise Refused('Facts hash mismatch')
        except (OSError,ValueError):add('/factsId','available immutable facts snapshot','unavailable','Call report_get_facts.')
        if snapshot and isinstance(analysis,dict):
            allowed={e['id'] for e in snapshot['facts']['evidence']}
            groups=[('/analysis/evidenceRefs',analysis.get('evidenceRefs'))]
            for key in ['problems','pluginContributions']:
                if isinstance(analysis.get(key),list):groups.extend((f'/analysis/{key}/{i}/evidenceRefs',v.get('evidenceRefs',[])) for i,v in enumerate(analysis[key]) if isinstance(v,dict))
            for pointer,refs in groups:
                if isinstance(refs,list):
                    for i,ref in enumerate(refs):
                        if isinstance(ref,str) and ref not in allowed:add(pointer+'/'+str(i),'evidence ID in facts scope','out-of-scope','Use the exact evidence ID from the facts snapshot.')
            if any(t.get('startedAt') for t in snapshot['facts']['trials']) and analysis.get('evidenceRefs')==[]:add('/analysis/evidenceRefs','at least one evidence ID','empty array','Cite evidence for an executed trial.')
        if errors:return self.rejected(campaign,errors)
        analysis_sha=analysis_sha or hashlib.sha256(encoded(analysis).encode()).hexdigest()
        row=self.service.reports.save(campaign,analysis,snapshot['batchId'],facts=snapshot['facts'],expected_revision=args['expectedReportRevision'],
            meta_request=request,analysis_schema=ANALYSIS['$id'],analysis_sha=analysis_sha)
        return self.report(campaign,row)
    def run(self,campaign,op,args,request=None):
        c=self.store.get('campaigns',campaign)
        if c['state'] in ['draft','finished','failed']:raise Refused('Meta session is not active')
        if op=='campaign_status':return self.status(campaign)
        if op=='candidate_list':
            rows=self.candidates(campaign)
            return receipt(f'找到 {len(rows)} 个候选；版本与源码入口见目录。',self.snapshot(campaign,op,args,{'total':len(rows),'items':rows}),total=len(rows),retainedCandidateId=c['retainedCandidateId'],finalCandidateId=c['finalCandidateId'])
        if op=='evidence_list':
            for key,table in [('batchId','batches'),('trialId','trials')]:
                if key in args and self.store.get(table,args[key])['campaignId']!=campaign:raise Refused('Evidence scope outside Campaign')
            catalog=self.evidence_catalog(campaign,args)
            return receipt(f"找到 {catalog['total']} 条证据，其中 {catalog['unavailableCount']} 条原件不可用；完整不可变目录见文件。",
                self.snapshot(campaign,op,args,{'total':catalog['total'],'items':catalog['items']}),
                total=catalog['total'],unavailableCount=catalog['unavailableCount'])
        if op=='sdk_read':
            pack=self.service.knowledge_for(campaign);id=args['id'];text=pack._text(id)
            file=self.files.publish(campaign,'sdk:'+pack.manifest['id']+':'+id,text,kind='sdk',source=pack.manifest['documents'][id]['source'],version=pack.manifest['dshVersion'])
            documents=[]
            for doc,entry in pack.manifest['documents'].items():
                descriptor=self.files.publish(campaign,'sdk:'+pack.manifest['id']+':'+doc,pack._text(doc),kind='sdk',source=entry['source'],version=pack.manifest['dshVersion'])
                documents.append({'id':doc,'source':entry['source'],'file':compact(descriptor)})
            atomic_json(self.files.directory(campaign)/'sdk/index.json',{'knowledgePackId':pack.manifest['id'],'sdkVersion':pack.manifest['dshVersion'],'documents':public(documents)})
            return receipt('已定位当前冻结知识包的完整文档；使用原生文件工具读取，同版本导航见 /sdk/index.json。',file,documentId=id,knowledgePackId=pack.manifest['id'],sdkVersion=pack.manifest['dshVersion'])
        if op=='results_compare':
            result=self.api._call(campaign,op,args)
            result['evidence']=[self.evidence(campaign,e) for e in self.store.list('evidence',campaign) if e['trialId'] in {t['id'] for t in result['attempts']}]
            trials=result['attempts'];scored=sum(t.get('score') is not None for t in trials);failed=sum(t['state']=='failed' for t in trials)
            from .store import comparison_issues
            issues=comparison_issues(trials);result['comparisonLimitations']=issues
            return receipt(f'比较 {len(trials)} 次尝试：已评分 {scored}，未评分 {len(trials)-scored}，失败 {failed}；比较限制 {len(issues)} 项。',self.snapshot(campaign,op,args,result),evaluationRule=result['evaluation']['rule'],candidateCount=len(args.get('candidateIds',self.store.list('candidates',campaign))),trialCount=len(trials),limitationCount=len(issues))
        if op=='candidate_retain':
            from src.execution.bundle.manifest import verify
            candidate=self.api._candidate(campaign,args['candidateId'])
            if verify(candidate['bundlePath'])['id']!=candidate['bundleId']:raise Refused('Frozen candidate identity mismatch')
            self.store.retain(campaign,args['candidateId'],args['reason'],args['evidenceRefs'],**{k:args[k] for k in ['tradeoffs','limitations','reconsiderWhen','expectedSelectionRevision']},meta_request=request,**{k:args[k] for k in ['summary','alternatives','researchRefs'] if k in args})
            return self.reconciled(campaign,op,request)
        if op=='report_save':return self.save_report(campaign,args,request)
        result=self.api._call(campaign,op,args)
        if op=='research_save':return self.research(campaign,result)
        if op in ['research_list','research_read','evidence_excerpt']:
            return receipt('研究解释与核验后的片段见文件。',self.snapshot(campaign,op,args,result))
        if op=='report_get_facts':
            # Keep the original facts identity, publish a derived view with usable paths.
            facts=json.loads((self.service.data/'campaigns'/campaign/'report-facts'/(result['factsId']+'.json')).read_text())['facts']
            result['file']=compact(self.publish(campaign,'facts:'+result['factsId'],{**facts,'fileView':{'kind':'path-projection','sourceFactsId':result['factsId']},'evidence':[self.evidence(campaign,self.store.get('evidence',e['id'])) for e in facts['evidence']]}))
            result.update(self.report_navigation(campaign))
        if op=='report_get':return self.report(campaign,self.store.get('reports',args['reportId']))
        return result
