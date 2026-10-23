"""Meta technical recovery is separate from Solver request/scientific retries."""
# Host-owned backoff; replacing a frozen Meta plugin does not change this policy.
DELAYS=(2,5,10,20,30,60)
NONRECOVERABLE={'model_authentication','model_permission','model_invalid_request','request_cancelled',
    'model_auth_error','model_permission_error','model_invalid_request_error','model_configuration_error',
    'trial_deadline','token_limit','budget_exhausted','budget_admission_denied','admission_denied','integrity_error',
    'accounting_auth_failed','accounting_lease_expired'}

def recovery(summary,attempt,now,deadline,stopped=False):
    failure=summary.get('failure') or {};code=failure.get('code','')
    text=str(summary.get('error','')).lower()
    status=failure.get('observed',{}).get('transport',{}).get('httpStatus')
    denied=stopped or code in NONRECOVERABLE or status in [400,401,403,404,422] or any(word in text for word in ['integrity mismatch','identity mismatch','permission denied','unauthorized','authentication','budget exhausted','required plugin failed','missing dependency','restore matching'])
    if denied or attempt>=len(DELAYS) or now+DELAYS[attempt]>=deadline:
        return {'state':'needs_attention','automaticRecovery':False,'failure':failure,'reason':'nonrecoverable' if denied else 'recovery_exhausted'}
    return {'state':'recovering','automaticRecovery':True,'retryAt':now+DELAYS[attempt],'nextAttempt':attempt+1,'failure':failure}
