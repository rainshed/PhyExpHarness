import {api,key} from './transport.mjs';
import {createAttempt,sameCreateConfig} from './create-attempt.mjs';
import {configError,numericConfig,numericFields,withoutUsageLimits} from './form.mjs';
export function createCommands({store,request=api,makeKey=key}){
 return {
  async create(config,modelCatalogRevision){
   const problem=configError(config);if(problem)throw Error(problem);
   const previous=store.read().attempt,normalized=numericConfig(config);
   const values=sameCreateConfig(normalized,previous)?normalized:withoutUsageLimits(normalized),attempt=createAttempt(values,previous,makeKey);
   store.update({config:values,attempt});
   const result=await request('/campaigns',{config:values,idempotencyKey:attempt.key,modelCatalogRevision});
   // Persist completion before allowing another intentional creation.
   store.update({attempt:null});return result;
  },
  control(campaign,action,changes){return request('/campaigns/'+campaign.id+'/control',{
   action,changes,expectedRevision:campaign.revision,idempotencyKey:makeKey()});},
  deletion(campaign,signal){return request('/campaigns/'+encodeURIComponent(campaign)+'/deletion',undefined,signal);},
  deleteCampaign(campaign,preview,{retry=false}={}){return request('/campaigns/'+encodeURIComponent(campaign)+'/deletion',{
   expectedRevision:preview?.expectedRevision,idempotencyKey:makeKey(),retry});},
  async limits(campaign,config){
   const problem=configError(config);if(problem)throw Error(problem);
   const values=numericConfig(config),changes={};
   for(const name of Object.keys(numericFields))if(!Object.is(values[name],campaign.config[name]))changes[name]=values[name];
   if(!Object.keys(changes).length)return false;
   await this.control(campaign,'limits',changes);return true;
  },
 };
}
