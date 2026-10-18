"""Use operator-frozen images with Harbor's unchanged mounts, network and verifier lifecycle."""
import json
import re
import subprocess
import tempfile
from pathlib import Path
from harbor.environments.docker.docker import DockerEnvironment


class PinnedDockerEnvironment(DockerEnvironment):
    def __init__(self, *args, task_env_config, pinned_images, **kwargs):
        # Separate verifiers have an explicit image; public agent environments do not.
        verifier = task_env_config.docker_image is not None
        if verifier and task_env_config.docker_image != pinned_images['verifierSource']:
            raise ValueError('Verifier image does not match the frozen environment')
        image = pinned_images['verifier' if verifier else 'main']
        self._expected_images = {'main': image} if verifier else {'main': image, 'qsim': pinned_images['qsim']}
        self._pin_role = 'verifier' if verifier else 'agent'
        self._pin_dir = tempfile.TemporaryDirectory(prefix='phyexp-image-lock-')
        config = task_env_config.model_copy(update={'docker_image': image})
        super().__init__(*args, task_env_config=config, **kwargs)
        if not verifier:
            # Compose up reuses these exact images; no source build or mutable tag resolution.
            overlay = Path(self._pin_dir.name) / 'images.json'
            overlay.write_text(json.dumps({'services': {
                'main': {'image': image, 'pull_policy': 'never'},
                'qsim': {'image': pinned_images['qsim'], 'pull_policy': 'never'},
            }}))
            self.extra_docker_compose_paths.append(overlay)

    async def start(self, force_build=False):
        if force_build:
            raise ValueError('Frozen task images cannot be rebuilt within a Trial')
        await super().start(force_build=False)
        project = self.session_id.lower()
        if not re.match(r'^[a-z0-9]', project): project = '0'+project
        project = re.sub(r'[^a-z0-9_-]', '-', project)
        actual = {}
        for role, expected in self._expected_images.items():
            containers = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project='+project,
                '--filter', 'label=com.docker.compose.service='+role], text=True).split()
            if len(containers) != 1: raise ValueError('Cannot identify frozen task container: '+role)
            image = subprocess.check_output(['docker', 'inspect', containers[0], '--format', '{{.Image}}'], text=True).strip()
            if image != expected: raise ValueError('Running task image differs from frozen identity: '+role)
            actual[role] = image
        evidence = self.trial_paths.trial_dir / 'phyexp'
        evidence.mkdir(exist_ok=True)
        (evidence / ('pinned-images-'+self._pin_role+'.json')).write_text(json.dumps(actual, indent=2)+'\n')

    async def stop(self, delete=True):
        try:
            await super().stop(delete)
        finally:
            self._pin_dir.cleanup()
