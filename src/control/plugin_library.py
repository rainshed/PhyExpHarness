"""User-owned plugin catalog. Immutable assets outlive their originating Campaign.

Catalog APIs are deliberately absent from Meta's tool registry. Source capture is
backend bookkeeping; it never returns cross-Campaign catalog metadata to Meta.
"""
import contextlib
import json
import re
import shutil
import threading
from pathlib import Path
from jsonschema.exceptions import SchemaError, ValidationError
from .store import Refused, Conflict, encoded, identity
from src.evidence.objects import Objects
from src.execution.bundle.freeze import _object
from src.execution.bundle.manifest import canonical, digest, safe_relative, checked_path, resolve
from src.execution.bundle.project import SourceFiles

KIND = 'execution-plugin-library-v1'
ASSEMBLY = 'dsh-plugin-v1'
ASSEMBLY_SCHEMA=json.loads((Path(__file__).resolve().parents[2]/'schemas/execution/plugin-assembly.schema.json').read_text())
HEX = re.compile(r'[a-f0-9]{64}')


def validate_description(manifest):
    if not isinstance(manifest, dict) or any(k in manifest and not isinstance(manifest[k], str) for k in ('name', 'version', 'displayName', 'functionSummary', 'purpose', 'mechanism')):
        raise ValueError('插件名称、版本与说明必须使用文本')


