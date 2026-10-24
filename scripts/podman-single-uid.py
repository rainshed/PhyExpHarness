#!/usr/bin/env python3
"""Deployment-scoped Docker CLI entry for a single-UID rootless Podman pilot.

Runtime commands use Docker's client against Podman's private Unix socket.
Builds use an explicit, labelled adaptation: file ownership and image USER are
collapsed to 0, and Debian fakeroot handles ownership during RUN only. This is
not a general Docker replacement. Configuration and build receipts stay outside
the checkout; no host paths or credentials are mounted into build containers.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

POLICY = 'podman-single-uid-v1'
HELPERS = '.phyexp-build-helpers'


def adapt(dockerfile):
    """Adapt build mechanics only; preserve task code, dependencies and scoring."""
    if not re.search(r'^FROM\s', dockerfile, re.M | re.I):
        raise ValueError('A Dockerfile with an explicit base is required')
    if re.search(r'^(SHELL|ONBUILD)\s', dockerfile, re.M | re.I):
        raise ValueError('Custom SHELL/ONBUILD requires a reviewed build adapter')
    build_network(dockerfile)  # Reject mixed per-step network policies.
    lines = []
    shell = ['/usr/bin/env', 'FAKEROOTDONTTRYCHOWN=1', '/'+HELPERS+'/fakeroot-sysv',
             '-l', '/'+HELPERS+'/libfakeroot-sysv.so', '-f', '/'+HELPERS+'/faked-sysv',
             '/bin/sh', '-c']
    for line in dockerfile.splitlines():
        line = re.sub(r'^RUN\s+--network=none\s+', 'RUN ', line, flags=re.I)
        if re.match(r'^USER\s', line, re.I):
            line = 'USER 0:0'
        if re.match(r'^(COPY|ADD)\s', line, re.I):
            line = re.sub(r'--chown=\S+', '--chown=0:0', line)
        # apt's download sandbox cannot switch to an unmapped _apt identity.
        if not line.lstrip().startswith('#'):
            line = re.sub(r'\bapt-get\b', 'apt-get -o APT::Sandbox::User=root', line)
        lines.append(line)
        if re.match(r'^FROM\s', line, re.I):
            lines.extend(['USER 0:0', f'COPY {HELPERS}/ /{HELPERS}/',
                          'SHELL '+json.dumps(shell)])
    lines.extend(['USER 0:0', 'SHELL ["/bin/sh", "-c"]', f'RUN rm -rf /{HELPERS}',
                  'LABEL org.phyexp.container-runtime="'+POLICY+'"',
                  'LABEL org.phyexp.source-dockerfile-sha256="'+hashlib.sha256(dockerfile.encode()).hexdigest()+'"'])
    return '\n'.join(lines)+'\n'


def build_network(dockerfile):
    runs = re.findall(r'^RUN\s+(.+)', dockerfile, re.M | re.I)
    isolated = [line.startswith('--network=none ') for line in runs]
    if any(isolated) and not all(isolated):
        raise ValueError('Mixed RUN network policies require a reviewed adapter')
    if any('--network=' in line and not line.startswith('--network=none ') for line in runs):
        raise ValueError('Unsupported RUN network policy')
    return ['--network=none'] if any(isolated) else []


def build(argv, config):
    if not argv or argv[-1].startswith('-'):
        raise ValueError('A local build context is required')
    context = Path(argv[-1]).resolve(strict=True)
    if not context.is_dir():
        raise ValueError('Only local directory contexts are supported')
    arguments, dockerfile = [], context/'Dockerfile'
    i = 0
    while i < len(argv)-1:
        arg = argv[i]
        if arg in ('-f', '--file'):
            dockerfile = Path(argv[i+1]).resolve(strict=True); i += 2
        elif arg in ('-t', '--tag', '--build-arg', '--label', '--target', '--platform'):
            arguments.extend(argv[i:i+2]); i += 2
        elif arg in ('--no-cache', '--quiet', '-q'):
            arguments.append(arg); i += 1
        else:
            raise ValueError('Unsupported build argument for single-UID pilot: '+arg)
    source = dockerfile.read_text()
    transformed = adapt(source)
    work = Path(config['work']); work.mkdir(parents=True, exist_ok=True)
    receipts = work/'build-receipts'; receipts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-', dir=work) as temp:
        staged = Path(temp)/'context'
        # Excluded directories are never build assets. Docker's own ignore file
        # continues to govern the remaining files sent to the builder.
        shutil.copytree(context, staged, symlinks=True,
                        ignore=shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__', '.runtime', 'runs', 'reports'))
        if (staged/HELPERS).exists():
            raise ValueError('Reserved build helper path already exists')
        helper = staged/HELPERS; helper.mkdir()
        helper_hashes = {}
        for name, path in config['fakeroot'].items():
            if name not in ('fakeroot-sysv', 'faked-sysv', 'libfakeroot-sysv.so'):
                raise ValueError('Unexpected build helper')
            shutil.copyfile(path, helper/name); (helper/name).chmod(0o755)
            helper_hashes[name] = hashlib.sha256((helper/name).read_bytes()).hexdigest()
        if len(helper_hashes) != 3:
            raise ValueError('Complete Debian fakeroot helpers required')
        # Ensure the explicit helper inputs survive restrictive ignore rules.
        for name in ['.dockerignore', '.containerignore']:
            ignore = staged/name
            if name == '.containerignore' and not ignore.exists(): continue
            if ignore.is_symlink(): raise ValueError('Ignore file must not be a symlink')
            with ignore.open('a') as stream:
                stream.write('\n!'+HELPERS+'/\n!'+HELPERS+'/**\n!PhyExp.Containerfile\n')
        file = staged/'PhyExp.Containerfile'
        if file.exists() or file.is_symlink(): raise ValueError('Reserved build file already exists')
        file.write_text(transformed)
        image_file = Path(temp)/'image-id'
        command = [config['podman'], 'build', '--format', 'docker', '--layers',
                   '--signature-policy', config['signaturePolicy'], '--memory', '8g',
                   '--cpu-period', '100000', '--cpu-quota', '400000',
                   '--iidfile', str(image_file), *build_network(source), '-f', str(file), *arguments, str(staged)]
        result = subprocess.run(command)
        receipt = {'policy': POLICY, 'sourceDockerfile': str(dockerfile),
                   'sourceSha256': hashlib.sha256(source.encode()).hexdigest(),
                   'adaptedSha256': hashlib.sha256(transformed.encode()).hexdigest(),
                   'helpers': helper_hashes, 'arguments': arguments, 'exitCode': result.returncode,
                   'image': image_file.read_text().strip() if image_file.exists() else None,
                   'finishedAt': time.time()}
        key = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
        (receipts/(key+'.json')).write_text(json.dumps(receipt, indent=2)+'\n')
        (receipts/(key+'.Containerfile')).write_text(transformed)
        return result.returncode


def startup_ready(container):
    state = container['State']
    if state.get('Status') in ('exited', 'dead', 'removing'):
        raise RuntimeError('Container exited during startup: '+container.get('Name', ''))
    test = (container.get('Config', {}).get('Healthcheck') or {}).get('Test', [])
    if not test or test == ['NONE']:
        # Podman 4 returns an empty Health object even for HEALTHCHECK NONE.
        # Docker Compose treats that as a broken configured healthcheck.
        return state.get('Running', False)
    health = (state.get('Health') or {}).get('Status')
    if health == 'unhealthy':
        raise RuntimeError('Container failed its healthcheck: '+container.get('Name', ''))
    return state.get('Running', False) and health == 'healthy'


def startup_snapshot(containers):
    snapshot = []
    for container in containers:
        state = container.get('State') or {}
        health = state.get('Health') or {}
        snapshot.append({'id': container.get('Id'), 'name': container.get('Name'),
            'status': state.get('Status'), 'running': state.get('Running'),
            'exitCode': state.get('ExitCode'), 'oomKilled': state.get('OOMKilled'),
            'health': health.get('Status'), 'failingStreak': health.get('FailingStreak'),
            'healthLog': [{k: str(entry[k])[-2048:] if k == 'Output' else entry[k]
                           for k in ('Start', 'End', 'ExitCode', 'Output') if k in entry}
                          for entry in (health.get('Log') or [])[-3:]]})
    return snapshot


def compose_wait(argv, config, environment):
    index = argv.index('up')
    prefix = [config['dockerClient'], *argv[:index]]
    arguments = argv[index:]
    if '--detach' not in arguments and '-d' not in arguments:
        raise ValueError('Pilot compose wait requires detached startup')
    timeout = 180  # Legacy callers; new frozen adapters pass the remaining task budget.
    if '--wait-timeout' in arguments:
        offset = arguments.index('--wait-timeout')
        timeout = int(arguments[offset+1]); del arguments[offset:offset+2]
    if timeout <= 0:
        raise ValueError('Compose startup timeout must be positive')
    arguments.remove('--wait')
    started = time.monotonic()
    deadline = started+timeout
    containers, phase = [], 'compose-up'

    def report(code=None):
        # No Config.Env, mounts or hidden task configuration in this receipt.
        print('PHYEXP_ENVIRONMENT_STARTUP='+json.dumps({'code': code, 'phase': phase,
              'elapsedSeconds': time.monotonic()-started, 'budgetSeconds': timeout,
              'containers': startup_snapshot(containers)}), file=sys.stderr, flush=True)

    def remaining():
        value = deadline-time.monotonic()
        if value <= 0:
            raise TimeoutError('Compose containers did not become ready')
        return value

    try:
        result = subprocess.run([*prefix, *arguments], env=environment, timeout=remaining())
        if result.returncode:
            raise RuntimeError('Compose up failed with exit code '+str(result.returncode))
        phase = 'container-discovery'
        ids = subprocess.check_output([*prefix, 'ps', '--all', '--quiet'], env=environment,
                                      text=True, timeout=remaining()).split()
        if not ids:
            raise RuntimeError('Compose did not create any containers')
        phase = 'healthcheck'
        previous = None
        while True:
            containers = json.loads(subprocess.check_output([config['podman'], 'inspect', *ids],
                                                            text=True, timeout=remaining()))
            snapshot = startup_snapshot(containers)
            if snapshot != previous:
                report()  # Preserve observations even if Harbor's outer timer cancels us.
                previous = snapshot
            # Evaluate every service: a starting first service must not hide a
            # failed later service until the entire budget expires.
            ready = [startup_ready(container) for container in containers]
            remaining()
            if len(containers) == len(ids) and all(ready):
                return 0
            time.sleep(min(1, remaining()))
    except Exception as error:
        code = ('environment_start_timeout' if isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
                else 'environment_healthcheck_failed' if str(error).startswith('Container failed its healthcheck:')
                else 'environment_container_exited' if str(error).startswith('Container exited during startup:')
                else 'environment_start_failed')
        report(code)
        raise


def main():
    config = json.loads(Path(os.environ['PHYEXP_PODMAN_CONFIG']).read_text())
    if config.get('policy') != POLICY:
        raise ValueError('Unsupported Podman deployment policy')
    if not config['socket'].startswith('unix://'):
        raise ValueError('Only a private Unix socket is supported')
    argv = sys.argv[1:]
    if argv[:1] == ['build']:
        return build(argv[1:], config)
    if argv[:1] == ['run']:
        # Podman 4's Docker-compatible create endpoint hardcodes the system
        # catatonit path. Native run supports an explicit user-installed init.
        extra = ['--init-path', config['init']] if '--init' in argv else []
        os.execv(config['podman'], [config['podman'], 'run', *extra, *argv[1:]])
    environment = dict(os.environ, DOCKER_HOST=config['socket'], DOCKER_CONFIG=config['dockerConfig'])
    if argv[:1] == ['compose'] and 'up' in argv and '--wait' in argv:
        return compose_wait(argv, config, environment)
    os.execve(config['dockerClient'], [config['dockerClient'], *argv], environment)


if __name__ == '__main__':
    raise SystemExit(main())
