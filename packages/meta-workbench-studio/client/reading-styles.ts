export const readingStyles=`
.mh-root.studio-root{--paper:light-dark(#f7f8f5,#1a1c1d);--panel:light-dark(#ffffff,#222527);--sunk:light-dark(#f0f2ed,#2a2d2f);--ink:light-dark(#28382f,#e9e5dc);--muted:light-dark(#647168,#a9aba7);--line:light-dark(#e1e6de,#3a3f41);--accent:light-dark(#365f52,#7acbb6);--soft:light-dark(#eaf2ed,#1d3532);grid-template-columns:208px minmax(0,1fr)}
.studio-root .studio-content{padding:20px 32px 32px;max-width:1400px}
.studio-root .studio-sidebar{background:var(--paper)}
.studio-root .studio-sidebar nav button:nth-child(5){margin-top:0}
.studio-root .studio-sidebar nav button:nth-child(6){margin-top:20px}
.studio-root .studio-campaign{align-items:center;padding-bottom:12px;border-bottom:1px solid var(--line);margin-bottom:26px}
.studio-root .studio-campaign h2{font-size:14px;font-weight:500;margin:0 0 5px;color:var(--muted)}
.studio-root .studio-campaign .mh-eyebrow{display:none}
.studio-root .studio-model-line{font-size:11px}
.studio-root .studio-model-line .mh-badge{font-size:11px;border:0;background:var(--sunk);padding:2px 7px}
.studio-root .studio-models{display:inline-block;font-size:12px;margin:0}
.studio-root .studio-models summary{padding:0;min-height:24px;color:var(--muted)}
.studio-root .studio-models[open]{display:block;flex-basis:100%;padding:8px 12px;background:var(--panel)}
.studio-root .studio-models p{margin:6px 0}
.studio-root .studio-ended-reason{font-size:12px;color:var(--muted);margin:-14px 0 20px}
.studio-root .studio-page-intro{margin:8px 0 26px}
.studio-root .studio-page-intro>small,.studio-root .studio-kicker{display:block;font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--accent);margin-bottom:10px}
.studio-root .studio-page-intro h1{font-size:28px;letter-spacing:-.4px;font-weight:650}
.studio-root .studio-page-intro p{color:var(--muted);font-size:14px;margin:8px 0}
.studio-root .studio-reading-hero{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--panel);margin-bottom:34px}
.studio-root .studio-hero-findings,.studio-root .studio-hero-choice{padding:28px;min-width:0}
.studio-root .studio-hero-findings h2{font-size:25px;line-height:1.6}
.studio-root .studio-hero-lede{font-size:19px;line-height:1.85;font-weight:500;margin:12px 0 18px}
.studio-root .studio-hero-choice{background:var(--soft);display:flex;flex-direction:column;align-items:flex-start;border-left:1px solid var(--line)}
.studio-root .studio-hero-choice h2{font-size:21px;line-height:1.5}
.studio-root .studio-hero-choice p{font-size:14px;line-height:1.85}
.studio-root .studio-hero-choice>small:last-of-type{font-size:11px}
.studio-root .studio-hero-choice>button{margin-top:22px}
.studio-root .studio-reading-limits{color:var(--muted);font-size:12px;line-height:1.8;margin:14px 0}
.studio-root .studio-reading-limits>p{margin:0}
.studio-root .studio-reading-limits details{margin:4px 0}
.studio-root .studio-reading-limits summary{min-height:26px;padding:0;font-size:12px}
.studio-root .studio-source-note{font-size:11px;line-height:1.7;color:var(--muted)}
.studio-root button.studio-text-link{padding:4px 0;border:0;background:none;color:var(--accent);font-size:13px;text-align:left}
.studio-root .studio-comparison{margin:0 0 38px}
.studio-root .studio-section-title{align-items:center;margin:0 0 16px}
.studio-root .studio-section-title h2{font-size:22px;margin-bottom:4px}
.studio-root .studio-section-title p{margin:4px 0}
.studio-root .studio-performance-status{border:1px solid var(--line);border-bottom:0;border-radius:10px 10px 0 0;padding:14px 18px;background:var(--panel);display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between;font-size:12px;color:var(--muted)}
.studio-root .studio-performance-status strong{font-weight:500;color:var(--accent)}
.studio-root .studio-compare-settings{border:1px solid var(--line);border-top:0;border-bottom:0;background:var(--panel);margin:0;padding:0 18px}
.studio-root .studio-compare-settings>summary{font-size:12px;min-height:32px;padding:4px 0;color:var(--muted)}
.studio-root .studio-comparison-warning{font-size:12px;background:var(--warn-bg);padding:10px 14px;border-radius:4px;margin:0}
.studio-root .studio-matrix{border-radius:0 0 10px 10px}
.studio-root .studio-matrix-head button{background:none;border:0;font-size:15px;font-weight:650;padding:0;min-height:30px;color:var(--accent)}
.studio-root .studio-matrix-head small{font-size:12px;font-weight:400}
.studio-root .studio-result-cell{padding:20px 18px;min-height:118px;gap:5px}
.studio-root .studio-rate{font-size:25px}
.studio-root .studio-task-name{padding:18px}
.studio-root .studio-aggregate{font-size:12px}
.studio-root .studio-matrix-footer{display:flex;flex-wrap:wrap;gap:8px 20px;justify-content:space-between;color:var(--muted);font-size:11px;padding:10px 2px}
.studio-root .studio-matrix-footer details{margin:0}
.studio-root .studio-matrix-footer details[open]{flex-basis:100%}
.studio-root .studio-matrix-footer summary{min-height:20px;padding:0;font-size:11px}
.studio-root .studio-mobile-version-actions{display:none}
.studio-root .studio-cost-details{font-size:13px;border-bottom:1px solid var(--line);padding-bottom:8px}
.studio-root .studio-cost-details>summary{min-height:30px}
.studio-root .studio-research-notebook{margin:34px 0}
.studio-root .studio-turning-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.studio-root .studio-research-node{margin:0;border:1px solid var(--line);border-radius:10px;background:var(--panel);min-width:0;overflow:hidden}
.studio-root .studio-research-node>summary{padding:20px;list-style:none;color:var(--ink)}
.studio-root .studio-research-node>summary::-webkit-details-marker{display:none}
.studio-root .studio-research-node>summary>small{font-size:11px;display:block;color:var(--accent)}
.studio-root .studio-research-node>summary>p{font-size:14px;line-height:1.9}
.studio-root .studio-node-state{font-size:11px;border-radius:4px;background:var(--sunk);padding:4px 7px}
.studio-root .studio-node-open{display:block;color:var(--accent);font-size:12px;margin-top:15px}
.studio-root .studio-turning-grid>.studio-research-node[open]{grid-column:1/-1}
.studio-root .studio-research-list{display:grid;gap:12px}
.studio-root .studio-next-step{display:flex;align-items:center;gap:20px;padding:22px 24px;background:var(--soft);border-radius:10px;margin:28px 0}
.studio-root .studio-next-step>span{font-size:26px;color:var(--accent)}
.studio-root .studio-next-step>div{flex:1}
.studio-root .studio-next-step p{font-size:14px;margin:5px 0}
.studio-root .studio-next-step button{flex-shrink:0;background:transparent}
.studio-root .studio-path-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}
.studio-root .studio-path-grid>button{padding:20px;text-align:left;display:grid;gap:5px}
.studio-root .studio-path-grid strong{font-size:15px}
.studio-root .studio-path-grid span{font-size:12px;color:var(--muted)}
.studio-root .studio-run-strip{display:flex;flex-wrap:wrap;align-items:center;gap:8px 20px;border-top:1px solid var(--line);padding-top:18px;margin-top:28px;font-size:12px;color:var(--muted)}
.studio-root .studio-run-strip button{font-size:12px;background:none;border:0;min-height:28px;padding:0;color:var(--accent)}
.studio-root .studio-run-strip strong{color:var(--warn)}
.studio-root .studio-plugin-picker{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}
.studio-root .studio-plugin-picker button{display:flex;flex-direction:column;align-items:flex-start;text-align:left;padding:12px 18px;min-width:180px}
.studio-root .studio-plugin-picker button[aria-pressed=true]{background:var(--soft);border-color:var(--accent)}
.studio-root .studio-plugin-picker strong{font-size:14px}
.studio-root .studio-plugin-picker small{font-size:11px}
.studio-root .studio-plugin-purpose{margin-bottom:14px}
.studio-root .studio-reading-section{margin:14px 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.studio-root .studio-reading-section>summary{padding:20px 22px;display:flex;gap:18px;align-items:flex-start;list-style:none;color:var(--ink)}
.studio-root .studio-reading-section>summary::-webkit-details-marker{display:none}
.studio-root .studio-reading-section>summary>span:nth-child(2){flex:1;min-width:0}
.studio-root .studio-reading-section summary strong{font-size:16px;display:block}
.studio-root .studio-reading-section summary small{font-size:13px;display:block;margin-top:6px;line-height:1.8}
.studio-root .studio-reading-number{color:var(--accent);font-size:12px;padding-top:5px;font-variant-numeric:tabular-nums}
.studio-root .studio-reading-plus{color:var(--accent);font-size:20px;font-weight:300}
.studio-root .studio-reading-section[open]>.studio-reading-section-body{border-top:1px solid var(--line)}
.studio-root .studio-reading-section-body{padding:24px}
.studio-root .studio-explanation-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px 30px;margin:25px 0}
.studio-root .studio-explanation-grid h4{font-size:14px;color:var(--accent);margin:0}
.studio-root .studio-explanation-grid p{font-size:14px;line-height:1.9}
.studio-root .studio-observation{margin:20px 0}
.studio-root .studio-mechanism{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:16px 0}
.studio-root .studio-mechanism>div{background:var(--sunk);padding:16px;border-radius:6px;display:grid;gap:6px}
.studio-root .studio-mechanism strong{font-size:14px}
.studio-root .studio-evidence-context{border:1px solid var(--line);background:var(--paper)}
.studio-root .studio-evidence-context pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}
.studio-root .studio-reason-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:25px 0}
.studio-root .studio-reason-grid>section{border-top:2px solid var(--line);padding:20px 0}
.studio-root .studio-reason-grid small{color:var(--accent);font-size:12px}
.studio-root .studio-reason-grid h3{margin:10px 0}
.studio-root .studio-reason-grid p{font-size:14px;line-height:1.9}
.studio-root .studio-selection-reading{margin-top:36px}
.studio-root .studio-decision{padding:20px 24px;border-radius:0 10px 10px 0;font-size:17px}
.studio-root .studio-alternatives{margin:30px 0}
.studio-root .studio-alternative-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
.studio-root .studio-alternative-grid>article{background:var(--panel);border:1px solid var(--line);padding:22px;border-radius:10px}
.studio-root .studio-alternative-grid h4{margin:8px 0;font-size:17px}
.studio-root .studio-alternative-grid p{font-size:14px;line-height:1.9}
.studio-root .studio-history-decision{padding:12px 0;border-bottom:1px solid var(--line)}
@container (max-width:850px){
 .studio-root .studio-hero-findings,.studio-root .studio-hero-choice{padding:22px}
 .studio-root .studio-turning-grid{grid-template-columns:1fr}
 .studio-root .studio-reason-grid{grid-template-columns:1fr;gap:0}
 .studio-root .studio-reason-grid>section{padding:18px 0}
}
@container (max-width:650px){
 .studio-root .studio-reading-hero{grid-template-columns:1fr}
 .studio-root .studio-hero-choice{border-left:0;border-top:1px solid var(--line)}
 .studio-root .studio-page-intro h1{font-size:25px}
 .studio-root .studio-hero-lede{font-size:17px}
 .studio-root .studio-hero-findings h2{font-size:22px}
 .studio-root .studio-explanation-grid,.studio-root .studio-path-grid{grid-template-columns:1fr}
 .studio-root .studio-next-step{align-items:flex-start;flex-wrap:wrap;padding:20px}
 .studio-root .studio-next-step>span{display:none}
 .studio-root .studio-next-step>div{flex-basis:100%}
}
@container (max-width:600px){
 .studio-root .studio-mobile-version-actions{display:flex}
 .studio-root .studio-reading-section>summary{padding:16px;gap:12px}
 .studio-root .studio-reading-section-body{padding:16px}
 .studio-root .studio-mechanism{grid-template-columns:1fr}
 .studio-root .studio-mechanism>div{display:flex;justify-content:space-between;gap:10px}
 .studio-root .studio-plugin-picker button{min-width:0;flex:1 1 160px}
 .studio-root .studio-alternative-grid{grid-template-columns:1fr}
}
@media(max-width:760px){
 .studio-root .studio-content{padding:18px 14px}
 .studio-root .studio-campaign{margin-bottom:20px}
 .studio-root .studio-page-intro{margin-top:0}
 .studio-root .studio-hero-findings,.studio-root .studio-hero-choice{padding:20px}
 .studio-root .studio-sidebar nav button:nth-child(6){margin-top:10px}
}
`;
