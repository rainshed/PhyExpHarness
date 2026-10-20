"""Three linked, deterministic views of frozen plugins, candidates and batches.

Descriptions describe intended capabilities, never evidence of effectiveness.
Round comparisons use acceptance order, independently of candidate ancestry.
"""
import re
import hashlib
import json
from pathlib import Path
from src.evidence.outcomes import outcome_summary


def stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def plugin_key(plugin):
    identity = [plugin['name'], plugin['version'], plugin.get('digest')]
    return 'plugin-' + hashlib.sha256(stable(identity).encode()).hexdigest()


def read_annotations(data):
    path = Path(data) / 'plugin-annotations.json'
    if not path.exists():
        return {}
    entries = json.loads(path.read_text()).get('plugins', [])
    return {plugin_key(p): p for p in entries}


def config_changes(before, after, path='$'):
    """Preserve added/removed/null distinctions; arrays retain their exact order."""
    if stable(before) == stable(after):
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        rows = []
        for key in sorted(before.keys() | after.keys()):
            loc = path + '[' + json.dumps(key, ensure_ascii=False) + ']'
            if key not in before:
                rows.append({'path': loc, 'kind': 'added', 'after': after[key]})
            elif key not in after:
                rows.append({'path': loc, 'kind': 'removed', 'before': before[key]})
            else:
                rows.extend(config_changes(before[key], after[key], loc))
        return rows
    return [{'path': path, 'kind': 'changed', 'before': before, 'after': after}]


def plugin_changes(previous, current):
    if current is None or previous is None:
        return [{'kind': 'unavailable', 'label': '版本记录缺失，无法比较', 'pluginKeys': []}]
    old = {p['name']: p for p in previous['plugins']}
    new = {p['name']: p for p in current['plugins']}
    changes = []
    for name in sorted(old.keys() | new.keys()):
        a, b = old.get(name), new.get(name)
        keys = [plugin_key(p) for p in [a, b] if p]
        keys = list(dict.fromkeys(keys))
        if a is None:
            changes.append({'kind': 'added', 'label': f"新增 {name} {b['version']}", 'pluginKeys': keys})
        elif b is None:
            changes.append({'kind': 'removed', 'label': f"移除 {name} {a['version']}", 'pluginKeys': keys})
        else:
            if plugin_key(a) != plugin_key(b):
                label = f"更新 {name}：{a['version']} → {b['version']}"
                if a['version'] == b['version']:
                    label = f"更新 {name}：版本号仍为 {b['version']}，内容摘要已变化"
                changes.append({'kind': 'updated', 'label': label, 'pluginKeys': keys})
            diffs = config_changes(a.get('config', {}), b.get('config', {}))
            if diffs:
                changes.append({'kind': 'configured', 'label': f'调整 {name} 配置', 'pluginKeys': keys, 'configChanges': diffs})
    # Index shifts from additions/removals are not themselves reorderings.
    common = old.keys() & new.keys()
    before = [p['name'] for p in previous['plugins'] if p['name'] in common]
    after = [p['name'] for p in current['plugins'] if p['name'] in common]
    if before != after:
        changes.append({'kind': 'reordered', 'label': '调整共有插件加载顺序：' + ' → '.join(before) + ' ⇒ ' + ' → '.join(after),
                        'pluginKeys': [plugin_key(new[name]) for name in after]})
    if not changes:
        same = previous['bundleId'] == current['bundleId']
        changes.append({'kind': 'unchanged' if same else 'other', 'label': '无变化，复测同一执行版本' if same else '插件无变化；其他冻结执行内容不同', 'pluginKeys': []})
    return changes


