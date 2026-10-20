"""Versioned resource plans. User ceilings and accepted execution conditions stay separate."""
import json
from pathlib import Path
from src.execution.host.single_run import TRIAL_CLOSEOUT_RESERVE_SECONDS

POLICY = 'meta-resource-planning-v1'
LIMITS = ('maxRounds', 'maxTrials', 'concurrency', 'wallTimeSeconds', 'trialTimeSeconds',
          'softTokenLimit', 'reserveSeconds', 'reserveTokens', 'stopMode', 'drainGraceSeconds')
FIELDS = ('parallelism', 'defaultTrialTimeSeconds', 'closeoutReserveSeconds', 'closeoutReserveTokens')

def execution_time_policy():
    return {'version':'trial-closeout-v1','trialCloseoutReserveSeconds':TRIAL_CLOSEOUT_RESERVE_SECONDS,
            'minimumTrialTimeSeconds':TRIAL_CLOSEOUT_RESERVE_SECONDS+1,
            'scope':'Trial time includes startup, Solver, official verification and cleanup; startup also consumes time.'}


def trial_closeout(campaign):
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
            max(cfg['reserveTokens'], plan.get('closeoutReserveTokens', 0)) if cfg['softTokenLimit'] is not None else 0)


def validate_plan(campaign, value):
    from .store import Refused
    cfg = campaign['config']
    if set(value) - set(FIELDS) or set(FIELDS) - set(value):
        raise Refused('Plan requires exactly: ' + ', '.join(FIELDS))
    for key in FIELDS:
        if type(value[key]) is not int or value[key] < (0 if key.startswith('closeout') else 1):
            raise Refused('Invalid plan field: ' + key)
    if value['parallelism'] > cfg['concurrency']:
        raise Refused('Plan parallelism exceeds configured concurrency ceiling')
    ceiling = cfg['trialTimeSeconds'] or cfg['wallTimeSeconds'] + (cfg['drainGraceSeconds'] if cfg['stopMode'] == 'drain' else 0)
    if value['defaultTrialTimeSeconds'] > ceiling:
        raise Refused('Plan trial time exceeds configured execution ceiling')
    if value['defaultTrialTimeSeconds'] <= trial_closeout(campaign):
        raise Refused('Trial time must exceed fixed verification/cleanup reserve: '+str(trial_closeout(campaign))+' seconds')
    if value['closeoutReserveSeconds'] >= cfg['wallTimeSeconds']:
        raise Refused('Plan closeout time must be less than total time')
    if cfg['softTokenLimit'] is None:
        if value['closeoutReserveTokens']:
            raise Refused('Unlimited tokens require zero token closeout reservation')
    elif value['closeoutReserveTokens'] >= cfg['softTokenLimit']:
        raise Refused('Plan closeout tokens must be less than total tokens')
    return dict(value)


def trial_settings(campaign, candidate, execution=None):
    from .store import Refused
    plan = campaign.get('resourcePlan')
    if not plan:
        raise Refused('Submit a resource plan before accepting experiments')
    execution = execution or {}
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


def view(campaign, trials=()):
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
                'defaultTrialTimeSeconds': min(3600, cfg['trialTimeSeconds'] or cfg['wallTimeSeconds']),
                'closeoutReserveSeconds': 0, 'closeoutReserveTokens': 0},
            'effectiveReserves': dict(zip(('seconds', 'tokens'), reserves(campaign))),
            'schedulingWait':campaign.get('resourcePlanWait'),
            'runningConditions': [{k: t.get(k) for k in ('id', 'task', 'deadline', 'effectiveConditions', 'launchLimits')}
                                  for t in trials if t['state'] in ('launching', 'running')],
            'updateScope': 'Future batches; accepted conditions remain fixed. Running processes do not receive increased ceilings.'}
