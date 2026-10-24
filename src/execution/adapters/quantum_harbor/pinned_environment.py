"""Use Campaign-frozen images with Harbor's unchanged mounts, network and verifier lifecycle."""
import asyncio
import json
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path
from harbor.environments.docker.docker import DockerEnvironment
from src.execution.host.container_runtime import compose_security, verify_image


class PinnedDockerEnvironment(DockerEnvironment):
    def __init__(self, *args, task_env_config, pinned_images, **kwargs):
        # Separate verifiers have an explicit image; public agent environments do not.
        verifier = task_env_config.docker_image is not None
        if verifier and task_env_config.docker_image != pinned_images['verifierSource']:
            raise ValueError('Verifier image does not match the frozen environment')
        image = pinned_images['verifier' if verifier else 'main']
        self._expected_images = {'main': image} if verifier else {'main': image, 'qsim': pinned_images['qsim']}
        self._pin_role = 'verifier' if verifier else 'agent'
        self._startup_budget_seconds = float(task_env_config.build_timeout_sec)
        if not math.isfinite(self._startup_budget_seconds) or self._startup_budget_seconds <= 0:
            raise ValueError('Frozen environment startup budget must be positive and finite')
        self._startup_deadline = None
        self._pin_dir = tempfile.TemporaryDirectory(prefix='phyexp-image-lock-')
        config = task_env_config.model_copy(update={'docker_image': image})
        super().__init__(*args, task_env_config=config, **kwargs)
        # Task build declarations remain, but up --no-build --pull never below
        # prevents fallback execution. Apply the overlay to separate verifiers too.
        overlay = Path(self._pin_dir.name) / 'images.json'
        overlay.write_text(json.dumps({'services': {
            role: {'image': expected, 'pull_policy': 'never', **compose_security(role,
                cpus=self._effective_cpus, memory_mb=self._effective_memory_mb)}
            for role, expected in self._expected_images.items()
        }}))
        self.extra_docker_compose_paths.append(overlay)

    async def _run_docker_compose_command(self, command, *args, **kwargs):
        command = list(command)
        if command[0] in ('build', 'pull'):
            raise ValueError('Frozen task images cannot be built or pulled within a Trial')
        if command[0] == 'up':
            command += ['--no-build', '--pull', 'never']
            if self._startup_deadline is not None:
                command += ['--wait-timeout', str(math.ceil(self._remaining_startup()))]
                original_output = kwargs.get('on_output')

                async def observe(line, stream):
                    if self._observe_startup(line):
                        self._write_startup(self._startup_started, 'starting')
                    if original_output is not None:
                        await original_output(line, stream)

                kwargs['on_output'] = observe
        if command[0] == 'down' and '--rmi' in command:
            index = command.index('--rmi')
            del command[index:index+2]  # Keep shared images; containers and volumes are still removed.
        if self._startup_deadline is not None:
            self._startup_phase = 'compose-'+command[0]
            remaining = self._remaining_startup()
            kwargs['timeout_sec'] = min(kwargs.get('timeout_sec') or remaining, remaining)
        return await super()._run_docker_compose_command(command, *args, **kwargs)

    def _remaining_startup(self):
        remaining = self._startup_deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Frozen environment startup budget exhausted')
        return remaining

    async def _docker_output(self, arguments):
        return await asyncio.to_thread(subprocess.check_output, ['docker', *arguments],
                                       text=True, timeout=self._remaining_startup())

    def _observe_startup(self, line):
        if 'PHYEXP_ENVIRONMENT_STARTUP=' in line:
            try:
                detail, _ = json.JSONDecoder().raw_decode(line.split('PHYEXP_ENVIRONMENT_STARTUP=', 1)[1])
                if isinstance(detail, dict) and detail.get('code') in (None, 'environment_start_timeout',
                        'environment_healthcheck_failed', 'environment_container_exited', 'environment_start_failed'):
                    self._startup_observation = detail
                    return True
            except ValueError:
                pass
        return False

    def _write_startup(self, started, status, error=None):
        receipt = {'schemaVersion': 1, 'role': self._pin_role, 'status': status,
                   'phase': self._startup_phase, 'budgetSeconds': self._startup_budget_seconds,
                   'elapsedSeconds': time.monotonic()-started}
        if error is not None:
            receipt['errorType'] = type(error).__name__
            receipt['code'] = ('environment_start_timeout' if isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
                               or str(error).startswith('Command timed out after ')
                               else 'environment_start_interrupted' if isinstance(error, asyncio.CancelledError)
                               else 'environment_start_failed')
            for line in str(error).splitlines():
                self._observe_startup(line)
            if self._startup_observation and self._startup_observation.get('code'):
                receipt['code'] = self._startup_observation['code']
        if self._startup_observation:
            receipt['compose'] = self._startup_observation
        evidence = self.trial_paths.trial_dir / 'phyexp'
        evidence.mkdir(exist_ok=True)
        (evidence / ('environment-startup-'+self._pin_role+'.json')).write_text(json.dumps(receipt, indent=2)+'\n')

    async def start(self, force_build=False):
        if force_build:
            raise ValueError('Frozen task images cannot be rebuilt within a Trial')
        started = time.monotonic()
        self._startup_started = started
        self._startup_observation = None
        self._startup_deadline = started+self._startup_budget_seconds
        self._startup_phase = 'image-validation'
        try:
            self._write_startup(started, 'starting')
            await self._start_pinned()
            self._startup_phase = 'ready'
            self._write_startup(started, 'ready')
        except (Exception, asyncio.CancelledError) as error:
            try:
                self._write_startup(started, 'failed', error)
            except OSError:
                pass  # Evidence write failure must not replace the startup cause.
            raise
        finally:
            self._startup_deadline = None  # Cleanup has Harbor's own lifecycle/budget.

    async def _start_pinned(self):
        for role, expected in self._expected_images.items():
            actual = (await self._docker_output(['image', 'inspect', expected, '--format', '{{.Id}}'])).strip()
            if actual != expected: raise ValueError('Frozen task image is unavailable: '+role)
            await asyncio.to_thread(verify_image, expected, timeout=self._remaining_startup())
        await super().start(force_build=False)
        self._startup_phase = 'container-verification'
        project = self.session_id.lower()
        if not re.match(r'^[a-z0-9]', project): project = '0'+project
        project = re.sub(r'[^a-z0-9_-]', '-', project)
        actual, resources = {}, {}
        for role, expected in self._expected_images.items():
            containers = (await self._docker_output(['ps', '-q', '--filter', 'label=com.docker.compose.project='+project,
                '--filter', 'label=com.docker.compose.service='+role])).split()
            if len(containers) != 1: raise ValueError('Cannot identify frozen task container: '+role)
            image = (await self._docker_output(['inspect', containers[0], '--format', '{{.Image}}'])).strip()
            if image != expected: raise ValueError('Running task image differs from frozen identity: '+role)
            actual[role] = image
            mounts = json.loads(await self._docker_output(['inspect', containers[0], '--format', '{{json .Mounts}}']))
            resources[role] = {'container': containers[0], 'volumes': sorted(m['Name'] for m in mounts if m['Type']=='volume')}
        evidence = self.trial_paths.trial_dir / 'phyexp'
        evidence.mkdir(exist_ok=True)
        (evidence / ('pinned-images-'+self._pin_role+'.json')).write_text(json.dumps(actual, indent=2)+'\n')
        (evidence / ('pinned-resources-'+self._pin_role+'.json')).write_text(json.dumps(resources, indent=2)+'\n')

    async def stop(self, delete=True):
        try:
            await super().stop(delete)
        finally:
            self._pin_dir.cleanup()
