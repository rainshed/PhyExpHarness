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

export type ResearchRef={recordId:string;revision:number};
export type EvidenceAnchor={evidenceId:string;sha256:string;start:number;end:number;unit:'characters';supports:string};
export type EvidenceExcerpt={anchor:EvidenceAnchor;availability:'available'|'unavailable'|'unauthorized'|'stale'|'unsupported'|'invalid_range';text?:string;contextBefore?:string;contextAfter?:string;reason?:string};
export type ResearchSummary=ResearchRef&{summary:string;kind:string;state:string;author:string;recordedAt:number;factAt:number;limitations:string[];nextStep:string;candidateIds:string[];plugins:{candidateId:string;pluginKey:string}[];developmentRefs?:ResearchRef[]};
export type EvolutionView={schemaVersion:'evolution-view-v1';revision:string;observedAt:number;availability:'available'|'not_recorded';total:number;offset:number;nextOffset:number|null;items:ResearchSummary[];relationCounts?:{plugin:number;unlinked:number};pluginContext?:{developmentRef:ResearchRef|null;latestObservation:ResearchSummary|null}};
