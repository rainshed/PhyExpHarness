import React from 'react';
import {HarnessTables} from '../components/tables';
import {SelectionDecisions} from '../components/selection';
export function Page({w,c,table,setTable,tablesProps,readEvidence,open}:any){return <><nav className="mh-tabs" aria-label="实验工作区">{[['plugins','插件与配置'],['versions','版本详情与血缘']].map(([id,label])=><button key={id} className={table===id?'active':''} aria-pressed={table===id} onClick={()=>setTable(id)}>{label}</button>)}</nav><section className="mh-card"><HarnessTables tables={c.tables} {...tablesProps} section={table} onSectionChange={setTable}/></section><details><summary>版本选择、证据与比较局限</summary><SelectionDecisions decisions={c.selectionDecisions} tables={c.tables} readEvidence={readEvidence}/></details></>;}
