"""Reference authority and overlapping caps; never contributes to candidate scores."""
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
from ..store import Refused, Conflict, encoded

SCHEMA=json.loads((Path(__file__).resolve().parents[3]/'schemas/reference/policy.schema.json').read_text())
DEFAULT={'version':'meta-reference-v1','modelEnabled':False,'harnessEnabled':False,'modelRefs':[],
         'harnessRefs':[],'selectionMode':'meta-select','pairs':[],'limits':{},'catalogRevision':'unavailable'}
TERMINAL={'finished','failed','cancelled','unknown'}

def validate(policy):
    try:Draft202012Validator(SCHEMA).validate(policy)
    except ValidationError as error:raise Refused('Reference policy: '+error.message) from error
    if policy['modelEnabled'] and not policy['modelRefs']:raise Refused('Select at least one native reference model')
    if policy['harnessEnabled'] and not policy['harnessRefs']:raise Refused('Select at least one reference Harness')
    for pair in policy['pairs']:
        if pair['modelRef'] not in policy['modelRefs'] or pair['harnessRef'] not in policy['harnessRefs']:raise Refused('Pinned pair outside allowlist')
    if policy['modelEnabled'] and policy['harnessEnabled'] and policy['selectionMode']=='pinned-pairs' and not policy['pairs']:
        raise Refused('Select at least one pinned pair')
    return json.loads(encoded(policy))

def effective(c):return c.get('referencePolicy') or {**c['config'].get('referencePolicy',DEFAULT),'revision':1}
def enabled(policy,capabilities):return all(policy.get(axis+'Enabled',False) for axis in capabilities)
def charged(row):return row['state']!='cancelled' or row.get('startedAt') is not None

def admit_reference(store,db,c,reference,planned):
    policy=effective(c)
    if reference['policyRevision']!=policy['revision']:raise Conflict('Reference policy revision changed')
    if not enabled(policy,reference['requiredCapabilities']):raise Refused('Required reference plugin disabled')
    frozen=c['config'].get('referenceBindings',{})
    if reference.get('modelRef') and reference['modelRef'] not in policy['modelRefs']:raise Refused('Model outside reference allowlist')
    if reference.get('harnessRef') and reference['harnessRef'] not in policy['harnessRefs']:raise Refused('Harness outside reference allowlist')
    if reference['mode']=='joint-reference' and policy['selectionMode']=='pinned-pairs' and {'modelRef':reference['modelRef'],'harnessRef':reference['harnessRef']} not in policy['pairs']:raise Refused('Pair not selected')
    if reference.get('modelRef') and reference['modelRef'] not in frozen.get('models',{}):raise Refused('Model snapshot unavailable')
    if reference.get('harnessRef') and reference['harnessRef'] not in frozen.get('harnesses',{}):raise Refused('Harness snapshot unavailable')
    # H0 reserves the baseline first, even if a reference request races the scheduler.
    if not store._list(db,'batches',c['id']):raise Refused('Main H0 baseline must be reserved first')
    for axis in reference['requiredCapabilities']:
        cap=policy.get('limits',{}).get(axis,{}).get('maxTrials')
        used=sum(charged(t) and axis in t['reference']['requiredCapabilities'] for t in store._list(db,'reference_runs',c['id']))
        if cap is not None and used+planned>cap:raise Refused('Reference '+axis+' Trial limit reached')

def token_admission(store,db,c,owner,reserved):
    id=owner.get('trialId') or ''
    if not id.startswith('reference-run-'):return {}
    run=store._get(db,'reference_runs',id)
    # Disabling drains existing leases; only explicit stop revokes them.
    for axis in run['reference']['requiredCapabilities']:
        cap=effective(c).get('limits',{}).get(axis,{}).get('softTokenLimit')
        if cap is None:continue
        runs={t['id'] for t in store._list(db,'reference_runs',c['id']) if axis in t['reference']['requiredCapabilities']}
        leases={x['id'] for x in store._list(db,'leases',c['id']) if x.get('trialId') in runs}
        rows=[u for u in store._list(db,'usage',c['id']) if u['leaseId'] in leases]
        used=sum((u.get('confirmedTokens') or 0)+(u['reservedTokens'] if u['status']=='unknown' else 0) for u in rows)
        active=sum(u['reservedTokens'] for u in rows if u['status']=='inflight')
        if used+reserved>cap:return {'status':'denied','code':'budget_admission_denied','boundary':'reference_'+axis}
        if used+active+reserved>cap:return {'status':'waiting','code':'budget_inflight_wait','boundary':'reference_'+axis,'retryAfterMs':500}
    return {}

def release_cancelled_slots(store,db,c):
    counts=store._counts(db,c['id']);cfg=c['config']
    # Only admission closed by reserving the last Trial may reopen. Rounds,
    # user stop, time exhaustion and finished activities never reset.
    if c.get('stopReason')=='trial_limit' and c['state'] in ('running','closing') and counts['trials']<cfg['maxTrials'] and (cfg['maxRounds'] is None or counts['rounds']<cfg['maxRounds']) and store.clock()<c['deadline']:
        c.update(state='running',explorationClosed=False,stopReason=None);store._save(db,'campaigns',c)
        store._event(db,c['id'],'reference_reservations_released',counts=counts)
