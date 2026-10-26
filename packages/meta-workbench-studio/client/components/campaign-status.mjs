// Presentation only: never change the activity lifecycle or trigger recovery.
const labels={draft:'待启动',running:'运行中',paused:'已暂停',closing:'收尾中',finished:'已结束',failed:'失败'};
const failures={
 storage_capacity:'存储空间达到保护线',storage_write_error:'日志写入失败，请检查存储状态与文件权限',
 log_size_limit:'输出日志达到显式容量上限',log_record_size_limit:'单条日志超过可处理大小',
 model_transport_error:'模型连接中断',model_service_overloaded:'模型服务暂时过载',
 request_timeout:'单次模型请求达到时间上限',stream_idle_timeout:'模型连接长时间没有返回数据',
 control_unavailable:'后台运行控制暂时不可用',request_auth_failed:'后台请求凭证验证失败',request_lease_expired:'后台请求凭证已到期或撤销',control_protocol_error:'后台运行控制协议异常',
 accounting_unavailable:'后台用量账本暂时不可用',accounting_auth_failed:'后台请求凭证验证失败',
 accounting_lease_expired:'后台请求凭证已到期或被撤销',budget_admission_denied:'剩余额度不足以继续模型请求',
 model_authentication:'模型服务认证失败',model_auth_error:'模型服务认证失败',
 model_permission:'模型服务拒绝访问',model_permission_error:'模型服务拒绝访问',
 model_configuration_error:'模型配置不可用',integrity_error:'运行资料未通过完整性检查',
};
export function currentMeta(c={}) {
 // Full detail takes precedence over a list projection from an earlier read.
 if(Array.isArray(c.metaSessions)){
  const latest=c.metaSessions.at(-1);
  return latest?{...latest,publicFailure:c.metaStatus&&c.metaStatus.sessionId===latest.id?c.metaStatus.failure:null}:null;
 }
 return c.metaStatus||null;
}
export function metaFailureReason(meta) {
 const failure=meta?.recovery?.failure||meta?.summary?.failure||meta?.failure;
 const transport=failure?.observed?.transport;
 if(failure?.code==='model_transport_error'&&(meta?.connectionTimedOut||['ETIMEDOUT','UND_ERR_CONNECT_TIMEOUT'].includes(transport?.errorCode)))return '连接模型服务超时';
 if(failures[failure?.code])return failures[failure.code];
 if(meta?.publicFailure?.code&&meta.publicFailure.code!=='unknown_failure')return meta.publicFailure.message;
 // The list projection contains fixed backend descriptions, never raw error logs.
 if(meta?.sessionId&&failure?.code!=='unknown_failure'&&failure?.message)return failure.message;
 return 'Meta 会话未能完成，具体原因尚未确认';
}
export function campaignStatus(c={}) {
 if(c.deletion||c.state==='deleting')return {label:c.deletion?.state==='failed'?'删除失败，待重试':'正在删除',attention:false,recovering:false};
 const meta=currentMeta(c),live=['running','closing'].includes(c.state)&&!(c.config?.stopPolicy==='meta-closeout-v1'&&c.finishAssessment?.summary);
 const attention=live&&['needs_attention','failed'].includes(meta?.state);
 const recovering=live&&meta?.state==='recovering';
 const manualRecovery=recovering&&(meta?.recovery?.userResumedAt!=null||meta?.recoveryRequested===true);
 const recoveryReason=meta?.recovery?.reason||meta?.recoveryReason;
 const label=attention?'需要处理':recovering?'正在恢复':labels[c.state]||'状态待核实';
 return {label,attention,recovering,manualRecovery,meta,reason:attention||recovering?metaFailureReason(meta):'',
  recoveryNote:recoveryReason==='recovery_exhausted'?'自动恢复次数已用完。':recoveryReason==='nonrecoverable'?'此故障不适合自动重试，需先处理原因。':'自动恢复已停止。'};
}
