"""Inventory and remove only Campaign-owned files and unreferenced content.

No glob-based global garbage collection. The saved plan survives partial removal;
all paths are validated again at use time, without following directory symlinks.
"""
import json
import itertools
import os
import re
import shutil
import stat
from pathlib import Path

from .store import TABLES, Refused


def safe_path(data, value, *, checked=None):
    path = Path(value)
    if checked is not None and path in checked:return path
    if not path.is_absolute():
        path = data / path
    inside = path.parts[:len(data.parts)] == data.parts
    if not inside and '..' not in path.parts:
        # macOS /var and /tmp are aliases outside the managed root. Normalize
        # only the root alias; links INSIDE the data directory remain forbidden.
        for parent in path.parents:
            if parent.resolve()==data:
                path=data/path.relative_to(parent);break
    if '..' in path.parts or path.parts[:len(data.parts)] != data.parts or path == data:
        raise Refused('清理路径超出活动数据目录：' + str(path))
    validated = []
    for parent in itertools.chain((path,),path.parents):
        if parent == data or checked is not None and parent in checked:
            break
        if parent.is_symlink():
            raise Refused('清理路径经过符号链接：' + str(parent))
        validated.append(parent)
    if checked is not None:checked.update(validated)
    return path


def child(data, root, value, *, checked=None):
    path = safe_path(data, value, checked=checked)
    parent = data / root
    if path.parts[:len(parent.parts)] != parent.parts or path == parent:
        raise Refused('文件归属与受管目录不匹配：' + str(path))
    return parent / path.parts[len(parent.parts)]


def read_json(path):
    return json.loads(path.read_text())


def walk(root):
    """Do not traverse links, including links created in a generated workspace."""
    for path, _ in walk_stats(root):yield path


def walk_stats(root):
    """Read each directory entry once; never follow a generated symlink."""
    if not root.exists():
        return
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_symlink():continue
            if entry.is_dir(follow_symlinks=False):yield from walk_stats(Path(entry.path))
            else:yield Path(entry.path), entry.stat(follow_symlinks=False)


