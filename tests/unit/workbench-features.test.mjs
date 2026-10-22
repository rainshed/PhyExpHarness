import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {defaults} from '@phyexp/meta-workbench-client';

test('all registered Studio pages render, including report appendices after module extraction',async()=>{
 const result=await build({entryPoints:['packages/meta-workbench-studio/client/shell/features.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 const jsx=(type,props)=>({type,props}),react={Fragment:Symbol('Fragment'),createElement:jsx,useState:initial=>[typeof initial==='function'?initial():initial,()=>{}],useEffect(){},useRef:initial=>({current:initial}),useId:()=> 'fixture-id'};
 const sandbox={module:{exports:{}},exports:null,require:id=>{assert.ok(['react','react/jsx-runtime'].includes(id));return {...react,jsx,jsxs:jsx}}};sandbox.exports=sandbox.module.exports;
 vm.runInNewContext(result.outputFiles[0].text,sandbox);
 const {features,FeaturePage}=sandbox.module.exports;
 const c={id:'fixture',state:'running',config:defaults,trials:[],batches:[],candidates:[],evidence:[],reports:[],exports:[],operations:[],metaSessions:[],selectionDecisions:[],tables:{plugins:[],versions:[],rounds:[]},counts:{rounds:0,startedTrials:0,activeTrials:0,reservedTrials:0},usage:{confirmedTokens:0,unknownRequests:0,inflightReservedTokens:0,unknownReservedTokens:0},elapsedSeconds:0};
 const report={id:'report',kind:'final',createdAt:100,analysisRevision:1,analysis:{summary:'Fixture summary',decision:'Fixture decision',limitations:[],evidenceRefs:[]},facts:{campaign:c,trials:[],evidence:[],batches:[]},tables:c.tables};
 const w={c,events:[],report,finalReport:report,readEvidence(){},readReport(){},navigate(){},setNotice(){}};
 const props={w,c,table:'plugins',setTable(){},tablesProps:{},readEvidence(){},open(){}};
 function render(node){
  if(node==null||typeof node==='boolean')return '';
  if(Array.isArray(node))return node.map(render).join('');
  if(typeof node!=='object')return String(node);
  if(typeof node.type==='function')return render(node.type(node.props));
  return render(node.props?.children);
 }
 assert.equal(new Set(features.map(f=>f.id)).size,features.length);
 for(const feature of features){const output=render(FeaturePage({id:feature.id,...props}));assert.ok(output.length,feature.id);if(feature.id==='reports')assert.match(output,/Fixture summary/);}
 const overview=render(FeaturePage({id:'overview',...props}));
 assert.ok(overview.indexOf('这次进化，为什么这样走')<overview.indexOf('每个版本，现在表现怎样'));
 assert.ok(overview.indexOf('每个版本，现在表现怎样')<overview.indexOf('研究如何走到这一步'));
 assert.doesNotMatch(overview,/计划收尾：|活动目标、固定配置与请求保护/);
 assert.match(render(FeaturePage({id:'reports',...props})),/报告当时的逐任务表现/);
 report.facts.selectionDecisions=[{id:'fixture-decision',createdAt:100,candidateId:'candidate',summary:'保留历史版本',reason:'当时已有完整结果'}];
 const historical=render(FeaturePage({id:'reports',...props}));
 assert.match(historical,/为什么当时保留这一版/);assert.doesNotMatch(historical,/为什么现在保留这一版/);
 assert.match(render(FeaturePage({id:'removed',...props})),/此页面当前不可用/);
 const plugin={id:'p',name:'review',displayName:'方法审阅',version:'1',digest:'abc',categories:['tools','prompt-context'],functionSummary:'提供方法审阅',mechanism:'调用后返回审阅意见',descriptionSource:{label:'清单说明'}};
 c.tables.plugins=[plugin];
 c.tables.versions=[{id:'base',label:'H0',displayName:'H0 · 基线',plugins:[]},{id:'v',label:'H1',displayName:'H1 · 审阅版',plugins:[{pluginId:'p',order:1,config:{enabled:false,limit:null}}]}];
 const lab=render(FeaturePage({id:'lab',...props}));
 assert.ok(lab.indexOf('调用后返回审阅意见')<lab.indexOf('为什么想到这个办法'));
 assert.doesNotMatch(lab,/版本、配置与代码继承|执行版本表/);
 const compare=render(FeaturePage({id:'compare',...props}));
 assert.match(compare,/这些版本如何组合/);assert.match(compare,/原始基线 · 无额外插件/);
 assert.match(compare,/方法审阅/);assert.match(compare,/"enabled": false/);assert.match(compare,/"limit": null/);
 assert.ok(compare.indexOf('这些版本如何组合')<compare.indexOf('所选任务等权'));
 assert.doesNotMatch(compare,/版本详情与改名|新增插件|移除插件/);
});
