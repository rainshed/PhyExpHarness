"""Inventory and remove only Campaign-owned files and unreferenced content.

No glob-based global garbage collection. The saved plan survives partial removal;
all paths are validated again at use time, without following directory symlinks.
"""
import json
import os
import re
import shutil
from pathlib import Path

from .store import TABLES, Refused


def safe_path(data, value):
    path = Path(value)
    if not path.is_absolute():
        path = data / path
    if not path.is_relative_to(data) and '..' not in path.parts:
        # macOS /var and /tmp are aliases outside the managed root. Normalize
        # only the root alias; links INSIDE the data directory remain forbidden.
        for parent in path.parents:
            if parent.resolve()==data:
                path=data/path.relative_to(parent);break
    if '..' in path.parts or not path.is_relative_to(data) or path == data:
        raise Refused('清理路径超出活动数据目录：' + str(path))
    for parent in [path, *path.parents]:
        if parent == data:
            break
        if parent.is_symlink():
            raise Refused('清理路径经过符号链接：' + str(parent))
    return path


def child(data, root, value):
    path = safe_path(data, value)
    parent = data / root
    if not path.is_relative_to(parent) or path == parent:
        raise Refused('文件归属与受管目录不匹配：' + str(path))
    return parent / path.relative_to(parent).parts[0]


def read_json(path):
    return json.loads(path.read_text())


def walk(root):
    """Do not traverse links, including links created in a generated workspace."""
    if not root.exists():
        return
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            path = Path(base) / name
            if not path.is_symlink():
                yield path


