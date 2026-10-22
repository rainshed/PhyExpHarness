import React from 'react';
import {SelectionDecisions} from '../components/selection';
import {VersionComparison} from '../components/version-comparison';
import {PageIntro} from '../components/reading-layout';
export function Page({w,c,tablesProps,readEvidence}:any){
 return <><PageIntro eyebrow="COMPARE / 组成、表现与选择依据" title="哪个版本值得继续？">先了解各版本的插件组合，再比较每项任务的结果、进度和选择依据。</PageIntro><VersionComparison key={c.id} c={c} onEvidence={tablesProps.onEvidence} onStopTrial={tablesProps.onStopTrial} onReport={w.readReport} onPlugin={w.openPlugin} onRename={tablesProps.onRename} canRename={w.connected&&!w.busy} readingState={w.readingPages?.compare} onReadingStateChange={w.saveReadingPage?((state:any)=>w.saveReadingPage('compare',state)):undefined} showComposition/><SelectionDecisions onReport={w.readReport} campaignId={c.id} decisions={c.selectionDecisions} tables={c.tables} readEvidence={readEvidence}/></>;
}
