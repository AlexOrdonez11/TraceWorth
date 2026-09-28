import {useState} from 'react';
import {ChartWidget} from './ChartWidget';
import type {ChartWidget as ChartConfig,ReportCohort} from './DashboardCreator';

type Props={
  cohort:ReportCohort;
  synthetic:boolean;
  onInspectWorkflow:(id:string)=>void;
  onBuild?:()=>void;
  buildLabel?:string;
};

export function OverviewVisuals({cohort,synthetic,onInspectWorkflow,onBuild,buildLabel='Build a dashboard'}:Props){
  const [workflowView,setWorkflowView]=useState<'workflow_outcome'|'workflow_status'>('workflow_outcome');
  const [runView,setRunView]=useState<'cost_by_run'|'usage_by_run'>(cohort.costs.length?'cost_by_run':'usage_by_run');
  const workflowChart:ChartConfig={type:'chart',id:'overview-workflow',width:'half',dataset:workflowView,visualization:workflowView==='workflow_outcome'?'pie':'vertical_bar'};
  const runChart:ChartConfig={type:'chart',id:'overview-runs',width:'half',dataset:runView,visualization:'horizontal_bar'};
  const workflows=cohort.summary.workflows??cohort.workflows.length;
  const outcomes=cohort.summary.outcome_workflows??cohort.workflows.filter(workflow=>workflow.accepted!==null).length;
  const priced=cohort.summary.known_cost_events??0;
  const unknown=cohort.summary.unknown_cost_events??0;
  const days=new Set(cohort.workflows.map(workflow=>{
    const raw=workflow.steps.find(step=>step.kind==='workflow'&&(step.depth===0||step.depth===undefined))?.started_at;
    const stamp=raw?Date.parse(raw):NaN;
    return Number.isFinite(stamp)?new Date(stamp).toISOString().slice(0,10):null;
  }).filter((day):day is string=>day!==null));
  const hasDuration=cohort.workflows.filter(workflow=>typeof workflow.duration_ms==='number').length>=2;
  const hasTime=days.size>=2;
  const observedDays=[...days].map(day=>Date.parse(`${day}T00:00:00.000Z`)).sort((a,b)=>a-b);
  const consecutiveDays=observedDays.every((day,index)=>index===0||day-observedDays[index-1]===86_400_000);
  const timeChart:ChartConfig={type:'chart',id:'overview-time',width:'half',dataset:'workflows_over_time',visualization:consecutiveDays?'trend':'vertical_bar'};
  const durationChart:ChartConfig={type:'chart',id:'overview-duration',width:'half',dataset:'duration_by_run',visualization:'vertical_bar'};
  return <section className="overview-evidence" aria-labelledby="overview-evidence-heading">
    <div className="overview-evidence-head"><div><span className="eyebrow">{synthetic?'SYNTHETIC SAMPLE':'SELECTED REPORT COHORT'}</span><h2 id="overview-evidence-heading">What did each run record?</h2><p>Start with outcomes, then compare usage and the costs that have price evidence. Select a run to inspect its steps.</p></div>{onBuild&&<button className="button primary" type="button" onClick={onBuild}>{buildLabel} →</button>}</div>
    <div className="overview-evidence-summary" aria-label="Selected cohort evidence"><div><strong>{workflows}</strong><span>recorded workflows</span></div><div><strong>{outcomes}<small> / {workflows}</small></strong><span>with an explicit outcome</span></div><div><strong>{priced}<small> / {priced+unknown}</small></strong><span>usage events with a price</span></div><p>{unknown} usage event{unknown===1?'':'s'} with unknown cost. This is evidence coverage in the selected {synthetic?'generated sample':'report window'}, not complete application accounting.</p></div>
    <div className="overview-chart-grid">
      <article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">01 / OUTCOMES</span><h3>How did the work finish?</h3></div><div className="overview-chart-switch" role="group" aria-label="Workflow chart view"><button type="button" aria-pressed={workflowView==='workflow_outcome'} onClick={()=>setWorkflowView('workflow_outcome')}>Outcomes</button><button type="button" aria-pressed={workflowView==='workflow_status'} onClick={()=>setWorkflowView('workflow_status')}>Status</button></div></div><ChartWidget key={workflowView} config={workflowChart} cohort={cohort}/></article>
      <article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">02 / RUN COMPARISON</span><h3>What did each run use?</h3></div><div className="overview-chart-switch" role="group" aria-label="Run comparison chart view"><button type="button" aria-pressed={runView==='cost_by_run'} onClick={()=>setRunView('cost_by_run')}>Recorded cost</button><button type="button" aria-pressed={runView==='usage_by_run'} onClick={()=>setRunView('usage_by_run')}>Usage events</button></div></div><ChartWidget key={runView} config={runChart} cohort={cohort} onInspectWorkflow={onInspectWorkflow}/></article>
    </div>
    {(hasTime||hasDuration)&&<div className="overview-chart-grid overview-chart-grid-secondary">
      {hasTime&&<article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">03 / OBSERVED ACTIVITY</span><h3>How did recorded starts change?</h3></div></div><ChartWidget config={timeChart} cohort={cohort}/>{!consecutiveDays&&<p className="chart-caveat">Observed days are shown as separate bars. Gaps have no recorded root start; they do not mean zero activity.</p>}</article>}
      {hasDuration&&<article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">04 / DURATION</span><h3>How long did runs take?</h3></div></div><ChartWidget config={durationChart} cohort={cohort} onInspectWorkflow={onInspectWorkflow}/></article>}
    </div>}
    <p className="overview-evidence-foot">{synthetic?'Generated examples only. ':'Received-time report, subject to its selected window and limits. '}Unknown prices are excluded from recorded cost amounts, never filled in as zero. Charts can be inspected with mouse, touch, or keyboard; each includes a data table.</p>
  </section>;
}
