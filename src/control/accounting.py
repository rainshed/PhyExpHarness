"""Reconcile ended workers from trusted host audit, never from Runner claims."""
import json
import io
from src.execution.host.log_store import read_log


def reconcile_audit(store,campaign,lease,file):
    rows=[];contacted=set()
    for line in io.StringIO(read_log(file).decode('utf-8')):
        try:row=json.loads(line)
        except json.JSONDecodeError:continue
        if not isinstance(row,dict) or not isinstance(row.get('id'),str):continue
        if row.get('type') in ('request','admitted','chunk','settled'):contacted.add(row['id'])
        if row.get('type') in ('settled','admission_denied'):rows.append(row)
    # Absence of a request is insufficient evidence. Require the host's explicit
    # pre-provider denial, and refuse to release any contradictory request ID.
    for row in rows:
        if row.get('type')=='settled':
            usage=row.get('usage') or {};confirmed=usage.get('totalTokens')
            unknown=not row.get('finish') or row['finish'].get('kind')=='error' or type(confirmed) is not int
        elif row.get('type')=='admission_denied' and row.get('id') not in contacted:
            failure=row.get('failure') or {}
            if failure.get('source')!='host-admission' or failure.get('stage')!='admission' or failure.get('requestId')!=row.get('id'):continue
            confirmed=0;unknown=False
        else:continue
        try:store.settle(campaign,lease,row['id'],confirmed,unknown,host_audit=True)
        except (KeyError,ValueError):pass
