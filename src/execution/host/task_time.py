"""Benchmark phase ceilings and an independent, versioned activity deadline."""
import hashlib
import math
import tomllib
from datetime import datetime
from pathlib import Path

LEGACY_POLICY = 'benchmark-time-v1'
POLICY = 'benchmark-time-v2'
POLICIES = (LEGACY_POLICY, POLICY)


class ActivityDeadlineError(TimeoutError):
    """The activity window ended, independently of the benchmark solver limit."""


def benchmark_time(config):
    return config.get('executionTimePolicy', {}).get('version') in POLICIES


def late_start(config):
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
    # An unbounded phase stays unbounded; the activity deadline is independent.
    values = {'solverTimeSeconds': seconds,
              'environmentTimeSeconds': config.environment.build_timeout_sec,
              'setupTimeSeconds': Trial._AGENT_SETUP_TIMEOUT_SEC,
              'verifierTimeSeconds': config.verifier.timeout_sec}
    if any(v is not None and (not math.isfinite(v) or v <= 0) for v in values.values()):
        raise ValueError('Invalid benchmark phase duration: ' + task)
    # Separate verifier environments have their own build/start phase. This is
    # an admission reservation, not a new timer or a deduction from solver time.
    separate = config.verifier.environment_mode == 'separate'
    reservation = None if any(v is None for v in values.values()) else sum(values.values()) + (values['environmentTimeSeconds'] if separate else 0)
    # Task metadata has not changed; admission policy belongs to the activity.
    return {'version': LEGACY_POLICY, 'task': task, **values,
            'verifierEnvironmentTimeSeconds': values['environmentTimeSeconds'] if separate else 0,
            'requiredTimeSeconds': reservation,
            'taskConfigSha256': hashlib.sha256(raw).hexdigest(),
            'source': 'harbor_tasks/' + task + '/task.toml'}


def verify_task_time(root, task, expected):
    actual = read_task_time(root, task)
    if actual != expected:
        raise ValueError('Benchmark time configuration changed: ' + task)
    return actual


def start_solver_clock(timing, activity_deadline, started, policy=LEGACY_POLICY):
    seconds=timing['solverTimeSeconds']
    if policy == POLICY:
        if started >= activity_deadline:raise ActivityDeadlineError('Activity deadline reached before Solver start')
        nominal=None if seconds is None else started+seconds
        deadline=min(activity_deadline,nominal) if nominal is not None else activity_deadline
        return {**timing,'timePolicy':policy,'solverStartedAt':started,'solverDeadline':deadline,
                'benchmarkSolverDeadline':nominal,'activityDeadline':activity_deadline,
                'availableTimeAtSolverStartSeconds':activity_deadline-started,
                'effectiveSolverTimeSeconds':deadline-started,
                'deadlineCause':'campaign_deadline' if nominal is None or activity_deadline<=nominal else 'trial_deadline'}
    if seconds is None or activity_deadline-started < seconds+timing['verifierTimeSeconds']+timing['verifierEnvironmentTimeSeconds']:
        raise RuntimeError('Activity cannot fit full benchmark after setup; refusing shortened solve')
    return {**timing,'solverStartedAt':started,'solverDeadline':started+seconds,
            'activityDeadline':activity_deadline}


def execution_timing(provenance, harbor=None):
    """Observed durations only. Missing phase endpoints never become zero."""
    harbor=harbor or {};phase=provenance.get('solverTiming',{})
    def elapsed(start,end):
        if isinstance(start,(int,float)) and isinstance(end,(int,float)) and end>=start:return end-start
        return None
    def duration(value):
        try:
            seconds=(datetime.fromisoformat(value['finished_at'])-datetime.fromisoformat(value['started_at'])).total_seconds()
            return seconds if seconds>=0 else None
        except (KeyError,TypeError,ValueError):return None
    started=provenance.get('executionStartedAt')
    solver=duration(harbor.get('agent_execution') or {})
    if solver is None:solver=elapsed(phase.get('solverStartedAt'),phase.get('solverFinishedAt'))
    return {'timePolicy':provenance.get('recipe',{}).get('timePolicy'),
            'solverTimeSeconds':provenance.get('benchmarkTime',{}).get('solverTimeSeconds'),
            'phaseLimits':provenance.get('benchmarkTime'),
            'availableTimeSeconds':provenance.get('availableTimeSeconds'),
            **{k:phase.get(k) for k in ('solverStartedAt','solverDeadline','benchmarkSolverDeadline','availableTimeAtSolverStartSeconds','effectiveSolverTimeSeconds','deadlineCause')},
            'executionTimeSeconds':elapsed(started,provenance.get('executionFinishedAt')),
            'preparationSeconds':elapsed(started,phase.get('solverStartedAt')),
            'environmentSeconds':duration(harbor.get('environment_setup') or {}),
            'setupSeconds':duration(harbor.get('agent_setup') or {}),
            'solverSeconds':solver,'verifierSeconds':duration(harbor.get('verifier') or {})}
