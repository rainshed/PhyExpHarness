import React from 'react';
import {categoriesFor} from './plugin-reading.mjs';
export function PluginCategories({plugin}:any){
 const categories=categoriesFor(plugin);
 return <span className="studio-plugin-categories">{categories.length?categories.map(([id,label]:string[])=><span key={id}>{label}</span>):<span className="studio-unclassified">分类待补充</span>}</span>;
}
