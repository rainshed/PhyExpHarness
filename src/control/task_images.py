"""Prepare official task images before a Campaign; Trials only consume frozen IDs."""
import fcntl
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

from .store import PUBLIC_TASKS, encoded
from src.execution.host.single_run import task_image_sources, validate_task_image_lock, write_json

POLICY = 'campaign-pinned-v1'
ROLES = ('main', 'qsim', 'verifier')


def sources_digest(sources):
    return hashlib.sha256(encoded(sources).encode()).hexdigest()


def image_id(reference):
    try:
        result = subprocess.run(['docker', 'image', 'inspect', reference, '--format', '{{.Id}}'],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            # inspect also fails when the engine is stopped or inaccessible. Only
            # report a missing image after confirming that the engine responds.
            engine = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                                    capture_output=True, text=True, timeout=10)
            if engine.returncode:
                raise ValueError('无法连接 Docker 引擎。请启动 Docker Desktop，等待引擎就绪后重试；若已启动，请检查当前 Docker context 和访问权限。')
    except FileNotFoundError:
        raise ValueError('未找到 Docker 命令。请安装 Docker Desktop，并确保后台进程可以调用 docker。') from None
    except subprocess.TimeoutExpired:
        raise ValueError('Docker 镜像检查超时。请确认 Docker 引擎已就绪且能够响应，然后重试。') from None
    if result.returncode:
        if not any(message in result.stderr.lower() for message in ['no such image', 'no such object']):
            raise ValueError('Docker 引擎可以连接，但无法检查任务镜像：'+reference+'。请检查 Docker 权限和引擎状态。')
        if reference.startswith('sha256:'):
            raise ValueError('Task image unavailable: '+reference+'; restore this exact frozen image or select the Docker context containing it')
        raise ValueError('Task image unavailable: '+reference+'; install the official Quantum-Harbor images first')
    return result.stdout.strip()


def verify_locks(root, tasks, locks):
    sources = {}
    identities = set()
    for task in tasks:
        if task not in locks:
            raise ValueError('Task images are not prepared: '+task)
        lock = locks[task]
        version = lock.get('schemaVersion', 1)
        if version not in sources:
            sources[version] = task_image_sources(root, version)
        images = validate_task_image_lock(lock, task, sources[version])
        identities.update(images[role] for role in ROLES)
    for expected in sorted(identities):
        if image_id(expected) != expected:
            raise ValueError('Frozen task image identity changed: '+expected)


def prepare_task_images(root, tasks, cache, log_path, expected_sources_digest=None):
    """Serialize cache writes across processes, and return a complete immutable snapshot.

    main/qsim use the official Dockerfiles. Separate verifier images are installed
    by Quantum-Harbor's own provisioning process, including its private contexts.
    No mutable official tag is written and no solver or verifier is executed here.
    """
    root, cache, log_path = map(Path, (root, cache, log_path))
    tasks = list(dict.fromkeys(tasks))
    if not tasks or any(task not in PUBLIC_TASKS for task in tasks):
        raise ValueError('Select supported public tasks for image preparation')
    cache.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (cache/'prepare.lock').open('a') as mutex, log_path.open('a') as log:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        sources = task_image_sources(root)
        digest = sources_digest(sources)
        if expected_sources_digest and digest != expected_sources_digest:
            raise ValueError('Task sources changed after Campaign creation; create a new Campaign')
        pending_receipts = {}

        def command(args):
            log.write('$ '+encoded(args)+'\n'); log.flush()
            subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)

        def cached_build(role, key, arguments):
            key = sources_digest(key)
            tag = 'phyexp-task:'+role+'-'+key[:24]
            receipt = cache/(role+'-'+key+'.json')
            if receipt.is_file():
                stored = json.loads(receipt.read_text())
                try:
                    expected = stored['image']
                    if image_id(expected) == expected:
                        log.write('Reuse '+tag+' '+expected+'\n'); log.flush()
                        return expected
                except ValueError:
                    pass  # A new Campaign may repair its cache; existing ones never do.
            command(['docker', 'build', '-t', tag, *arguments])
            result = image_id(tag)
            pending_receipts[receipt] = {'image': result, 'tag': tag}
            return result

        # Resolve every external prerequisite first, so a missing verifier does not
        # leave the user waiting through unrelated builds before reporting failure.
        base = image_id('qiqcbench-agent:latest')
        verifiers = {}
        for task in tasks:
            config = tomllib.loads((root/'harbor_tasks'/task/'task.toml').read_text())
            reference = config['verifier']['environment']['docker_image']
            verifiers[task] = (reference, image_id(reference))
        base_tag = 'phyexp-task:base-'+base.removeprefix('sha256:')
        command(['docker', 'tag', base, base_tag])
        qsim = cached_build('qsim', {'sources': digest},
                            ['-f', str(root/'docker/qsim/Dockerfile'), str(root)])
        locks = {}
        for task in tasks:
            main = cached_build('main', {'task': task, 'sources': digest, 'base': base},
                                ['--build-arg', 'AGENT_IMAGE='+base_tag, str(root/'harbor_tasks'/task/'environment')])
            reference, verifier = verifiers[task]
            # Retain a tag even if the official mutable tag is later moved.
            command(['docker', 'tag', verifier, 'phyexp-task:verifier-'+verifier.removeprefix('sha256:')])
            locks[task] = {'schemaVersion': 2, 'task': task, 'taskSourcesDigest': digest,
                           'images': {'main': main, 'qsim': qsim, 'verifier': verifier, 'verifierSource': reference},
                           'agentBaseImage': base,
                           'source': 'Official Dockerfiles and installed official verifier image; provisioning only.'}
        # Check both source stability during builds and availability before publishing
        # any Campaign lock. The cache is never the authority for an existing Campaign.
        verify_locks(root, tasks, locks)
        # Publish new cache entries only after source stability is proven. Otherwise
        # a failed build against changing files could poison the old source key.
        for receipt, value in pending_receipts.items():
            write_json(receipt, value)
        return locks
