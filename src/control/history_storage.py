"""Explicit, resumable storage deduplication for closed legacy Campaigns.

Keep the original Bundle bytes, IDs and paths. Content objects own the shared
payload; hard links expose the old file layout to already-running old readers.
Installed dependencies are reconstructible, separately verified shared caches.
No database row, report, trajectory, image, or live Campaign is modified.
"""
import fcntl
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import uuid
import zipfile
from contextlib import contextmanager, closing
from pathlib import Path

from src.execution.bundle.freeze import _object
from src.execution.bundle.manifest import canonical, digest, resolve, verify, checked_path, safe_relative
from .execution_cache import prepare_dependencies

TERMINAL = {'finished', 'failed'}


def write_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + '.tmp')
    temporary.write_bytes(canonical(value) + b'\n')
    os.replace(temporary, file)


@contextmanager
def database(data):
    db = sqlite3.connect((Path(data) / 'control.sqlite').as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def rows(db, table):
    return [json.loads(row[0]) for row in db.execute('SELECT data FROM "' + table + '"')]


def eligible(data):
    """A shared Bundle is excluded if ANY referring Campaign remains open."""
    data = Path(data).resolve()
    with database(data) as db:
        campaigns = {c['id']: c for c in rows(db, 'campaigns')}
        candidates = rows(db, 'candidates')
        active = {t['campaignId'] for t in rows(db, 'trials') if t['state'] in ('reserved', 'launching', 'running')}
        active.update(s['campaignId'] for s in rows(db, 'meta_sessions') if s.get('state') in ('starting', 'running'))
        active.update(o['campaignId'] for o in rows(db, 'operations') if o.get('state') in ('pending', 'running'))
    grouped = {}
    for c in candidates:
        grouped.setdefault(c['bundlePath'], []).append(c)
    accepted, excluded = [], []
    for path, references in sorted(grouped.items()):
        root = Path(path).resolve()
        if root.parent != data / 'objects/sha256':
            excluded.append({'path': path, 'reason': 'outside primary candidate store'})
            continue
        if any(campaigns[c['campaignId']]['state'] not in TERMINAL or c['campaignId'] in active for c in references):
            excluded.append({'path': path, 'reason': 'referenced by open Campaign or active work'})
            continue
        manifest = json.loads(checked_path(root, 'bundle.json').read_text())
        if digest(canonical({k: v for k, v in manifest.items() if k != 'id'})) != manifest.get('id'):
            raise ValueError('Historical Bundle identity mismatch')
        if manifest.get('schemaVersion', 1) != 1:
            excluded.append({'path': path, 'reason': 'already uses new composition format'})
            continue
        if manifest['id'] != root.name or any(c['bundleId'] != manifest['id'] for c in references):
            raise ValueError('Historical candidate identity mismatch')
        accepted.append({'path': str(root), 'bundleId': manifest['id'],
                         'candidateIds': sorted(c['id'] for c in references),
                         'campaignIds': sorted({c['campaignId'] for c in references}),
                         'manifestSha256': digest((root / 'bundle.json').read_bytes())})
    return {'bundles': accepted, 'excluded': excluded}


def _assert_idle(data, entry):
    current = next((r for r in eligible(data)['bundles'] if r['bundleId'] == entry['bundleId']), None)
    if current != entry:
        raise ValueError('Historical references changed or Campaign is no longer idle')
    # Also protect directly-launched supervisors not represented by database state.
    listing = subprocess.check_output(['ps', '-axo', 'command='], text=True)
    if any(entry['path'] in line for line in listing.splitlines()):
        raise ValueError('A process still references this Bundle')


def _blob(data, content, mode=0o444):
    key = digest(content)
    root = Path(data) / 'objects/blobs'
    root.mkdir(parents=True, exist_ok=True)
    target = root / (key + '-' + oct(mode)[2:])
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.read_bytes() != content or stat.S_IMODE(target.stat().st_mode) != mode:
            raise ValueError('Shared source blob is damaged')
    else:
        temporary = root / ('.publishing-' + uuid.uuid4().hex)
        temporary.write_bytes(content)
        temporary.chmod(mode)
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ValueError('Shared source blob publication conflict')
        finally:
            temporary.unlink()
    return target


def _link(source, target, staging):
    if target.exists() and not target.is_symlink() and os.path.samefile(source, target):
        return
    temporary = staging / ('.link-' + uuid.uuid4().hex)
    try:
        os.link(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_layout(data, entry, staging):
    root = Path(entry['path'])
    resolved = resolve(root)
    original = {'bundle.json': root / 'bundle.json', **resolved.assets}
    content = {p: f.read_bytes() for p, f in original.items()}
    modes = {p: stat.S_IMODE(f.stat().st_mode) for p, f in original.items()}
    blob_files = {p: _blob(data, value, modes[p] & ~0o222) for p, value in content.items()}
    remaining = set(resolved.assets) - {'recipe.json'}
    objects, plugins = {}, []

    def save_object(kind, files):
        reference, descriptor = _object(Path(data) / 'objects/sha256', kind, files)
        object_root = Path(data) / 'objects/sha256' / reference
        # Deduplicate common files even across different historical adapter versions.
        for name, value in files.items():
            _link(_blob(data, value), object_root / 'assets' / name, staging)
        objects[reference] = descriptor
        return reference

    for plugin in resolved.manifest['plugins']:
        prefix = 'plugins/' + plugin['name'] + '/'
        files = {p[len(prefix):]: content[p] for p in remaining if p.startswith(prefix)}
        reference = save_object('plugin', files)
        plugins.append({k: plugin[k] for k in ('name', 'version', 'digest', 'config')} | {'object': reference})
        remaining -= {prefix + p for p in files}
    dependency_names = remaining & {'package.json', 'package-lock.json', 'requirements.lock', 'requirements.txt'}
    dependencies = save_object('dependencies', {p: content[p] for p in dependency_names})
    adapter = save_object('legacy-execution-adapter', {p: content[p] for p in remaining - dependency_names})
    lock = json.loads(content['package-lock.json'])
    framework = lock['packages']['node_modules/@deepseek-ai/dsh-sdk-minimal']
    layout = {'schemaVersion': 1, 'kind': 'legacy-bundle-projection', 'bundleId': resolved.manifest['id'],
              'legacyManifestSha256': digest(content['bundle.json']),
              'recipeDigest': digest(content['recipe.json']),
              'framework': {'package': '@deepseek-ai/dsh-sdk-minimal',
                            **{k: framework[k] for k in ('version', 'resolved', 'integrity')}},
              'plugins': plugins, 'adapter': adapter, 'dependencies': dependencies,
              'files': {p: {'sha256': digest(value), 'blob': str(blob_files[p].relative_to(data)), 'mode': modes[p]}
                        for p, value in content.items()}}
    return layout, blob_files


def _backup(session, entry):
    root = Path(entry['path'])
    resolved = resolve(root)
    archive = session / 'backups' / (entry['bundleId'] + '.zip')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix('.tmp')
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name in ['bundle.json', *resolved.assets]:
                z.write(root / name, name)
        os.replace(temporary, archive)
    # Verify archived bytes independently before any source replacement.
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist()) != {'bundle.json', *resolved.assets}:
            raise ValueError('Historical backup file set mismatch')
        for name in z.namelist():
            if z.read(name) != checked_path(root, name).read_bytes():
                raise ValueError('Historical backup mismatch')
    return {'path': str(archive.relative_to(session)), 'sha256': digest(archive.read_bytes())}


def _preview(entry, layout, dependencies, session, log):
    root = session / 'previews' / entry['bundleId']
    root.mkdir(parents=True, exist_ok=True)
    data = Path(json.loads((session / 'plan.json').read_text())['data'])
    for name, record in layout['files'].items():
        target = root / safe_relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        _link(data / record['blob'], target, session)
    modules = root / 'node_modules'
    temporary = session / ('.preview-modules-' + uuid.uuid4().hex)
    temporary.symlink_to(dependencies / 'node_modules', target_is_directory=True)
    os.replace(temporary, modules)
    verify(root)
    checks = session / 'checks' / entry['bundleId']
    checks.mkdir(parents=True, exist_ok=True)
    # Original frozen check, original image, no image builds or real provider.
    subprocess.run(['node', str(root / 'src/execution/bundle/check.mjs'), str(root), str(checks)],
                   cwd='/tmp', stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    receipt = json.loads((checks / 'assembly.json').read_text())
    if receipt['status'] != 'passed' or receipt['bundleId'] != entry['bundleId']:
        raise ValueError('Historical native assembly did not pass')
    return str(checks.relative_to(session))


def plan(data, session):
    data, session = Path(data).resolve(), Path(session).resolve()
    session.mkdir(parents=True, exist_ok=False)
    value = {'schemaVersion': 1, 'data': str(data), **eligible(data)}
    pending = []
    for entry in value['bundles']:
        record = data / 'objects/legacy-compositions' / (entry['bundleId'] + '.json')
        organized = False
        if record.is_file() and not record.is_symlink():
            layout = json.loads(record.read_text());root = Path(entry['path'])
            expected = {**verify(root)['files'], 'bundle.json': entry['manifestSha256']}
            if (layout.get('bundleId') != entry['bundleId'] or
                    layout.get('legacyManifestSha256') != entry['manifestSha256'] or
                    {p: f['sha256'] for p, f in layout['files'].items()} != expected):
                raise ValueError('Historical layout identity mismatch')
            organized = ((root / 'node_modules').is_symlink() and (root / 'node_modules').is_dir() and
                         (root / 'node_modules').resolve().is_relative_to(data / 'cache/dependencies') and
                         all(os.path.samefile(checked_path(root, name), checked_path(data, f['blob']))
                             for name, f in layout['files'].items()))
        if organized:
            value['excluded'].append({'path': entry['path'], 'reason': 'already organized historical view'})
        else:
            pending.append(entry)
    value['bundles'] = pending
    write_json(session / 'plan.json', value)
    with database(data) as db, closing(sqlite3.connect(session / 'control-before.sqlite')) as backup:
        db.backup(backup)
    (session / 'control-before.sqlite').chmod(0o600)
    return value


def apply(session):
    session = Path(session).resolve()
    value = json.loads((session / 'plan.json').read_text())
    data = Path(value['data'])
    # Serializes migration/resume/restore; candidate locks also coordinate builders.
    with (data / 'history-storage.lock').open('a') as mutex, (session / 'migration.log').open('a') as log:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        results = []
        for entry in value['bundles']:
            id = entry['bundleId'];root = Path(entry['path'])
            journal = session / 'entries' / (id + '.json')
            state = json.loads(journal.read_text()) if journal.exists() else None
            lock = data / 'locks' / (id + '.lock');lock.parent.mkdir(exist_ok=True)
            with lock.open('a') as candidate_mutex:
                fcntl.flock(candidate_mutex, fcntl.LOCK_EX)
                _assert_idle(data, entry)
                if not state:
                    backup = _backup(session, entry)
                    layout, _ = prepare_layout(data, entry, session)
                    state = {'entry': entry, 'backup': backup, 'layout': layout, 'phase': 'prepared'}
                    write_json(journal, state)
                if state['phase'] == 'released':
                    verify(root)
                    results.append(state)
                    continue
                if state['phase'] == 'restored':
                    raise ValueError('Start a new plan after restore')
                dependencies = prepare_dependencies(resolve(root), data / 'cache', log)
                state['dependencies'] = str(dependencies)
                if state['phase'] == 'prepared':
                    state['nativeCheck'] = _preview(entry, state['layout'], dependencies, session, log)
                    state['phase'] = 'validated';write_json(journal, state)
                _assert_idle(data, entry)
                for name, record in state['layout']['files'].items():
                    source = checked_path(data, record['blob'])
                    if digest(source.read_bytes()) != record['sha256']:
                        raise ValueError('Migration content changed')
                    _link(source, root / safe_relative(name), session)
                # Journal quarantine location before moving the old installation.
                quarantine = session / 'quarantine' / id
                quarantine.parent.mkdir(exist_ok=True)
                state['quarantine'] = str(quarantine.relative_to(session))
                state['phase'] = 'linking';write_json(journal, state)
                modules = root / 'node_modules'
                if modules.exists() and not modules.is_symlink():
                    if quarantine.exists():
                        raise ValueError('Ambiguous old dependency installation')
                    state['oldInstallationBytes'] = int(subprocess.check_output(['du', '-sk', str(modules)], text=True).split()[0]) * 1024
                    write_json(journal, state)
                    modules.rename(quarantine)
                temporary = session / ('.modules-' + uuid.uuid4().hex)
                temporary.symlink_to(dependencies / 'node_modules', target_is_directory=True)
                os.replace(temporary, modules)
                verify(root)
                write_json(data / 'objects/legacy-compositions' / (id + '.json'), state['layout'])
                state['phase'] = 'committed';write_json(journal, state)
                # Only redundant install caches are deleted, after backup/check/commit.
                if quarantine.exists():
                    shutil.rmtree(quarantine)
                state['phase'] = 'released';write_json(journal, state)
                results.append(state)
                print(json.dumps({'bundleId': id, 'status': 'migrated', 'oldInstallationBytes': state.get('oldInstallationBytes', 0)}), flush=True)
        report = {'status': 'passed', 'bundles': len(results),
                  'candidateReferences': sum(len(s['entry']['candidateIds']) for s in results),
                  'removedInstallationBytes': sum(s.get('oldInstallationBytes', 0) for s in results),
                  'sharedInstallations': sorted({s['dependencies'] for s in results}),
                  'excluded': value['excluded'], 'databaseRowsChanged': 0, 'externalModelCalls': 0}
        write_json(session / 'result.json', report)
        return report


def restore(session, bundle_id):
    session = Path(session).resolve()
    data = Path(json.loads((session / 'plan.json').read_text())['data'])
    if len(bundle_id) != 64 or any(c not in '0123456789abcdef' for c in bundle_id):
        raise ValueError('Invalid Bundle ID')
    journal = session / 'entries' / (bundle_id + '.json')
    with (data / 'history-storage.lock').open('a') as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        state = json.loads(journal.read_text())
        _assert_idle(data, state['entry'])
        archive = checked_path(session, state['backup']['path'])
        if digest(archive.read_bytes()) != state['backup']['sha256']:
            raise ValueError('Backup integrity mismatch')
        root = Path(state['entry']['path'])
        with zipfile.ZipFile(archive) as z:
            for name, record in state['layout']['files'].items():
                content = z.read(name)
                if digest(content) != record['sha256']:
                    raise ValueError('Backup asset mismatch')
                temporary = session / ('.restore-' + uuid.uuid4().hex)
                temporary.write_bytes(content);temporary.chmod(record['mode'])
                os.replace(temporary, root / safe_relative(name))
        # Restoring source does not require downloading anything. The locked
        # shared installation remains usable; it is not historical evidence.
        verify(root)
        (data / 'objects/legacy-compositions' / (bundle_id + '.json')).unlink(missing_ok=True)
        state['phase'] = 'restored';write_json(journal, state)
        return {'status': 'restored', 'bundleId': bundle_id, 'dependencies': 'shared-cache'}
