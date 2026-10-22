import React from 'react';
import {SelectionDecisions} from '../components/selection';
import {VersionComparison} from '../components/version-comparison';
export function Page({w,c,table,setTable,tablesProps,readEvidence,open}:any){return <><VersionComparison c={c} onEvidence={tablesProps.onEvidence} onStopTrial={tablesProps.onStopTrial} onReport={w.readReport} onVersion={()=>{setTable('versions');open('lab')}}/><SelectionDecisions campaignId={c.id} decisions={c.selectionDecisions} tables={c.tables} readEvidence={readEvidence}/></>;}
