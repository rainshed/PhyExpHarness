import defaults from '../../../schemas/meta-defaults.json' with {type:'json'};
export const defaultObjective=defaults.objective;
const oldDefault='基于真实执行证据，开发并测试至少一个可复用的执行插件，说明其作用与局限，生成每轮及最终报告。改进方法由 Meta 自主决定。';
export function loadGoalDraft(storage,fallback){
 const raw=storage.getItem('phyexp-draft');
 const draft=raw?JSON.parse(raw):null;
 if(!draft)return fallback;
 if(draft.objective===oldDefault){
  if(!storage.getItem('phyexp-draft-before-meta-goal-v1'))storage.setItem('phyexp-draft-before-meta-goal-v1',raw);
  return {...draft,objective:defaultObjective};
 }
 return draft;
}
