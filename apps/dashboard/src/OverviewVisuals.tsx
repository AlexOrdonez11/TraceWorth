import {useState} from 'react';
import {ChartWidget} from './ChartWidget';
import type {ChartWidget as ChartConfig,ReportCohort} from './DashboardCreator';

type Props={cohort:ReportCohort,synthetic:boolean,onInspectWorkflow:(id:string)=>void,onBuild?:()=>void,buildLabel?:string};
type Run=ReportCohort['workflows'][number];
type Ranked={workflow:Run,index:number,value:string};
type Decimal={units:bigint,scale:number};
const validNumber=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
const durationText=(value:number)=>{
  const rounded=Number(value.toPrecision(3));
  return `${rounded===value?'':'≈'}${rounded} ms`;
};
const runLabel=(workflow:Run,index:number)=>`Run ${index+1} · ${workflow.steps[0]?.name||'Workflow'}`;
const groupKey=(currency:string,basis:string)=>JSON.stringify([currency,basis]);

function parseDecimal(raw:string):Decimal|null{
  const match=/^(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(raw);
  if(!match)return null;
  const digits=(match[1]+(match[2]??'')).replace(/^0+/,'')||'0';
  if(digits==='0')return {units:0n,scale:0};
  const exponent=Number(match[3]??0)-(match[2]?.length??0);
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000||digits.length>10000)return null;
  return exponent>=0?{units:BigInt(digits+'0'.repeat(exponent)),scale:0}:{units:BigInt(digits),scale:-exponent};
}
function decimalAdd(left:Decimal,right:Decimal):Decimal{
  const scale=Math.max(left.scale,right.scale);
  return {units:left.units*10n**BigInt(scale-left.scale)+right.units*10n**BigInt(scale-right.scale),scale};
}
function decimalCompare(left:Decimal,right:Decimal):number{
  const scale=Math.max(left.scale,right.scale);
  const a=left.units*10n**BigInt(scale-left.scale);
  const b=right.units*10n**BigInt(scale-right.scale);
  return a>b?1:a<b?-1:0;
}
function decimalText(value:Decimal):string{
  const digits=value.units.toString();
  if(!value.scale&&digits.length<=32)return digits;
  if(value.scale>32||digits.length-value.scale>32){
    const significant=digits.replace(/0+$/,'');
    const exponent=digits.length-1-value.scale;
    return `${significant[0]}${significant.length>1?'.'+significant.slice(1):''}E${exponent>=0?'+':''}${exponent}`;
  }
  const padded=digits.padStart(value.scale+1,'0');
  return `${padded.slice(0,-value.scale)}.${padded.slice(-value.scale)}`.replace(/\.?0+$/,'');
}
function rootStart(workflow:Run):number|null{
  const raw=workflow.steps.find(step=>step.kind==='workflow'&&(step.depth===0||step.depth===undefined))?.started_at;
  const stamp=raw?Date.parse(raw):NaN;
  return Number.isFinite(stamp)?stamp:null;
}
function Ranking({title,rows,total,caveat,onInspectWorkflow}:{title:string,rows:Ranked[],total:number,caveat:string,onInspectWorkflow:(id:string)=>void}){
  return <article className="overview-ranking" aria-label={title}><header><h4>{title}</h4><span>Top {Math.min(rows.length,10)} of {rows.length} eligible</span></header>
    {rows.length?<ol>{rows.slice(0,10).map(({workflow,index,value},position)=><li key={workflow.workflow_id}><button type="button" data-workflow-id={workflow.workflow_id} onClick={()=>onInspectWorkflow(workflow.workflow_id)} aria-label={`Inspect ${runLabel(workflow,index)} from ${title} ranking`}><span className="overview-rank-number">{String(position+1).padStart(2,'0')}</span><span className="overview-rank-name"><strong>{runLabel(workflow,index)}</strong><small>{workflow.workflow_id}</small></span><b>{value}</b><span aria-hidden="true">↗</span></button></li>)}</ol>:<p className="overview-ranking-empty">No runs have a comparable recorded value for this ranking.</p>}
    <p className="overview-ranking-note">{caveat} {total-rows.length} of {total} selected runs excluded.</p>
  </article>;
}

