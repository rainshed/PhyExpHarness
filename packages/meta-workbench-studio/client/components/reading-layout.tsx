import React,{useEffect,useRef,useState} from 'react';
import {readableText} from '../readability.mjs';

export function PageIntro({eyebrow,title,children}:any){
 return <div className="studio-page-intro"><small>{eyebrow}</small><h1>{title}</h1><p>{children}</p></div>;
}

// Keep authored text intact. Placement changes, not the saved conclusions.
export function ReadingLimits({items=[],compact=false}:any){
 if(!items.length)return null;
 return <div className="studio-reading-limits"><p><strong>重要限制：</strong>{readableText(items[0])}</p>{items.length>1&&<details><summary>{compact?'其他限制':'查看其余限制'} · {items.length-1} 条</summary><ul>{items.slice(1).map((s:string,i:number)=><li key={i}>{readableText(s)}</li>)}</ul></details>}</div>;
}

export function ReadingSection({number,title,description,children,open=false}:any){
 const [expanded,setExpanded]=useState(open),trigger=useRef<HTMLElement|null>(null);
 useEffect(()=>{if(open)setExpanded(true)},[open]);
 return <details className="studio-reading-section" open={expanded} onToggle={e=>setExpanded(e.currentTarget.open)} onKeyDown={e=>{if(e.key==='Escape'&&expanded){e.stopPropagation();setExpanded(false);trigger.current?.focus({preventScroll:true})}}}><summary ref={trigger as any}><span className="studio-reading-number">{number}</span><span><strong>{title}</strong>{description&&<small>{readableText(description)}</small>}</span><span aria-hidden="true" className="studio-reading-plus">{expanded?'−':'＋'}</span></summary>{expanded&&<div className="studio-reading-section-body">{children}</div>}</details>;
}
