"""Immutable query trees: stable shards share records across successive snapshots."""
import hashlib
from src.control.store import encoded

FORMAT = 'query-tree-v1'


class Snapshots:
    def __init__(self, files, campaign):
        self.files=files;self.campaign=campaign

    def save(self, value):
        data=encoded(value)
        descriptor=self.files.publish(self.campaign,'snapshot:'+hashlib.sha256(data.encode()).hexdigest(),data,
            kind='query',source={'archive':'snapshot.json'},version=FORMAT)
        return {'format':FORMAT,'file':{k:descriptor[k] for k in ('ref','path','mediaType','bytes','sha256','completeness')}}

    def node(self, value):
        if len(encoded(value).encode()) <= 4096: return value
        if isinstance(value, list):
            buckets={}
            for index,item in enumerate(value):
                identity=next((str(item[k]) for k in ('id','ref','recordId','trialId') if isinstance(item,dict) and item.get(k) is not None),str(index))
                bucket=hashlib.sha256(identity.encode()).hexdigest()[:2]
                buckets.setdefault(bucket,[]).append({'position':index,'value':self.node(item)})
            shards=[{'bucket':key,**self.save({'format':FORMAT,'kind':'items','items':rows})} for key,rows in sorted(buckets.items())]
            return self.save({'format':FORMAT,'kind':'list','count':len(value),'shards':shards})
        if isinstance(value,dict):return self.save({'format':FORMAT,'kind':'object','fields':{k:self.node(v) for k,v in value.items()}})
        return self.save({'format':FORMAT,'kind':'value','value':value})

    def publish(self, operation, filters, value):
        # No observation timestamp in immutable identity. A -> B -> A reuses A.
        return self.save({'format':FORMAT,'operation':operation,'filters':filters,
            'reading':'References have format=query-tree-v1 and file.path. Read kind=object fields; kind=list shards then kind=items items ordered by position; kind=value value. All files are complete immutable JSON.',
            'data':{k:self.node(v) for k,v in value.items()} if isinstance(value,dict) else self.node(value)})['file']
