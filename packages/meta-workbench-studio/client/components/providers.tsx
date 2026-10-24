import React,{useEffect,useRef,useState} from 'react';
import {NumberField} from './fields';

const protocols:any={'openai-completions':'OpenAI Chat Completions','openai-responses':'OpenAI Responses','anthropic-messages':'Anthropic Messages'};
const levels=['off','minimal','low','medium','high','xhigh','max'];
const clone=(v:any)=>JSON.parse(JSON.stringify(v));
const blank=()=>({id:'',name:'',enabled:true,route:{adapter:'pi-ai',api:'openai-completions',baseURL:'',auth:{type:'api-key',env:''},models:[{id:'',name:'',reasoningEfforts:false}]}});
const credentialText=(c:any)=>c.source==='codex'?(c.state==='configured'?'宿主已登录':c.state==='expired'?'宿主登录已过期':'未检测到宿主登录'):c.source==='saved'?'已保存密钥':c.source==='environment'?'使用后台环境变量':'尚未配置密钥';
const testStates:any={running:'测试中',passed:'测试通过',failed:'测试未通过',interrupted:'测试已中断'};

function ModelEditor({model,onChange,onRemove,native,locked}:any){
 const [advanced,setAdvanced]=useState(false);
 const update=(key:string,value:any)=>{const next={...model};if(value===undefined)delete next[key];else next[key]=value;onChange(next)};
 const reasoning=model.reasoningEfforts!==false;
 const toggleLevel=(level:string,enabled:boolean)=>{
  const map={...(model.reasoningEfforts||{})};if(enabled)map[level]=native?level:level==='off'?null:level;else delete map[level];
  onChange({...model,reasoningEfforts:map,defaultReasoningEffort:Object.hasOwn(map,model.defaultReasoningEffort)?model.defaultReasoningEffort:Object.keys(map)[0]});
 };
 return <fieldset className="mh-provider-model"><legend>{model.name||model.id||'新模型'}</legend>
  <div className="mh-grid"><label>模型 ID<input value={model.id} disabled={locked} onChange={e=>update('id',e.target.value)} maxLength={200}/></label><label>显示名称<input value={model.name||''} onChange={e=>update('name',e.target.value||undefined)}/></label></div>
  <button type="button" aria-expanded={advanced} onClick={()=>setAdvanced(!advanced)}>{advanced?'收起':'展开'}模型能力</button>
  {advanced&&<div className="mh-provider-advanced">
   <div className="mh-grid">{[['contextWindow','上下文长度'],['maxTokens','最大输出 token']].map(([key,label])=><NumberField key={key} label={label} value={model[key]??''} note={key==='maxTokens'?'留空默认 8192':'按服务商资料填写'} onChange={(value:string)=>update(key,value===''?undefined:Number(value))}/>)}</div>
   <div className="mh-provider-inputs">输入类型 {['text','image'].map(type=><label key={type} className="mh-check"><input type="checkbox" checked={(model.input||['text']).includes(type)} onChange={e=>update('input',e.target.checked?[...(model.input||['text']),type]:(model.input||['text']).filter((v:string)=>v!==type))}/>{type==='text'?'文字':'图片'}</label>)}</div>
   <label className="mh-check"><input type="checkbox" disabled={native||locked} checked={reasoning} onChange={e=>{const next={...model,reasoningEfforts:e.target.checked?{low:'low',high:'high'}:false};if(e.target.checked)next.defaultReasoningEffort='high';else delete next.defaultReasoningEffort;onChange(next)}}/>支持推理强度</label>
   {reasoning&&<><div className="mh-provider-inputs">{(native?['off','low','high','max']:levels).map(level=><label key={level} className="mh-check"><input type="checkbox" disabled={locked} checked={Object.hasOwn(model.reasoningEfforts,level)} onChange={e=>toggleLevel(level,e.target.checked)}/>{level}</label>)}</div>
    <label>默认推理强度<select value={model.defaultReasoningEffort||''} onChange={e=>update('defaultReasoningEffort',e.target.value)}>{Object.keys(model.reasoningEfforts).map(level=><option key={level}>{level}</option>)}</select></label>
    {!native&&!locked&&<details><summary>推理等级与服务端值的映射</summary>{Object.entries(model.reasoningEfforts).map(([level,value])=><label key={level}>{level}<input value={value===null?'':String(value)} placeholder={level==='off'?'留空表示省略协议推理字段':''} onChange={e=>update('reasoningEfforts',{...model.reasoningEfforts,[level]:level==='off'&&e.target.value===''?null:e.target.value})}/></label>)}<small>off 留空仅省略请求字段，不保证远端关闭推理。</small></details>}
   </>}
  </div>}
  {onRemove&&<button type="button" className="mh-provider-remove" onClick={onRemove}>移除此模型</button>}
 </fieldset>;
}

