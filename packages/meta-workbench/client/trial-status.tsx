import React from 'react';
import {date,duration} from './common';
import {trialStage,trialTiming,waitingReason,activityProgress} from './trial-status.mjs';

export function TrialStatus({trial:t,campaign:c={}}:any) {
 const stage=trialStage(t),timing=trialTiming(t,c),reason=waitingReason(t,c);
 return <div className="mh-trial-status"><strong className={'mh-phase '+stage.key}>{c.historical?'当时 · ':''}{stage.label}</strong>
 <div className="mh-trial-time">{t.taskAssessment?.category==='not_started'?'未启动，无执行耗时':timing.seconds==null?(stage.key==='queued'?'排队起点未记录':'耗时未完整记录'):`${timing.label} ${duration(timing.seconds)}`}{timing.start!=null&&<small>{stage.key==='queued'?'本轮受理于 ':'启动于 '}{date(timing.start)}</small>}</div>
 {reason&&<p className="mh-wait-reason">{c.historical?'当时等待原因：':'等待原因：'}{reason}</p>}</div>;
}
export function SnapshotNotice({campaign:c,recordedAt}:any) {
 return <aside className="mh-snapshot"><strong>历史快照 · {c.snapshotAt!=null?'截至 '+date(c.snapshotAt):'原始采集时间未记录'}</strong>
 <p>这里保留当时的排队、运行和计分状态，时长固定在快照时刻。当前进度请查看活动的实验记录。</p>
 {recordedAt!=null&&<small>报告修订于 {date(recordedAt)}；修订时间不代表实验状态已更新。</small>}</aside>;
}
export function ProgressNotice({campaign:c}:any) {
 return <div className="mh-progress-note"><strong>{activityProgress(c)}</strong><p>排队尚未开始；运行中表示实验已启动；覆盖不足表示部分任务还没有可计分结果。</p>
 <details><summary>评分阶段如何显示？</summary><p>只有明确的评分阶段记录才显示“评分中”。当前后台尚未单独上报评分进度，“运行中 · 阶段未细分”可能包含执行、评分或结果归集；等待结果不等于正在评分。</p></details></div>;
}
