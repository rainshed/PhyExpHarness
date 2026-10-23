import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {defaults} from '@phyexp/meta-workbench-client';

test('task selection renders API time limits and blocks tasks whose configuration is unavailable',async()=>{
 const bundle=await build({entryPoints:['packages/meta-workbench-studio/client/features/create.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',
  external:['react','react/jsx-runtime','@phyexp/meta-workbench-client/react'],jsx:'automatic'});
 let catalog={value:{tasks:[{id:'time_budgeted_hamlearn_10q',solverTimeSeconds:3720,verifierTimeSeconds:300}]},error:'',load(){}};
 const jsx=(type,props)=>({type,props});const react={Fragment:Symbol(),createElement:jsx,useState:()=>[1,()=>{}],useEffect(){}};
 const sandbox={module:{exports:{}},exports:null,require:id=>id==='@phyexp/meta-workbench-client/react'?{useResource:()=>catalog}:{...react,jsx,jsxs:jsx}};
 sandbox.exports=sandbox.module.exports;vm.runInNewContext(bundle.outputFiles[0].text,sandbox);
 let error;const w={config:{...defaults,tasks:['time_budgeted_hamlearn_10q']},setConfig(){},models:[],setFormError:e=>error=e,connected:true};
 function nodes(n){if(n==null||typeof n!=='object')return [];if(Array.isArray(n))return n.flatMap(nodes);if(typeof n.type==='function')return nodes(n.type(n.props));return [n,...nodes(n.props?.children)];}
 function text(n){if(n==null||typeof n==='boolean')return '';if(Array.isArray(n))return n.map(text).join('');if(typeof n!=='object')return String(n);if(typeof n.type==='function')return text(n.type(n.props));return text(n.props?.children);}
 let tree=sandbox.module.exports.CreateCampaign({w});
 assert.match(text(tree),/求解上限：1小时 2分 0秒.*评分上限：0小时 5分 0秒/);
 assert.match(text(tree),/准备环境和评分不占用求解时间/);
 const choices=nodes(tree).filter(n=>n.type==='input'&&n.props.type==='checkbox');
 assert.equal(choices.length,5);assert.equal(choices.filter(n=>!n.props.disabled).length,1);
 catalog={...catalog,value:null,error:'offline'};tree=sandbox.module.exports.CreateCampaign({w});
 assert.match(text(tree),/任务时限读取失败：offline/);
 assert.equal(nodes(tree).filter(n=>n.type==='input'&&n.props.type==='checkbox'&&!n.props.disabled).length,1,'unavailable selected task can still be deselected');
 nodes(tree).find(n=>n.type==='form').props.onSubmit({preventDefault(){}});
 assert.match(error,/配置尚不可用/);
});
