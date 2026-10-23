"""Host-only native snapshots. Public catalog contains no raw provider configuration."""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from ..store import Refused,encoded
from .plugins import descriptor

HARNESS={
 'codex':{'id':'codex','name':'Codex','version':'0.155.0','package':'@openai/codex','wire':'responses'},
 'claude-code':{'id':'claude-code','name':'Claude Code','version':'2.1.280','package':'@anthropic-ai/claude-code','wire':'anthropic'},
 'dsh-standard':{'id':'dsh-standard','name':'DeepSeek Harness 标准模式','version':'0.2.1-rc.2','package':'@deepseek-ai/dsh','wire':'native','profile':'dsh-base + dsh-sdk-app'},
}

def atomic_private(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:stream.write(encoded(value))
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

class Catalog:
    def __init__(self,service):
        self.service=service;self.root=service.data/'reference-native';self.file=self.root/'catalog.json';self.lock=threading.RLock()
    def sync(self,document):
        with self.lock:return self._sync(document)
    def _sync(self,document):
        if document.get('version')!='native-reference-catalog-v1' or not isinstance(document.get('bindings'),list) or len(document['bindings'])>4096:raise Refused('Invalid native catalog')
        public=[]
        for row in document['bindings']:
            frozen=row['frozen'];id=row['id']
            if not isinstance(id,str) or len(id)!=71 or not id.startswith('native-') or any(x not in '0123456789abcdef' for x in id[7:]):raise Refused('Invalid native binding')
            if frozen.get('adapter') not in ('pi-ai','deepseek-api-key') or frozen.get('pluginVersion')!='0.2.1-rc.2':raise Refused('Unsupported native adapter')
            if frozen['call'].get('provider')!=row['provider'] or frozen['call'].get('model')!=row['model']:raise Refused('Native identity mismatch')
            content=encoded(frozen);digest=hashlib.sha256(content.encode()).hexdigest();id='native-'+digest
            path=self.root/'bindings'/(id+'.json')
            if path.exists() and json.loads(path.read_text())!=frozen:raise Refused('Native binding is immutable')
            atomic_private(path,frozen)
            # Credential rotation updates only the private credential handle, never the model config.
            if row.get('credential'):atomic_private(self.root/'credentials'/(id+'.json'),row['credential'])
            else:(self.root/'credentials'/(id+'.json')).unlink(missing_ok=True)
            public.append({k:row.get(k) for k in ('id','label','provider','model','unavailable')}|{'id':id,'digest':digest,'source':'deepseek-harness-native'})
            name=row['model'].lower()
            if name in ('auto','default','best','sonnet','opus','haiku') or name.endswith(('-latest',':latest')):
                public[-1]['unavailable']='请配置具体模型版本；参考实验不接受浮动模型别名'
        revision=hashlib.sha256(encoded(public).encode()).hexdigest()
        atomic_private(self.file,{'revision':revision,'models':public})
        return {'revision':revision,'count':len(public)}
    def read(self):return json.loads(self.file.read_text()) if self.file.exists() else {'revision':'unavailable','models':[]}
    def binding(self,id):
        if not isinstance(id,str) or len(id)!=71 or not id.startswith('native-') or any(c not in '0123456789abcdef' for c in id[7:]):raise Refused('Invalid native model reference')
        try:return json.loads((self.root/'bindings'/(id+'.json')).read_text())
        except OSError as error:raise Refused('Frozen native model unavailable') from error
    def public(self):
        result=self.read();installed={}
        for axis in ('model','harness'):
            try:descriptor(self.service.source,axis);installed[axis]=True
            except Refused:installed[axis]=False
        matrix=[]
        for model in result['models']:
            for harness in HARNESS:
                try:check=self.service.references.compatibility({'config':{}},model['id'],harness)
                except (ValueError,KeyError,OSError):check={'state':'temporarily-unavailable','reason':'Native snapshot unavailable'}
                matrix.append({'modelRef':model['id'],'harnessRef':harness,**check})
        return {**result,'compatibility':matrix,'plugins':installed,'harnesses':list(HARNESS.values()),'source':'DeepSeek Harness native Models settings'}