def build_tables(candidates, batches, trials, campaign=None, annotations=None, batch_id=None):
    campaign, annotations = campaign or {}, annotations or {}
    candidates = sorted(candidates, key=lambda c: (c.get('createdAt', 0), c['id']))
    batches = sorted(batches, key=lambda b: b['round'])
    batch_candidates={b['id']:b['candidateId'] for b in batches}
    trials=[{**t,'candidateId':t.get('candidateId',batch_candidates.get(t.get('batchId')))} for t in trials]
    labels = {c['id']: f'H{i}' for i, c in enumerate(candidates)}
    lookup = {c['id']: c for c in candidates}
    if batch_id:
        focus = next(b for b in batches if b['id'] == batch_id)
        batches = [b for b in batches if b['round'] <= focus['round']]
        # Include earlier candidates and ancestors, never candidates introduced later.
        needed = {b['candidateId'] for b in batches}
        for id in list(needed):
            seen = set()
            while id in lookup and id not in seen:
                seen.add(id); needed.add(id); id = lookup[id].get('parentId')
        candidates = [c for c in candidates if c['id'] in needed or c.get('createdAt', float('inf')) <= focus.get('acceptedAt', -1)]
    plugin_rows, version_rows, round_rows = {}, [], []
    for c in candidates:
        members = []
        for order, p in enumerate(c['plugins'], 1):
            key = plugin_key(p); manifest = p.get('manifest', {})
            note = annotations.get(key, {})
            summary = note.get('functionSummary') or manifest.get('functionSummary') or manifest.get('purpose') or '功能说明尚未提供'
            source = note.get('source') or {'kind': 'manifest', 'label': '冻结插件清单声明；不代表效果已验证'}
            if key not in plugin_rows:
                plugin_rows[key] = {'id': key, 'name': p['name'], 'version': p['version'], 'digest': p.get('digest'),
                    'candidateId': c['id'], 'entry': p.get('entry'),
                    'displayName': note.get('displayName') or manifest.get('displayName') or p['name'],
                    'functionSummary': summary, 'mechanism': note.get('mechanism') or manifest.get('mechanism') or
                        ('声明接口：' + '、'.join(map(str, manifest.get('intervenes', []))) if manifest.get('intervenes') else '实现方式尚未说明'),
                    'descriptionSource': source, 'declaration': manifest, 'usedBy': []}
            plugin_rows[key]['usedBy'].append(c['id'])
            members.append({'pluginId': key, 'order': order, 'config': p.get('config', {}), 'entry': p.get('entry')})
        parent = c.get('parentId')
        version_rows.append({'id': c['id'], 'label': labels[c['id']], 'description': c.get('description', ''),
            'displayName': labels[c['id']]+' · '+(c.get('displayName') or ('原始基线' if not members else '、'.join(plugin_rows[m['pluginId']]['displayName'] for m in members)+'版')),
            'bundleId': c['bundleId'], 'parentId': parent, 'parentLabel': labels.get(parent), 'plugins': members,
            'final': c['id'] == campaign.get('finalCandidateId'), 'retained': c['id'] == campaign.get('retainedCandidateId'),
            'assemblyStatus': c.get('check', {}).get('status', 'unknown'),
            'taskEvaluation':outcome_summary([t for t in trials if t['candidateId']==c['id'] and (not batch_id or t['batchId'] in {b['id'] for b in batches})],campaign.get('config',{}).get('tasks'),campaign.get('config'))})
    names={v['id']:v['displayName'] for v in version_rows}
    previous = None
    for b in batches:
        selected = lookup.get(b['candidateId'])
        previous_candidate = lookup.get(previous['candidateId']) if previous else None
        changes = plugin_changes(previous_candidate, selected) if previous else [
            {'kind': 'initial', 'label': '首轮，无上一轮比较对象', 'pluginKeys': []}]
        results = [{k: t.get(k) for k in ['id', 'task', 'repeat', 'state', 'score', 'stopReason', 'fixture', 'startedAt', 'finishedAt', 'comparisonContext', 'failure', 'scoringStatus', 'resultLabel', 'completionLabel', 'taskAssessment', 'effectiveConditions', 'conditionsRequired', 'executionSettings']}
                   for t in trials if t['batchId'] == b['id']]
        round_rows.append({'id': b['id'], 'round': b['round'], 'candidateId': b['candidateId'],
            'versionName': names.get(b['candidateId'],'版本缺失'), 'testSettings':b.get('testSettings'),
            'versionLabel': labels.get(b['candidateId'], '版本缺失'), 'previousRound': previous['round'] if previous else None,
            'previousCandidateId': previous['candidateId'] if previous else None,
            'previousVersionLabel': labels.get(previous['candidateId']) if previous else None,
            'changes': changes, 'tasks': b['tasks'], 'repeats': b['repeats'], 'state': b['state'],
            'results': results, 'focus': b['id'] == batch_id,'taskEvaluation':outcome_summary(results,b['tasks'],campaign.get('config'))})
        previous = b
    return {'schemaVersion': 2, 'plugins': list(plugin_rows.values()), 'versions': version_rows, 'rounds': round_rows,
            'groups': group_rounds(round_rows), 'focusBatchId': batch_id, 'comparisonBasis': '按受理轮次与上一轮比较；版本父子关系单独记录。',
            'descriptionNotice': '插件表描述能力与设计用途；实际作用和效果见有证据引用的轨迹分析。'}


