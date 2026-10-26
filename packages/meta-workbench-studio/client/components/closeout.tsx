import React from 'react';

export function Closeout({campaign}:any){
 const decision=campaign.finishAssessment;
 const current=campaign.config?.stopPolicy==='meta-closeout-v1';
 if(!decision&&(!current||!['closing','finished','failed'].includes(campaign.state)))return null;
 return <section className="mh-card" aria-label="Meta 收尾记录"><h3>Meta 收尾记录</h3>
  {decision?<><h4>结束理由</h4><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{decision.reason}</p>
   {decision.summary?<><h4>本次实验总结</h4><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{decision.summary}</p></>:<p>此历史记录未单独保存 Meta 收尾总结。</p>}
  </>:<p>尚未收到 Meta 提交的收尾理由与实验总结。系统事实摘要不代替 Meta 总结。</p>}
  <p className="mh-muted">活动结束不表示平台认证目标已经达成。</p>
 </section>;
}
