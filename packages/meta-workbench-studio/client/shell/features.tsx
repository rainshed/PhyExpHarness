import React from 'react';
import {Overview} from '../features/overview';
import {Reports} from '../features/reports';
import {Page as Comparison} from '../features/comparison';
import {Page as Experiments} from '../features/experiments';
import {Page as Lab} from '../features/lab';
import {Page as Runtime} from '../features/runtime';
import {Page as Exports} from '../features/exports';

export const features=[
 {id:'overview',title:'进化概览',icon:'▦',render:({w,c,readEvidence,...props}:any)=><Overview w={{...w,readEvidence}} {...props}/>},
 {id:'lab',title:'插件与动机',icon:'◇',render:Lab},
 {id:'compare',title:'版本对比',icon:'⌘',render:Comparison},
 {id:'rounds',title:'实验记录',icon:'☷',render:Experiments},
 {id:'reports',title:'研究报告',icon:'▤',render:({w,readEvidence,tablesProps}:any)=><Reports w={{...w,readContextEvidence:readEvidence}} tablesProps={tablesProps}/>},
 {id:'meta',title:'运行详情',icon:'⌁',render:Runtime},
 {id:'exports',title:'获取 Harness',icon:'↓',render:Exports},
];
export function FeaturePage({id,...props}:any){
 const feature=features.find(item=>item.id===id);
 if(!feature)return <p role="status">此页面当前不可用，请从导航选择其他页面。</p>;
 const Page=feature.render;return <Page {...props}/>;
}
