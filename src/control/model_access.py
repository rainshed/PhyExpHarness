"""Model access without usage accounting. Older frozen activities keep their protocol."""
POLICY = 'control-only-v1'
TOKEN_FIELDS = ('softTokenLimit', 'reserveTokens', 'hardTokenLimit', 'dollarLimit')


def control_only(config):
    return config.get('modelAccessPolicy') == POLICY


def check_config(config):
    from .store import Refused
    if config.get('softTokenLimit') is not None or any(config.get(key) not in (None, 0) for key in TOKEN_FIELDS[1:]):
        raise Refused('Token accounting and token budgets have been removed; use time and Trial limits')
    policy=config.get('referencePolicy', {})
    if not isinstance(policy,dict) or not isinstance(policy.get('limits',{}),dict):raise Refused('Invalid reference policy')
    for limits in policy.get('limits', {}).values():
        if not isinstance(limits,dict):raise Refused('Invalid reference limits')
        if limits.get('softTokenLimit') is not None:
            raise Refused('Reference token budgets have been removed; use Trial limits')


def environment(base, lease, token, config):
    if control_only(config):
        return {'PHYEXP_MODEL_ACCESS_URL': base+'/model-access/'+lease,
                'PHYEXP_MODEL_ACCESS_TOKEN': token, 'PHYEXP_ACCOUNTING_URL': '', 'PHYEXP_ACCOUNTING_TOKEN': '', 'PHYEXP_RUN_TOKEN_LIMIT': ''}
    return {'PHYEXP_ACCOUNTING_URL': base+'/accounting/'+lease,
            'PHYEXP_ACCOUNTING_TOKEN': token, 'PHYEXP_MODEL_ACCESS_URL': '', 'PHYEXP_MODEL_ACCESS_TOKEN': ''}


def check_access(store, lease, agent_id=None):
    """Read-only authorization; no reservation, admission record, or settlement."""
    from .store import Refused
    from .resource_planning import end_time
    with store.read_snapshot():
        owner = store.get('leases', lease)
        c = store.get('campaigns', owner['campaignId'])
        if not control_only(c['config']):
            raise Refused('Frozen activity requires its original model access protocol')
        role = owner['role']
        if role not in ('meta', 'solver'):
            raise Refused('Model access role mismatch')
        if owner.get('revoked') or c['state'] in ('draft', 'finished', 'failed', 'deleting') or (role == 'meta' and c['state'] == 'paused'):
            return {'status': 'denied', 'code': 'request_cancelled'}
        deadline = end_time(c) if role == 'solver' else c['deadline']
        if store.clock() >= min(owner['deadline'], deadline):
            return {'status': 'denied', 'code': 'trial_deadline' if role == 'solver' else 'campaign_deadline'}
        if role == 'meta':
            sessions = store.list('meta_sessions', c['id'])
            if not isinstance(agent_id,str) or not any(s['leaseId'] == lease and agent_id in s.get('agents', {}) for s in sessions):
                raise Refused('Unregistered model caller')
        return {'status': 'granted'}
