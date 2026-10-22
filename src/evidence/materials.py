"""Campaign-scoped material catalogue. Explicit sources only; never a host file browser."""
import hashlib
import json
import re
from pathlib import Path
from src.control.store import Refused, encoded
from src.control.operations import workspace_path
from src.control.meta_context import activity_state
from src.execution.bundle.manifest import verify,resolve
from src.reporting.tables import plugin_changes

KINDS = ('activity', 'task', 'sdk', 'version', 'plugin', 'experiment', 'evidence', 'analysis', 'guide')
GUIDES = {
    'interface': '来源：平台工具契约。插件草稿使用工作区相对路径。冻结和实验提交返回持久 ID；完成通知只提供状态，可按需查询材料。重复请求使用相同 idempotencyKey，参数改变须使用新键。候选冻结只接受插件目录和配置，Solver 配方由后台确定。null 次数/token 上限表示没有该项上限，时间及并发约束仍生效。额外模型调用计入预算，无自动重试。候选保留规则和当前决策可查询 activity:current，完整历史在 campaign_status 的 full 视图。meta-selection-v1 由 Meta 主动选择，candidate_retain 需提交 candidateId、reason、evidenceRefs、tradeoffs、limitations（可为空数组）、reconsiderWhen；平台核验证据并保存比较限制，不因缺分、在途试验、环境差异或退步否决。选择不代表认证。旧活动遵循绑定规则。',
    'reporting': '来源：平台报告契约。report_save 的 summary、observations、hypotheses、limitations、decision、evidenceRefs 为必需字段；可提供 process（简短中文过程节点）、problems（已解决及未解决问题）、pluginContributions（plugin、expected、observed、comparison、assessment、evidenceRefs）。引用使用 evidence 原始 ID。版本、插件差异、分数和消耗由系统生成；分析说明实际发生的过程、问题和插件作用，区分加载、触发、行为改变及因果收益，缺少对比时明确说明。省略 batchId 保存总报告，填写则保存每轮报告。总报告说明进化过程、保留版本、是否达标、停止原因和局限。插件 manifest 的 displayName/functionSummary/mechanism 及候选 displayName 使用可读名称；mechanism 用中文讲明工作过程、触发条件和关键限制，不只列接口名。categories 可多选 prompt-context/tools/tool-results/execution-control/other，分别为提示与上下文、工具能力、工具结果处理、执行控制与恢复、其他扩展，不额外填写行为分类。历史分析是模型判断，不是新的官方证据。比较版本和撰写报告以后台 taskEvaluation 绑定的规则版本为准：模型输出异常、未提交、约定限额耗尽计任务完成分0，v2 另将最终未恢复的模型过载和连接故障计0，v1 保持原口径；其余外部故障/取消/待定/待归因单列；官方评分保持原值。使用逐任务分子分母与任务等权成功率，不以有评分样本比例代替成功率。',
}
GUIDES_NATIVE={
    'interface':GUIDES['interface'].replace('额外模型调用计入预算，无自动重试。','额外模型调用计入同一预算。Meta 技术恢复与 Solver 请求重试分别遵循绑定契约。')+' 原生 v2 日常开发使用文件、搜索、终端和 jobs 工具，插件草稿在 /work/plugins，分析在 /work/analysis。业务参数直接传对象；candidate_retain 还须提交 expectedSelectionRevision。candidate_check/candidate_freeze 和 export_create 返回 operationId；检查/冻结从 campaign_status 的 full 视图查询，导出从 export_status 查询。完整来源路径及未决操作见 /evidence/index.json、/outputs/index.json 和 campaign_status.metaRequests。',
    'reporting':'来源：平台 meta-tools-v2 报告契约。先用 report_get_facts（可带 batchId）取得不可变 factsId 和完整事实文件，再用 report_save 提交 factsId、analysis 或带 path/sha256 的 analysisFile、expectedReportRevision、idempotencyKey。每轮与总报告各自维护修订，首次为 0。analysis 中的内容要求如下：'+GUIDES['reporting'].replace('report_save 的','analysis 的').replace('省略 batchId 保存总报告，填写则保存每轮报告。','报告范围由 report_get_facts 的 batchId 决定，不能在 analysis 内另改范围。')
}


def checked_text(root, relative, digest=None):
    file = workspace_path(root, relative)
    data = file.read_bytes()
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise Refused('Material integrity mismatch')
    return data.decode('utf-8')


