import React,{useState} from 'react';
import {api} from './common';
function Question({row}:any){
 const [values,setValues]=useState<any>({});const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [sent,setSent]=useState(false);
 if(row.state==='answered'||sent)return <p>已回复：{row.questions.map((q:any)=>q.question).join('；')}</p>;
 return <form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await api('/meta-questions/'+row.id+'/answer',{answers:row.questions.map((q:any)=>({id:q.id,selected:values[q.id]?.selected||[],custom:values[q.id]?.custom||''}))});setSent(true);}catch(e:any){setError(e.message);}finally{setBusy(false);}}}>
 {row.questions.map((q:any)=><fieldset key={q.id}><legend>{q.question}</legend>{q.detail&&<p>{q.detail}</p>}
 {(q.options||[]).map((o:any)=><label key={o.label}><input type={q.multiSelect?'checkbox':'radio'} name={row.id+q.id} checked={(values[q.id]?.selected||[]).includes(o.label)} onChange={e=>setValues({...values,[q.id]:{...values[q.id],selected:q.multiSelect?(e.target.checked?[...(values[q.id]?.selected||[]),o.label]:(values[q.id]?.selected||[]).filter((v:string)=>v!==o.label)):[o.label]}})}/>{o.label}{o.description&&<small> · {o.description}</small>}</label>)}
 <label>补充说明<textarea value={values[q.id]?.custom||''} onChange={e=>setValues({...values,[q.id]:{...values[q.id],custom:e.target.value}})}/></label></fieldset>)}
 {error&&<p role="alert">{error}</p>}<button disabled={busy}>提交回复</button><small>空白提交表示暂不提供答案；关闭页面不会自动提交。</small></form>;
}
export function MetaQuestions({rows=[]}:any){return rows.length?<section className="mh-card"><h3>Meta 的问题</h3>{rows.map((row:any)=><Question key={row.id} row={row}/>)}</section>:null;}
