"""Explicit execution policy for the limited single-UID Podman pilot."""
import json
import os
import subprocess

PODMAN_SINGLE_UID = 'podman-single-uid-v1'
SUPPORTED_TASKS = frozenset({'time_budgeted_hamlearn_10q'})


def policy():
    value = os.environ.get('PHYEXP_CONTAINER_RUNTIME', 'docker')
    if value not in ('docker', PODMAN_SINGLE_UID):
        raise ValueError('Unknown container runtime policy: '+value)
    return value


def require_tasks(tasks):
    if policy() == PODMAN_SINGLE_UID and (not tasks or set(tasks)-SUPPORTED_TASKS):
        raise ValueError('当前无 sudo Podman 试运行仅支持 time_budgeted_hamlearn_10q；其他任务的多用户沙箱尚未验证，不能启动。')


def preflight(tasks):
    require_tasks(tasks)
    if policy() == PODMAN_SINGLE_UID:
        # Podman 4's Docker-compatible /info omits rootless in SecurityOptions.
        # Check the native fact and prove the compatibility client uses its store.
        info = json.loads(subprocess.check_output(
            ['podman', 'info', '--format', 'json'], text=True, timeout=45))
        if not info.get('host', {}).get('security', {}).get('rootless'):
            raise ValueError('The single-UID policy requires a rootless engine')
        store = subprocess.check_output(['docker', 'info', '--format', '{{.DockerRootDir}}'], text=True, timeout=45).strip()
        if store != info.get('store', {}).get('graphRoot'):
            raise ValueError('Docker compatibility client and rootless Podman use different stores')


def verify_image(image):
    if policy() != PODMAN_SINGLE_UID:
        return
    labels = json.loads(subprocess.check_output(
        ['docker', 'image', 'inspect', image, '--format', '{{json .Config.Labels}}'], text=True, timeout=30)) or {}
    if labels.get('org.phyexp.container-runtime') != PODMAN_SINGLE_UID:
        raise ValueError('Image was not provisioned for the single-UID runtime: '+image)


def verify_lock(lock, task):
    require_tasks([task])
    if lock.get('containerRuntime', 'docker') != policy():
        raise ValueError('Container runtime differs from the frozen task environment; create a new Campaign')


def compose_security(role):
    if policy() != PODMAN_SINGLE_UID:
        return {}
    # UID 0 maps to the ordinary host user. No container receives capabilities,
    # privilege escalation, host networking, or the engine's control socket.
    return {'user': '0:0', 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
            'pids_limit': 256, 'cpus': 4 if role == 'qsim' else 2,
            'mem_limit': '8g' if role == 'qsim' else '4g'}
