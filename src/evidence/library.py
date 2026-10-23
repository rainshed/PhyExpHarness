"""Allowlisted derived feedback. Raw official archives remain unchanged and separately verifiable."""
import hashlib
import gzip
import json
from pathlib import Path
from src.control.store import identity,Refused
from .objects import Objects, enabled

HAMLEARN_METRICS = {'linf','relative_l2','relative_l2_within_threshold','level','scored_vector_kind',
    'support_detected_true','support_false_positives','uncertainty_covered','uncertainty_total','uncertainty_median_1sigma',
    'budget_us','budget_used_us','within_budget','accepted_row_count','ran_nonzero_time_probe',
    'verifiable_activity_consistent','evidence_mean_binomial_deviance','evidence_p90_binomial_deviance',
    'evidence_data_compatible','binary_pass','reward_binary','penalties'}

def feedback(task,score):
    if not isinstance(score,dict):return None
    # Unknown report fields are not published by default, even for registered public tasks.
    result={k:score[k] for k in ['task_id','schema_version','reward_binary','reward','passed','disposition'] if k in score}
    if task=='time_budgeted_hamlearn_10q':
        result['penalties']=score.get('penalties',[])
        if isinstance(score.get('result'),dict):result['result']={k:v for k,v in score['result'].items() if k in HAMLEARN_METRICS}
        else:result['result']=None
    result['feedbackPolicy']='public-development-v1'
    return result