def local_schema(schema):
    """Plugin configuration validation must not fetch source-controlled URLs."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in ('$ref', '$dynamicRef', '$recursiveRef') and isinstance(value, str) and not value.startswith('#'):
                raise ValueError('配置规范只能引用当前文档内的定义')
            local_schema(value)
    elif isinstance(schema, list):
        for value in schema: local_schema(value)


def dependencies(manifest):
    assembly=manifest.get('assembly')
    value=assembly.get('requires') if isinstance(assembly,dict) else None
    return [x for x in value if isinstance(x,str) and HEX.fullmatch(x)] if isinstance(value,list) else []


class PluginLibrary:
    def __init__(self, service):
        self.service, self.store, self.data = service, service.store, service.data
        self.root = self.data / 'objects/sha256'
        self.root.mkdir(parents=True, exist_ok=True)
        self.mutex, self.local = threading.RLock(), threading.local()
        self.worker = None
        with self.store.connection(True) as db:
            for table in ('plugin_library', 'plugin_library_jobs', 'plugin_library_publications'):
                db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            for row in self.rows(db, 'plugin_library_jobs'):
                if row['state'] == 'running':
                    row['state'] = 'pending'; self.write(db, row, 'plugin_library_jobs')

        self.recover_publications()

    def recover_publications(self):
        with self.locked():
            self.recovery_issues=[]
            with self.store.connection() as db:pending=self.rows(db,'plugin_library_publications')
            for item in pending:
                try:
                    files,manifest=self.contents(item['id'])
                    for source in item['sources']:self.save(files,manifest,source)
                except (OSError,ValueError,KeyError) as error:
                    self.recovery_issues.append({'id':item['id'],'reason':'源码发布未完成；重新补录原快照后核对。'+str(error)[:200]})

    @contextlib.contextmanager
    def locked(self):
        with self.mutex:
            if getattr(self.local, 'locked', False):
                yield; return
            with Objects(self.data).locked():
                self.local.locked = True
                try: yield
                finally: self.local.locked = False

    @staticmethod
    def rows(db, table='plugin_library'):
        return [json.loads(r['data']) for r in db.execute(f'SELECT data FROM {table} ORDER BY rowid')]

    @staticmethod
    def write(db, row, table='plugin_library'):
        db.execute(f'INSERT OR REPLACE INTO {table} VALUES(?,?)', (row['id'], encoded(row)))

    def get(self, id, db=None):
        if not isinstance(id, str) or not HEX.fullmatch(id): raise Refused('插件版本不可用')
        if db is None:
            with self.store.connection() as connection: return self.get(id, connection)
        row = db.execute('SELECT data FROM plugin_library WHERE id=?', (id,)).fetchone()
        if not row: raise Refused('插件版本不可用')
        return json.loads(row['data'])

    def contents(self, id):
        if not isinstance(id, str) or not HEX.fullmatch(id): raise Refused('插件版本不可用')
        root = self.root / id
        descriptor = json.loads(checked_path(root, 'object.json').read_bytes())
        if digest(canonical(descriptor)) != id or descriptor.get('kind') != KIND:
            raise ValueError('Plugin content identity mismatch')
        contents = SourceFiles()
        for name, expected in descriptor['files'].items():
            body = checked_path(root, 'assets/' + name).read_bytes()
            if digest(body) != expected: raise ValueError('Plugin source content mismatch: ' + name)
            contents[name] = body
        metadata = json.loads(contents.pop('library.json'))
        contents.modes = metadata['modes']
        return contents, metadata['manifest']

    def save(self, files, manifest, source):
        """Store only the plugin's declared closure, never its parent workspace."""
        if not files: raise ValueError('插件源码未定位')
        validate_description(manifest)
        for name in files:
            safe_relative(name)
            if name == 'library.json': raise ValueError('Reserved plugin asset: library.json')
        modes = {n: getattr(files, 'modes', {}).get(n, 0o644) for n in files}
        metadata = {'manifest': manifest, 'modes': modes}
        bodies = {**files, 'library.json': canonical(metadata)}
        with self.locked():
            expected=digest(canonical({'schemaVersion':1,'kind':KIND,'files':{n:digest(v) for n,v in bodies.items()}}))
            with self.store.connection() as db:
                prior=db.execute('SELECT data FROM plugin_library WHERE id=?',(expected,)).fetchone()
                if prior and source.get('kind')=='platform-template' and json.loads(prior['data'])['deleted']:return expected
            with self.store.connection(True) as db:
                pending=db.execute('SELECT data FROM plugin_library_publications WHERE id=?',(expected,)).fetchone()
                sources=json.loads(pending['data'])['sources'] if pending else []
                if source not in sources:sources.append(source)
                self.write(db,{'id':expected,'sources':sources},'plugin_library_publications')
            id, _ = _object(self.root, KIND, bodies)
            # _object converges concurrent publications; verify pre-existing bytes too.
            self.contents(id)
            with self.store.connection(True) as db:
                prior = db.execute('SELECT data FROM plugin_library WHERE id=?', (id,)).fetchone()
                row = json.loads(prior['data']) if prior else {
                    'id': id, 'name': manifest.get('name', '未命名插件'), 'version': manifest.get('version', 'unversioned'),
                    'displayName': manifest.get('displayName') or manifest.get('name', '未命名插件'),
                    'description': manifest.get('functionSummary') or manifest.get('purpose') or '',
                    'manifest': manifest, 'bytes': sum(map(len, files.values())), 'files': sorted(files),
                    'createdAt': self.store.clock(), 'revision': 0, 'deleted': False, 'sources': [], 'checks': []}
                if prior and all(s in row['sources'] for s in sources):
                    db.execute('DELETE FROM plugin_library_publications WHERE id=?',(id,));return id
                for item in sources:
                    if item not in row['sources']:row['sources'].append(item)
                row['revision'] += 1
                row['updatedAt'] = self.store.clock()
                self.write(db, row)
                db.execute('DELETE FROM plugin_library_publications WHERE id=?',(id,))
        return id

    def capture(self, contents, spec, source):
        """Best-effort discovery doesn't restrict arbitrary complete projects.

        Publication failures propagate; missing declarations are explicit catalog
        diagnostics. No guessing of unknown source locations or external files.
        """
        result = {'plugins': [], 'issues': []}
        for index, declaration in enumerate(spec.get('plugins', [])):
            name = declaration.get('name', 'component-' + str(index))
            try:
                path = str(safe_relative(declaration.get('path')))
                selected = [n for n in contents if n == path or n.startswith(path + '/')]
                if not selected: raise ValueError('声明的插件源码不在冻结工程中')
                files = SourceFiles()
                for n in selected:
                    relative = n[len(path)+1:] if n != path else Path(n).name
                    files[relative] = contents[n]
                    files.modes[relative] = getattr(contents, 'modes', {}).get(n, 0o644)
                metadata = json.loads(files['plugin.json']) if 'plugin.json' in files else {}
                if not isinstance(metadata, dict): raise ValueError('插件说明必须是对象')
                # Configuration and source provenance do not change plugin content.
                manifest = {k: v for k, v in declaration.items() if k not in ('config', 'path', 'libraryId')}
                manifest.update(metadata)
                if metadata.get('name', name) != name: raise ValueError('插件声明名称不一致')
                manifest.setdefault('name', name); manifest.setdefault('version', 'unversioned')
                validate_description(manifest)
            except (ValueError, KeyError, TypeError) as error:
                result['issues'].append({'name': name, 'reason': str(error)});continue
            # Disk publication/integrity failures are not a successful capture.
            id = self.save(files, manifest, {**source, 'pluginName': name, 'sourcePath': path})
            result['plugins'].append({'id': id, 'path': path, 'name': name})
        return result

    def checked(self, capture, source, status, candidate=None, error=None):
        with self.store.connection(True) as db:
            for item in capture.get('plugins', []):
                row = self.get(item['id'], db)
                record = {**source, 'status': status, 'observedAt': self.store.clock()}
                if candidate: record['candidateId'] = candidate['id']; record['bundleId'] = candidate['bundleId']
                if error: record['error'] = str(error)[:1000]
                row['checks'] = [r for r in row['checks'] if r.get('checkId') != source.get('checkId') or r.get('campaignId') != source.get('campaignId')]
                row['checks'].append(record); row['revision'] += 1; self.write(db, row)

    def compatibility(self, row):
        assembly = row['manifest'].get('assembly', {})
        if row['deleted']: return {'state': 'deleted', 'reason': '用户已从库中删除'}
        if not isinstance(assembly,dict) or assembly.get('contract') != ASSEMBLY:
            return {'state': 'needs_adaptation', 'reason': '缺少当前基础模板的装配声明；源码仍可阅读'}
        try:
            entry = str(safe_relative(assembly['entry']))
            if entry not in row['files']: raise ValueError('入口不在插件源码中')
            from jsonschema import Draft202012Validator
            Draft202012Validator(ASSEMBLY_SCHEMA).validate(assembly)
            Draft202012Validator.check_schema(assembly.get('configSchema', {}))
            local_schema(assembly.get('configSchema', {}))
            if not isinstance(assembly.get('requires', []), list) or any(not isinstance(x, str) or not HEX.fullmatch(x) for x in assembly.get('requires', [])):
                raise ValueError('依赖必须绑定准确插件摘要')
            if not isinstance(assembly.get('conflicts',[]),list) or any(not isinstance(x,str) or not x for x in assembly.get('conflicts',[])):raise ValueError('冲突必须是插件名称或准确摘要列表')
            return {'state': 'declared', 'reason': '已声明装配接口，实际组合仍需隔离构建与加载检查'}
        except (ValueError, KeyError, TypeError, SchemaError, ValidationError) as error: return {'state': 'needs_adaptation', 'reason': str(error)}

    def public(self, row):
        return {**row, 'compatibility': self.compatibility(row),
                'saved': True, 'buildStatus': 'passed' if any(c['status'] == 'passed' for c in row['checks']) else 'failed' if any(c['status'] == 'failed' for c in row['checks']) else 'not_checked',
                'effectiveness': 'not_certified'}

    def page(self, query='', offset=0, limit=50, includeDeleted=False):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100: raise Refused('Invalid library page')
        with self.store.connection() as db: rows = self.rows(db)
        query = query.casefold().strip()
        rows = [r for r in rows if (includeDeleted or not r['deleted']) and (not query or query in json.dumps({k:r[k] for k in ('name','version','displayName','description','sources')}, ensure_ascii=False).casefold())]
        rows.sort(key=lambda r: (r['updatedAt'], r['id']), reverse=True)
        return {'publicationIssues':self.recovery_issues,'items': [self.public(r) for r in rows[offset:offset+limit]], 'total': len(rows), 'offset': offset,
                'nextOffset': offset+limit if offset+limit < len(rows) else None}

    def origins(self,row,exclude_campaign=None):
        campaigns={c['id']:c for c in self.store.list('campaigns')}
        candidates=self.store.list('candidates');labels={}
        for cid,campaign in campaigns.items():
            local=sorted((c for c in candidates if c['campaignId']==cid),key=lambda c:(c.get('createdAt',0),c['id']))
            if campaign.get('h0CandidateId'):local.sort(key=lambda c:c['id']!=campaign['h0CandidateId'])
            labels.update({c['id']:c.get('versionLabel','H'+str(i)) for i,c in enumerate(local)})
        origins=[];seen=set()
        for source in row['sources']:
            cid=source.get('campaignId')
            if cid and cid==exclude_campaign:continue
            checked=next((c for c in row['checks'] if c.get('campaignId')==cid and c.get('checkId')==source.get('checkId') and c.get('candidateId')), {})
            candidate=source.get('candidateId') or checked.get('candidateId')
            key=(cid,candidate or source.get('checkId'),source.get('kind'))
            if key in seen:continue
            seen.add(key)
            origins.append({**source,'candidateId':candidate,'candidateLabel':labels.get(candidate),
                            'campaignName':campaigns.get(cid,{}).get('config',{}).get('name'),
                            'available':not cid or cid in campaigns})
        return origins

    def detail(self, id, file=None):
        with self.locked():
            row = self.public(self.get(id))
            row['origins']=self.origins(row)
            if row['deleted'] and not (self.root/id).exists():
                return {**row,'sourceStatus':'reclaimed','content':None,'runtimeStatus':'unknown','runs':[]}
            files, _ = self.contents(id)
            if file is not None:
                if file not in files: raise Refused('文件不在插件版本中')
                if len(files[file]) > 2_000_000: raise Refused('文件过大，无法预览')
                try: body = files[file].decode('utf-8')
                except UnicodeDecodeError: body = '二进制资产'
                row.update(file=file, content=body)
            candidates = {r['id']:r for r in self.store.list('candidates')}
            ids = {c['candidateId'] for c in row['checks'] if c.get('candidateId') in candidates}
            runs = [t for table in ('trials','reference_runs') for t in self.store.list(table) if t.get('candidateId') in ids]
            row['runs'] = [{k:t.get(k) for k in ('id','campaignId','candidateId','task','state','score','startedAt','stopReason','comparisonContext')} for t in runs]
            row['runtimeStatus'] = 'attempted' if any(t.get('startedAt') is not None for t in runs) else 'not_run'
            row['sourceAvailability'] = [{'source':s, 'available':not s.get('campaignId') or any(c['id']==s['campaignId'] for c in self.store.list('campaigns'))} for s in row['sources']]
            return row

    def references(self, id, db):
        campaigns = [json.loads(r['data']) for r in db.execute('SELECT data FROM campaigns')]
        pins = [c['id'] for c in campaigns if id in [p['id'] for p in c['config'].get('h0Selection', {}).get('plugins', [])]]
        dependents = [r['id'] for r in self.rows(db) if not r['deleted'] and id in dependencies(r['manifest'])]
        # Independent frozen candidate copies survive a library deletion too.
        snapshots = [r['id'] for r in self.store.list('candidates') if id in [p.get('id') for p in r.get('libraryCapture', {}).get('plugins', [])]]
        return {'campaigns': pins, 'plugins': dependents, 'candidateSnapshots': snapshots}

    def preview(self, id, scope='version'):
        if scope not in ('version', 'plugin'): raise Refused('Unknown deletion scope')
        with self.store.connection() as db:
            selected = self.get(id, db)
            rows = [r for r in self.rows(db) if r['id']==id or scope=='plugin' and r['name']==selected['name']]
            return {'scope':scope, 'versions':[{'id':r['id'],'revision':r['revision'],'deleted':r['deleted'],'references':self.references(r['id'],db)} for r in rows],
                    'estimatedReclaimBytes':None, 'message':'从可选库移除；已有活动的冻结源码和实验历史继续保留。无引用内容在清理时释放。'}

    def change(self, id, action, expected, key):
        if action not in ('delete', 'restore'): raise Refused('Unknown library action')
        if not isinstance(key,str) or not 1<=len(key)<=200: raise Refused('Idempotency key required')
        payload = {'id':id,'action':action,'expected':expected}
        with self.locked(), self.store.connection(True) as db:
            prior = self.store._idem(db, 'plugin-library', 'change', key, payload)
            if prior: return prior
            if not isinstance(expected,list) or not expected or len({v['id'] for v in expected}) != len(expected): raise Refused('需要准确版本修订')
            anchor = self.get(id, db)
            for value in expected:
                row = self.get(value['id'], db)
                if row['name']!=anchor['name'] or row['revision']!=value['revision']: raise Conflict('插件库已变化，请重新查看')
                if action=='restore':
                    if not (self.root/row['id']).exists() and any(s.get('kind')=='platform-template' for s in row['sources']):
                        from src.execution.bundle.project import snapshot
                        contents,spec=snapshot(self.service.source/'templates/harness/default')
                        for declaration in spec['plugins']:
                            prefix=declaration['path']+'/'
                            files=SourceFiles()
                            for n,b in contents.items():
                                if n.startswith(prefix):files[n[len(prefix):]]=b;files.modes[n[len(prefix):]]=contents.modes[n]
                            bodies={**files,'library.json':canonical({'manifest':row['manifest'],'modes':files.modes})}
                            expected_id=digest(canonical({'schemaVersion':1,'kind':KIND,'files':{n:digest(v) for n,v in bodies.items()}}))
                            if expected_id==row['id']:_object(self.root,KIND,bodies)
                    try:self.contents(row['id'])
                    except FileNotFoundError as error:raise Refused('源码已释放；请先从仍存在的历史快照补录，再重新导入。') from error
                row.update(deleted=action=='delete',revision=row['revision']+1,updatedAt=self.store.clock())
                self.write(db,row)
            result = {'state':'deleted' if action=='delete' else 'available','versions':[v['id'] for v in expected]}
            return self.store._remember(db, 'plugin-library', 'change', key, payload, result)

    def import_candidate(self, candidate):
        from src.execution.bundle.plugin_reading import project_sources, candidate_plugins, source_view, plugin_key
        source = {'campaignId':candidate['campaignId'],'candidateId':candidate['id'],'bundleId':candidate['bundleId']}
        raw = json.loads((Path(candidate['bundlePath'])/'bundle.json').read_text())
        if raw.get('schemaVersion')==3:
            raw, hashes, asset = project_sources(candidate['bundlePath'],candidate['bundleId'])
            contents = SourceFiles()
            for name, sha in hashes.items():
                body = asset(name).read_bytes()
                if digest(body)!=sha: raise ValueError('Frozen source mismatch')
                contents[name]=body
            contents.modes=raw.get('buildReceipt',{}).get('inputs',{}).get('sourceModes',{})
            capture=self.capture(contents,raw['project'],source)
        else:
            resolved=resolve(candidate['bundlePath'])
            if resolved.manifest['id']!=candidate['bundleId']:raise ValueError('Frozen candidate identity mismatch')
            capture={'plugins':[],'issues':[]}
            for plugin in candidate_plugins(candidate):
                try:
                    info=source_view(candidate,plugin_key(plugin)); files=SourceFiles()
                    for name in info['files']:
                        # source_view authenticated the legacy manifest; read original bytes.
                        file=checked_path(Path(info['directory']),name)
                        files[name]=file.read_bytes();files.modes[name]=0o755 if file.stat().st_mode&0o111 else 0o644
                    id=self.save(files,plugin['manifest'],{**source,'pluginName':plugin['name']})
                    capture['plugins'].append({'id':id,'name':plugin['name']})
                except (ValueError,KeyError,TypeError,OSError) as error: capture['issues'].append({'name':plugin.get('name'),'reason':str(error)})
        self.checked(capture, {**source,'checkId':candidate['id']}, candidate.get('check',{}).get('status','not_checked'), candidate)
        return capture

    def rescan(self, key):
        self.recover_publications()
        if not isinstance(key,str) or not 1<=len(key)<=200: raise Refused('Idempotency key required')
        with self.store.connection(True) as db:
            prior=self.store._idem(db,'plugin-library','rescan',key,{})
            if prior:return prior
            row={'id':identity('library-job'),'state':'pending','candidateIds':[c['id'] for c in self.store._list(db,'candidates')],
                 'cursor':0,'results':[],'createdAt':self.store.clock()}
            self.write(db,row,'plugin_library_jobs')
            return self.store._remember(db,'plugin-library','rescan',key,{}, {'jobId':row['id']})

    def job(self, id):
        with self.store.connection() as db:
            row=db.execute('SELECT data FROM plugin_library_jobs WHERE id=?',(id,)).fetchone()
        if not row:raise Refused('补录任务不存在')
        return json.loads(row['data'])

    def run_job(self, id):
        job=self.job(id)
        if job['state']=='finished':return job
        job['state']='running'
        with self.store.connection(True) as db:self.write(db,job,'plugin_library_jobs')
        for cid in job['candidateIds'][job['cursor']:]:
            try:
                candidate=self.store.get('candidates',cid)
                with self.service.access.enter(candidate['campaignId']):
                    self.store.writable(candidate['campaignId'])
                    result=self.import_candidate(candidate)
                result={'candidateId':cid,**result}
            except (OSError,ValueError,KeyError,TypeError,Refused,Conflict) as error:
                result={'candidateId':cid,'error':str(error)}
            job['results'].append(result);job['cursor']+=1
            with self.store.connection(True) as db:self.write(db,job,'plugin_library_jobs')
        job['state']='finished';job['finishedAt']=self.store.clock()
        with self.store.connection(True) as db:self.write(db,job,'plugin_library_jobs')
        return job

    def prune(self, before):
        """Only catalog-owned objects; activity candidates contain their own copy.

        Keep deletion tombstones after bytes are reclaimed. Sources can be
        explicitly reimported, but a background scan cannot undelete entries.
        """
        reclaimed=0
        with self.locked(), self.store.connection() as db:
            rows={r['id']:r for r in self.rows(db)}
            keep={id for id,r in rows.items() if not r['deleted']}
            for raw in db.execute('SELECT data FROM campaigns'):
                keep.update(p['id'] for p in json.loads(raw['data'])['config'].get('h0Selection',{}).get('plugins',[]))
            pending=list(keep)
            while pending:
                id=pending.pop()
                for dependency in dependencies(rows.get(id,{}).get('manifest',{})):
                    if dependency not in keep:keep.add(dependency);pending.append(dependency)
            for id,row in rows.items():
                if id in keep or not row['deleted'] or row['updatedAt']>=before:continue
                root=self.root/id
                if not root.exists():continue
                self.contents(id)  # Refuse corrupt/escaping storage instead of guessing.
                reclaimed+=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
                shutil.rmtree(root)
        return reclaimed

    def schedule(self):
        with self.mutex:
            if self.worker and self.worker.is_alive():return
            with self.store.connection() as db:
                jobs=[j for j in self.rows(db,'plugin_library_jobs') if j['state'] in ('pending','running')]
            if not jobs:return
            def work():
                try:self.run_job(jobs[0]['id'])
                except Exception as error:
                    job=self.job(jobs[0]['id']);job.update(state='failed',error=str(error))
                    with self.store.connection(True) as db:self.write(db,job,'plugin_library_jobs')
            self.worker=threading.Thread(target=work,name='phyexp-plugin-library',daemon=True);self.worker.start()