def snapshot_tasks(service, campaign):
    """New campaigns snapshot only the public instruction; no task tree traversal."""
    directory = service.data / 'campaigns' / campaign / 'materials'
    manifest = directory / 'tasks.json'
    if manifest.exists():
        return
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in service.store.get('campaigns', campaign)['config']['tasks']:
        relative = f'harbor_tasks/{task}/instruction.md'
        row = {'task': task, 'source': relative, 'createdAt': service.store.clock()}
        try:
            text = checked_text(service.quantum, relative)
            digest = hashlib.sha256(text.encode()).hexdigest()
            file = directory / (digest + '.txt')
            if not file.exists():
                file.write_text(text); file.chmod(0o444)
            row.update(file=file.name, sha256=digest, availability='available')
        except (OSError, ValueError):
            row.update(availability='unavailable', reason='允许的任务原文缺失或路径不安全；未读取其他任务文件')
        rows.append(row)
    temporary = directory / 'tasks.json.tmp'
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(manifest)


class Materials:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def _record(self, ref, kind, title, source, load, **meta):
        return {'ref': ref, 'kind': kind, 'title': title, 'source': source,
                'availability': 'available', **meta, '_load': load}

    def _tasks(self, campaign):
        directory = self.service.data / 'campaigns' / campaign / 'materials'
        manifest = directory / 'tasks.json'
        snapshots=set()
        if manifest.exists():
            for row in json.loads(checked_text(directory, 'tasks.json')):
                task = row['task']
                if task not in self.store.get('campaigns', campaign)['config']['tasks']:
                    raise Refused('Task outside Campaign')
                snapshots.add(task)
                yield self._record('task:' + task, 'task', task + ' · 任务原文', row['source'],
                    lambda r=row: checked_text(directory, r['file'], r['sha256']),
                    **{k: v for k, v in row.items() if k not in ('file', 'source')}, version=row.get('sha256'))
        # Legacy activities: read the instruction archived with that actual run,
        # never silently substitute the current task checkout for historical input.
        for task in self.store.get('campaigns', campaign)['config']['tasks']:
            found = task in snapshots
            for trial in self.store.list('trials', campaign):
                if trial['task'] != task or not trial.get('output'):
                    continue
                root = Path(trial['output'])
                for name,label in [('instruction.md','实际任务原文'),('environment.json','公开执行环境'),('prompt.txt','实际任务与环境输入')]:
                    for file in sorted(root.glob('harbor/*/phyexp/'+name)):
                        relative = str(file.relative_to(root))
                        yield self._record('task:' + trial['id'] + ':' + name, 'task', task + ' · ' + label,
                            {'trialId': trial['id'], 'archive': relative},
                            lambda r=root, p=relative: checked_text(r, p), task=task,
                            trialId=trial['id'], batchId=trial['batchId'], candidateId=trial['candidateId'],
                            version=trial['id'], createdAt=trial.get('startedAt'))
                        if name=='instruction.md':found = True
            if not found:
                yield self._record('task:' + task, 'task', task + ' · 任务原文', '历史归档',
                    lambda: '', task=task, availability='unavailable', reason='没有可核对的历史任务原文；未替换为当前文件')

    def _version(self, candidate):
        manifest = verify(candidate['bundlePath'])
        recipe = json.loads(checked_text(candidate['bundlePath'], 'recipe.json', manifest['files']['recipe.json']))
        parent=self.store.get('candidates',candidate['parentId']) if candidate.get('parentId') else None
        return encoded({'source': '冻结执行组合', 'candidateId': candidate['id'],
                        'bundleId': manifest['id'], 'parentId': candidate.get('parentId'),
                        'changesFromParent':plugin_changes(parent,candidate) if parent else None,
                        'description': candidate.get('description'), 'recipe': recipe, 'plugins': manifest['plugins']})

    def _plugin(self, candidate, relative):
        resolved = resolve(candidate['bundlePath']);manifest = resolved.manifest
        if not relative.startswith('plugins/') or relative not in manifest['files']:
            raise Refused('Not a frozen plugin asset')
        file = resolved.asset(relative)
        return checked_text(file.parent, file.name, manifest['files'][relative])

    def _experiment(self, campaign, batch):
        from .diagnostics import trial_diagnostics
        trials = trial_diagnostics([t for t in self.store.list('trials', campaign) if t['batchId'] == batch['id']],self.service.data)
        fields = ('id', 'candidateId', 'task', 'state', 'score', 'startedAt', 'finishedAt', 'stopReason', 'failure', 'scoringStatus', 'resultLabel', 'deadline')
        previous=next((b for b in self.store.list('batches',campaign) if b['round']==batch['round']-1),None)
        change=plugin_changes(self.store.get('candidates',previous['candidateId']),self.store.get('candidates',batch['candidateId'])) if previous else None
        return encoded({'source': '后台实验账本；详细官方反馈和轨迹见 evidence',
                        'batch': batch, 'previousBatchId':previous['id'] if previous else None,
                        'changesFromPreviousRound':change,'trials': [{k: t.get(k) for k in fields} for t in trials]})

    def _records(self, campaign, kind=None):
        self.store.get('campaigns', campaign)
        include = lambda k: kind is None or kind == k
        if include('activity'):
            yield self._record('activity:current', 'activity', '活动目标、约束与实时状态', '固定后台配置与账本',
                               lambda: encoded(activity_state(self.service, campaign)), version='live')
        if include('guide'):
            native=self.store.get('campaigns',campaign)['config'].get('metaComposition',{}).get('version')=='meta-composition-v2'
            from src.control.meta_contracts import version,analysis_for
            ANALYSIS=analysis_for(self.service,campaign)
            guides=GUIDES_NATIVE if native else GUIDES
            if native and version(self.service,campaign) in ('meta-tools-v3','meta-tools-v4'):
                guides={
                    'interface':GUIDES_NATIVE['interface'].replace('full 视图','完整快照文件').replace('campaign_status.metaRequests','campaign_status.file 的 requests').replace('原生 v2','原生 v3')+' campaign_status/candidate_list 输入为空对象，evidence_list 可按 batchId/trialId 过滤但不分页。七个精简工具只返回描述和完整文件路径；原生 read/grep/bash 按需读取正文。sdk_read 只接受 id，同版本导航见 /sdk/index.json。',
                    'reporting':ANALYSIS['$id']+'：report_get_facts 返回 factsId、完整事实、analysisSchema 和 analysisTemplate 路径。report_save 只传 factsId、expectedReportRevision、idempotencyKey，以及 analysis / analysisFile 中恰好一个；推荐先用原生工具写 /work/analysis/*.json，再提交路径和 SHA-256。合法最小结构与正式 schema：'+encoded(ANALYSIS)}
            for name, text in guides.items():
                yield self._record('guide:' + name, 'guide', name, '平台工具契约', lambda t=text: t, version='2' if native else '1')
        if include('task'):
            yield from self._tasks(campaign)
        if include('sdk'):
            pack = self.service.knowledge_for(campaign)
            for id, entry in pack.manifest['documents'].items():
                yield self._record(f'sdk:{pack.manifest["id"]}:{id}', 'sdk', id, entry['source'],
                    lambda i=id, p=pack: checked_text(p.path, p.manifest['documents'][i]['file'], p.manifest['documents'][i]['sha256']),
                    version=pack.manifest['dshVersion'], packId=pack.manifest['id'], profileDigest=pack.manifest['profileDigest'], sha256=entry['sha256'])
        if include('version') or include('plugin'):
            for c in self.store.list('candidates', campaign):
                title = c.get('displayName') or c.get('description') or c['id']
                if include('version'):
                    yield self._record('version:' + c['id'], 'version', title, '冻结执行 Bundle',
                        lambda r=c: self._version(r), candidateId=c['id'], version=c['bundleId'], createdAt=c.get('createdAt'))
                if include('plugin'):
                    # Only the frozen manifest's plugin assets are addressable.
                    try:manifest = verify(c['bundlePath'])
                    except (OSError,ValueError) as error:
                        yield self._record('plugin:'+c['id'],'plugin',title,'冻结执行组合',lambda:'',
                            candidateId=c['id'],availability='unavailable',reason=str(error))
                        continue
                    for relative, digest in sorted(manifest['files'].items()):
                        if relative.startswith('plugins/'):
                            yield self._record('plugin:' + c['id'] + ':' + relative, 'plugin', title + ' / ' + relative,
                                {'candidateId': c['id'], 'asset': relative}, lambda r=c, p=relative: self._plugin(r, p),
                                candidateId=c['id'], version=c['bundleId'], sha256=digest)
        if include('experiment'):
            for b in self.store.list('batches', campaign):
                yield self._record('experiment:' + b['id'], 'experiment', '第 ' + str(b['round']) + ' 轮实验', '后台实验账本',
                    lambda r=b: self._experiment(campaign, r), batchId=b['id'], candidateId=b['candidateId'],
                    tasks=b['tasks'], version='live', createdAt=b.get('acceptedAt'))
        if include('evidence'):
            trials = {t['id']: t for t in self.store.list('trials', campaign)}
            for e in self.store.list('evidence', campaign):
                t = trials.get(e['trialId'], {})
                yield self._record('evidence:' + e['id'], 'evidence', e['kind'],
                    {'evidenceId':e['id'],'archive':e['source'].get('archive'),'policy':e['policy'],**({'adoption':e['source']['adoption']} if e['source'].get('adoption') else {})},
                    lambda r=e: checked_text(Path(r['path']).parent, Path(r['path']).name, r['sha256']),
                    evidenceId=e['id'], trialId=e['trialId'], batchId=t.get('batchId'), task=t.get('task'),
                    candidateId=t.get('candidateId'), version=e['sha256'], sha256=e['sha256'])
        if include('analysis'):
            for r in self.store.list('research_records',campaign):
                yield self._record('analysis:research:'+r['id'],'analysis',r['record']['summary'],{'author':r['author'],'classification':'authored-research'},lambda row=r:encoded(row),version=r['revision'])
            for r in self.store.list('reports', campaign):
                trials=r.get('facts',{}).get('trials',[])
                yield self._record('analysis:' + r['id'], 'analysis', ('总报告' if not r['batchId'] else '每轮报告') + ' · 分析修订 ' + str(r['analysisRevision']),
                    {'author': r['author'], 'classification': 'model-analysis' if r['author'] == 'meta' else 'system-summary'},
                    lambda row=r: encoded({k: row.get(k) for k in ('id', 'kind', 'batchId', 'analysisRevision', 'previousReportId', 'analysis', 'factsSha256')}),
                    batchId=r['batchId'], version=r['analysisRevision'], createdAt=r['createdAt'],
                    tasks=sorted({t['task'] for t in trials}),candidateIds=sorted({t['candidateId'] for t in trials}))

    def _filtered(self, campaign, kind=None, task=None, candidateId=None, batchId=None):
        if kind is not None and kind not in KINDS:
            raise Refused('Unknown material kind')
        config = self.store.get('campaigns', campaign)['config']
        for value in (task,candidateId,batchId):
            if value is not None and (not isinstance(value,str) or not value):raise Refused('Material filters require nonempty identifiers')
        if task is not None and task not in config['tasks']:
            raise Refused('Task outside Campaign')
        for table, id in [('candidates', candidateId), ('batches', batchId)]:
            if id is not None and self.store.get(table, id)['campaignId'] != campaign:
                raise Refused('Material filter belongs to another Campaign')
        for row in self._records(campaign, kind):
            if task and row.get('task') != task and task not in row.get('tasks', []): continue
            if candidateId and row.get('candidateId') != candidateId and candidateId not in row.get('candidateIds',[]): continue
            if batchId and row.get('batchId') != batchId: continue
            yield row

    @staticmethod
    def _range(offset, limit, maximum):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= maximum:
            raise Refused('Invalid material range')

    @staticmethod
    def _public(row):
        return {'schemaVersion':1,**{k: v for k, v in row.items() if k != '_load'}}

    def list(self, campaign, offset=0, limit=20, **filters):
        self._range(offset, limit, 100)
        rows = list(self._filtered(campaign, **filters))
        return {'source': '当前活动允许材料目录', 'items': [self._public(r) for r in rows[offset:offset+limit]],
                'total': len(rows), 'nextOffset': offset+limit if offset+limit < len(rows) else None}

    def read(self, campaign, ref, offset=0, limit=16000):
        self._range(offset, limit, 32000)
        if not isinstance(ref, str) or ':' not in ref:
            raise Refused('Material reference required')
        kind = ref.split(':', 1)[0]
        for row in self._filtered(campaign, kind=kind):
            if row['ref'] != ref: continue
            result = self._public(row)
            if row['availability'] != 'available': return result
            try:text = row['_load']()
            except UnicodeDecodeError:return {**result,'encoding':'binary','previewAvailable':False}
            return {**result, 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'observedAt': self.store.clock(),
                    'offset': offset, 'total': len(text), 'text': text[offset:offset+limit],
                    'nextOffset': offset+limit if offset+limit < len(text) else None}
        raise Refused('Material unavailable in this Campaign')

    def search(self, campaign, query, offset=0, limit=20, **filters):
        self._range(offset, limit, 100)
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise Refused('Invalid material query')
        matches = []
        for row in self._filtered(campaign, **filters):
            if row['availability'] != 'available': continue
            try:text = row['_load']()
            except UnicodeDecodeError:continue
            match = re.search(re.escape(query),text,re.IGNORECASE)
            if match:
                pos=match.start()
                start = max(0, pos-80)
                matches.append({**self._public(row), 'offset': start, 'matchOffset': pos,
                                'sha256': hashlib.sha256(text.encode()).hexdigest(), 'excerpt': text[start:pos+240]})
        return {'source': '当前活动允许材料全文搜索', 'matches': matches[offset:offset+limit], 'total': len(matches),
                'nextOffset': offset+limit if offset+limit < len(matches) else None}
