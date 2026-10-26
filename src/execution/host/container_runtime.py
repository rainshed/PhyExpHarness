"""Explicit execution policy for the five public single-UID Podman tasks."""
import json
import os
import subprocess

PODMAN_SINGLE_UID = 'podman-single-uid-v1'
QSIM_CPUS = 4
# These tasks use data submissions and separate verifier containers. None
# enables syndrome_feedback_control, whose submitted Python requires UID 65534.
# Keep an explicit allowlist: new tasks do not inherit this compatibility claim.
SUPPORTED_TASKS = frozenset({'time_budgeted_hamlearn_10q', 'time_budgeted_shadow_surrogate_60q',
    'tunable_coupler_cz_netzero', 'logical_cnot_decoder_calibration', 'adaptive_clustered_clbcs_h2o'})


def policy():
    value = os.environ.get('PHYEXP_CONTAINER_RUNTIME', 'docker')
    if value not in ('docker', PODMAN_SINGLE_UID):
        raise ValueError('Unknown container runtime policy: '+value)
    return value


def require_tasks(tasks):
    if policy() == PODMAN_SINGLE_UID and (not tasks or set(tasks)-SUPPORTED_TASKS):
        raise ValueError('当前无 sudo Podman 环境支持工作台中的 5 个公开任务；请选择至少一个受支持任务。新增任务需要单独验证容器与隔离兼容性。')


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


def verify_image(image, *, timeout=30):
    if policy() != PODMAN_SINGLE_UID:
        return
    labels = json.loads(subprocess.check_output(
        ['docker', 'image', 'inspect', image, '--format', '{{json .Config.Labels}}'], text=True, timeout=timeout)) or {}
    if labels.get('org.phyexp.container-runtime') != PODMAN_SINGLE_UID:
        raise ValueError('Image was not provisioned for the single-UID runtime: '+image)


def verify_lock(lock, task):
    require_tasks([task])
    if lock.get('containerRuntime', 'docker') != policy():
        raise ValueError('Container runtime differs from the frozen task environment; create a new Campaign')


def compose_security(role, *, cpus=None, memory_mb=None):
    if policy() != PODMAN_SINGLE_UID:
        return {}
    # UID 0 maps to the ordinary host user. No container receives capabilities,
    # privilege escalation, host networking, or the engine's control socket.
    result = {'user': '0:0', 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
              'pids_limit': 256, 'cpus': QSIM_CPUS if role == 'qsim' else (cpus or 2),
              'mem_limit': '8g' if role == 'qsim' else (str(memory_mb)+'m' if memory_mb else '4g')}
    if role == 'qsim':
        # BLAS sees host CPUs rather than the cgroup quota. Oversubscription can
        # stall the Hamiltonian eigendecomposition before its HTTP server starts.
        result['environment'] = {key: str(QSIM_CPUS) for key in
                                 ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}
    return result
