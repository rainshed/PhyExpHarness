"""Complete, sharded global report views for the TensorTrain 2 deployment.

The source facts and their identity are unchanged. Evidence bodies are resolved
through the existing verified evidence_read operation, not eagerly republished.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from .store import encoded, Refused
from src.evidence.files import atomic_json
from src.evidence.snapshots import Snapshots, FORMAT

READING = ('Complete immutable query-tree-v1. Read data, follow format/file.path '
           'references: kind=object fields; kind=list shards then kind=items items '
           'ordered by position; kind=value value. Evidence contains every original '
           'metadata record, not an eager body-availability assertion. Read a body '
           'with evidence_read({id: record.id}); that operation validates '
           'and materializes its authorized file. No evidence record is omitted.')


def _file(ref):
    return {k: ref[k] for k in ('ref', 'path', 'mediaType', 'bytes', 'sha256', 'completeness') if k in ref}


def _verify_node(files, campaign, node):
    ref = node['file']
    relative = Path(ref['path'].lstrip('/'))
    if relative.parts[:2] != ('materials', 'objects') or '..' in relative.parts:
        raise Refused('Invalid facts view path')
    path = files.directory(campaign) / relative
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
        raise Refused('Facts view integrity mismatch')


def facts_node(files, campaign, facts_id, facts, evidence_id=None):
    from .meta_receipts import public
    index = files.service.data/'campaigns'/campaign/'report-views'/(facts_id+'.json')
    if index.exists():
        saved = json.loads(index.read_text())
        if saved['factsId'] != facts_id:
            raise Refused('Facts view identity mismatch')
        _verify_node(files, campaign, saved['node'])
        return saved['node']
    tree = Snapshots(files, campaign)
    fields = {k: tree.node(public(v)) for k, v in facts.items() if k != 'evidence'}
    rows = facts['evidence']
    evidence_id = evidence_id or hashlib.sha256(encoded(rows).encode()).hexdigest()
    evidence_index = index.parent/('evidence-metadata-v1-'+evidence_id+'.json')
    if evidence_index.exists():
        saved = json.loads(evidence_index.read_text())
        if saved['evidenceId'] != evidence_id: raise Refused('Evidence metadata identity mismatch')
        _verify_node(files, campaign, saved['node'])
        fields['evidence'] = saved['node']
    else:
        shards = []
        # Fixed ordered pages avoid repeatedly encoding the entire large list and
        # never limit the number of pages or silently truncate a large record.
        for start in range(0, len(rows), 1024):
            items = [{'position': i, 'value': public(rows[i])}
                     for i in range(start, min(start+1024, len(rows)))]
            shards.append({'bucket': str(start), **tree.save({'format': FORMAT, 'kind': 'items', 'items': items})})
        fields['evidence'] = tree.save({'format': FORMAT, 'kind': 'list', 'count': len(rows), 'shards': shards})
        atomic_json(evidence_index, {'evidenceId': evidence_id, 'node': fields['evidence']})
    node = tree.save({'format': FORMAT, 'kind': 'object', 'fields': fields})
    atomic_json(index, {'factsId': facts_id, 'node': node})
    return node


def global_facts(api, campaign, batch_id=None):
    facts = api.service.reports.facts(campaign, batch_id)
    # Encode each original value once. Reuse the exact evidence fragment for its
    # cache key; a state/version race cannot associate a changed row with old data.
    evidence = encoded(facts['evidence']).encode('utf-8')
    evidence_id = hashlib.sha256(evidence).hexdigest()
    body = b'{'+b','.join(encoded(k).encode()+b':'+(evidence if k=='evidence' else encoded(facts[k]).encode())
                         for k in sorted(facts))+b'}'
    del evidence
    facts_id = hashlib.sha256(body).hexdigest()
    directory = api.service.data/'campaigns'/campaign/'report-facts'
    directory.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(dir=directory, prefix='.publishing-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            # Identical canonical JSON to encoded({'facts': facts, 'batchId': batch_id}).
            stream.write(b'{"batchId":'+encoded(batch_id).encode()+b',"facts":'); stream.write(body); stream.write(b'}\n')
        os.replace(pending, directory/(facts_id+'.json'))
    finally:
        if os.path.exists(pending): os.unlink(pending)
    del body
    node = facts_node(api.files, campaign, facts_id, facts, evidence_id)
    tree = Snapshots(api.files, campaign)
    view = tree.save({'format': FORMAT, 'operation': 'report_get_facts', 'filters': {'batchId':batch_id} if batch_id else {},
                      'sourceFactsId': facts_id, 'reading': READING, 'data': node})
    return {'factsId': facts_id, 'batchId': batch_id, 'file': view['file'],
            **api.receipts.report_navigation(campaign)}


def report_view(receipts, campaign, row):
    from .meta_receipts import public
    tree = Snapshots(receipts.files, campaign)
    fields = {k: tree.node(public(v)) for k, v in row.items() if k != 'facts'}
    fields['facts'] = facts_node(receipts.files, campaign, row['factsSha256'], row['facts'])
    return tree.save({'format': FORMAT, 'operation': 'report_get', 'filters': {'reportId': row['id']},
                      'reading': READING, 'data': fields})['file']
