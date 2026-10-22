import React from 'react';
import {CampaignDetails} from '../components/campaign';
import {ResourcePlan} from '../components/resource-plan';
import {MetaComposition} from '../components/meta-composition';
import {ActivityLog} from '../components/activity-log';
import {EvidenceIndex} from '../components/evidence';
import {TaskEvaluation} from '../components/outcomes';
export function Page({w,c,table,setTable,tablesProps,readEvidence,open}:any){return <><CampaignDetails c={c}/><ResourcePlan c={c}/><MetaComposition campaign={c} observations={c.metaObservations} sessions={c.metaSessions} reviews={c.stopReviews}/><ActivityLog w={w}/><EvidenceIndex key={c.id} c={c} readEvidence={readEvidence}/><details className="mh-card"><summary>跨版本历史统计 · 不代表单一版本能力</summary><TaskEvaluation value={c.taskEvaluation} rows={c.trials} campaign={c} details/></details></>;}