export function ProviderSettings({api,onCatalogChanged,onClose}:any){
 const [snapshot,setSnapshot]=useState<any>(null),[draft,setDraft]=useState<any>(null),[selected,setSelected]=useState(''),[newProvider,setNewProvider]=useState(false);
 const [key,setKey]=useState(''),[showKey,setShowKey]=useState(false),[busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[dirty,setDirty]=useState(false),[confirmRemove,setConfirmRemove]=useState(false);
 const [test,setTest]=useState<any>(null),[testModel,setTestModel]=useState(''),[effort,setEffort]=useState<any>(undefined),[compat,setCompat]=useState('');
 const mounted=useRef(true),lock=useRef(false),pendingTest=useRef<any>(null);
 const acceptTest=(value:any)=>{setTest(value);setSnapshot((old:any)=>old?{...old,providers:old.providers.map((p:any)=>p.id===value.provider?{...p,lastTest:value}:p)}:old)};
 const current=snapshot?.providers.find((p:any)=>p.id===selected);
 const select=(item:any,isNew=false)=>{setDraft(clone(item));setSelected(item.id);setNewProvider(isNew);setKey('');setShowKey(false);setDirty(false);setError('');setNotice('');setConfirmRemove(false);setTest(item.lastTest||null);setCompat(item.route.compat?JSON.stringify(item.route.compat,null,2):'');const m=item.route.models[0];setTestModel(m.id);setEffort(m.defaultReasoningEffort);pendingTest.current=null;};
 async function reload(){const next=await api('/providers');if(!mounted.current)return;setSnapshot(next);if(!draft)select(next.providers[0]||blank(),!next.providers.length);return next;}
 useEffect(()=>{mounted.current=true;reload().catch((e:any)=>setError('读取模型设置失败：'+e.message));return()=>{mounted.current=false}},[]);
 useEffect(()=>{
  if(test?.state!=='running')return;
  let live=true,loading=false;
  const poll=async()=>{if(loading)return;loading=true;try{const value=await api('/provider-tests/'+test.id);if(live){acceptTest(value);setError(previous=>previous.startsWith('测试结果读取失败')?'':previous);}}catch(e:any){if(live)setError('测试结果读取失败：'+e.message+'。重连后继续读取，不会重复调用。')}finally{loading=false}};
  const timer=setInterval(poll,1000);poll();return()=>{live=false;clearInterval(timer)};
 },[test?.id,test?.state]);
 const edit=(next:any)=>{setDraft(next);setDirty(true);setNotice('');setConfirmRemove(false)};
 const editRoute=(changes:any)=>edit({...draft,route:{...draft.route,...changes}});
 const changeModel=(index:number,next:any)=>editRoute({models:draft.route.models.map((m:any,i:number)=>i===index?next:m)});
 const action=async(name:string,fn:()=>Promise<void>)=>{if(lock.current)return;lock.current=true;setBusy(name);setError('');setNotice('');try{await fn()}catch(e:any){setError(e.message)}finally{if(mounted.current)setBusy('');lock.current=false}};
 const apply=()=>action('save',async()=>{
  const route=clone(draft.route);
  if(newProvider&&snapshot.providers.some((p:any)=>p.id===draft.id))throw Error('此供应商 ID 已存在，请选择其他 ID 或编辑已有连接。');
  if(newProvider)route.auth.env='PHYEXP_PROVIDER_'+draft.id.replace(/-/g,'_').toUpperCase()+'_API_KEY';
  if(route.adapter==='pi-ai'){
   if(compat.trim()){try{route.compat=JSON.parse(compat)}catch{throw Error('协议兼容选项须为有效的 JSON 对象。')}}else delete route.compat;
  }
  for(const m of route.models){if(!m.name)delete m.name;if(m.reasoningEfforts!==false&&Object.keys(m.reasoningEfforts).length===0)throw Error('推理模型至少选择一种强度。');}
  const next=await api('/providers/save',{id:draft.id,name:draft.name,enabled:draft.enabled,route,expectedRevision:snapshot.revision,...(key?{apiKey:key}:{})});
  if(!mounted.current)return;setSnapshot(next);select(next.providers.find((p:any)=>p.id===draft.id));setNotice('配置已保存并立即生效；已有活动继续使用原配置。');await onCatalogChanged();
 });
 const removeKey=()=>action('remove',async()=>{const next=await api('/providers/'+draft.id+'/credential/remove',{expectedRevision:snapshot.revision});if(!mounted.current)return;setSnapshot(next);select(next.providers.find((p:any)=>p.id===draft.id));setNotice('已删除后台保存的密钥。已配置的环境变量仍可作为认证来源。');});
 const runTest=()=>action('test',async()=>{
  const request={model:testModel,...(effort!==undefined?{reasoningEffort:effort}:{}),expectedRevision:snapshot.revision};
  const signature=JSON.stringify({provider:draft.id,...request});
  if(pendingTest.current?.signature!==signature)pendingTest.current={signature,id:crypto.randomUUID()};
  const result=await api('/providers/'+draft.id+'/test',{...request,idempotencyKey:pendingTest.current.id});
  if(mounted.current)acceptTest(result);pendingTest.current=null;
 });
 const leavingBlocked=dirty||!!key;
 return <section className="mh-provider-settings mh-card" aria-label="供应商与模型设置">
  <div className="mh-title"><div><h2>供应商与模型</h2><p className="mh-muted">配置保存在独立后台。新活动使用最新目录，已有活动保留冻结配置。</p></div><button disabled={!!busy||leavingBlocked} onClick={onClose}>返回工作台</button></div>
  {error&&<div className="mh-alert" role="alert">{error}<div className="mh-actions"><button disabled={!!busy} onClick={()=>action('reload',async()=>{await reload();await onCatalogChanged();setNotice('已重新读取后台版本；当前编辑草稿保留。请核对后保存。')})}>重新读取后台设置</button></div></div>}
  {notice&&<p role="status" className="mh-notice">{notice}</p>}
  {!snapshot?<p role="status">正在读取供应商配置…</p>:<>
   <div className="mh-provider-list">{snapshot.providers.map((p:any)=><button key={p.id} disabled={!!busy||leavingBlocked} className={selected===p.id&&!newProvider?'selected':''} onClick={()=>select(p)}><strong>{p.name}</strong><small>{p.enabled?'已启用':'已停用'} · {p.route.models.length} 个模型</small><small>{credentialText(p.credential)}</small></button>)}<button disabled={!!busy||leavingBlocked} onClick={()=>select(blank(),true)}>＋ 添加供应商</button></div>
   {draft&&<>
    {leavingBlocked&&<p className="mh-notice">有未保存修改。保存或取消编辑后可切换连接、返回活动；密钥草稿不会保存在浏览器中。</p>}
    <form onSubmit={e=>{e.preventDefault();apply()}}>
     <fieldset disabled={!!busy}><legend>{newProvider?'添加自定义服务':current?.name}</legend>
      <div className="mh-grid"><label>供应商名称<input value={draft.name} maxLength={100} onChange={e=>edit({...draft,name:e.target.value})} required/></label><label>供应商 ID<input disabled={!newProvider} value={draft.id} maxLength={64} pattern="[a-z][a-z0-9-]*" placeholder="my-gateway" onChange={e=>edit({...draft,id:e.target.value})} required/><small>创建后固定，用于活动中的模型身份。</small></label></div>
      <label className="mh-check"><input type="checkbox" checked={draft.enabled} onChange={e=>edit({...draft,enabled:e.target.checked})}/>供新活动选择</label>
      {draft.route.auth.type==='codex'?<p>使用后台主机的 Codex 登录，认证方式和订阅端点固定。{current&&credentialText(current.credential)}。</p>:<>
       <div className="mh-grid"><label>服务地址<input value={draft.route.baseURL||''} type="url" required placeholder="https://gateway.example.com/v1" onChange={e=>editRoute({baseURL:e.target.value})}/><small>{draft.route.adapter==='deepseek'?'DeepSeek 原生 Messages 接口。':draft.route.api==='anthropic-messages'?'填写协议根地址，SDK 会追加 /v1/messages。':'通常包含 /v1，按服务商文档填写。'}</small></label>
       {draft.route.adapter==='pi-ai'?<label>API 协议<select value={draft.route.api} onChange={e=>editRoute({api:e.target.value})}>{Object.entries(protocols).map(([id,name])=><option key={id} value={id}>{String(name)}</option>)}</select></label>:<label>API 协议<input readOnly value="DeepSeek 原生 Messages"/></label>}</div>
       <label>API Key<div className="mh-provider-key"><input type={showKey?'text':'password'} autoComplete="new-password" value={key} placeholder={current?.credential.saved?'留空保留已保存密钥':'输入密钥，或留空使用后台环境变量'} onChange={e=>{setKey(e.target.value);setShowKey(false)}}/><button type="button" disabled={!key} onClick={()=>setShowKey(!showKey)}>{showKey?'隐藏':'显示'}输入</button></div><small>{current?credentialText(current.credential):'密钥仅发送给控制后台，保存后不可读取。'}。环境变量引用：{newProvider?'PHYEXP_PROVIDER_'+draft.id.replace(/-/g,'_').toUpperCase()+'_API_KEY':draft.route.auth.env}</small></label>
       {current?.credential.saved&&<div className="mh-actions"><button type="button" disabled={!current.credential.canDelete||leavingBlocked} onClick={()=>setConfirmRemove(!confirmRemove)}>删除已保存密钥</button>{!current.credential.canDelete&&<small>未结束活动仍引用此密钥，暂不能删除。</small>}</div>}
       {confirmRemove&&<div className="mh-notice">删除后仍可使用后台已配置的环境变量。<button type="button" onClick={removeKey}>确认删除密钥</button><button type="button" onClick={()=>setConfirmRemove(false)}>取消</button></div>}
      </>}
      <div className="mh-title"><h3>模型目录</h3><button type="button" onClick={()=>editRoute({models:[...draft.route.models,{id:'',name:'',reasoningEfforts:draft.route.adapter==='deepseek'?{off:'off',low:'low',high:'high',max:'max'}:false,...(draft.route.adapter==='deepseek'?{defaultReasoningEffort:'high'}:{})}]})}>＋ 添加模型</button></div>
      {draft.route.models.map((m:any,index:number)=><ModelEditor key={index} model={m} native={draft.route.adapter==='deepseek'} locked={false} onChange={(next:any)=>changeModel(index,next)} onRemove={draft.route.models.length>1?()=>editRoute({models:draft.route.models.filter((_:any,i:number)=>i!==index)}):null}/>)}
      {draft.route.adapter==='pi-ai'&&draft.route.auth.type!=='codex'&&<details><summary>协议兼容选项（高级）</summary><label>兼容参数 JSON<textarea rows={5} value={compat} placeholder={'例如：{"supportsDeveloperRole": false}'} onChange={e=>{setCompat(e.target.value);setDirty(true)}}/></label><small>按服务商的实际协议填写。后台使用现有 schema 校验，未编辑的模型字段会保留。</small></details>}
      <div className="mh-actions"><button type="submit" className="primary">{busy==='save'?'正在保存…':'保存并应用'}</button><button type="button" onClick={()=>select(current||blank(),!current)}>取消编辑</button></div>
     </fieldset>
    </form>
    {!newProvider&&<section aria-label="供应商测试" className="mh-provider-test">
     <h3>测试调用</h3><p className="mh-muted">使用已保存配置，最多 2 次真实模型请求、总时限 45 秒；每次输出参数上限 512 token，可能产生少量费用。不计入实验次数。</p>
     <div className="mh-grid"><label>测试模型<select disabled={!!busy||test?.state==='running'||leavingBlocked} value={testModel} onChange={e=>{setTestModel(e.target.value);setEffort(current.route.models.find((m:any)=>m.id===e.target.value)?.defaultReasoningEffort)}}>{current.route.models.map((m:any)=><option key={m.id} value={m.id}>{m.name||m.id}</option>)}</select></label>
     {current.route.models.find((m:any)=>m.id===testModel)?.reasoningEfforts!==false&&<label>测试推理强度<select disabled={!!busy||test?.state==='running'||leavingBlocked} value={effort||''} onChange={e=>setEffort(e.target.value)}>{Object.keys(current.route.models.find((m:any)=>m.id===testModel)?.reasoningEfforts||{}).map(e=><option key={e}>{e}</option>)}</select></label>}</div>
     <button type="button" disabled={!!busy||test?.state==='running'||leavingBlocked||current.credential.state!=='configured'} onClick={runTest}>{test?.state==='running'?'正在测试…':leavingBlocked?'保存后测试':'测试调用'}</button>
     {test&&<div role="status" className="mh-notice"><strong>{testStates[test.state]}</strong>{test.configurationRevision!==snapshot.revision&&<p>设置版本已变化，此结果属于先前配置。</p>}{test.checks&&<div className="mh-provider-checks">{Object.entries({response:'模型响应',stream:'流式输出',toolCall:'工具参数',toolResult:'工具回传'}).map(([id,label])=><span key={id}>{test.checks[id]?'✓':'—'} {label}</span>)}</div>}{test.error&&<p>{test.error}</p>}<p>{test.durationMs!=null?'耗时 '+(test.durationMs/1000).toFixed(1)+' 秒':''}</p></div>}
    </section>}
   </>}
  </>}
 </section>;
}

export const providerStyles=`.studio-root [hidden]{display:none!important}.mh-provider-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:20px 0}.mh-provider-list button{display:grid;gap:5px;text-align:left}.mh-provider-list button.selected{background:#e8eee3;border-color:var(--accent)}.mh-provider-settings .mh-provider-model{background:#fafcf8;margin:14px 0}.mh-provider-advanced{margin-top:16px}.mh-provider-inputs{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0}.mh-provider-inputs .mh-check{margin-bottom:0}.mh-provider-remove{margin-left:10px}.mh-provider-key{display:flex;gap:8px}.mh-provider-key input{flex:1}.mh-provider-key button{white-space:nowrap}.mh-provider-test{border-top:1px solid var(--line);padding-top:24px}.mh-provider-checks{display:flex;gap:14px;flex-wrap:wrap;margin:12px 0}.mh-provider-settings fieldset:disabled{opacity:.7}.mh-provider-settings small{overflow-wrap:anywhere}.mh-provider-settings{max-width:1100px;margin:0 auto}@media(max-width:600px){.mh-provider-list{grid-template-columns:1fr}.mh-provider-key{flex-wrap:wrap}.mh-provider-remove{margin-left:0;margin-top:8px}}`;