def cell(value):
    # Untrusted model text must not create links, raw HTML or extra table rows.
    text = str(value if value is not None else '—')
    for a, b in [('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'), ('|', '&#124;'), ('[', '&#91;'), (']', '&#93;'), ('`', '&#96;')]:
        text = text.replace(a, b)
    return text.replace('\n', '<br>').replace('\r', '')


def completion_lines(stats):
    rate=lambda value:'待定' if value is None else f'{value:.1%}'
    total=stats['total']
    lines=[f"所选任务等权成功率：{rate(stats['macroSuccessRate'])}；覆盖 {stats['coveredTasks']}/{stats['taskCount']} 个任务。",
           f"逐次通过 {total['passed']}/{total['eligible']}，其中按规则计 0：{total['derivedFailures']} 次；未计分外部故障 {total['external_failure']}，取消 {total['cancelled']}，待定 {total['pending']}，待归因 {total['unresolved']}。"]
    for task,row in stats['byTask'].items():
        lines.append(f"- {task}：成功率 {rate(row['successRate'])}（{row['passed']}/{row['eligible']}）；按规则计 0 {row['derivedFailures']}；未计分外部故障 {row['external_failure']}；取消 {row['cancelled']}；待定 {row['pending']}；待归因 {row['unresolved']}。")
    if total['unresolved']:lines.append('待归因按失败计的逐次保守成功率：'+rate(total['conservativeSuccessRate'])+'。')
    return lines


def group_rounds(rounds):
    """Display-only grouping; preserve every result and accepted round."""
    groups=[]
    for row in rounds:
        contexts={}
        for result in row['results']:
            context=result.get('comparisonContext')
            if not context or result.get('stopReason') in ['trial_deadline','campaign_deadline','user_stop']:
                contexts=None;break
            context=dict(context)
            if context.get('runnerExecutionManifest'):context.pop('runnerImageId',None)
            contexts.setdefault(result['task'],set()).add(stable(context))
        comparable=bool(contexts) and all(len(v)==1 for v in contexts.values()) and row['state']=='finished'
        signature=stable([row['candidateId'],sorted(row['tasks']),row.get('testSettings'),
            {k:sorted(v) for k,v in contexts.items()}]) if comparable else row['id']
        if groups and groups[-1]['signature']==signature and groups[-1]['lastRound']+1==row['round']:
            g=groups[-1];g['rounds'].append(row);g['lastRound']=row['round'];g['results'].extend(row['results'])
        else:
            groups.append({'id':row['id'],'signature':signature,'firstRound':row['round'],'lastRound':row['round'],
                'candidateId':row['candidateId'],'versionName':row['versionName'],'changes':row['changes'],
                'rounds':[row],'results':list(row['results'])})
    return [{k:v for k,v in g.items() if k!='signature'} for g in groups]


