export interface ModelSelection {provider:string;model:string;reasoningEffort?:string|null}
export interface CampaignConfig {
 name:string;objective:string;solver:ModelSelection;meta:ModelSelection;tasks:string[];
 concurrency:number;wallTimeSeconds:number;maxRounds:number|null;maxTrials:number|null;
 trialTimeSeconds:number|null;softTokenLimit:number|null;reserveSeconds:number|null;reserveTokens:number|null;
 stopMode:'strict'|'drain';drainGraceSeconds:number;resourcePolicy?:string;retries:number;
}
export interface CreateAttempt {signature:string;key:string}
export interface DraftState {version:1;config:CampaignConfig;selected:string;attempt:CreateAttempt|null}
export type Request=<T=unknown>(route:string,body?:unknown,signal?:AbortSignal)=>Promise<T>;
