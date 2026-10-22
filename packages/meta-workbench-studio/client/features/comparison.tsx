import React from 'react';
import {SelectionDecisions} from '../components/selection';
import {VersionComparison} from '../components/version-comparison';
import {PageIntro} from '../components/reading-layout';
export function Page({w,c,setTable,tablesProps,readEvidence,open}:any){
 return <><PageIntro eyebrow="COMPARE / 表现与选择依据" title="哪个版本值得继续？">先比较每项任务的结果与进度，再核对取舍和重新考虑的条件。</PageIntro><VersionComparison c={c} onEvidence={tablesProps.onEvidence} onStopTrial={tablesProps.onStopTrial} onReport={w.readReport} onVersion={()=>{setTable('versions');open('lab')}}/><SelectionDecisions onReport={w.readReport} campaignId={c.id} decisions={c.selectionDecisions} tables={c.tables} readEvidence={readEvidence}/></>;
}
