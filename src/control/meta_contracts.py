"""Exact protocol registry. Historical compositions retain their sealed tools and schemas."""
import hashlib
import json
from pathlib import Path
from .store import Refused,encoded

ROOT=Path(__file__).resolve().parents[2]/'packages/meta-harness'
ROOTS={'meta-tools-v3':ROOT/'protocols/meta-tools-v3','meta-tools-v4':ROOT/'protocols/meta-tools-v4','meta-tools-v5':ROOT/'protocols/meta-tools-v5','meta-tools-v6':ROOT/'protocols/meta-tools-v6','meta-tools-v7':ROOT/'protocols/meta-tools-v7','meta-tools-v8':ROOT/'protocols/meta-tools-v8','meta-tools-v9':ROOT/'protocols/meta-tools-v9','meta-tools-v10':ROOT}
ANALYSES={v:json.loads((root/'report-analysis.schema.json').read_text()) for v,root in ROOTS.items()}
ANALYSIS=ANALYSES['meta-tools-v8']
CONTRACTS={'meta-tools-v2':json.loads((ROOT/'contracts-v2.json').read_text())['operations']}
for v,root in ROOTS.items():
    CONTRACTS[v]=json.loads((root/'contracts.json').read_text())['operations']
    CONTRACTS[v]['report_save']['input']['properties']['analysis']=ANALYSES[v]
for v in ('meta-tools-v4','meta-tools-v5','meta-tools-v6','meta-tools-v7','meta-tools-v8','meta-tools-v9','meta-tools-v10'):
    CONTRACTS[v]['research_save']['input']['properties']['record']=json.loads((ROOTS[v]/'research.schema.json').read_text())

def binding(protocol='meta-tools-v10'):
    root=ROOTS[protocol]
    files=['contracts.json','receipt.schema.json','report-analysis.schema.json','domain-tools.mjs','output-context.mjs']
    if protocol in ('meta-tools-v4','meta-tools-v5','meta-tools-v6','meta-tools-v7','meta-tools-v8','meta-tools-v9','meta-tools-v10'):files.append('research.schema.json')
    return {'version':protocol,'receiptVersion':'meta-tool-receipt-v1','analysisVersion':ANALYSES[protocol]['$id'],
        'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}}

def version(service,campaign):
    ref=service.store.get('campaigns',campaign)['config'].get('metaComposition',{})
    declared=ref.get('toolContract')
    if declared is None:return 'meta-tools-v2'
    protocol=declared.get('version')
    if protocol not in ROOTS or declared!=binding(protocol):raise Refused('Exact frozen Meta tool protocol is unavailable')
    manifest=json.loads((service.data/'meta-compositions'/ref['id']/'manifest.json').read_text())
    if hashlib.sha256(encoded({k:v for k,v in manifest.items() if k!='id'}).encode()).hexdigest()!=ref['id'] or manifest.get('toolContract')!=declared:
        raise Refused('Frozen Meta tool protocol integrity mismatch')
    return protocol

def analysis_for(service,campaign):return ANALYSES.get(version(service,campaign),ANALYSES['meta-tools-v3'])
