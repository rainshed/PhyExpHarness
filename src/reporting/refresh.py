"""Append three-table presentation revisions for completed Campaigns, without model calls."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from src.control.paths import data_dir
from src.control.store import Store
from .reports import Reports


def refresh(data, campaign_ids=None):
    data=Path(data);store=Store(data/'control.sqlite');reports=Reports(store,data)
    selected=[c for c in store.list('campaigns') if c['state'] in ['finished','failed'] and (campaign_ids is None or c['id'] in campaign_ids)]
    result={'checkedAt':datetime.now(timezone.utc).isoformat(),'modelCalls':0,'campaigns':[]}
    for c in selected:
        latest={}
        old=store.list('reports',c['id'])
        hashes={r['markdownPath']:hashlib.sha256(Path(r['markdownPath']).read_bytes()).hexdigest() for r in old}
        json_hashes={str(Path(r['markdownPath']).with_name('report.json')):hashlib.sha256(Path(r['markdownPath']).with_name('report.json').read_bytes()).hexdigest() for r in old}
        for r in old:latest[(r['kind'],r['batchId'])]=r
        updated=[]
        for r in latest.values():
            new=reports.refresh_presentation(r['id'])
            assert new['analysis']==r['analysis'] and new['facts']==r['facts'] and new['factsSha256']==r['factsSha256']
            updated.append({'originalReportId':r['id'],'reportId':new['id'],'kind':new['kind'],'batchId':new['batchId'],'markdownPath':new['markdownPath'],'created':new['id']!=r['id']})
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in {**hashes,**json_hashes}.items())
        result['campaigns'].append({'id':c['id'],'reports':updated,'originalReportsUnchanged':True,'originalFileHashes':{**hashes,**json_hashes}})
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir');group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--campaign',action='append');group.add_argument('--all-finished',action='store_true')
    parser.add_argument('--record',required=True)
    args=parser.parse_args();result=refresh(data_dir(args.data_dir),args.campaign)
    record=Path(args.record);record.parent.mkdir(parents=True,exist_ok=True)
    record.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'campaigns':len(result['campaigns']),'newReports':sum(r['created'] for c in result['campaigns'] for r in c['reports']),'modelCalls':0,'record':str(record)},ensure_ascii=False))
