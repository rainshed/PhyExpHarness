"""Stop verified activity processes and reclaim its runtime resources."""
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from .deletion_storage import safe_path, walk, read_json
from .store import Refused


def processes():
    output = subprocess.check_output(['ps','-axo','pid=,ppid=,stat=,lstart=,command='],text=True,timeout=10)
    result = {}
    for line in output.splitlines():
        parts = line.strip().split(None,8)
        if len(parts) == 9:
            pid, parent = map(int,parts[:2])
            result[pid] = {'pid':pid,'parent':parent,'state':parts[2],
                           'started':' '.join(parts[3:8]),'command':parts[8]}
    return result


def stop_processes(service, campaign, job, save):
    current = processes()
    runs = service.store.runs(campaign)
    sessions = service.store.list('meta_sessions',campaign)
    owned = dict(service.children)
    if service.meta_driver:owned.update(service.meta_driver.children)
    selected = {}
    for row in runs + sessions:
        handle = owned.get(row['id'])
        if handle and handle.poll() is not None:continue
        pid = handle.pid if handle else row.get('pid')
        process = current.get(pid)
        output = row.get('output')
        if process and (handle or (output and (str(safe_path(service.data,output)) in process['command'] or str(output) in process['command']))):
            selected[pid] = process
    for previous in job.get('processes',[]):
        process = current.get(previous['pid'])
        if process and process['started'] == previous['started']:selected[process['pid']] = process
    # Harbor starts a separate process group; parent/child ancestry covers it as
    # well as the Meta host, Docker clients and their local descendants.
    changed = True
    while changed:
        changed = False
        for pid, process in current.items():
            if process['parent'] in selected and pid not in selected:
                selected[pid] = process;changed = True
    active = [p for p in selected.values() if not p['state'].startswith('Z')]
    job['processes'] = list(selected.values())
    job.setdefault('stopStartedAt',time.time())
    save(job)  # Identities survive a restart before the first signal.
    for process in active:
        if process['pid'] == os.getpid():raise Refused('不能终止控制服务自身')
        try:os.kill(process['pid'], signal.SIGKILL if time.time()-job['stopStartedAt'] > 10 else signal.SIGTERM)
        except ProcessLookupError:pass
    for mapping in [service.children, service.meta_driver.children if service.meta_driver else {}]:
        for row in runs + sessions:
            handle = mapping.get(row['id'])
            if handle and handle.poll() is not None:del mapping[row['id']]
    if active and time.time()-job['stopStartedAt'] > 45:
        raise Refused('所属进程未能退出，请处理后重试删除。')
    return not active


def docker(*args):
    try:
        return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.PIPE,timeout=30).strip()
    except (OSError,subprocess.SubprocessError) as error:
        raise Refused('无法确认或清理活动容器资源，请恢复容器引擎后重试：' + str(error)) from error


def engine_inventory(kind):
    listing=('ps','-aq') if kind=='container' else (kind,'ls','-q')
    inspect=('inspect',) if kind=='container' else (kind,'inspect')
    ids=docker(*listing).split()
    for attempt in range(3):
        if not ids:return []
        try:return json.loads(docker(*inspect,*ids))
        except Refused:
            # Unrelated activities can remove resources between ls and inspect.
            # Retry reads only after proving an enumerated resource disappeared;
            # engine/permission failures with the same set remain failures.
            current=docker(*listing).split()
            if attempt==2 or not set(ids)-set(current):raise
            ids=current


