"""v5 model-facing boundary. Full results live in files, including replay/errors."""
import hashlib
import traceback
import sqlite3
from .database import busy as database_busy
from .store import Refused,Conflict,encoded
from .meta_receipts import receipt,compact

PAGE_TOOLS={'evidence_read','materials_read'}
PAGE_BYTES=48*1024
IDENTITIES=('operationId','batchId','trialId','candidateId','campaignId','reportId','factsId',
            'recordId','requestId','decisionId','reviewId','state','kind')

class ToolBoundary:
    def __init__(self,api):self.api=api
    def publish(self,campaign,operation,value):
        # Keep the complete authorized result, including long diagnostics. Unlike
        # a status index, this is not a lossy projection of its source record.
        data=encoded(value)
        return self.api.files.publish(campaign,'tool:'+operation+':'+hashlib.sha256(data.encode()).hexdigest(),
            data,kind='query',source={'archive':'tool-result.json'})
    def project(self,campaign,operation,value):
        if isinstance(value,dict) and value.get('receiptVersion')=='meta-tool-receipt-v1':
            # Revalidate even replayed receipts before allowing the fast path.
            return receipt(**{k:v for k,v in value.items() if k!='receiptVersion'})
        if operation in PAGE_TOOLS and isinstance(value,dict) and isinstance(value.get('text'),str):
            # Metadata must not smuggle a large source/diagnostic into a page.
            result={k:value[k] for k in ('offset','offsetUnit','total','nextOffset','text','encoding') if k in value}
            result.update(compact(value));result['offsetUnit']='characters'
            while len(encoded(result).encode())>PAGE_BYTES and result['text']:
                result['text']=result['text'][:max(0,len(result['text'])//2)]
                result['nextOffset']=result.get('offset',0)+len(result['text'])
            if len(encoded(result).encode())<=PAGE_BYTES:return result
        file=self.publish(campaign,operation,value)
        fields={k:v for k,v in value.items() if k in IDENTITIES and isinstance(v,str) and len(v)<=200} if isinstance(value,dict) else {}
        if isinstance(value,dict):
            for key in ('total','nextOffset','revision','planRevision','selectionRevision'):
                if key in value and (type(value[key]) is int and value[key]>=0 or key=='nextOffset' and value[key] is None):fields[key]=value[key]
            if 'id' in value and isinstance(value['id'],str) and len(value['id'])<=200:
                key='batchId' if operation.endswith(('_submit','_cancel')) else 'trialId' if operation=='trial_conditions_accept' else 'campaignId' if operation=='campaign_finish' else 'operationId' if operation=='export_status' else None
                if key:fields[key]=value['id']
        state=value.get('status',value.get('state')) if isinstance(value,dict) else None
        status=state if state in ('accepted','running','failed','rejected','committed','outcome_unknown') else 'completed'
        if isinstance(value,dict) and value.get('reconciliationRequired'):fields['reconciliationRequired']=True;status='outcome_unknown'
        return receipt('完整结果已保存；按文件路径分页读取。',file,status=status,**fields)
    def error(self,campaign,operation,error,*,write=False):
        refused=isinstance(error,(Refused,Conflict))
        status='rejected' if refused else 'outcome_unknown' if write else 'failed'
        if isinstance(error,sqlite3.OperationalError):
            busy=database_busy(error)
            # Database outages may also prevent diagnostic-file publication. The
            # receipt itself must still identify the layer and preserve unknown writes.
            return receipt('控制数据库暂时繁忙；稍后使用原参数和幂等键核对结果，避免重复提交。' if busy else '控制数据库异常；保留原请求身份并核对后台结果。',
                status=status,code='control_database_busy' if busy else 'control_database_error',reconciliationRequired=write)
        file=self.publish(campaign,operation,{'operation':operation,'status':status,'error':str(error),'type':type(error).__name__,'traceback':traceback.format_exc()})
        return receipt('请求未获接受；详见诊断文件。' if refused else '请求未完成；核对文件及后台状态后再决定重试。',file,
            status=status,code='request_refused' if refused else 'tool_failed',**({'committed':False} if refused else {'reconciliationRequired':write}))
