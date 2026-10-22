export const pluginCategories = [
 ['prompt-context','提示与上下文'],['tools','工具能力'],['tool-results','工具结果处理'],
 ['execution-control','执行控制与恢复'],['other','其他扩展'],
];
export function categoriesFor(plugin) {
 return pluginCategories.filter(([id])=>Array.isArray(plugin?.categories)&&plugin.categories.includes(id));
}
export function filterPlugins(plugins, category) {
 return plugins.filter(p=>category==='all'||(category==='unclassified'?!categoriesFor(p).length:categoriesFor(p).some(([id])=>id===category)));
}
export function pluginIdentity(plugin, plugins=[]) {
 const ambiguous=plugins.some(p=>p.id!==plugin.id&&p.name===plugin.name&&p.version===plugin.version);
 return plugin.version+(ambiguous?' · 内容 '+(plugin.digest?.slice(0,8)||'身份缺失'):'');
}
export function pluginVersions(tables, id) {
 return (tables?.versions||[]).filter(v=>v.plugins.some(p=>p.pluginId===id));
}
