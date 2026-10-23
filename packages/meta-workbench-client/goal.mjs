import defaults from '../../schemas/meta-defaults.json' with {type:'json'};
export const defaultObjective=defaults.objective;
const oldDefaults=new Map([
 ['基于真实执行证据，开发并测试至少一个可复用的执行插件，说明其作用与局限，生成每轮及最终报告。改进方法由 Meta 自主决定。','v1'],
 ['在活动规定的资源和权限范围内，持续改进执行 Harness，使固定 Solver 能够更稳定地完成目标范围内的任务。依据真实执行结果和轨迹，自主决定如何改进与验证。达到约定的稳定完成标准、根据已有尝试和证据判断暂未发现值得继续投入当前资源的改进方向，或触及活动资源上限时结束；如实报告结果、未解决的问题与证据局限。','v2']
]);
export function loadGoalDraft(storage,fallback){
 const raw=storage.getItem('phyexp-draft');
 const draft=raw?JSON.parse(raw):null;
 if(!draft)return fallback;
 const migration=oldDefaults.get(draft.objective);
 if(migration){
  const backup='phyexp-draft-before-meta-goal-'+migration;
  if(!storage.getItem(backup))storage.setItem(backup,raw);
  return {...fallback,...draft,objective:defaultObjective};
 }
 return {...fallback,...draft};
}
