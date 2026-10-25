"""Versioned resource plans. User ceilings and accepted execution conditions stay separate."""
import json
from pathlib import Path
from src.execution.host.single_run import TRIAL_CLOSEOUT_RESERVE_SECONDS
from src.execution.host.task_time import benchmark_time, POLICY as BENCHMARK_TIME

from .model_access import control_only, TOKEN_FIELDS

def limit_keys(config):
    return tuple(k for k in LIMITS if not control_only(config) or k not in TOKEN_FIELDS)

POLICY = 'meta-resource-planning-v1'
LIMITS = ('maxRounds', 'maxTrials', 'concurrency', 'wallTimeSeconds', 'trialTimeSeconds',
          'softTokenLimit', 'reserveSeconds', 'reserveTokens', 'stopMode', 'drainGraceSeconds')
FIELDS = ('parallelism', 'defaultTrialTimeSeconds', 'closeoutReserveSeconds', 'closeoutReserveTokens')

def execution_time_policy():
    return {'version':'trial-closeout-v1','trialCloseoutReserveSeconds':TRIAL_CLOSEOUT_RESERVE_SECONDS,
            'minimumTrialTimeSeconds':TRIAL_CLOSEOUT_RESERVE_SECONDS+1,
            'scope':'Trial time includes startup, Solver, official verification and cleanup; startup also consumes time.'}


def trial_closeout(campaign):
    if benchmark_time(campaign['config']):return 0
    # Activities created before this metadata existed used the same fixed 330-second reserve.
    return campaign['config'].get('executionTimePolicy',{'trialCloseoutReserveSeconds':330})['trialCloseoutReserveSeconds']


def enabled(config):
    return config.get('resourcePolicy') == POLICY


def end_time(campaign):
    config = campaign['config']
    return campaign['deadline'] + (config['drainGraceSeconds'] if config['stopMode'] == 'drain' else 0)


def reserves(campaign):
    cfg = campaign['config']
    if not enabled(cfg):
        return cfg['reserveSeconds'], cfg['reserveTokens']
    plan = campaign.get('resourcePlan') or {}
    return (max(cfg['reserveSeconds'], plan.get('closeoutReserveSeconds', 0)),
            max(cfg['reserveTokens'], plan.get('closeoutReserveTokens', 0)) if cfg.get('softTokenLimit') is not None else 0)


def validate_plan(campaign, value):
    from .store import Refused
    cfg = campaign['config']
    fields=tuple(k for k in FIELDS if (k!='defaultTrialTimeSeconds' or not benchmark_time(cfg)) and (k!='closeoutReserveTokens' or not control_only(cfg)))
    if set(value) != set(fields):
        raise Refused('Plan requires exactly: ' + ', '.join(fields))
    for key in fields:
        if type(value[key]) is not int or value[key] < (0 if key.startswith('closeout') else 1):
            raise Refused('Invalid plan field: ' + key)
    if value['parallelism'] > cfg['concurrency']:
        raise Refused('Plan parallelism exceeds configured concurrency ceiling')
    ceiling = cfg['trialTimeSeconds'] or cfg['wallTimeSeconds'] + (cfg['drainGraceSeconds'] if cfg['stopMode'] == 'drain' else 0)
    if not benchmark_time(cfg) and value['defaultTrialTimeSeconds'] > ceiling:
        raise Refused('Plan trial time exceeds configured execution ceiling')
    if not benchmark_time(cfg) and value['defaultTrialTimeSeconds'] <= trial_closeout(campaign):
        raise Refused('Trial time must exceed fixed verification/cleanup reserve: '+str(trial_closeout(campaign))+' seconds')
    if value['closeoutReserveSeconds'] >= cfg['wallTimeSeconds']:
        raise Refused('Plan closeout time must be less than total time')
    if cfg.get('softTokenLimit') is None:
        if value.get('closeoutReserveTokens',0):
            raise Refused('Unlimited tokens require zero token closeout reservation')
    elif value['closeoutReserveTokens'] >= cfg.get('softTokenLimit'):
        raise Refused('Plan closeout tokens must be less than total tokens')
    return dict(value)