class Inventory:
    def __init__(self, service, campaign, db):
        self.service, self.data, self.campaign = service, service.data, campaign
        self.rows = {table: service.store._list(db, table) for table in TABLES}
        self.own = {t: [r for r in rows if r.get('campaignId', r['id']) == campaign]
                    for t, rows in self.rows.items()}
        self.paths, self.shared, self.keep = set(), set(), set()
        self.blockers, self.rewrites = [], []
        self.bundles = set()
        self.artifact_inodes = {}
        artifacts = safe_path(self.data,self.data/'artifacts/sha256')
        for file in artifacts.glob('*/*'):
            safe_path(self.data,file)
            info=file.stat()
            self.artifact_inodes[(info.st_dev,info.st_ino)] = file

    def add(self, value, *, shared=False):
        path = safe_path(self.data, value)
        (self.shared if shared else self.paths).add(path)
        return path

    def bundle(self, value):
        root = child(self.data, 'objects/sha256', value)
        paths = {root}
        manifest = root / 'bundle.json'
        if not root.exists():
            return paths
        raw = read_json(safe_path(self.data, manifest))
        if raw.get('schemaVersion', 1) not in (1, 2):
            raise Refused('未知执行组合格式：' + str(root))
        references = [raw.get('adapter'), raw.get('dependencies'),
                      *[p.get('object') for p in raw.get('plugins', [])]]
        layout = self.data / 'objects/legacy-compositions' / (root.name + '.json')
        if layout.exists():
            projection = read_json(safe_path(self.data, layout))
            paths.add(layout)
            references += [projection['adapter'], projection['dependencies'],
                           *[p['object'] for p in projection['plugins']]]
            for record in projection['files'].values():
                blob = safe_path(self.data, record['blob'])
                if blob.parent != self.data / 'objects/blobs':
                    raise Refused('未知历史内容布局：' + str(layout))
                paths.add(blob)
        for ref in filter(None, references):
            if not re.fullmatch('[0-9a-f]{64}', ref):
                raise Refused('无效的共享对象引用：' + str(root))
            paths.add(safe_path(self.data, self.data / 'objects/sha256' / ref))
        if raw.get('knowledgePackId'):
            paths.add(child(self.data, 'knowledge-packs', self.data / 'knowledge-packs' / raw['knowledgePackId']))
        paths.add(self.data / 'locks' / (root.name + '.lock'))
        return paths

    def shared_for(self, campaign):
        paths, bundle_roots = set(), set()
        for row in self.rows['candidates']:
            if row['campaignId'] == campaign:
                bundle_roots.add(row['bundlePath'])
        for row in self.rows['owned_artifacts']:
            if row['campaignId'] == campaign and row['kind'] == 'bundle':
                bundle_roots.add(row['path'])
            if row['campaignId'] == campaign and row['kind'] == 'object':
                paths.add(child(self.data,'objects/sha256',row['path']))
        # Old check-only/failed builds may have a receipt but no Candidate row.
        checks = safe_path(self.data, self.data / 'campaigns' / campaign / 'checks')
        for file in checks.glob('*/assembly.json'):
            raw = read_json(safe_path(self.data, file))
            if raw.get('bundleId'):
                bundle_roots.add(str(self.data / 'objects/sha256' / raw['bundleId']))
        bundle_roots={str(child(self.data,'objects/sha256',root)) for root in bundle_roots}
        for root in bundle_roots:
            paths.update(self.bundle(root))
        config = next(c for c in self.rows['campaigns'] if c['id'] == campaign)['config']
        if config.get('knowledgePackId'):
            paths.add(child(self.data, 'knowledge-packs', self.data / 'knowledge-packs' / config['knowledgePackId']))
        composition = config.get('metaComposition', {})
        if composition.get('id'):
            root = child(self.data, 'meta-compositions', self.data / 'meta-compositions' / composition['id'])
            paths.update([root, self.data / 'cache/meta-runtimes' / root.name])
            if root.exists():
                raw = read_json(safe_path(self.data, root / 'manifest.json'))
                if raw.get('version') == 'meta-composition-v2':
                    for sha in raw['files'].values():
                        if not re.fullmatch('[0-9a-f]{64}', sha):
                            raise Refused('无效的 Meta 内容引用')
                        paths.add(self.data / 'meta-objects/sha256' / sha)
                elif raw.get('version') != 'meta-composition-v1':
                    raise Refused('未知 Meta 组合格式：' + str(root))
        for row in self.rows['evidence']:
            if row['campaignId'] == campaign:
                path=safe_path(self.data,row['path'])
                canonical=self.data/'artifacts/sha256'/row['sha256'][:2]/row['sha256']
                if path==canonical:paths.add(path)
                else:paths.add(child(self.data, 'evidence', path))
        for row in self.rows['source_adoptions']:
            if row['campaignId'] == campaign:
                paths.add(child(self.data, 'evidence', self.data / 'evidence' / row['sha256']))
                canonical=self.data/'artifacts/sha256'/row['sha256'][:2]/row['sha256']
                if canonical.exists():paths.add(canonical)
        # Native file views and archived Trials may point to shared bodies only
        # through hard links, with no Evidence row for each original log chunk.
        roots=[self.data/'campaigns'/campaign]
        roots += [Path(r['output']) for t in ('trials','reference_runs') for r in self.rows[t]
                  if r['campaignId']==campaign and r.get('output')]
        for root in roots:
            root=safe_path(self.data,root)
            for file in walk(root):
                info=file.stat();body=self.artifact_inodes.get((info.st_dev,info.st_ino))
                if body:paths.add(body)
        return paths, bundle_roots

    def dependencies(self):
        names = {c['id']: c['config'].get('name') or c['id'] for c in self.rows['campaigns']}
        for row in self.rows['source_adoptions']:
            if row['campaignId'] != self.campaign and row['source']['sourceCampaignId'] == self.campaign:
                self.blockers.append({'kind': 'historical_source', 'campaignId': row['campaignId'],
                    'message': '活动“' + names.get(row['campaignId'], row['campaignId']) + '”已纳入此活动的历史材料。',
                    'sourceId': row['source']['sourceId'], 'adoptionId': row['id']})

    def files(self):
        self.add(self.data / 'campaigns' / self.campaign)
        for row in self.own['trials'] + self.own['reference_runs']:
            if row.get('output'):
                self.add(child(self.data, 'trials', row['output']))
            if row.get('launchId'):
                self.add(child(self.data, 'trials', self.data / 'trials' / row['launchId']))
                self.add(self.data / 'trials' / (row['launchId'] + '.supervisor.log'))
                self.add(self.data / 'trials' / (row['launchId'] + '.supervisor.log.segments'))
        for row in self.own['reports']:
            self.add(self.data / 'reports' / row['id'])
            if row.get('markdownPath'):
                self.add(child(self.data, 'reports', row['markdownPath']))
        for row in self.own['exports']:
            self.add(self.data / 'exports' / row['id'])
            for key in ('path', 'archive'):
                if row.get(key):self.add(child(self.data, 'exports', row[key]))
            if row.get('validationEvidence'):
                self.add(child(self.data, 'export-checks', row['validationEvidence']))
        for row in self.own['owned_artifacts']:
            if row['kind'] not in ('bundle','object'):
                root = {'export': 'exports', 'export_check': 'export-checks','report':'reports'}.get(row['kind'])
                if not root:raise Refused('未知生成文件归属：' + row['kind'])
                self.add(child(self.data, root, row['path']))
        recovery = self.data / 'result-recoveries'
        safe_path(self.data, recovery)
        for file in recovery.glob('*'):
            raw = read_json(safe_path(self.data, file))
            if raw.get('campaignId') == self.campaign:self.add(file)
        export_ids = {r['id'] for r in self.own['exports']}
        checks = self.data / 'export-checks'
        safe_path(self.data, checks)
        for directory in checks.glob('*'):
            safe_path(self.data, directory)
            if directory in self.paths:continue
            proof = directory / 'validation.json'
            if proof.exists():
                if read_json(safe_path(self.data, proof)).get('exportId') in export_ids:self.add(directory)
            elif directory.is_dir() and not any(r['path'] == str(directory) for r in self.rows['owned_artifacts']):
                self.blockers.append({'kind':'unowned_export_check', 'path':str(directory),
                    'message':'旧导出检查缺少归属记录，请先核实并处理此目录：' + str(directory)})

    def mixed_files(self):
        tokens = {self.campaign, *[r['id'] for t, rows in self.own.items() for r in rows]}
        # Migration snapshots contain the whole database. Never rewrite/delete a
        # mixed backup as a side effect of removing one Campaign.
        excluded = {'campaigns','trials','reports','exports','export-checks','evidence','artifacts','cache','meta-objects','meta-compositions','knowledge-packs','objects','deletions',
                    'ui','reference-native','locks','runner-runtime-locks','task-runtime-locks','runtime-image-proofs'}
        for directory in self.data.iterdir():
            if directory.name in excluded or directory.is_symlink():continue
            if directory.is_dir():
                for file in walk(directory):
                    if file.name == 'control-before.sqlite' or file.suffix in ('.sqlite','.sqlite3','.db'):
                        self.blockers.append({'kind':'mixed_backup','path':str(file),
                            'message':'受管目录中存在混合数据库备份，请先移出或明确处理：' + str(file)})
            elif directory.name not in ('control.sqlite','provider-settings.sqlite') and directory.suffix in ('.sqlite','.sqlite3','.db'):
                self.blockers.append({'kind':'mixed_backup','path':str(directory),
                    'message':'受管目录中存在混合数据库备份，请先移出或明确处理：' + str(directory)})
        annotations = self.data / 'plugin-annotations.json'
        if annotations.exists():
            from src.reporting.tables import plugin_key
            value = read_json(safe_path(self.data, annotations))
            own = {plugin_key(p) for c in self.own['candidates'] for p in c.get('plugins', [])}
            keep = {plugin_key(p) for c in self.rows['candidates'] if c['campaignId'] != self.campaign for p in c.get('plugins', [])}
            remaining = [p for p in value.get('plugins', []) if plugin_key(p) not in own - keep]
            if remaining != value.get('plugins', []):
                self.rewrites.append({'path':str(annotations),'kind':'annotations','remove':sorted(own-keep)})
        log = self.data / 'supervisor-errors.jsonl'
        if log.exists():
            safe_path(self.data, log)
            lines = log.read_text().splitlines(keepends=True)
            remaining = [line for line in lines if not any(token in line for token in tokens)]
            if remaining != lines:self.rewrites.append({'path':str(log),'kind':'diagnostics','remove':sorted(tokens)})

    def build(self):
        self.dependencies()
        try:
            self.files()
            self.shared, self.bundles = self.shared_for(self.campaign)
            for c in self.rows['campaigns']:
                if c['id'] != self.campaign:self.keep.update(self.shared_for(c['id'])[0])
            self.mixed_files()
            for path in self.paths | self.shared | self.keep:safe_path(self.data,path)
            # A corrupted ownership record must never claim another activity's directory.
            for table, fields, root in [('trials',('output',),'trials'),('reference_runs',('output',),'trials'),
                                        ('reports',('markdownPath',),'reports'),('exports',('path','archive'),'exports'),
                                        ('exports',('validationEvidence',),'export-checks')]:
                for row in self.rows[table]:
                    if row['campaignId'] == self.campaign:continue
                    for field in fields:
                        if row.get(field) and child(self.data,root,row[field]) in self.paths:
                            raise Refused('专属文件也被其他活动引用：' + row[field])
            for row in self.rows['owned_artifacts']:
                if row['campaignId'] != self.campaign and Path(row['path']) in self.paths:
                    raise Refused('生成目录也被其他活动引用：' + row['path'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.blockers.append({'kind':'storage','message':str(error)})
        targets = self.paths | (self.shared - self.keep)
        targets = sorted(p for p in targets if not any(parent in targets for parent in p.parents))
        return {'paths':[str(p.relative_to(self.data)) for p in targets],
                'rewrites':self.rewrites,'blockers':self.blockers,
                'sharedRetained':len(self.shared & self.keep),
                'trialIds':[r['id'] for r in self.own['trials']+self.own['reference_runs']],
                'counts':{t:len(rows) for t,rows in self.own.items()},
                'bundleIds':[Path(p).name for p in self.bundles if Path(p) not in self.keep]}


def remove_path(data, value):
    path = safe_path(data, value)
    if path.is_dir():
        # rmtree unlinks internal symlinks and does not descend through them.
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def rewrite(data, entry):
    path = safe_path(data, entry['path'])
    if not path.exists():return
    if entry['kind']=='annotations':
        from src.reporting.tables import plugin_key
        value=read_json(path)
        content=json.dumps({**value,'plugins':[p for p in value['plugins'] if plugin_key(p) not in entry['remove']]},ensure_ascii=False)+'\n'
    else:
        content=''.join(line for line in path.read_text().splitlines(keepends=True) if not any(token in line for token in entry['remove']))
    temp = path.with_name(path.name + '.deleting')
    safe_path(data,temp)
    with temp.open('w') as stream:
        stream.write(content);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