class Inventory:
    def __init__(self, service, campaign, db):
        self.service, self.data, self.campaign = service, service.data, campaign
        # Ownership needs identifiers and references, not report bodies, request
        # transcripts or large facts snapshots from every activity.
        fields = {'campaigns':('config',), 'candidates':('bundlePath','plugins'),
                  'trials':('output','launchId'), 'reference_runs':('output','launchId'),
                  'reports':('markdownPath',), 'exports':('path','archive','validationEvidence'),
                  'owned_artifacts':('kind','path'), 'evidence':('path','sha256'),
                  'source_adoptions':('sha256','source')}
        self.rows = {}
        for table in TABLES:
            projection = "'id',id,'campaignId',campaign" + ''.join(
                f",'{field}',json_extract(data,'$.{field}')" for field in fields.get(table,()))
            self.rows[table] = [{k:v for k,v in json.loads(row[0]).items() if v is not None}
                                for row in db.execute(f'SELECT json_object({projection}) FROM {table}')]
        self.own = {t: [r for r in rows if r.get('campaignId', r['id']) == campaign]
                    for t, rows in self.rows.items()}
        self.paths, self.shared, self.keep = set(), set(), set()
        self.blockers, self.rewrites = [], []
        self.bundles = set()
        self.checked_paths = set()
        self.bundle_paths = {}
        self.artifact_inodes = {}
        self.artifact_links = {}
        self.own_links = None
        artifacts = self.checked(self.data/'artifacts/sha256')
        for directory in artifacts.glob('*'):
            self.checked(directory)
            if not directory.is_dir():continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_symlink():raise Refused('清理路径经过符号链接：' + entry.path)
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        path=Path(entry.path)
                        self.artifact_inodes[(info.st_dev,info.st_ino)] = path
                        self.artifact_links[path] = info.st_nlink

    def checked(self, value):
        # Only this inventory pass caches ancestor checks. Destructive actions
        # always call safe_path afresh, including after a failed/restarted job.
        return safe_path(self.data,value,checked=self.checked_paths)

    def child(self, root, value):
        return child(self.data,root,value,checked=self.checked_paths)

    def build_cache(self, inputs):
        from src.execution.bundle.manifest import canonical, digest
        key = digest(canonical(inputs))
        return {self.checked(self.data/'cache/project-builds'/(key+suffix)) for suffix in ('.json','.tar','.lock')}

    def add(self, value, *, shared=False):
        path = self.checked(value)
        (self.shared if shared else self.paths).add(path)
        return path

    def bundle(self, value):
        root = self.child('objects/sha256', value)
        if root in self.bundle_paths:return self.bundle_paths[root]
        paths = {root}
        manifest = root / 'bundle.json'
        if not root.exists():
            return paths
        raw = read_json(self.checked(manifest))
        version = raw.get('schemaVersion', 1)
        if version not in (1, 2, 3) or version == 3 and raw.get('kind') != 'harness-composition-v3':
            raise Refused('未知执行组合格式：' + str(root))
        if version == 3:
            references = [raw['adapter'],raw['sources'],raw['artifact']]
            if raw.get('buildReceipt',{}).get('inputs'):
                paths.update(self.build_cache(raw['buildReceipt']['inputs']))
        else:
            references = [raw.get('adapter'), raw.get('dependencies'),
                          *[p.get('object') for p in raw.get('plugins', [])]]
        layout = self.data / 'objects/legacy-compositions' / (root.name + '.json')
        if layout.exists():
            projection = read_json(self.checked(layout))
            paths.add(layout)
            references += [projection['adapter'], projection['dependencies'],
                           *[p['object'] for p in projection['plugins']]]
            for record in projection['files'].values():
                blob = self.checked(record['blob'])
                if blob.parent != self.data / 'objects/blobs':
                    raise Refused('未知历史内容布局：' + str(layout))
                paths.add(blob)
        for ref in filter(None, references):
            if not re.fullmatch('[0-9a-f]{64}', ref):
                raise Refused('无效的共享对象引用：' + str(root))
            paths.add(self.checked(self.data / 'objects/sha256' / ref))
        if raw.get('knowledgePackId'):
            paths.add(self.child('knowledge-packs', self.data / 'knowledge-packs' / raw['knowledgePackId']))
        paths.add(self.data / 'locks' / (root.name + '.lock'))
        self.bundle_paths[root] = paths
        return paths

    def shared_for(self, campaign, *, views=True):
        paths, bundle_roots = set(), set()
        for row in self.rows['candidates']:
            if row['campaignId'] == campaign:
                bundle_roots.add(row['bundlePath'])
        for row in self.rows['owned_artifacts']:
            if row['campaignId'] == campaign and row['kind'] == 'bundle':
                bundle_roots.add(row['path'])
            if row['campaignId'] == campaign and row['kind'] == 'object':
                paths.add(self.child('objects/sha256',row['path']))
            if row['campaignId'] == campaign and row['kind'] == 'project_build':
                path=self.checked(row['path'])
                if path.parent != self.data/'cache/project-builds' or not re.fullmatch(r'[0-9a-f]{64}\.(json|tar|lock)',path.name):
                    raise Refused('未知构建缓存归属：' + str(path))
                paths.add(path)
        # Old check-only/failed builds may have a receipt but no Candidate row.
        checks = self.checked(self.data / 'campaigns' / campaign / 'checks')
        for file in checks.glob('*/assembly.json'):
            raw = read_json(self.checked(file))
            if raw.get('bundleId'):
                bundle_roots.add(str(self.data / 'objects/sha256' / raw['bundleId']))
            if raw.get('build',{}).get('inputs'):
                paths.update(self.build_cache(raw['build']['inputs']))
        bundle_roots={str(self.child('objects/sha256',root)) for root in bundle_roots}
        for root in bundle_roots:
            paths.update(self.bundle(root))
        config = next(c for c in self.rows['campaigns'] if c['id'] == campaign)['config']
        if config.get('knowledgePackId'):
            paths.add(self.child('knowledge-packs', self.data / 'knowledge-packs' / config['knowledgePackId']))
        composition = config.get('metaComposition', {})
        if composition.get('id'):
            root = self.child('meta-compositions', self.data / 'meta-compositions' / composition['id'])
            paths.update([root, self.data / 'cache/meta-runtimes' / root.name])
            if root.exists():
                raw = read_json(self.checked(root / 'manifest.json'))
                if raw.get('version') == 'meta-composition-v2':
                    for sha in raw['files'].values():
                        if not re.fullmatch('[0-9a-f]{64}', sha):
                            raise Refused('无效的 Meta 内容引用')
                        paths.add(self.data / 'meta-objects/sha256' / sha)
                elif raw.get('version') != 'meta-composition-v1':
                    raise Refused('未知 Meta 组合格式：' + str(root))
        for row in self.rows['evidence']:
            if row['campaignId'] == campaign:
                path=self.checked(row['path'])
                canonical=self.data/'artifacts/sha256'/row['sha256'][:2]/row['sha256']
                if path==canonical:paths.add(path)
                else:paths.add(self.child('evidence', path))
        for row in self.rows['source_adoptions']:
            if row['campaignId'] == campaign:
                paths.add(self.child('evidence', self.data / 'evidence' / row['sha256']))
                canonical=self.data/'artifacts/sha256'/row['sha256'][:2]/row['sha256']
                if canonical.exists():paths.add(canonical)
        if views:paths.update(self.view_bodies(campaign))
        return paths, bundle_roots

    def view_bodies(self, campaign):
        # Native file views and archived Trials may point to shared bodies only
        # through hard links, with no Evidence row for each original log chunk.
        roots=[self.data/'campaigns'/campaign]
        roots += [Path(r['output']) for t in ('trials','reference_runs') for r in self.rows[t]
                  if r['campaignId']==campaign and r.get('output')]
        if campaign==self.campaign:self.own_links={}
        for root in dict.fromkeys(roots):
            root=self.checked(root)
            for file, info in walk_stats(root):
                body=self.artifact_inodes.get((info.st_dev,info.st_ino))
                if body:
                    if campaign==self.campaign:self.own_links[body]=self.own_links.get(body,0)+1
                    yield body

    def retained(self, targets):
        keep=set()
        others=[c['id'] for c in self.rows['campaigns'] if c['id']!=self.campaign]
        for campaign in others:keep.update(self.shared_for(campaign,views=False)[0])
        # Most bodies are private to the deleted activity. Count its links once
        # and search other file views only for bodies with additional links.
        # Unknown extra links remain in the plan and still fail the final purge.
        if self.own_links is None:
            for _ in self.view_bodies(self.campaign):pass
        needed={p for p in targets-keep if self.artifact_links.get(p,0)>self.own_links.get(p,0)+1}
        for campaign in others:
            if not needed:break
            for body in self.view_bodies(campaign):
                if body in needed:
                    keep.add(body);needed.remove(body)
                    if not needed:break
        return keep

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
                self.add(self.child('trials', row['output']))
            if row.get('launchId'):
                self.add(self.child('trials', self.data / 'trials' / row['launchId']))
                self.add(self.data / 'trials' / (row['launchId'] + '.supervisor.log'))
                self.add(self.data / 'trials' / (row['launchId'] + '.supervisor.log.segments'))
        for row in self.own['reports']:
            self.add(self.data / 'reports' / row['id'])
            if row.get('markdownPath'):
                self.add(self.child('reports', row['markdownPath']))
        for row in self.own['exports']:
            self.add(self.data / 'exports' / row['id'])
            for key in ('path', 'archive'):
                if row.get(key):self.add(self.child('exports', row[key]))
            if row.get('validationEvidence'):
                self.add(self.child('export-checks', row['validationEvidence']))
        for row in self.own['owned_artifacts']:
            if row['kind'] == 'project_build_temp':
                self.add(self.child('cache/project-builds',row['path']))
            elif row['kind'] not in ('bundle','object','project_build'):
                root = {'export': 'exports', 'export_check': 'export-checks','report':'reports'}.get(row['kind'])
                if not root:raise Refused('未知生成文件归属：' + row['kind'])
                self.add(self.child(root, row['path']))
        recovery = self.data / 'result-recoveries'
        self.checked(recovery)
        for file in recovery.glob('*'):
            raw = read_json(self.checked(file))
            if raw.get('campaignId') == self.campaign:self.add(file)
        export_ids = {r['id'] for r in self.own['exports']}
        checks = self.data / 'export-checks'
        self.checked(checks)
        for directory in checks.glob('*'):
            self.checked(directory)
            if directory in self.paths:continue
            proof = directory / 'validation.json'
            if proof.exists():
                if read_json(self.checked(proof)).get('exportId') in export_ids:self.add(directory)
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
            value = read_json(self.checked(annotations))
            own = {plugin_key(p) for c in self.own['candidates'] for p in c.get('plugins', [])}
            keep = {plugin_key(p) for c in self.rows['candidates'] if c['campaignId'] != self.campaign for p in c.get('plugins', [])}
            remaining = [p for p in value.get('plugins', []) if plugin_key(p) not in own - keep]
            if remaining != value.get('plugins', []):
                self.rewrites.append({'path':str(annotations),'kind':'annotations','remove':sorted(own-keep)})
        log = self.data / 'supervisor-errors.jsonl'
        if log.exists():
            self.checked(log)
            lines = log.read_text().splitlines(keepends=True)
            remaining = [line for line in lines if not any(token in line for token in tokens)]
            if remaining != lines:self.rewrites.append({'path':str(log),'kind':'diagnostics','remove':sorted(tokens)})

    def build(self):
        self.dependencies()
        try:
            self.files()
            self.shared, self.bundles = self.shared_for(self.campaign)
            self.keep = self.retained(self.shared)
            self.mixed_files()
            for path in self.paths | self.shared | self.keep:self.checked(path)
            # A corrupted ownership record must never claim another activity's directory.
            for table, fields, root in [('trials',('output',),'trials'),('reference_runs',('output',),'trials'),
                                        ('reports',('markdownPath',),'reports'),('exports',('path','archive'),'exports'),
                                        ('exports',('validationEvidence',),'export-checks')]:
                for row in self.rows[table]:
                    if row['campaignId'] == self.campaign:continue
                    for field in fields:
                        if row.get(field) and self.child(root,row[field]) in self.paths:
                            raise Refused('专属文件也被其他活动引用：' + row[field])
            for row in self.rows['owned_artifacts']:
                if row['campaignId'] != self.campaign and Path(row['path']) in self.paths:
                    raise Refused('生成目录也被其他活动引用：' + row['path'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.blockers.append({'kind':'storage','message':str(error)})
        targets = self.paths | (self.shared - self.keep)
        parts = {p.parts for p in targets}
        targets = sorted(p for p in targets if not any(p.parts[:n] in parts for n in range(len(self.data.parts)+1,len(p.parts))))
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