export function OverviewVisuals({cohort,synthetic,onInspectWorkflow,onBuild,buildLabel='Build a dashboard'}:Props){
  const [workflowView,setWorkflowView]=useState<'workflow_outcome'|'workflow_status'>('workflow_outcome');
  const [costGroup,setCostGroup]=useState('');
  const workflowChart:ChartConfig={type:'chart',id:'overview-workflow',width:'half',dataset:workflowView,visualization:workflowView==='workflow_outcome'?'pie':'vertical_bar'};
  const total=cohort.workflows.length;
  const workflows=cohort.summary.workflows??total;
  const outcomes=cohort.summary.outcome_workflows??cohort.workflows.filter(workflow=>workflow.accepted!==null).length;
  const priced=cohort.summary.known_cost_events??0;
  const unknown=cohort.summary.unknown_cost_events??0;
  const usageTotal=priced+unknown;
  const groups=[...cohort.costs].sort((a,b)=>a.currency.localeCompare(b.currency)||a.cost_basis.localeCompare(b.cost_basis));
  const reference=groups.find(cost=>groupKey(cost.currency,cost.cost_basis)===costGroup)??groups[0];
  const durations=cohort.workflows.map(workflow=>workflow.duration_ms).filter(validNumber).sort((a,b)=>a-b);
  const median=durations.length?durations.length%2?durations[(durations.length-1)/2]:(durations[durations.length/2-1]+durations[durations.length/2])/2:null;
  const days=new Set(cohort.workflows.map(workflow=>{const stamp=rootStart(workflow);return stamp===null?null:new Date(stamp).toISOString().slice(0,10);}).filter((day):day is string=>day!==null));
  const observedDays=[...days].map(day=>Date.parse(`${day}T00:00:00.000Z`)).sort((a,b)=>a-b);
  const consecutiveDays=observedDays.every((day,index)=>index===0||day-observedDays[index-1]===86_400_000);
  const timeChart:ChartConfig={type:'chart',id:'overview-time',width:'half',dataset:'workflows_over_time',visualization:days.size>1&&consecutiveDays?'trend':'vertical_bar'};

  let unrankableCost=0;
  const costRows:{workflow:Run,index:number,value:Decimal}[]=cohort.workflows.flatMap((workflow,index)=>{
    if(!reference)return [];
    const amounts=workflow.costs.filter(cost=>cost.currency===reference.currency&&cost.cost_basis===reference.cost_basis);
    if(!amounts.length)return [];
    const parsed=amounts.map(cost=>parseDecimal(cost.amount));
    if(parsed.some(value=>value===null)){unrankableCost++;return [];}
    return [{workflow,index,value:parsed.reduce<Decimal>((sum,value)=>decimalAdd(sum,value!),{units:0n,scale:0})}];
  }).sort((a,b)=>decimalCompare(b.value,a.value)||a.workflow.workflow_id.localeCompare(b.workflow.workflow_id));
  const durationRows=cohort.workflows.flatMap((workflow,index)=>validNumber(workflow.duration_ms)?[{workflow,index,value:workflow.duration_ms}]:[]).sort((a,b)=>b.value-a.value||a.workflow.workflow_id.localeCompare(b.workflow.workflow_id));
  const usageRows=cohort.workflows.flatMap((workflow,index)=>validNumber(workflow.usage_events)?[{workflow,index,value:workflow.usage_events}]:[]).sort((a,b)=>b.value-a.value||a.workflow.workflow_id.localeCompare(b.workflow.workflow_id));
  const failed=cohort.summary.failed_steps??0;
  const retries=cohort.summary.retry_steps??0;
  const steps=cohort.summary.steps??0;

  return <section className="overview-evidence" aria-labelledby="overview-evidence-heading">
    <div className="overview-evidence-head"><div><span className="eyebrow">{synthetic?'SYNTHETIC SAMPLE':'SELECTED REPORT COHORT'}</span><h2 id="overview-evidence-heading">What does this cohort show?</h2><p>Review the selected cohort as a whole, then inspect ranked runs and their underlying steps.</p></div>{onBuild&&<button className="button primary" type="button" onClick={onBuild}>{buildLabel} →</button>}</div>
    <div className="overview-evidence-summary" aria-label="Selected cohort evidence"><div><strong>{workflows}</strong><span>recorded workflows</span></div><div><strong>{outcomes}<small> / {workflows}</small></strong><span>with an explicit outcome</span></div><div><strong>{priced}<small> / {usageTotal}</small></strong><span>usage events with a price</span></div><p>{unknown} usage event{unknown===1?'':'s'} with unknown cost. These are evidence counts in the selected {synthetic?'generated sample':'received-time report window'}, not complete application accounting.</p></div>
    <div className="overview-aggregate-grid">
      <article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">01 / WORKFLOW DISTRIBUTION</span><h3>Workflow outcomes and status</h3></div><div className="overview-chart-switch" role="group" aria-label="Workflow chart view"><button type="button" aria-pressed={workflowView==='workflow_outcome'} onClick={()=>setWorkflowView('workflow_outcome')}>Outcomes</button><button type="button" aria-pressed={workflowView==='workflow_status'} onClick={()=>setWorkflowView('workflow_status')}>Status</button></div></div><ChartWidget key={workflowView} config={workflowChart} cohort={cohort}/></article>
      <article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">02 / USAGE EVIDENCE</span><h3>Usage price coverage</h3></div></div><div className="overview-aggregate-body"><p className="overview-aggregate-lead">{usageTotal?`${priced} of ${usageTotal} recorded usage events include a price.`:'No usage events were recorded in this cohort.'}</p><div className="overview-coverage-track" role="img" aria-label={`${priced} priced usage events; ${unknown} usage events with unknown cost`}>{usageTotal>0&&<><span style={{width:`${priced/usageTotal*100}%`}}/><i style={{width:`${unknown/usageTotal*100}%`}}/></>}</div><dl className="overview-coverage-legend"><div><dt>Price recorded</dt><dd>{priced}</dd></div><div><dt>Cost unknown</dt><dd>{unknown}</dd></div></dl><p className="overview-aggregate-note">A missing price is not a zero-dollar event. These are usage-event counts, not tokens or complete spend.</p></div></article>
      <article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">03 / PRICE EVIDENCE</span><h3>Recorded cost by currency and basis</h3></div></div><div className="overview-aggregate-body">{groups.length?<ul className="overview-cost-list">{groups.map((cost,index)=><li key={`${cost.currency}-${cost.cost_basis}-${index}`}><strong>{cost.amount} {cost.currency}</strong><span>{cost.cost_basis} basis{cost.partial?' · partial':''}</span></li>)}</ul>:<p className="overview-aggregate-lead">No priced usage recorded. Cost is unknown, not zero.</p>}<p className="overview-aggregate-note">Amounts remain separate by currency and price basis. Unknown-price usage is excluded{groups.length?'; amounts may be partial.':'.'}</p></div></article>
      <article className="overview-chart-card"><div className="overview-chart-head"><div><span className="eyebrow">04 / TIMING EVIDENCE</span><h3>Recorded root duration</h3></div></div><div className="overview-aggregate-body">{median===null?<p className="overview-aggregate-lead">No root workflow durations were recorded.</p>:<><div className="overview-duration-primary"><strong>{durationText(median)}</strong><span>median of {durations.length} recorded root durations</span></div><div className="overview-duration-range" role="img" aria-label={`Recorded root duration range: minimum ${durationText(durations[0])}, median ${durationText(median)}, maximum ${durationText(durations.at(-1)!)}`}><span style={{left:`${durations[0]===durations.at(-1)?50:(median-durations[0])/(durations.at(-1)!-durations[0])*100}%`}}/></div><dl className="overview-duration-ends"><div><dt>Fastest recorded</dt><dd>{durationText(durations[0])}</dd></div><div><dt>Slowest recorded</dt><dd>{durationText(durations.at(-1)!)}</dd></div></dl></>}<p className="overview-aggregate-note">{total-durations.length} of {total} runs lack a recorded root duration and are excluded. This observed range is not a latency guarantee.</p></div></article>
      <article className="overview-chart-card overview-activity-card"><div className="overview-chart-head"><div><span className="eyebrow">05 / OBSERVED ACTIVITY</span><h3>Observed daily starts</h3></div></div>{days.size?<><ChartWidget config={timeChart} cohort={cohort}/>{!consecutiveDays&&<p className="overview-activity-gap">Observed days are shown as separate bars. Gaps have no recorded root start in this cohort; they do not mean zero activity.</p>}</>:<p className="overview-aggregate-body">No root start timestamps were recorded, so daily activity cannot be plotted.</p>}</article>
    </div>
    <div className="overview-analysis" aria-label="What the evidence says"><span className="eyebrow">DERIVED OBSERVATIONS</span><h3>What the evidence says</h3><ul><li>{outcomes} of {workflows} workflows have an explicit outcome; {workflows-outcomes} do not.</li><li>{failed} failed step{failed===1?'':'s'} and {retries} retry step{retries===1?'':'s'} were recorded among {steps} steps.</li><li>{priced} of {usageTotal} recorded usage events have a price; {unknown} have unknown cost.</li><li>{durations.length} of {total} selected runs have a recorded root duration{median===null?'.':`; their median is ${durationText(median)}.`}</li></ul><p>These are descriptive observations from the selected report. They are not verified improvement recommendations.</p></div>
    <div className="overview-investigations"><div className="overview-investigations-head"><div><span className="eyebrow">INSPECT THE EVIDENCE</span><h3>Runs to investigate</h3><p>Rankings describe observed values; they do not establish causes or complete accounting.</p></div><span>{total} selected runs · up to 10 per list</span></div>{groups.length>1&&<label className="overview-cost-select">Comparable cost group<select aria-label="Comparable cost group" value={groupKey(reference.currency,reference.cost_basis)} onChange={event=>setCostGroup(event.target.value)}>{groups.map(cost=><option key={groupKey(cost.currency,cost.cost_basis)} value={groupKey(cost.currency,cost.cost_basis)}>{cost.currency} · {cost.cost_basis}</option>)}</select></label>}<div className="overview-ranking-grid">
      <Ranking title="Highest comparable recorded cost" rows={costRows.map(row=>({...row,value:`${decimalText(row.value)} ${reference?.currency??''}`}))} total={total} caveat={reference?`Only ${reference.currency} · ${reference.cost_basis} priced amounts are compared. Other groups and unpriced usage are excluded from values; ranked amounts may be partial.${unrankableCost?` ${unrankableCost} priced run${unrankableCost===1?'':'s'} could not be ranked because an amount exceeds the chart's exact comparison limit.`:''}`:'No currency and price basis has recorded cost.'} onInspectWorkflow={onInspectWorkflow}/>
      <Ranking title="Longest recorded duration" rows={durationRows.map(row=>({...row,value:`${durationText(row.value)}`}))} total={total} caveat="Only recorded root durations are ranked; missing durations are not zero. Approximate labels are rounded for display; ranking uses recorded values." onInspectWorkflow={onInspectWorkflow}/>
      <Ranking title="Most usage events" rows={usageRows.map(row=>({...row,value:`${row.value} events`}))} total={total} caveat="Usage-event counts are ranked, not token totals. Missing counts are excluded; recorded zero remains eligible." onInspectWorkflow={onInspectWorkflow}/>
    </div></div>
    <p className="overview-evidence-foot">{synthetic?'Generated examples only. ':'Received-time report, subject to its selected window and limits. '}Unknown prices are excluded from recorded cost amounts, never filled in as zero. Rankings use all workflows in the selected report cohort; configure per-run charts in the dashboard builder.</p>
  </section>;
}
