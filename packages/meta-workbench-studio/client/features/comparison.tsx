import React from 'react';
import {VersionComparison} from '../components/version-comparison';
export function Page({w,c,table,setTable,tablesProps,readEvidence,open}:any){return <VersionComparison c={c} onEvidence={tablesProps.onEvidence} onStopTrial={tablesProps.onStopTrial} onVersion={()=>{setTable('versions');open('lab')}}/>;}
