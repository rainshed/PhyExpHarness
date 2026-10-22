"""Human reading projection. Source analysis/facts remain immutable and separate."""
import hashlib
import json
from pathlib import Path
from .tables import readable_text, stable, markdown_tables, cell

PRESENTATION_VERSION=7
REASONS={'round_limit':'达到轮次上限','trial_limit':'达到实验次数上限','time_limit':'达到探索时间上限，进入收尾',
    'token_threshold':'达到用量软阈值','campaign_deadline':'达到活动截止时间','trial_deadline':'达到单次时限',
    'user_stop':'用户停止','meta_finished':'Meta 主动结束','meta_session_failed':'Meta 会话未正常结束','completed':'执行完成'}

def project(report,data=None):
    a=report['analysis'];tables=report['tables'];facts=report['facts'];notes={}
    if data and (Path(data)/'report-readings.json').exists():
        entries=json.loads((Path(data)/'report-readings.json').read_text()).get('reports',[])
        notes=next((x for x in entries if x['campaignId']==report['campaignId'] and x.get('batchId')==report['batchId']
                    and x['analysisSha256']==hashlib.sha256(stable(a).encode()).hexdigest()),{})
    content=notes.get('reading',a)
    rounds=[r for r in tables['rounds'] if not report['batchId'] or r['id']==report['batchId']]
    candidate_ids={r['candidateId'] for r in rounds}
    used={m['pluginId'] for v in tables['versions'] if v['id'] in candidate_ids for m in v['plugins']}
    contributions=content.get('pluginContributions')
    if contributions is None:
        contributions=[{'plugin':p['displayName'],'expected':p['functionSummary'],
            'observed':'原报告未单独评价该插件在本轮的行为，请结合下方原分析和证据查看。',
            'comparison':'没有单独移除该插件的对照。','assessment':'贡献尚无法单独确认。','evidenceRefs':[]} for p in tables['plugins'] if p['id'] in used]
    reading={'summary':content.get('brief',content.get('summary',a['summary'])),
        'process':content.get('process',a.get('observations',[])),
        'problems':content.get('problems',[]),
        'pluginContributions':contributions,'decision':content.get('decision',a['decision']),
        'limitations':content.get('limitations',a.get('limitations',[])),
        'hypotheses':a.get('hypotheses',[]),
        'source':'根据原 Meta 分析整理的阅读版；不是新增模型分析。' if notes else
                 'Meta 提供的过程与插件作用分析。' if 'process' in a else '按原 Meta 分析整理；未单独记录的事项明确留空。',
        'sourceReportId':notes.get('sourceReportId'),
        'evidenceRefs':a.get('evidenceRefs',[])}
    if report.get('analysisSchema') in ('meta-report-analysis-v1','meta-report-analysis-v2'):
        reading['problems']=[('已解决：' if p['status']=='resolved' else '未解决：')+p['description'] for p in content.get('problems',[])]
    # Evidence identifiers remain exact machine links, never rewrite their values.
    refs=reading.pop('evidenceRefs');contribution_refs=[v.get('evidenceRefs',[]) for v in reading['pluginContributions']]
    reading=readable_text(reading,tables);reading['evidenceRefs']=refs;reading['sourceReportId']=notes.get('sourceReportId')
    for v,ids in zip(reading['pluginContributions'],contribution_refs):v['evidenceRefs']=ids
    return reading


def paragraphs(value):
    if isinstance(value,list):return ['- '+(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)) for x in value] or ['未单独记录。']
    return [str(value)]


