import test from 'node:test';
import assert from 'node:assert/strict';
import {categoriesFor,filterPlugins,pluginIdentity,pluginVersions} from '../../packages/meta-workbench-studio/client/components/plugin-reading.mjs';

test('plugin filters allow multiple categories without duplicate rows or permission inference',()=>{
 const plugins=[{id:'both',categories:['tools','prompt-context','tools']},{id:'old',declaration:{capabilities:['tools']}},{id:'new',categories:['future']},{id:'other',categories:['other']}];
 assert.deepEqual(filterPlugins(plugins,'tools').map(p=>p.id),['both']);
 assert.deepEqual(filterPlugins(plugins,'prompt-context').map(p=>p.id),['both']);
 assert.equal(categoriesFor(plugins[0]).length,2);
 assert.deepEqual(filterPlugins(plugins,'unclassified').map(p=>p.id),['old','new']);
 assert.deepEqual(filterPlugins(plugins,'other').map(p=>p.id),['other']);
 assert.equal(filterPlugins(plugins,'all').length,4);
});
test('same plugin name and version never merge different content or version use',()=>{
 const a={id:'a',name:'audit',version:'1',digest:'aaaabbbbcccc'},b={...a,id:'b',digest:'dddd11112222'};
 assert.notEqual(pluginIdentity(a,[a,b]),pluginIdentity(b,[a,b]));
 const tables={versions:[{id:'h0',plugins:[]},{id:'h1',plugins:[{pluginId:'a'}]},{id:'h2',plugins:[{pluginId:'b'}]},{id:'h3',plugins:[{pluginId:'a'}]}]};
 assert.deepEqual(pluginVersions(tables,'a').map(v=>v.id),['h1','h3']);
 assert.deepEqual(pluginVersions(tables,'b').map(v=>v.id),['h2']);
});