def trial_settings(campaign, candidate, execution=None):
    from .store import Refused
    plan = campaign.get('resourcePlan')
    if not plan:
        raise Refused('Submit a resource plan before accepting experiments')
    execution = execution or {}
    if benchmark_time(campaign['config']):
        if execution:raise Refused('Benchmark owns task time; batch overrides and shortening are unavailable')
        return {'solver':campaign['config']['solver'],'timePolicy':BENCHMARK_TIME,
                'resourcePlanRevision':plan['revision'],'userLimitsRevision':campaign.get('userLimitsRevision',1)}
    if set(execution) - {'trialTimeSeconds', 'allowShortened'}:
        raise Refused('Unknown batch execution setting')
    seconds = execution.get('trialTimeSeconds', plan['defaultTrialTimeSeconds'])
    if type(seconds) is not int or seconds <= 0 or type(execution.get('allowShortened', False)) is not bool:
        raise Refused('Invalid batch execution setting')
    cfg = campaign['config']
    if cfg['trialTimeSeconds'] is not None and seconds > cfg['trialTimeSeconds']:
        raise Refused('Batch trial time exceeds configured ceiling')
    if seconds <= trial_closeout(campaign):
        raise Refused('Batch time cannot fit fixed verification/cleanup reserve')
    recipe = Path(candidate['bundlePath']) / 'recipe.json'
    frozen = json.loads(recipe.read_text())['agentTimeoutSec'] if recipe.is_file() else cfg['trialTimeSeconds'] or cfg['wallTimeSeconds']
    if seconds > frozen:
        raise Refused('Batch trial time exceeds frozen recipe ceiling: ' + str(frozen))
    return {'solver': cfg['solver'], 'trialTimeSeconds': seconds,
            'allowShortened': execution.get('allowShortened', False),
            'resourcePlanRevision': plan['revision'], 'userLimitsRevision': campaign.get('userLimitsRevision', 1),
            'frozenTrialCeilingSeconds': frozen,'trialCloseoutReserveSeconds':trial_closeout(campaign)}


def feasibility(campaign,trial,now):
    """Current wall-clock conditions; never shorten the benchmark or choose a task."""
    if trial.get('state')!='reserved' or not benchmark_time(campaign['config']):return None
    timing=trial.get('executionSettings',{}).get('benchmarkTime') or campaign['config']['taskTimeLimits'][trial['task']]
    required=timing['requiredTimeSeconds'];end=end_time(campaign)
    latest=min(end-required,campaign['deadline']-reserves(campaign)[0]) if required is not None else None
    available=max(0,end-now)
    feasible=latest is not None and now<campaign['deadline']-reserves(campaign)[0] and now<=latest
    return {'state':'waiting_resources' if feasible else 'currently_infeasible','reason':None if feasible else 'benchmark_time_unavailable',
        'requiredSeconds':required,'availableSeconds':available,'latestStartAt':latest,'observedAt':now,
        'solverTimeSeconds':timing['solverTimeSeconds'],'canShorten':False,
        'nextAction':'等待调度名额' if feasible else '撤回未启动项，或在授权范围内调整活动截止时间'}


def pending_view(campaign,trials,now):
    return [{**t,**({'scheduling':feasibility(campaign,t,now)} if t.get('state')=='reserved' and benchmark_time(campaign['config']) else {})} for t in trials]


def view(campaign, trials=(), now=None):
    import time
    now=time.time() if now is None else now
    cfg = campaign['config']
    if not enabled(cfg):
        return {'policy': 'legacy', 'configurationSources': {key: {'source': 'legacy_unverified'} for key in LIMITS}}
    plan = campaign.get('resourcePlan')
    return {'policy': POLICY, 'plan': plan, 'planRevision': (plan or {}).get('revision', 0),
            'effectiveParallelism': min(cfg['concurrency'],plan['parallelism']) if plan else 0,
            'userLimitsRevision': campaign.get('userLimitsRevision', 1),
            'configurationSources': cfg.get('configurationSources', {}),
            'executionTimePolicy':cfg.get('executionTimePolicy',execution_time_policy()),
            'suggestions': {'parallelism': cfg['concurrency'],
                **({} if benchmark_time(cfg) else {'defaultTrialTimeSeconds': min(3600, cfg['trialTimeSeconds'] or cfg['wallTimeSeconds'])}),
                'closeoutReserveSeconds': 0, **({} if control_only(cfg) else {'closeoutReserveTokens':0})},
            'taskTimeLimits':cfg.get('taskTimeLimits',{}),
            'effectiveReserves': {'seconds':reserves(campaign)[0],**({} if control_only(cfg) else {'tokens':reserves(campaign)[1]})},
            'schedulingWait':campaign.get('resourcePlanWait'),
            'pendingTrials':[{'trialId':t['id'],**feasibility(campaign,t,now)} for t in trials if feasibility(campaign,t,now) is not None],
            'runningConditions': [{k: t.get(k) for k in ('id', 'task', 'deadline', 'effectiveConditions', 'launchLimits')}
                                  for t in trials if t['state'] in ('launching', 'running')],
            'updateScope': 'Future batches; accepted conditions remain fixed. Running processes do not receive increased ceilings.'}
