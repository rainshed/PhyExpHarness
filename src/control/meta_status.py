"""Small, read-only Meta health projection for activity lists and detail views."""
from src.execution.host.failure import public_failure


def meta_status(sessions):
    if not sessions:
        return None
    # Store.list returns insertion order; an older failed session is not current health.
    latest = sessions[-1]
    recovery = latest.get('recovery') or {}
    summary = latest.get('summary') or {}
    failure = recovery.get('failure') or summary.get('failure') or {}
    public = public_failure(failure) if failure else None
    transport = (failure.get('observed') or {}).get('transport') or {}
    return {
        'sessionId': latest['id'], 'state': latest['state'],
        'recoveryReason': recovery.get('reason'),
        'recoveryRequested': recovery.get('userResumedAt') is not None,
        'failure': {k: public[k] for k in ('code', 'message', 'detectedAt') if k in public} if public else None,
        'connectionTimedOut': transport.get('errorCode') in ('ETIMEDOUT', 'UND_ERR_CONNECT_TIMEOUT'),
    }
