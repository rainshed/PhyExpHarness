"""User-owned model settings and write-only credentials. Never exposed to Meta tools."""
import base64
import contextlib
import copy
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from .store import Conflict, Refused
from src.execution.host.models import validate_provider_config, model_catalog, campaign_route, provider_route
from src.execution.host.network import provider_environment


class ProviderSettings:
    def __init__(self, service):
        self.service = service
        self.base = copy.deepcopy(service.store.model_config)
        self.path = service.data / 'provider-settings.sqlite'
        self.lock = threading.RLock()
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connection(True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS credentials(provider TEXT, reference TEXT, value TEXT NOT NULL, PRIMARY KEY(provider,reference))')
            db.execute('CREATE TABLE IF NOT EXISTS tests(id TEXT PRIMARY KEY, command TEXT UNIQUE, payload TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (json.dumps({'revision': 0, 'providers': {}, 'names': {}, 'disabled': []}),))
            # A lost test is never retried, and no receipt does not mean zero consumption.
            for row in db.execute('SELECT id,data FROM tests').fetchall():
                test = json.loads(row['data'])
                if test['state'] == 'running':
                    test.update(state='interrupted', finishedAt=time.time(), error='后台重启，测试已中断；未自动重试，用量待核实。', usageStatus='unknown')
                    db.execute('UPDATE tests SET data=? WHERE id=?', (json.dumps(test), row['id']))
            self.service.store.model_config = self.effective(self.document(db))

    @contextlib.contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def document(self, db):
        return json.loads(db.execute('SELECT data FROM settings WHERE id=1').fetchone()['data'])

    def effective(self, doc, include_disabled=False):
        routes = {**self.base['providers'], **doc['providers']}
        return validate_provider_config({'schemaVersion': 1, 'providers': copy.deepcopy({
            k: v for k, v in routes.items() if include_disabled or k not in doc['disabled']})})

    def check_revision(self, doc, revision):
        if type(revision) is not int or doc['revision'] != revision:
            raise Conflict('模型设置已在其他窗口更新，请重新读取后再保存；当前草稿仍保留。')

    def references(self, provider, reference=None):
        result = []
        for c in self.service.store.list('campaigns'):
            roles = []
            for role in ['solver', 'meta']:
                if c['config'][role]['provider'] != provider:
                    continue
                route = campaign_route(c['config'], role)
                if reference is None or route['auth'].get('env') == reference:
                    roles.append(role)
            if roles:
                result.append({'id': c['id'], 'name': c['config'].get('name') or c['id'], 'state': c['state'],
                               'active': c['state'] not in ['finished', 'failed'], 'roles': roles})
        return result

    def credential(self, db, provider, route):
        ref = route['auth'].get('env')
        if ref is None:
            return None
        row = db.execute('SELECT value FROM credentials WHERE provider=? AND reference=?', (provider, ref)).fetchone()
        return row['value'] if row else os.environ.get(ref, '').strip() or None

    def describe_credential(self, db, provider, route):
        if route['auth']['type'] == 'codex':
            state = 'missing'
            try:
                path = Path(os.environ.get('PHYEXP_CODEX_AUTH_FILE', str(Path.home() / '.codex/auth.json')))
                auth = json.loads(path.read_text())
                token = auth.get('tokens', {}).get('access_token', '')
                claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
                if auth.get('auth_mode', 'chatgpt') == 'chatgpt':
                    state = 'configured' if claims.get('exp', 0) > time.time() + 120 else 'expired'
            except (OSError, ValueError, IndexError, TypeError, AttributeError):
                pass
            return {'source': 'codex', 'state': state, 'saved': False, 'canDelete': False}
        ref = route['auth']['env']
        saved = db.execute('SELECT 1 FROM credentials WHERE provider=? AND reference=?', (provider, ref)).fetchone() is not None
        env = bool(os.environ.get(ref, '').strip())
        refs = self.references(provider, ref)
        return {'reference': ref, 'saved': saved, 'environment': env, 'state': 'configured' if saved or env else 'missing',
                'source': 'saved' if saved else 'environment' if env else 'missing',
                'canDelete': saved and not any(c['active'] for c in refs), 'references': refs}

    def snapshot(self):
        with self.lock, self.connection() as db:
            doc = self.document(db)
            rows = []
            for id, route in self.effective(doc, True)['providers'].items():
                test_row = db.execute('SELECT data FROM tests WHERE json_extract(data,\'$.provider\')=? ORDER BY rowid DESC LIMIT 1', (id,)).fetchone()
                rows.append({'id': id, 'name': doc['names'].get(id, {'openai-codex': 'Codex 订阅', 'deepseek-official': 'DeepSeek 官方'}.get(id, id)),
                             'route': route, 'enabled': id not in doc['disabled'],
                             'source': 'ui' if id in doc['providers'] else 'deployment',
                             'credential': self.describe_credential(db, id, route), 'references': self.references(id),
                             'lastTest': json.loads(test_row['data']) if test_row else None})
            return {'revision': doc['revision'], 'providers': rows}

    def catalog(self):
        with self.lock, self.connection() as db:
            doc = self.document(db)
            rows = model_catalog(self.effective(doc))
            for row in rows:
                row['providerName'] = doc['names'].get(row['provider'], row['provider'])
            return {'schemaVersion': 2, 'revision': doc['revision'], 'models': rows,
                    'limitKind': 'soft', 'hardOutputLimitVerified': False}

    @staticmethod
    def writable_reference(ref):
        # Keys enter trusted child environments so old frozen bundles keep working.
        # A credential reference must not change process launch/security settings.
        reserved = {'PATH', 'HOME', 'SHELL', 'TMPDIR', 'BASH_ENV', 'ENV', 'IFS', 'ZDOTDIR', 'NODE_OPTIONS',
                    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}
        if ref in reserved or ref.startswith(('NODE_', 'PYTHON', 'LD_', 'DYLD_', 'DSH_')) or (ref.startswith('PHYEXP_') and not ref.endswith('_KEY')):
            raise ValueError('此凭据引用属于宿主运行配置，请使用独立的 API_KEY 环境变量名。')

    def save(self, body):
        if set(body) - {'id', 'name', 'route', 'enabled', 'expectedRevision', 'apiKey'}:
            raise ValueError('供应商设置含未知字段')
        id, name, route = body.get('id'), body.get('name'), body.get('route')
        if not isinstance(id, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', id):
            raise ValueError('供应商 ID 须以小写字母开头，只能包含小写字母、数字和连字符，最多 64 字符。')
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError('请输入 1–100 字的供应商名称。')
        enabled = body.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError('启用状态无效')
        validate_provider_config({'schemaVersion': 1, 'providers': {id: route}})
        secret = body.get('apiKey', '')
        if not isinstance(secret, str) or len(secret) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in secret):
            raise ValueError('密钥须为不含换行和控制字符的文本，最多 8192 字符。')
        secret = secret.strip()
        if secret and route['auth']['type'] != 'api-key':
            raise ValueError('Codex 订阅使用宿主登录，不能保存 API Key。')
        if secret:
            self.writable_reference(route['auth']['env'])
        with self.lock:
            with self.connection(True) as db:
                doc = self.document(db)
                self.check_revision(doc, body.get('expectedRevision'))
                doc['providers'][id] = route
                doc['names'][id] = name.strip()
                doc['disabled'] = [p for p in doc['disabled'] if p != id] + ([] if enabled else [id])
                effective = self.effective(doc)
                if secret:
                    db.execute('INSERT INTO credentials VALUES(?,?,?) ON CONFLICT(provider,reference) DO UPDATE SET value=excluded.value', (id, route['auth']['env'], secret))
                doc['revision'] += 1
                db.execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(doc),))
            self.service.store.model_config = effective
            return self.snapshot()

    def remove_credential(self, provider, body):
        with self.lock:
            with self.connection(True) as db:
                doc = self.document(db)
                self.check_revision(doc, body.get('expectedRevision'))
                route = self.effective(doc, True)['providers'][provider]
                if route['auth']['type'] != 'api-key':
                    raise Refused('Codex 登录由宿主管理。')
                ref = route['auth']['env']
                if any(c['active'] for c in self.references(provider, ref)):
                    raise Refused('仍有未结束活动引用此密钥，不能删除；可以更新密钥或停用供应商供后续活动选择。')
                db.execute('DELETE FROM credentials WHERE provider=? AND reference=?', (provider, ref))
                doc['revision'] += 1
                db.execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(doc),))
            return self.snapshot()

    def environment(self, provider, route):
        env = provider_environment()
        if route['auth']['type'] == 'api-key':
            with self.lock, self.connection() as db:
                key = self.credential(db, provider, route)
            if not key:
                raise Refused('请配置 '+provider+' 的 API Key 或后台环境变量 '+route['auth']['env'])
            self.writable_reference(route['auth']['env'])
            env[route['auth']['env']] = key
        return env

    def get_test(self, id):
        with self.connection() as db:
            row = db.execute('SELECT data FROM tests WHERE id=?', (id,)).fetchone()
            if row is None:
                raise KeyError(id)
            return json.loads(row['data'])

    def start_test(self, provider, body):
        if set(body) - {'model', 'reasoningEffort', 'expectedRevision', 'idempotencyKey'}:
            raise ValueError('测试参数含未知字段')
        key = body.get('idempotencyKey')
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError('测试请求需要幂等标识')
        payload = json.dumps({'provider': provider, **{k: v for k, v in body.items() if k != 'idempotencyKey'}}, sort_keys=True)
        with self.lock, self.connection(True) as db:
            prior = db.execute('SELECT payload,data FROM tests WHERE command=?', (key,)).fetchone()
            if prior:
                if prior['payload'] != payload:
                    raise Conflict('测试标识已用于其他参数')
                return json.loads(prior['data'])
            doc = self.document(db)
            self.check_revision(doc, body.get('expectedRevision'))
            if db.execute("SELECT 1 FROM tests WHERE json_extract(data,'$.state')='running'").fetchone():
                raise Conflict('已有测试调用进行中，请等待结果后再测试。')
            model = {'provider': provider, 'model': body.get('model')}
            if body.get('reasoningEffort') is not None:
                model['reasoningEffort'] = body['reasoningEffort']
            route = provider_route(model, self.effective(doc, True))
            from src.execution.host.models import supported_model
            if not supported_model(model, {'schemaVersion': 1, 'providers': {provider: route}}):
                raise ValueError('测试模型或推理强度无效')
            env = self.environment(provider, route)
            id = 'test-' + str(uuid.uuid4())
            test = {'id': id, **model, 'configurationRevision': doc['revision'], 'state': 'running', 'startedAt': time.time(),
                    'usageStatus': 'pending', 'maxRequests': 2, 'timeoutSeconds': 45, 'maxOutputTokensPerRequest': min(512, route['models'][0].get('maxTokens', 8192))}
            db.execute('INSERT INTO tests VALUES(?,?,?,?)', (id, key, payload, json.dumps(test)))
        self.service.pool.submit(self._test_worker, test, route, env)
        return test

    def _test_worker(self, test, route, env):
        try:
            request = {'model': {k: test[k] for k in ['provider', 'model', 'reasoningEffort'] if k in test}, 'providerConfig': route}
            process = subprocess.run(['node', str(self.service.source / 'src/control/provider_probe.mjs')],
                                     input=json.dumps(request), env=env, capture_output=True, text=True, timeout=55, cwd=self.service.source)
            line = next((l for l in reversed(process.stdout.splitlines()) if l.startswith('PHYEXP_PROVIDER_TEST=')), None)
            if line is None:
                raise RuntimeError('测试进程未返回完整结果；用量待核实。')
            result = json.loads(line.split('=', 1)[1])
            test.update(result, state='passed' if result.get('passed') else 'failed')
        except subprocess.TimeoutExpired:
            test.update(state='failed', error='测试超过时限，已停止；未取得完整回执，用量待核实。', usageStatus='unknown')
        except Exception:
            test.update(state='failed', error='测试进程未完成；用量待核实。', usageStatus='unknown')
        test['finishedAt'] = time.time()
        # No request bodies, environment or raw stderr are retained in the test history.
        with self.lock, self.connection(True) as db:
            db.execute('UPDATE tests SET data=? WHERE id=?', (json.dumps(test), test['id']))