def render_reading(report):
    f=report['facts'];c=f['campaign'];cfg=c['config'];u=c['usage'];a=report['reading'];tables=report['tables']
    versions={v['id']:v['displayName'] for v in tables['versions']}
    rounds=[r for r in tables['rounds'] if not report['batchId'] or r['id']==report['batchId']]
    title=f"第 {rounds[-1]['round']} 轮报告" if report['batchId'] and rounds else '进化总报告' if report['kind']=='final' else '运行状态摘要'
    lines=['# '+title,'',a['summary'],'',a['source'],'']
    if report.get('revisionReason'):lines += [report['revisionReason'],'']
    if report.get('evaluationNotice'):lines += [report['evaluationNotice'],'']
    assessment=report.get('taskEvaluation') or f.get('taskEvaluation')
    if assessment:
        from .tables import completion_lines
        lines += ['## 任务成功率','',assessment['description'],'',*completion_lines(assessment),'']
        for candidate_id,stats in assessment.get('byCandidate',{}).items():
            lines += ['### '+versions.get(candidate_id,candidate_id),'',*completion_lines(stats),'']
    if report['batchId'] and rounds:
        r=rounds[-1];lines += [f"执行版本：{r['versionName']}。",'插件变化：'+'；'.join(d['label'] for d in r['changes'])+'。',
            '任务结果：'+' / '.join(t.get('completionLabel') or t.get('resultLabel') or ('未评分' if t['score'] is None else str(t['score'])) for t in r['results'])+'。','']
    for key,label in [('process','进化过程' if not report['batchId'] else 'Agent 完成任务的过程'),('problems','遇到的问题')]:
        lines += ['## '+label,'',*paragraphs(a[key]),'']
    lines += ['## 插件在本次实验中的作用','','| 插件 | 预期作用 | 轨迹中实际观察 | 对照情况 | 判断 |','|---|---|---|---|---|']
    for row in a['pluginContributions']:
        lines.append('| '+' | '.join(cell(row.get(k,'尚未记录')) for k in ['plugin','expected','observed','comparison','assessment'])+' |')
    if not a['pluginContributions']:lines.append('| 无额外插件 | 固定基线能力 | — | — | 不涉及新增插件贡献 |')
    for key,label in [('decision','最终选择' if not report['batchId'] else '本轮后的决定'),('limitations','尚不能确定的事情')]:
        lines+=['','## '+label,'',*paragraphs(a[key])]
    for r in report.get('researchRecords',[]):
        record=r['record']
        lines+=['','## 研究解释 · '+record['summary'],'',f"来源：{r['author']}；记录时间：{r['recordedAt']}；事实时间：{record['factAt']}；修订：{r['revision']}。"]
        for key,label in [('problem','问题'),('hypothesis','假设'),('change','改动目的'),('validation','如何验证'),('limitations','局限'),('nextStep','下一步计划')]:lines+=['',label+'：',*paragraphs(record.get(key,[]))]
        for anchor in record.get('anchors',[]):lines+=['',anchor['supports']+f"（证据 {anchor['evidenceId']}，SHA-256 {anchor['sha256']}，字符 {anchor['start']}–{anchor['end']}）"]
    if f.get('selectionDecisions'):
        lines+=['','## Meta 版本选择记录','','选定是 Meta 判断；证据核验不代表平台认证稳定性或因果提升。以下为决策当时的完整记录摘要。']
        for d in f['selectionDecisions']:
            lines+=['',f"- 决策：{d['id']}；此前保留：{versions.get(d['previousCandidateId'],d['previousCandidateId'] or '未选择')}；本次选定：{versions.get(d['candidateId'],d['candidateId'])}；时间：{d['createdAt']}。",
                '  概述：'+cell(d.get('summary') or '未记录独立概述'),'  理由：'+cell(d['reason']),'  权衡：'+cell(d['tradeoffs']),
                '  Meta 声明的局限：'+cell('；'.join(d['limitations']) or '未另行声明'),
                '  重新考虑的条件：'+cell(d['reconsiderWhen']),
                '  平台比较限制：'+cell('；'.join(d['assessment']['comparisonLimitations'])),
                '  已核验证据：'+cell('、'.join(d['evidenceRefs'])),
                '  完整的逐任务结果、全部尝试、证据摘要及决策链保存在配套 JSON。']
            for alternative in d.get('alternatives',[]):
                lines += ['  备选 '+versions.get(alternative['candidateId'],alternative['candidateId'])+'：'+cell(alternative['reason'])+'；依据：'+cell('、'.join(alternative['evidenceRefs']) or '未另列证据')+'。']
            if 'alternatives' not in d:lines += ['  未记录备选分析；不能据此认定其他版本已被否决。']
    lines+=['','## 消耗与停止原因','',f"活动：{cfg.get('name','进化活动')}。Solver：{cfg['solver']['model']} / {cfg['solver'].get('reasoningEffort','无')}；Meta：{cfg['meta']['model']} / {cfg['meta'].get('reasoningEffort','无')}。",
        f"活动累计 {c['counts']['rounds']} 轮、{c['counts']['startedTrials']} 次已启动实验；耗时 {c['elapsedSeconds']/60:.1f} 分钟。",
        f"活动累计已确认 {u['confirmedTokens']:,} token；在途预留 {u['inflightReservedTokens']:,}；未知请求 {u['unknownRequests']} 个，保守预留 {u['unknownReservedTokens']:,}。",
        '停止原因：'+REASONS.get(c['stopReason'],c['stopReason'] or '尚未停止')+'。',
        '最终版本：'+versions.get(c.get('finalCandidateId'),'尚未选择')+'。']
    if c.get('finishAssessment'):lines+=['Meta 结束依据：'+c['finishAssessment']['reason']]
    if f.get('metaComposition'):
        meta=f['metaComposition'];lines+=['','### Meta 插件组合与停止审查','',f"冻结组合：{meta['preset']}；标识：{meta['id']}。",'审查消耗已计入 Meta 总量，不重复相加；插件触发记录不代表效果认证。']
        for p in meta['plugins']:
            hits=sum(o['pluginId']==p['id'] and o['event']=='triggered' for o in f.get('metaObservations',[]))
            lines.append(f"- {p['id']}：{'启用' if p['enabled'] else '禁用'}；观察到 {hits} 次工具或审查触发。")
        for r in f.get('stopReviews',[]):
            lines.append(f"- 审查 {r['id']}：{r['state']}；{(r.get('result') or {}).get('reason') or r.get('failure') or r['request']['reason']}；已确认 {r.get('usage',{}).get('confirmedTokens',0)} token（包含在 Meta 总量内）。")
    for role,usage in f.get('usageByRole',{}).items():lines.append(f"- {'Solver 执行' if role=='solver' else 'Meta 设计与报告'}累计：{usage['confirmedTokens']:,} token。")
    for i,t in enumerate(f['trials'],1):
        elapsed=(t.get('finishedAt') or t.get('startedAt') or 0)-(t.get('startedAt') or 0)
        lines.append(f"- 实验 {i}：{'未评分' if t['score'] is None else '评分 '+str(t['score'])}；耗时 {elapsed/60:.1f} 分钟；已确认 {t.get('accountedUsage',{}).get('confirmedTokens',0):,} token。")
    lines += ['', '## 实验状态与故障原因', '']
    for r in rounds:
        for t in r['results']:
            lines.append('- '+cell(t.get('completionLabel') or t.get('resultLabel') or ('未评分' if t['score'] is None else str(t['score']))))
            if t.get('failure'):
                d=t['failure'];lines.append('  原因代码：'+cell(d['code'])+'；评分阶段：'+cell(d.get('scoringStatus','unknown'))+'；诊断来源：'+cell(d.get('source'))+'。')
                observed=d.get('observed') or {};transport=observed.get('transport')
                if transport:
                    started='已开始' if transport.get('protocolStarted') is True else '尚未观察到开始' if transport.get('protocolStarted') is False else '未记录'
                    lines.append('  传输：'+cell(transport.get('actualTransport') or '未记录')+'；协议响应：'+started+
                                 '；模型内容字节：'+cell(observed.get('responseContentBytes',observed.get('responseBytes','未记录')))+
                                 '；关闭码：'+cell(transport.get('closeCode','未记录'))+'。内容字节为 0 不表示没有协议事件。')
    limit=lambda x:'不限制' if x is None else str(x)
    planned=cfg.get('resourcePolicy')=='meta-resource-planning-v1'
    trial_label=str(cfg['trialTimeSeconds'])+' 秒' if cfg['trialTimeSeconds'] else '由 Meta 按批次分配' if planned else '自动（至多 1 小时，并受剩余时间约束）'
    lines+=['',f"总时限 {cfg['wallTimeSeconds']/3600:g} 小时；轮次 {limit(cfg['maxRounds'])}；实验次数 {limit(cfg['maxTrials'])}；最高并发 {cfg['concurrency']}。",
        f"总用量软阈值：{limit(cfg['softTokenLimit'])}；单次上限：{trial_label}；配置的收尾最低预留 {cfg['reserveSeconds']/60:g} 分钟 / {cfg['reserveTokens']:,} token，包含在总额度内。"]
    if planned:
        plan=c.get('resourcePlan') or {}
        lines+=['', '## 资源计划与有效条件', '',
                f"计划版本 {plan.get('revision',0)}；来源 {plan.get('source','尚未制定')}；理由：{plan.get('reason','等待初始计划')}。",
                f"计划并发 {plan.get('parallelism','待定')}；后续单次 {plan.get('defaultTrialTimeSeconds','待定')} 秒；计划收尾 {plan.get('closeoutReserveSeconds',0)} 秒 / {plan.get('closeoutReserveTokens',0)} token。"]
        if cfg.get('executionTimePolicy'):
            lines.append(f"单次时长包含启动、Solver、评分和清理；固定评分与清理预留 {cfg['executionTimePolicy']['trialCloseoutReserveSeconds']} 秒，启动还会消耗时间。")
        for key,value in cfg.get('configurationSources',{}).items():
            lines.append(f"- {key}：{limit(cfg.get(key))}；来源 {value.get('source','未核实')}。")
        for t in f['trials']:
            conditions=t.get('effectiveConditions')
            if conditions:lines.append(f"- {t['task']}：批次申请 {conditions['trialTimeSeconds']} 秒；启动时实际获配 {conditions['actualTimeSeconds']:g} 秒；计划版本 {conditions['resourcePlanRevision']}。")
    from datetime import datetime
    for key,label in [('deadline','配置截止时间'),('finishedAt','实际结束时间')]:
        if c.get(key):lines.append(label+'：'+datetime.fromtimestamp(c[key]).astimezone().isoformat(timespec='seconds')+'。')
    prior=cfg.get('precedingAttempt')
    if prior:lines.append(f"前序活动另有 {prior['trials']} 次失败尝试、已确认 {prior['confirmedTokens']:,} token、未知预留 {prior['unknownReservedTokens']:,} token；原记录保留。")
    if f.get('comparisonIssues'):lines+=['','比较条件存在差异或缺失，不能据此认定插件带来可靠提升。']
    if not report['batchId']:lines+=['',*markdown_tables(tables)]
    else:
        lines+=['','## 本轮插件组合','']
        for v in tables['versions']:
            if v['id']==rounds[-1]['candidateId']:
                for m in v['plugins']:
                    p=next(p for p in tables['plugins'] if p['id']==m['pluginId'])
                    lines.append(f"- {p['displayName']} · {p['version']}：{p['mechanism']}；配置 {stable(m['config'])}。")
                if not v['plugins']:lines.append('无额外执行插件。')
    lines+=['','## 证据与原记录','',f['generalization']]
    evidence={e['id']:e for e in f['evidence']}
    for i,ref in enumerate(a['evidenceRefs'],1):lines.append(f"- 证据 {i}：{evidence.get(ref,{}).get('kind','实验记录')}（工作台可直接打开；精确引用保存在 JSON 中）。")
    lines+=['','原始分析、事实快照与身份保留在配套 JSON；历史报告未改写。']
    return '\n'.join(lines)+'\n'
