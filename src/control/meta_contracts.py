"""Explicit protocol registry. Historical compositions never inherit the latest tools."""
import hashlib
import json
from pathlib import Path
from .store import Refused,encoded

ROOT=Path(__file__).resolve().parents[2]/'packages/meta-harness'
ANALYSIS=json.loads((ROOT/'report-analysis.schema.json').read_text())
CONTRACTS={v:json.loads((ROOT/file).read_text())['operations'] for v,file in
    [('meta-tools-v2','contracts-v2.json'),('meta-tools-v3','contracts.json')]}
# Both model registration and backend validation resolve this one schema.
CONTRACTS['meta-tools-v3']['report_save']['input']['properties']['analysis']=ANALYSIS
def binding():
    return {'version':'meta-tools-v3','receiptVersion':'meta-tool-receipt-v1','analysisVersion':ANALYSIS['$id'],
        'files':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ['contracts.json','receipt.schema.json','report-analysis.schema.json','domain-tools.mjs','output-context.mjs']}}

def version(service,campaign):
    ref=service.store.get('campaigns',campaign)['config'].get('metaComposition',{})
    declared=ref.get('toolContract')
    if declared is None:return 'meta-tools-v2'
    if declared!=binding():raise Refused('Exact frozen Meta tool protocol is unavailable')
    manifest=json.loads((service.data/'meta-compositions'/ref['id']/'manifest.json').read_text())
    if hashlib.sha256(encoded({k:v for k,v in manifest.items() if k!='id'}).encode()).hexdigest()!=ref['id'] or manifest.get('toolContract')!=declared:
        raise Refused('Frozen Meta tool protocol integrity mismatch')
    return declared['version']