class EvidenceLibrary:
    def __init__(self,store,data):self.store=store;self.root=Path(data)/'evidence';self.objects=Objects(data)
    def add(self,campaign,trial,kind,text,source,policy='public-development-v1'):
        data=text.encode() if isinstance(text,str) else text;sha=hashlib.sha256(data).hexdigest();file=self.root/sha
        with self.store.connection(True) as db:
            self.store.writable(campaign,db)
            if enabled(self.store._get(db,'campaigns',campaign)['config']):
                file=self.objects.put(data)
            else:
                file.parent.mkdir(parents=True,exist_ok=True)
                if not file.exists():file.write_bytes(data);file.chmod(0o444)
            existing=[x for x in self.store._list(db,'evidence',campaign) if x['trialId']==trial and x['kind']==kind and x['sha256']==sha]
            if existing:return existing[0]
            row={'id':identity('evidence'),'campaignId':campaign,'trialId':trial,'kind':kind,'sha256':sha,'path':str(file),
                 'bytes':len(data),'source':source,'policy':policy,'encoding':'utf-8' if self._utf8(data) else 'binary'}
            return self.store._save(db,'evidence',row)
    @staticmethod
    def _utf8(data):
        try:data.decode('utf-8');return True
        except UnicodeDecodeError:return False
    def ingest(self,trial,summary=None):
        folder=Path(trial['output']);summary=summary if summary is not None else json.loads((folder/'summary.json').read_text());items=[]
        config=self.store.get('campaigns',trial['campaignId'])['config']
        if config.get('metaComposition',{}).get('version')=='meta-composition-v2':
            return self.ingest_complete(trial,summary)
        safe={k:summary.get(k) for k in ['fixture','status','pipelineStatus','taskOutcome','officialReward','sciencePassed','submissionPresent',
            'scientificAssessmentPresent','wallTimeSeconds','stopReason','error','usage','bundleId','failure','scoringStatus','accounting','failureContract','requestRecovery','resultCollection']}
        safe['score']=feedback(trial['task'],summary.get('score'))
        items.append(self.add(trial['campaignId'],trial['id'],'official-result',json.dumps(safe,ensure_ascii=False,indent=2),
            {'archive':'summary.json','official':summary.get('evidence',{}).get('officialScore'),
             **({'collection':summary['resultCollection']} if summary.get('resultCollection') else {})}))
        for file in folder.glob('harbor/*/phyexp/events.json'):
            events=json.loads(file.read_text());allowed=[]
            for index,event in enumerate(events):
                if event.get('type') in ['request/header','tool/call','tool/result','assistant/message','turn/end','error']:
                    # Presentation includes returned actions/text, not hidden provider internals.
                    if event.get('type')=='assistant/message':
                        event=json.loads(json.dumps(event));message=event.get('data',{}).get('message',{})
                        message['content']=[x for x in message.get('content',[]) if x.get('type')!='reasoning']
                    allowed.append({'eventIndex':index,'event':event})
            text='\n'.join(json.dumps(x,ensure_ascii=False) for x in allowed)
            items.append(self.add(trial['campaignId'],trial['id'],'trajectory',text,{'archive':str(file.relative_to(folder))}))
        for name in ['container-exec.jsonl','mcp-discovery.json','load-receipt.json','bootstrap-receipt.json']:
            for file in folder.glob('harbor/*/phyexp/'+name):
                items.append(self.add(trial['campaignId'],trial['id'],name,file.read_text(),{'archive':str(file.relative_to(folder))}))
        return items
    def ingest_complete(self,trial,summary):
        """Publish actual development outputs, never task images or verifier inputs.

        No field/event whitelist is applied inside these output files. Legacy
        projections and their IDs remain unchanged for v1 Campaigns.
        """
        root=Path(trial['output']).resolve();files={}
        for pattern in ['summary.json','*.log','failure*.json','harbor/*/phyexp/*.json',
                        'harbor/*/phyexp/*.jsonl','harbor/*/phyexp/*.log','harbor/*/phyexp/*.segments/**/*',
                        'harbor/*/verifier/*.txt','harbor/*/verifier/*.log',
                        'harbor/*/verifier/artifacts/**/*','harbor/*/agent/*.txt','harbor/*/result.json']:
            for file in root.glob(pattern):
                if file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(root):files[file.relative_to(root).as_posix()]=file
        # Collector-verified output references may have different archive layouts.
        for rel in summary.get('evidence',{}).values():
            if not isinstance(rel,str):continue
            file=root/rel
            if not file.is_symlink() and file.is_file() and file.resolve().is_relative_to(root):files[file.relative_to(root).as_posix()]=file
        items=[]
        for rel,file in sorted(files.items()):
            kind='official-result' if rel=='summary.json' else 'trajectory-original' if file.name=='events.json' else 'raw-artifact'
            items.append(self.add(trial['campaignId'],trial['id'],kind,file.read_bytes(),
                {'archive':rel,'format':'segmented-log-tail' if Path(str(file)+'.segments/index.json').exists() else 'original-bytes','collection':summary.get('resultCollection'),**({'segments':rel+'.segments/index.json'} if Path(str(file)+'.segments/index.json').exists() else {}),**({'storageEncoding':'gzip'} if file.suffix=='.gz' else {})},policy='public-development-full-v2'))
        return items
    def read(self,campaign,id,offset=0,limit=16000):
        row=self.store.get('evidence',id)
        if row['campaignId']!=campaign:raise Refused('Evidence belongs to another Campaign')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=32000:raise Refused('Invalid evidence range')
        data=Path(row['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Refused('Evidence integrity mismatch')
        try:text=(gzip.decompress(data) if row.get('source',{}).get('archive','').endswith('.gz') else data).decode('utf-8')
        except UnicodeDecodeError:return {k:v for k,v in row.items() if k!='path'}|{'encoding':'binary','previewAvailable':False}
        return {k:v for k,v in row.items() if k!='path'}|{'offset':offset,'offsetUnit':'characters','total':len(text),'text':text[offset:offset+limit],
            'nextOffset':offset+limit if offset+limit<len(text) else None}

    def excerpt(self,campaign,anchor):
        """Unicode character anchors, checked against immutable bytes on every read."""
        result={'anchor':anchor,'availability':'unavailable'}
        try:row=self.store.get('evidence',anchor.get('evidenceId'))
        except (KeyError,TypeError):return {**result,'availability':'unavailable','reason':'原始证据不存在'}
        if row['campaignId']!=campaign:return {**result,'availability':'unauthorized','reason':'证据未纳入当前活动'}
        result.update(evidence={k:v for k,v in row.items() if k!='path'})
        if anchor.get('unit')!='characters':return {**result,'availability':'unsupported','reason':'此定位格式尚不支持；需要 Unicode 字符范围'}
        try:data=Path(row['path']).read_bytes()
        except OSError:return {**result,'reason':'原始文件缺失'}
        if hashlib.sha256(data).hexdigest()!=row['sha256'] or anchor.get('sha256')!=row['sha256']:
            return {**result,'availability':'stale','reason':'证据内容摘要不匹配'}
        try:text=(gzip.decompress(data) if row.get('source',{}).get('archive','').endswith('.gz') else data).decode('utf-8')
        except UnicodeDecodeError:return {**result,'availability':'unsupported','reason':'二进制证据无法按字符定位'}
        start,end=anchor.get('start'),anchor.get('end')
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or end-start>16000:
            return {**result,'availability':'invalid_range','reason':'字符范围失效或超过 16000 字符'}
        return {**result,'availability':'available','text':text[start:end],'contextBefore':text[max(0,start-160):start],
            'contextAfter':text[end:end+160],'totalCharacters':len(text),'originalOffset':start,'offsetUnit':'characters'}
