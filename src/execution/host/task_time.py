"""Benchmark-owned phase limits. Scheduling reservations never shorten the agent phase."""
import hashlib
import math
import tomllib
from pathlib import Path

POLICY = 'benchmark-time-v1'


def benchmark_time(config):
    return config.get('executionTimePolicy', {}).get('version') == POLICY


def read_task_time(root, task):
    from harbor.models.task.config import TaskConfig
    from harbor.trial.trial import Trial
    if not isinstance(task, str) or Path(task).name != task or task in ('.', '..'):
        raise ValueError('Invalid benchmark task name')
    path = Path(root) / 'harbor_tasks' / task / 'task.toml'
    if path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to((Path(root)/'harbor_tasks').resolve()):
        raise ValueError('Benchmark task configuration must stay inside its task directory')
    raw = path.read_bytes()
    config = TaskConfig.model_validate(tomllib.loads(raw.decode()))
    seconds = config.agent.timeout_sec
    # An unbounded task has no platform substitute. Admission under a finite
    # activity budget must explicitly report that it cannot reserve a full run.
    values = {'solverTimeSeconds': seconds,
              'environmentTimeSeconds': config.environment.build_timeout_sec,
              'setupTimeSeconds': Trial._AGENT_SETUP_TIMEOUT_SEC,
              'verifierTimeSeconds': config.verifier.timeout_sec}
    if any(v is not None and (not math.isfinite(v) or v <= 0) for v in values.values()):
        raise ValueError('Invalid benchmark phase duration: ' + task)
    # Separate verifier environments have their own build/start phase. This is
    # an admission reservation, not a new timer or a deduction from solver time.
    separate = config.verifier.environment_mode == 'separate'
    reservation = None if seconds is None else sum(values.values()) + (values['environmentTimeSeconds'] if separate else 0)
    return {'version': POLICY, 'task': task, **values,
            'verifierEnvironmentTimeSeconds': values['environmentTimeSeconds'] if separate else 0,
            'requiredTimeSeconds': reservation,
            'taskConfigSha256': hashlib.sha256(raw).hexdigest(),
            'source': 'harbor_tasks/' + task + '/task.toml'}


def verify_task_time(root, task, expected):
    actual = read_task_time(root, task)
    if actual != expected:
        raise ValueError('Benchmark time configuration changed: ' + task)
    return actual


def start_solver_clock(timing, activity_deadline, started):
    seconds=timing['solverTimeSeconds']
    if seconds is None or activity_deadline-started < seconds+timing['verifierTimeSeconds']+timing['verifierEnvironmentTimeSeconds']:
        raise RuntimeError('Activity cannot fit full benchmark after setup; refusing shortened solve')
    return {**timing,'solverStartedAt':started,'solverDeadline':started+seconds,
            'activityDeadline':activity_deadline}