def cleanup_resources(service, campaign, plan):
    """Engine mount/label ownership is required; arbitrary archived names cannot authorize rm."""
    root = service.data / 'campaigns' / campaign
    runs = service.store.runs(campaign)
    sessions = service.store.list('meta_sessions',campaign)
    build_stages = set()
    for row in service.store.list('owned_artifacts',campaign):
        if row['kind']=='project_build_temp':
            build_stages.update((str(safe_path(service.data,row['path'])),row['path']))
    roots = [safe_path(service.data,root)]
    roots += [safe_path(service.data,r['output']) for r in runs if r.get('output')]
    # A draft with no executed work can be removed on a machine without Docker.
    used = any(r.get('pid') or r.get('executionEntry') for r in runs + sessions)
    if not used:used = any((p/'provenance.json').exists() for p in roots)
    if not used:used = any(f.name == 'runner-identity.json' for p in roots for f in walk(p))
    export_checks = [r for r in service.store.list('exports',campaign) if r.get('relocationValidation') in ('passed','failed')]
    used |= bool(export_checks) or bool(build_stages)
    if not used:return
    containers = engine_inventory('container')
    launches = {r['launchId'] for r in runs if r.get('launchId')}
    projects = set()
    for path in roots[1:]:
        harbor = path / 'harbor'
        safe_path(service.data,harbor)
        for folder in harbor.glob('*'):
            if folder.is_dir() and not folder.is_symlink():
                project = folder.name.lower()
                if not re.match('^[a-z0-9]',project):project='0'+project
                project = re.sub('[^a-z0-9_-]','-',project)
                projects.update([project,project+'-verifier'])
    all_networks = engine_inventory('network')
    networks = [n for n in all_networks if (n.get('Labels') or {}).get('phyexp.launch') in launches]
    network_containers = {cid for n in networks for cid in (n.get('Containers') or {})}
    selected = set()
    for c in containers:
        labels = c.get('Config',{}).get('Labels') or {}
        mounts = [Path(m['Source']) for m in c.get('Mounts',[]) if m.get('Type') == 'bind']
        if (c['Id'] in network_containers or labels.get('phyexp.build.stage') in build_stages or
                any(p == r or p.is_relative_to(r) for p in mounts for r in roots)):
            selected.add(c['Id'])
            if labels.get('com.docker.compose.project'):projects.add(labels['com.docker.compose.project'])
    # Project labels also cover a separate verifier and leftover named volumes.
    for c in containers:
        if (c.get('Config',{}).get('Labels') or {}).get('com.docker.compose.project') in projects:
            selected.add(c['Id'])
    for c in containers:
        if c['Id'] in selected:continue
        for mount in c.get('Mounts',[]):
            if mount.get('Type') == 'bind' and any(Path(mount['Source']) == service.data/p or Path(mount['Source']).is_relative_to(service.data/p) for p in plan['paths']):
                raise Refused('待删除内容仍被其他容器使用：' + c.get('Name',c['Id']))
    if selected:docker('rm','-f','-v',*sorted(selected))
    # Enumerate once rather than spawning engine clients for every historical
    # Trial. This also bounds the time spent in the exclusive cleanup phase.
    if projects:
        volumes=engine_inventory('volume')
        selected_volumes=[v['Name'] for v in volumes if (v.get('Labels') or {}).get('com.docker.compose.project') in projects]
        if selected_volumes:docker('volume','rm',*selected_volumes)
    selected_networks=[n['Id'] for n in all_networks if (n.get('Labels') or {}).get('phyexp.launch') in launches or
                       (n.get('Labels') or {}).get('com.docker.compose.project') in projects]
    if selected_networks:docker('network','rm',*selected_networks)
    # Relocation validation images contain the exported plugin sources. Common
    # task/Runner images and dependency/build caches are not activity history.
    tags = set(docker('image','ls','--format','{{.Repository}}:{{.Tag}}').splitlines()) if export_checks else set()
    for bundle in plan['bundleIds']:
        tag = 'phyexp-relocation:export-' + bundle[:16]
        if tag in tags:docker('image','rm',tag)


def ensure_unused(data, plan):
    paths=[str(data/p) for p in plan['paths']]
    for process in processes().values():
        if process['pid'] == os.getpid() or process['state'].startswith('Z'):continue
        if str(data) not in process['command']:continue
        if any(path in process['command'] for path in paths):
            raise Refused('待删除目录仍被进程使用（PID ' + str(process['pid']) + '），请结束该进程后重试。')
