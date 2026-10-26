import {referenceError} from './reference.mjs';
export const numericFields={maxRounds:'最多轮次',maxTrials:'最多实验次数',concurrency:'最高并发',wallTimeSeconds:'活动时限（秒）',trialTimeSeconds:'单次时限（秒）',reserveSeconds:'收尾预留（秒）',drainGraceSeconds:'额外收尾时限（秒）'};
export const optionalFields=['maxRounds','maxTrials','trialTimeSeconds','reserveSeconds'];
const absent=(v)=>v===null||v===undefined;
export function configError(config){
 if(!config.name?.trim())return '请填写活动名称。';
 if(!config.tasks?.length)return '请至少选择一个开发任务。';
 for(const [key,label] of Object.entries(numericFields)){
  if(key==='drainGraceSeconds'&&config.stopMode!=='drain')continue;
  if(optionalFields.includes(key)&&absent(config[key]))continue;
  const min=key.startsWith('reserve')||key==='drainGraceSeconds'?0:1;
  if(config[key]===''||!Number.isSafeInteger(Number(config[key]))||Number(config[key])<min)return `${label}需要填写${min?'大于 0':'不小于 0'}的整数。`;
 }
 if(!absent(config.maxTrials)&&Number(config.concurrency)>Number(config.maxTrials))return '最大并发不能超过最多实验次数。';
 if(!absent(config.reserveSeconds)&&Number(config.reserveSeconds)>=Number(config.wallTimeSeconds))return '收尾预留时间必须小于活动时限。';
 if(config.stopMode==='drain'&&Number(config.drainGraceSeconds)>900)return '额外收尾时限不能超过 900 秒。';
 return referenceError(config.referencePolicy);
}
export function numericConfig(config){return {...config,...Object.fromEntries([...Object.keys(numericFields),'softTokenLimit','reserveTokens'].filter(k=>k in config).map(k=>[k,absent(config[k])?null:Number(config[k])]))};}

// Strip obsolete limits only for a new intent; uncertain historical creates replay exactly.
export function withoutUsageLimits(config){
 const result=structuredClone(config);delete result.softTokenLimit;delete result.reserveTokens;
 for(const value of Object.values(result.referencePolicy?.limits||{}))delete value.softTokenLimit;
 return result;
}
