from src.control.model_access import control_only
"""System facts and versioned Meta analysis stay distinct in every report."""
import hashlib
import copy
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from src.control.store import Refused,identity,encoded,comparison_issues,retention_rule_description
from .tables import build_tables, read_annotations
from src.evidence.diagnostics import trial_diagnostics
from src.evidence.outcomes import evaluation, outcome_summary
from .reading import project, render_reading, PRESENTATION_VERSION

class Reports:
    def __init__(self,store,data):self.store=store;self.root=Path(data)/'reports'
    def tables(self,campaign,batch_id=None,context=None):
        context=context or self.store.status(campaign)
        return build_tables(self.store.list('candidates',campaign), self.store.list('batches',campaign),
            trial_diagnostics(self.store.list('trials',campaign),self.root.parent,context['config']), context,
            read_annotations(self.root.parent), batch_id)
    def view(self,report):
        """Assess only the report's frozen attempts; no later outcomes or DB writes."""
        value=copy.deepcopy(report);config=value['facts']['campaign']['config']
        trials=trial_diagnostics(value['facts']['trials'],self.root.parent,config)
        value['taskEvaluation']=evaluation(trials,config['tasks'],value['facts'].get('candidates',[]),config)
        lookup={t['id']:t for t in trials}
        tables=value.get('tables') or build_tables(value['facts'].get('candidates',[]),value['facts'].get('batches',[]),trials,value['facts']['campaign'])
        value['tables']=tables
        for v in tables['versions']:v.setdefault('displayName',v.get('label',v['id']))
        names={v['id']:v['displayName'] for v in tables['versions']}
        for r in tables['rounds']:
            r.setdefault('versionName',names.get(r['candidateId'],r.get('versionLabel','版本缺失')))
            r['results']=trial_diagnostics([{**t,**lookup.get(t['id'],{})} for t in r['results']],self.root.parent,config)
            r['taskEvaluation']=outcome_summary(r['results'],r['tasks'],config)
        from .tables import group_rounds
        tables['groups']=group_rounds(tables['rounds'])
        for v in tables['versions']:
            v['taskEvaluation']=outcome_summary([t for r in tables['rounds'] if r['candidateId']==v['id'] for t in r['results']],config['tasks'],config)
        value['reading']=value.get('reading') or project(value,self.root.parent)
        if 'taskEvaluation' not in value['facts']:
            value['evaluationNotice']='按 '+value['taskEvaluation']['rule']+' 补充本报告快照的任务完成统计；原始评分、分析、事实快照和历史选择不变。'
        value['markdown']=render_reading(value)
        return value
    def refresh_presentation(self,report_id):
        """Append a display revision; never replace the original analysis or fact snapshot."""
        old=self.store.get('reports',report_id)
        if self.store.get('campaigns',old['campaignId'])['state'] not in ['finished','failed']:
            raise Refused('Display migration requires a terminal Campaign')
        tables=self.tables(old['campaignId'],old['batchId'],old['facts']['campaign'])
        # Preserve the result/state visible to the original report. This command is
        # restricted to terminal Campaigns by its CLI, and records that provenance.
        reading=project({**old,'tables':tables},self.root.parent)
        if old.get('tables')==tables and old.get('reading')==reading and old.get('presentationVersion')==PRESENTATION_VERSION:return old
        record=copy.deepcopy(old)
        for key in ['id','revision','analysisRevision','previousReportId','markdownPath','createdAt']:
            record.pop(key,None)
        record.update(id=identity('report'),createdAt=self.store.clock(),tables=tables,
            presentationSourceReportId=old['id'],revisionReason='阅读版更新；原始分析、事实快照和历史文件保留',
            presentationAuthor='system')
        return self._persist(record)
    def facts(self,campaign,batch_id=None):
        c=self.store.status(campaign)
        batches=self.store.list('batches',campaign)
        if batch_id:
            batches=[b for b in batches if b['id']==batch_id]
            if not batches:raise Refused('Batch unavailable')
        ids={b['id'] for b in batches};trials=[t for t in self.store.list('trials',campaign) if t['batchId'] in ids]
        usage=[] if control_only(c['config']) else self.store.list('usage',campaign)
        for t in trials:
            if 'taskSources' in t.get('comparisonContext',{}):
                context=t['comparisonContext'];context['taskSourcesDigest']=hashlib.sha256(encoded(context.pop('taskSources')).encode()).hexdigest()
            requests=[r for r in usage if r['leaseId']==t.get('leaseId')]
            if not control_only(c['config']):t['accountedUsage']={'confirmedTokens':sum(r.get('confirmedTokens') or 0 for r in requests),'unknownRequests':sum(r['status']=='unknown' for r in requests),'unknownReservedTokens':sum(r['reservedTokens'] for r in requests if r['status']=='unknown')}
        trials=trial_diagnostics(trials,self.root.parent,c['config'])
        for t in trials:t.pop('summary',None)
        candidates=[{**candidate,'versionLabel':f'H{index}'} for index,candidate in enumerate(sorted(self.store.list('candidates',campaign),key=lambda c:(c.get('createdAt',0),c['id'])))
            if not batch_id or any(t['candidateId']==candidate['id'] for t in trials)]
        roles={lease['id']:lease['role'] for lease in self.store.list('leases',campaign)}
        decisions=self.store.list('selection_decisions',campaign)
        research=self.store.list('research_records',campaign)
        research_refs={a['evidenceId'] for r in research for a in r['record'].get('anchors',[])+[a for o in r['record'].get('observations',[]) for a in o['anchors']]}
        decision_refs={ref for d in decisions for ref in d['evidenceRefs']}
        by_role={role:{'confirmedTokens':sum(r.get('confirmedTokens') or 0 for r in usage if roles.get(r['leaseId'])==role),
            'unknownReservedTokens':sum(r['reservedTokens'] for r in usage if roles.get(r['leaseId'])==role and r['status']=='unknown')}
            for role in ['solver','meta']}
        references=trial_diagnostics(self.store.list('reference_runs',campaign),self.root.parent,c['config'])
        for row in references:row.pop('summary',None)
        return {'referenceExperiments':{'batches':self.store.list('reference_batches',campaign),'runs':references,'scoreScope':'separate; excluded from primary results','attribution':'joint-reference does not isolate model or harness causality'},'stopReviews':self.store.list('stop_reviews',campaign),'metaObservations':self.store.list('meta_observations',campaign),
            'metaSessions':self.store.list('meta_sessions',campaign),'metaComposition':c['config'].get('metaComposition'),
            'campaign':c,'batches':batches,'trials':trials,'candidates':candidates,**({} if control_only(c['config']) else {'usageByRole':by_role}),
            'taskEvaluation':evaluation(trials,c['config']['tasks'],candidates,c['config']),
            'comparisonIssues':comparison_issues(self.store.list('trials',campaign)),
            'evidence':[{k:v for k,v in e.items() if k!='path'} for e in self.store.list('evidence',campaign) if e['id'] in decision_refs|research_refs or any(e['trialId']==t['id'] for t in trials+references)],
            'selectionDecisions':decisions,'researchRecords':research,'researchLinks':self.store.list('research_links',campaign),
            'generalization':'当前公开任务仅用于开发/回归；没有独立任务或实例上的泛化验证。',
            'comparisonRule':retention_rule_description(c['config'])}
    def save(self,campaign,analysis,batch_id=None,author='meta',facts=None,expected_revision=None,meta_request=None,analysis_schema=None,analysis_sha=None):
        fields={'summary','observations','hypotheses','limitations','decision','evidenceRefs'}
        if not fields.issubset(analysis) or not isinstance(analysis['summary'],str) or not analysis['summary'].strip():
            raise Refused('Analysis requires summary, observations, hypotheses, limitations, decision and evidenceRefs')
        refs=analysis['evidenceRefs']
        if not isinstance(refs,list) or not all(isinstance(x,str) for x in refs):raise Refused('evidenceRefs must be an array of exact evidence IDs')
        facts=self.facts(campaign,batch_id) if facts is None else copy.deepcopy(facts)
        if facts['campaign']['id']!=campaign:raise Refused('Facts belong to a different Campaign')
        allowed={x['id'] for x in facts['evidence']}
        if set(refs)-allowed:raise Refused('Unknown or unrelated evidence reference')
        if any(t.get('startedAt') for t in facts['trials']) and not refs:raise Refused('Analysis needs evidence references')
        optional={'process','problems','pluginContributions','researchRefs'}
        for key in optional & analysis.keys():
            if not isinstance(analysis[key],list):raise Refused(key+' must be an array')
        for item in analysis.get('pluginContributions',[]):
            if not isinstance(item,dict) or not all(isinstance(item.get(k),str) for k in ['plugin','expected','observed','comparison','assessment']):raise Refused('Plugin contribution requires plain-language fields')
            if not isinstance(item.get('evidenceRefs',[]),list) or any(x not in allowed for x in item.get('evidenceRefs',[])):raise Refused('Invalid contribution evidence')
        research=[]
        for ref in analysis.get('researchRefs',[]):
            row=next((r for r in facts.get('researchRecords',[]) if r['recordId']==ref.get('recordId') and r['revision']==ref.get('revision')),None)
            if row is None:raise Refused('Research revision outside report facts snapshot')
            research.append(row)
        record={'id':identity('report'),'campaignId':campaign,'batchId':batch_id,'kind':'round' if batch_id else 'final',
            **({'metaRequest':meta_request,'analysisSchema':analysis_schema,'analysisSha256':analysis_sha} if meta_request else {}),
            'author':author,'status':'analysis','facts':facts,'factsSha256':hashlib.sha256(encoded(facts).encode()).hexdigest(),
            'researchRecords':research,'analysis':{k:analysis[k] for k in fields | ((optional|{'brief'}) & analysis.keys())},'createdAt':self.store.clock(),
            'tables':build_tables(facts['candidates'],facts['batches'],facts['trials'],facts['campaign'],read_annotations(self.root.parent),batch_id)}
        return self._persist(record,expected_revision)
    def status_summary(self,campaign,reason):
        facts=self.facts(campaign)
        return self._persist({'id':identity('report'),'campaignId':campaign,'batchId':None,'kind':'status_summary','author':'system',
            'status':'analysis_incomplete','facts':facts,'factsSha256':hashlib.sha256(encoded(facts).encode()).hexdigest(),
            'analysis':{'summary':reason,'observations':[],'hypotheses':[],'limitations':['Meta 完整分析尚未完成。'],
                        'decision':'保留已有事实与版本，等待后续处理。','evidenceRefs':[]},'createdAt':self.store.clock(),
            'tables':self.tables(campaign,context=facts['campaign'])})
    def _persist(self,record,expected_revision=None):
        self.store.track_artifact(record['campaignId'],self.root/record['id'],'report')
        record['reading']=project(record,self.root.parent)
        record['presentationVersion']=PRESENTATION_VERSION
        directory=self.root/record['id'];directory.mkdir(parents=True)
        pending=Path(tempfile.mkdtemp(prefix='.publishing-',dir=directory))
        try:
            while True:
                with self.store.connection() as db:
                    previous=self._replay(db,record)
                    if previous:return previous
                    head=self._head(db,record)
                if expected_revision is not None and expected_revision!=head[0]:raise Refused('Report revision changed')
                result={**record,'analysisRevision':head[0]+1,'previousReportId':head[1],
                        'markdownPath':str(directory/'report.md'),'schemaVersion':1,'revision':record.get('revision',0)+1}
                # Render, serialize and write all bodies before taking the writer lock.
                body=encoded(result)
                (pending/'report.md').write_text(render(result))
                (pending/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                with self.store.connection(True,operation='report.publish') as db:
                    self.store.writable(record['campaignId'],db)
                    previous=self._replay(db,record)
                    if previous:return previous
                    if self._head(db,record)!=head:
                        if expected_revision is not None:raise Refused('Report revision changed')
                        continue
                    db.execute('INSERT INTO reports VALUES(?,?,?)',(result['id'],result['campaignId'],body))
                    # Only atomic renames remain under the lock. Readers see the DB
                    # row after both files exist. A crash leaves a tracked orphan,
                    # never a committed row pointing at unfinished files.
                    for name in ('report.md','report.json'):os.replace(pending/name,directory/name)
                    self.store._event(db,record['campaignId'],'report_saved',reportId=record['id'],reportKind=record['kind'])
                return result
        finally:shutil.rmtree(pending,ignore_errors=True)

    def _head(self,db,record):
        rows=db.execute("SELECT id FROM reports WHERE campaign=? AND json_extract(data,'$.batchId') IS ? AND json_extract(data,'$.kind')=? ORDER BY rowid",
                        (record['campaignId'],record['batchId'],record['kind'])).fetchall()
        return len(rows),rows[-1]['id'] if rows else None

    def _replay(self,db,record):
        request=record.get('metaRequest')
        if not request:return None
        row=db.execute("SELECT data FROM reports WHERE campaign=? AND json_extract(data,'$.metaRequest.requestId')=?",
                       (record['campaignId'],request['requestId'])).fetchone()
        if row:
            previous=json.loads(row['data'])
            if previous['metaRequest']['payload']!=request['payload']:raise Refused('Report request payload changed')
            return previous

def render(report):
    return render_reading(report)
