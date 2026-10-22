import React from 'react';
import {ExportView} from '../components/reading';
import {API,api} from '@phyexp/meta-workbench-client';
export function Page({w,c,table,setTable,tablesProps,readEvidence,open}:any){return <ExportView campaign={c} apiBase={API} api={api} act={w.act} busy={w.busy} connected={w.connected} notice={w.setNotice}/>;}
