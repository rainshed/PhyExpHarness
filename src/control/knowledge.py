"""Read-only SDK access. Never introspects the credential-bearing UI/control host."""
import hashlib,json
from pathlib import Path
class KnowledgePack:
    def __init__(self,path,version,profile_digest=None):
        self.path=Path(path);self.manifest=json.loads((self.path/'manifest.json').read_text())
        identity={k:v for k,v in self.manifest.items() if k!='id'}
        if hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()!=self.manifest['id']: raise ValueError('Knowledge manifest integrity mismatch')
        for item in self.manifest['documents'].values():
            target=(self.path/item['file'])
            if target.is_symlink() or not target.resolve().is_relative_to(self.path.resolve()):raise ValueError('Knowledge path escapes pack')
        if self.manifest['dshVersion']!=version: raise ValueError('SDK version mismatch')
        if profile_digest and self.manifest['profileDigest']!=profile_digest: raise ValueError('Execution profile mismatch')
    def read(self,id,offset=0,limit=16000):
        if id not in self.manifest['documents']: raise ValueError('Document unavailable')
        entry=self.manifest['documents'][id]; text=(self.path/entry['file']).read_text()
        if hashlib.sha256(text.encode()).hexdigest()!=entry['sha256']: raise ValueError('Knowledge integrity mismatch')
        if not isinstance(offset,int) or offset<0 or not isinstance(limit,int) or not 1<=limit<=32000: raise ValueError('Invalid range')
        return {'id':id,'source':entry['source'],'version':self.manifest['dshVersion'],'packId':self.manifest['id'],'sha256':entry['sha256'],'profileDigest':self.manifest['profileDigest'],'offset':offset,'total':len(text),'text':text[offset:offset+limit]}
    def search(self,query):
        if not isinstance(query,str) or not query or len(query)>200: raise ValueError('Invalid query')
        matches=[]
        for id in self.manifest['documents']:
            offset=0
            while True:
                item=self.read(id,offset,32000);pos=item['text'].lower().find(query.lower())
                if pos>=0:
                    matches.append({'id':id,'source':item['source'],'offset':offset+pos,'excerpt':item['text'][max(0,pos-80):pos+240]});break
                offset+=32000
                if offset>=item['total']:break
        return {'pack':self.manifest['id'],'matches':matches}
    def inspect(self,name):
        doc=self.manifest['api'].get(name)
        return {'name':name,'version':self.manifest['dshVersion'],'profileDigest':self.manifest['profileDigest'],
          'availability':'declared-in-execution-sdk' if doc else 'unavailable','document':doc,'readOnly':True}
