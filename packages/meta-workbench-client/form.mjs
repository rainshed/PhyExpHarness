import {referenceError} from './reference.mjs';
export const numericFields={maxRounds:'最多轮次',maxTrials:'最多实验次数',concurrency:'最高并发',wallTimeSeconds:'活动时限（秒）',trialTimeSeconds:'单次时限（秒）',softTokenLimit:'总用量软阈值（token）',reserveSeconds:'收尾预留（秒）',reserveTokens:'收尾预留（token）',drainGraceSeconds:'额外收尾时限（秒）'};
export const optionalFields=['maxRounds','maxTrials','trialTimeSeconds','softTokenLimit','reserveSeconds','reserveTokens'];
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
 if(!absent(config.maxTrials)&&config.tasks.length>Number(config.maxTrials))return `已选择 ${config.tasks.length} 个任务，H0 基线至少需要 ${config.tasks.length} 次实验；当前最多实验次数为 ${config.maxTrials}。请减少任务或增加实验次数。`;
 if(!absent(config.maxTrials)&&Number(config.concurrency)>Number(config.maxTrials))return '最大并发不能超过最多实验次数。';
 if(!absent(config.reserveSeconds)&&Number(config.reserveSeconds)>=Number(config.wallTimeSeconds))return '收尾预留时间必须小于活动时限。';
 if(!absent(config.softTokenLimit)&&!absent(config.reserveTokens)&&Number(config.reserveTokens)>=Number(config.softTokenLimit))return '收尾预留 token 必须小于总用量软阈值。';
 if(config.stopMode==='drain'&&Number(config.drainGraceSeconds)>900)return '额外收尾时限不能超过 900 秒。';
 return referenceError(config.referencePolicy);
}
export function numericConfig(config){return {...config,...Object.fromEntries(Object.keys(numericFields).filter(k=>k in config).map(k=>[k,absent(config[k])?null:Number(config[k])]))};}