def readable_text(value,tables):
    """Presentation only: retain untouched source text in the report JSON."""
    if isinstance(value,list):return [readable_text(v,tables) for v in value]
    if isinstance(value,dict):return {k:readable_text(v,tables) for k,v in value.items()}
    if not isinstance(value,str):return value
    for v in tables['versions']:
        value=value.replace(v['id'],v['displayName']).replace(v['bundleId'],v['displayName']+'的冻结内容')
    for p in tables['plugins']:
        if p.get('digest'):value=value.replace(p['digest'],p['displayName']+'的源码摘要')
    value=re.sub(r'(candidate|campaign|batch|trial|report|export|evidence|lease|launch)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',
                 lambda m:{'candidate':'相关执行版本','campaign':'前序活动','export':'独立项目','report':'原报告','evidence':'对应证据'}.get(m[1],'对应记录'),value)
    return re.sub(r'(?<![a-zA-Z0-9])[0-9a-f]{64}(?![a-zA-Z0-9])','已归档的内容摘要',value)


def markdown_tables(tables):
    lines=['## 插件表','','插件说明描述预期能力，实际作用见轨迹分析。','',
        '| 插件 | 实现方式 | 功能说明 |','|---|---|---|']
    plugins={p['id']:p for p in tables['plugins']}
    anchors={key:f'plugin-{i+1}' for i,key in enumerate(plugins)}
    versions={v['id']:v for v in tables['versions']}
    for p in plugins.values():
        lines.append(f"| <a id=\"{anchors[p['id']]}\"></a>{cell(p['displayName'])} · {cell(p['version'])} | {cell(p['mechanism'])} | {cell(p['functionSummary'])} |")
    if not plugins:lines.append('| 无额外执行插件 | 固定基线 | 使用原始执行能力 |')
    lines+=['','## 执行版本表','','| 执行版本 | 来源 | 插件组合（加载顺序） | 状态 |','|---|---|---|---|']
    for v in tables['versions']:
        members='<br>'.join(f"{m['order']}. [{cell(plugins[m['pluginId']]['displayName'])} {cell(plugins[m['pluginId']]['version'])}](#{anchors[m['pluginId']]})" for m in v['plugins']) or '无额外插件'
        parent=versions.get(v['parentId'],{}).get('displayName','起点' if not v['parentId'] else '来源记录缺失')
        lines.append(f"| <a id=\"{v['label']}\"></a>{cell(v['displayName'])} | {cell(parent)} | {members} | {'最终版本' if v['final'] else '当前保留' if v['retained'] else '候选'} |")
    lines+=['','## 实验轮次表','','连续同版本、可比条件的复测合并展示；所有评分保留。','',
        '| 轮次 | 执行版本 | 插件变化 | 测试安排 | 任务完成与官方评分（逐次） |','|---|---|---|---|---|']
    for g in tables.get('groups',group_rounds(tables['rounds'])):
        first=g['rounds'][0];span=str(g['firstRound']) if g['firstRound']==g['lastRound'] else f"{g['firstRound']}–{g['lastRound']}"
        changes='；'.join(cell(d['label']) for d in g['changes'])
        if len(g['rounds'])>1:changes+=f"；随后复测 {len(g['rounds'])-1} 轮"
        scores='；'.join(f"第 {r['round']} 轮："+' / '.join(cell(t['task'])+': '+cell(t.get('completionLabel') or t.get('resultLabel') or ('未评分' if t['score'] is None else t['score'])) for t in r['results']) for r in g['rounds'])
        lines.append(f"| 第 {span} 轮 | {cell(g['versionName'])} | {changes} | {len(first['tasks'])} 任务 × {first['repeats']} 次 / 轮 | {scores or '尚无结果'} |")
    lines+=['','### 插件配置','']
    for v in tables['versions']:
        for m in v['plugins']:
            lines.append(f"- {cell(v['displayName'])} / {cell(plugins[m['pluginId']]['displayName'])}：{cell(stable(m['config']))}。")
    lines+=['','精确身份、原始分析与事实快照保存在配套 JSON 记录中。']
    return lines
