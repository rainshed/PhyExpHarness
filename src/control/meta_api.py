"""Versioned, finite domain operations for the six native Meta plugins."""
import hashlib
import json
import threading
from pathlib import Path
from jsonschema import Draft202012Validator,ValidationError
from .store import Refused,Conflict,encoded
from .operations import workspace_path
from .meta_contracts import CONTRACTS,version
from .meta_receipts import Receipts,read_analysis_file
from src.evidence.files import FileViews,atomic_json
from src.evidence.diagnostics import trial_diagnostics
from src.evidence.outcomes import evaluation
from src.execution.bundle.manifest import resolve as resolve_bundle

CONTRACT=Path(__file__).resolve().parents[2]/'packages/meta-harness/contracts.json'

def validate(value,schema,label='input'):
    try:Draft202012Validator(schema).validate(value)
    except ValidationError as error:raise Refused(label+': '+error.message) from error

def page(rows,args):
    offset=args.get('offset',0);limit=args.get('limit',50)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise Refused('Invalid page range')
    return {'items':rows[offset:offset+limit],'total':len(rows),'nextOffset':offset+limit if offset+limit<len(rows) else None}

class MetaAPI:
    def __init__(self,service):
        self.service=service;self.store=service.store;self.files=FileViews(service)
        self.contract=CONTRACTS['meta-tools-v2'];self.lock=threading.RLock();self.receipts=Receipts(self)
    def call(self,campaign,operation,args):
        if version(self.service,campaign) not in ('meta-tools-v5','meta-tools-v6','meta-tools-v7','meta-tools-v8','meta-tools-v9'):return self._dispatch(campaign,operation,args)
        from .meta_tool_boundary import ToolBoundary
        from .meta_receipts import receipt
        boundary=ToolBoundary(self)
        write=CONTRACTS[version(self.service,campaign)].get(operation,{}).get('write',operation.endswith(('_submit','_cancel')))
        try:
            try:result=self._dispatch(campaign,operation,args)
            except Exception as error:return boundary.error(campaign,operation,error,write=write)
            return boundary.project(campaign,operation,result)
        except (OSError,ValueError):
            # A result can be committed before publication fails. The durable
            # request journal/reconciler remains authoritative; never replay it.
            identity=hashlib.sha256(encoded([campaign,operation,args.get('idempotencyKey')]).encode()).hexdigest()
            return receipt('结果文件暂不可用；使用相同参数和幂等键核对，不要创建重复请求。',status='outcome_unknown' if write else 'failed',
                code='file_publication_failed',requestId=identity,reconciliationRequired=bool(write))
    def _dispatch(self,campaign,operation,args):
        if operation.startswith('reference_'):
            from .reference.plugins import frozen_contracts
            spec=frozen_contracts(self.service,campaign).get(operation)
            if not spec:raise Refused('Reference capability was not frozen for this activity')
            validate(args,spec['input'])
            from .meta_receipts import public
            return public(self.service.references.call(campaign,operation,args))
        protocol=version(self.service,campaign);v3=protocol in ('meta-tools-v3','meta-tools-v4','meta-tools-v5','meta-tools-v6','meta-tools-v7','meta-tools-v8','meta-tools-v9')
        spec=CONTRACTS[protocol].get(operation)
        if not spec:raise Refused('Unknown Meta v2 operation')
        # The review grant is attached by the outside host, never part of the model schema.
        if not (v3 and operation=='report_save'):validate({k:v for k,v in args.items() if k!='reviewId'},spec['input'])
        if not spec['write']:return self.receipts.run(campaign,operation,args) if v3 else self._call(campaign,operation,args)
        key=args.get('idempotencyKey')
        if not isinstance(key,str) or not key.strip() or len(key)>200:raise Refused('Invalid idempotency key')
        identity=hashlib.sha256(encoded([campaign,operation,key]).encode()).hexdigest()
        payload=hashlib.sha256(encoded(args).encode()).hexdigest()
        # Durable unknown state is intentional: after a lost process never replay an
        # external side effect. Reconcile against operations/batches before deciding.
        directory=self.service.data/'campaigns'/campaign/'meta-requests';file=directory/(identity+'.json')
        with self.lock:
            if file.exists():
                prior=json.loads(file.read_text())
                if prior['payload']!=payload:raise Conflict('Idempotency key conflicts with prior input')
                if prior['state'] in ['completed','rejected']:return prior['result']
                reconciled=self.receipts.reconciled(campaign,operation,prior) if v3 else None
                if reconciled is None:reconciled=self._reconcile(campaign,operation,key)
                if reconciled is not None:
                    atomic_json(file,{**prior,'state':'committed' if reconciled.get('status')=='committed' else 'completed','result':reconciled,'reconciled':True})
                    return reconciled
                return {'status':prior['state'],'requestId':identity,'error':prior.get('error'),'reconciliationRequired':True}
            receipt={'requestId':identity,'operation':operation,'idempotencyKey':key,'payload':payload,'state':'outcome_unknown'}
            atomic_json(file,receipt)
            try:result=self.receipts.run(campaign,operation,args,receipt) if v3 else self._call(campaign,operation,args)
            except Exception as error:
                recovered=self.receipts.reconciled(campaign,operation,receipt) if v3 else None
                if recovered is not None:result=recovered
                elif v3 and isinstance(error,(Refused,Conflict)):
                    pointer='/evidenceRefs' if operation=='candidate_retain' and 'evidence' in str(error).lower() else '/'
                    hint=str(error)+(' Use raw evidence IDs, not query/material references or file paths.' if pointer=='/evidenceRefs' else '')
                    result=self.receipts.rejected(campaign,[{'pointer':pointer,'expected':'valid current scope and revision','actual':type(error).__name__,'hint':hint}],operation=operation,code='revision_conflict' if isinstance(error,Conflict) or 'revision' in str(error).lower() else 'request_refused')
                else:
                    atomic_json(file,{**receipt,'error':str(error)})
                    raise
            state=result.get('status') if result.get('status') in ['rejected','committed'] else 'completed'
            atomic_json(file,{**receipt,'state':state,'result':result})
            return result
    def _reconcile(self,campaign,operation,key):
        kind={'batch_submit':'batch','campaign_plan_update':'resource-plan','trial_conditions_accept':'trial-conditions','research_save':'research-save'}.get(operation)
        if kind:
            with self.store.connection() as db:
                row=db.execute('SELECT result FROM commands WHERE campaign=? AND kind=? AND key=?',(campaign,kind,key)).fetchone()
                if row:
                    value=json.loads(row['result'])
                    return self.receipts.research(campaign,value) if operation=='research_save' else value
        kind={'candidate_freeze':'freeze','candidate_check':'candidate_check','export_create':'export'}.get(operation)
        if kind:
            row=next((r for r in self.store.list('operations',campaign) if r['kind']==kind and r['payload'].get('idempotencyKey')==key),None)
            if row:return {'operationId':row['id'],'state':row['state'],'result':row.get('result'),'error':row.get('error')}
    def requests(self,campaign):
        directory=self.service.data/'campaigns'/campaign/'meta-requests'
        return [json.loads(p.read_text()) for p in sorted(directory.glob('*.json'))]
    def _candidate(self,campaign,id):
        row=self.store.get('candidates',id)
        if row['campaignId']!=campaign:raise Refused('Candidate unavailable')
        return row
    def _call(self,campaign,op,args):
        service=self.service;c=self.store.get('campaigns',campaign)
        if c['state'] in ['draft','finished','failed']:raise Refused('Meta session is not active')
        if op=='research_save':return service.research.save(campaign,**args)
        if op=='research_list':return service.research.overview(campaign,**args)
        if op=='research_read':return service.research.detail(campaign,**args)
        if op=='evidence_excerpt':return service.evidence.excerpt(campaign,args)
        if op=='campaign_status':
            result=service.meta_call(campaign,op,args)
            requests=self.requests(campaign)
            result['metaRequests']={'total':len(requests),'unresolved':[{k:r.get(k) for k in ['requestId','operation','idempotencyKey','state','error']} for r in requests if r['state']!='completed'],
                'file':self.files.publish(campaign,'runtime:requests',encoded(requests),kind='activity',source='controller-request-journal')}
            return result
        if op=='candidate_list':return page(service.meta_call(campaign,op,{}),args)
        if op=='evidence_list':
            rows=service.meta_call(campaign,op,{k:v for k,v in args.items() if k=='batchId'})
            if args.get('trialId'):rows=[r for r in rows if r['trialId']==args['trialId']]
            result=page(rows,args)
            result['items']=[{**r,**self.files.evidence(campaign,self.store.get('evidence',r['id']))} for r in result['items']]
            return result
        if op=='evidence_read':
            return {**service.evidence.read(campaign,**args),**self.files.evidence(campaign,self.store.get('evidence',args['id']))}
        if op.startswith('materials_'):
            if op=='materials_read':
                row=next((r for r in service.materials._records(campaign,args['ref'].split(':')[0]) if r['ref']==args['ref']),None)
                if row is None:raise Refused('Material unavailable')
                descriptor=self.files.material(campaign,row)
                if descriptor.get('encoding')=='binary':return {**descriptor,'previewAvailable':False}
                return {**service.materials.read(campaign,**args),**descriptor}
            result=service.meta_call(campaign,op,args)
            rows={r['ref']:r for r in service.materials._records(campaign,args.get('kind'))}
            key='items' if op=='materials_list' else 'matches'
            result[key]=[{**r,**self.files.material(campaign,rows[r['ref']])} for r in result[key]]
            return result
        if op.startswith('sdk_'):
            result=service.meta_call(campaign,op,args)
            if op=='sdk_read':
                pack=service.knowledge_for(campaign)
                result.update(self.files.publish(campaign,'sdk:'+pack.manifest['id']+':'+args['id'],pack._text(args['id']),kind='sdk',source=result['source'],version=pack.manifest['dshVersion']))
            return result
        if op=='candidate_diff':
            a,b=[resolve_bundle(self._candidate(campaign,args[k])['bundlePath']) for k in ['left','right']]
            keys=sorted(set(a.manifest['files'])|set(b.manifest['files']))
            return {'left':args['left'],'right':args['right'],'files':[{'path':k,'before':a.manifest['files'].get(k),'after':b.manifest['files'].get(k)} for k in keys if a.manifest['files'].get(k)!=b.manifest['files'].get(k)],
                'beforePlugins':a.manifest.get('plugins',[]),'afterPlugins':b.manifest.get('plugins',[])}
        if op=='batch_status':
            batch=self.store.get('batches',args['batchId'])
            if batch['campaignId']!=campaign:raise Refused('Batch unavailable')
            trials=trial_diagnostics([r for r in self.store.list('trials',campaign) if r['batchId']==batch['id']],service.data,c['config'])
            return {'batch':batch,'trials':page(trials,args),'evidenceIndex':'/evidence/index.json'}
        if op=='results_compare':
            candidates=self.store.list('candidates',campaign);trials=self.store.list('trials',campaign)
            for field,key,table in [('candidateId','candidateIds','candidates'),('batchId','batchIds','batches')]:
                if key in args:
                    allowed={r['id'] for r in self.store.list(table,campaign)}
                    if set(args[key])-allowed:raise Refused('Unknown comparison scope')
                    trials=[t for t in trials if t[field] in args[key]]
            tasks=args.get('tasks',c['config']['tasks'])
            if set(tasks)-set(c['config']['tasks']):raise Refused('Task outside Campaign')
            trials=trial_diagnostics([t for t in trials if t['task'] in tasks],service.data,c['config'])
            return {'evaluation':evaluation(trials,tasks,candidates,c['config']),'attempts':trials,'evidenceIndex':'/evidence/index.json'}
        if op=='candidate_check':
            if c['state']!='running' or c['explorationClosed']:raise Refused('Search writes closed')
            plugins=[{**p,'path':p['path'].removeprefix('/work/plugins/')} for p in args.get('plugins',[])]
            return service._operation(campaign,'candidate_check',args,lambda:service.build_candidate(campaign,plugins,'Development assembly check',check_only=True,project_path=args.get('projectPath')))
        if op=='report_get_facts':
            facts=service.reports.facts(campaign,args.get('batchId'));id=hashlib.sha256(encoded(facts).encode()).hexdigest()
            atomic_json(service.data/'campaigns'/campaign/'report-facts'/(id+'.json'),{'facts':facts,'batchId':args.get('batchId')})
            return {'factsId':id,'batchId':args.get('batchId'),'file':self.files.publish(campaign,'facts:'+id,encoded(facts),kind='facts',source='controller',version=id)}
        if op=='report_save':
            id=args['factsId']
            if len(id)!=64 or any(x not in '0123456789abcdef' for x in id):raise Refused('Invalid facts identity')
            file=service.data/'campaigns'/campaign/'report-facts'/(id+'.json')
            if not file.is_file():raise Refused('Facts snapshot unavailable')
            snapshot=json.loads(file.read_text())
            if hashlib.sha256(encoded(snapshot['facts']).encode()).hexdigest()!=id:raise Refused('Facts integrity mismatch')
            if ('analysis' in args)==('analysisFile' in args):raise Refused('Supply exactly one analysis source')
            analysis=args.get('analysis')
            if 'analysisFile' in args:
                root=service.data/'campaigns'/campaign/'meta-work'/ 'analysis'
                value=args['analysisFile'];relative=value['path'].removeprefix('/work/analysis/')
                data=read_analysis_file(root,relative)
                if hashlib.sha256(data).hexdigest()!=value['sha256']:raise Refused('Analysis integrity mismatch')
                analysis=json.loads(data)
            row=service.reports.save(campaign,analysis,snapshot['batchId'],facts=snapshot['facts'],expected_revision=args['expectedReportRevision'])
            return self._report(campaign,row)
        if op=='report_get':return self._report(campaign,self.store.get('reports',args['reportId']))
        if op=='export_create':
            self._candidate(campaign,args['candidateId'])
            def export():
                with service.operation_lock:row=service.export(campaign,args['candidateId'])
                file=self.files.publish(campaign,'export:'+row['id'],Path(row['archive']).read_bytes(),kind='export',source={'archive':'harness.zip'},version=row['archiveSha256'])
                return {**{k:v for k,v in row.items() if k not in ['path','archive']},'file':file}
            return service._operation(campaign,'export',args,export)
        if op=='export_status':
            row=self.store.get('operations',args['operationId'])
            if row['campaignId']!=campaign or row['kind']!='export':raise Refused('Export operation unavailable')
            return row
        if op=='candidate_retain':
            revision=len(self.store.list('selection_decisions',campaign))
            if revision!=args['expectedSelectionRevision']:raise Conflict('Selection revision changed')
        if op=='candidate_freeze':
            if 'plugins' in args:args={**args,'plugins':[{**p,'path':p['path'].removeprefix('/work/plugins/')} for p in args['plugins']]}
        return service.meta_call(campaign,op,args)
    def _report(self,campaign,row):
        if row['campaignId']!=campaign:raise Refused('Report unavailable')
        return {'id':row['id'],'analysisRevision':row['analysisRevision'],'factsSha256':row['factsSha256'],
            'file':self.files.publish(campaign,'report:'+row['id'],encoded(row),kind='analysis',source='controller-report',version=row['analysisRevision'])}
