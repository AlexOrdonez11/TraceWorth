import {useState} from 'react';
import type {ChartWidget as ChartConfig, ReportCohort} from './DashboardCreator';

export const chartDatasets = {
  workflow_status: {label:'Workflow status',visualizations:['horizontal_bar','vertical_bar','pie']},
  workflow_outcome: {label:'Workflow outcome',visualizations:['horizontal_bar','vertical_bar','pie']},
  usage_by_run: {label:'Usage events by run',visualizations:['horizontal_bar','vertical_bar','trend']},
  cost_by_run: {label:'Recorded cost by run',visualizations:['horizontal_bar','vertical_bar','trend']},
  duration_by_run: {label:'Duration by run',visualizations:['horizontal_bar','vertical_bar','trend']},
  workflows_over_time: {label:'Workflows over time',visualizations:['vertical_bar','trend']},
} as const;
export type ChartDataset = keyof typeof chartDatasets;
export type ChartVisualization = 'horizontal_bar'|'vertical_bar'|'pie'|'trend';
export const visualizationLabels:Record<ChartVisualization,string> = {
  horizontal_bar:'Horizontal bars', vertical_bar:'Vertical bars', pie:'Pie', trend:'Trend',
};
export const supportsVisualization=(dataset:ChartDataset,visualization:ChartVisualization):boolean =>
  (chartDatasets[dataset].visualizations as readonly string[]).includes(visualization);

type Point = {id:string,label:string,value:number|null,note?:string};
type ChartData = {points:Point[],unit:string,caveat:string,missing:number,kind:'count'|'money'|'duration'};
const colors=['#84ae69','#426f59','#dda974','#a1b6ac','#a88262','#7390ae'];
const validNumber=(value:unknown):number|null => typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
const rootStart=(workflow:ReportCohort['workflows'][number]):number|null => {
  const root=workflow.steps.find(step=>step.kind==='workflow'&&(step.depth===0||step.depth===undefined));
  const raw=root?.started_at;
  if(!raw)return null;
  const time=Date.parse(raw);
  return Number.isFinite(time)?time:null;
};
const runName=(workflow:ReportCohort['workflows'][number],index:number)=>`Run ${index+1} · ${workflow.steps[0]?.name||'Workflow'}`;

function chartData(config:ChartConfig,cohort:ReportCohort):ChartData{
  const {dataset,visualization}=config;
  const workflows=cohort.workflows;
  if(dataset==='workflow_status'){
    const groups=new Map<string,number>();
    workflows.forEach(workflow=>groups.set(workflow.status,1+(groups.get(workflow.status)??0)));
    return {points:[...groups].map(([status,value])=>({id:status,label:status.replaceAll('_',' '),value})),unit:'workflows',caveat:'Counts reflect workflow states recorded in this report window.',missing:0,kind:'count'};
  }
  if(dataset==='workflow_outcome'){
    const accepted=workflows.filter(workflow=>workflow.accepted===true).length;
    const rejected=workflows.filter(workflow=>workflow.accepted===false).length;
    const missing=workflows.length-accepted-rejected;
    return {points:[{id:'accepted',label:'Accepted',value:accepted},{id:'rejected',label:'Not accepted',value:rejected},{id:'missing',label:'Not recorded',value:missing}],unit:'workflows',caveat:'Not recorded is an unknown outcome, not a failed result.',missing,kind:'count'};
  }
  if(dataset==='workflows_over_time'){
    const groups=new Map<string,number>();
    let missing=0;
    workflows.forEach(workflow=>{
      const start=rootStart(workflow);
      if(start===null){missing++;return;}
      const day=new Date(start).toISOString().slice(0,10);
      groups.set(day,1+(groups.get(day)??0));
    });
    const days=[...groups].sort(([a],[b])=>a.localeCompare(b));
    const visible=days.slice(-20);
    return {points:visible.map(([day,value])=>({id:day,label:`${day} UTC`,value})),unit:'workflows',caveat:`Showing ${visible.length} of ${days.length} observed UTC days${days.length>20?' (latest 20 only)':''}. ${days.length===1?'One observed day does not establish a historical trend. ':''}Only days with recorded root start timestamps appear; ${missing} of ${workflows.length} runs lack one. Timestamps may be caller-supplied. Missing days are not zero-activity days.`,missing,kind:'count'};
  }
  const reference=dataset==='cost_by_run'?cohort.costs[0]:undefined;
  if(dataset==='cost_by_run'&&!reference)return {points:[],unit:'recorded cost',caveat:'No priced cost is available for a single currency and basis. Unknown cost is not zero.',missing:workflows.length,kind:'money'};
  const visibleWorkflows=visualization==='trend'?workflows.map((workflow,index)=>({workflow,index,start:rootStart(workflow)})).filter(row=>row.start!==null).sort((a,b)=>(a.start??0)-(b.start??0)).slice(-20):workflows.map((workflow,index)=>({workflow,index,start:rootStart(workflow)})).slice(-20);
  const rows=visibleWorkflows.map(({workflow,index,start})=>{
    let value:number|null;
    let note='';
    if(dataset==='usage_by_run')value=validNumber(workflow.usage_events);
    else if(dataset==='duration_by_run')value=validNumber(workflow.duration_ms);
    else {
      const matching=workflow.costs.filter(cost=>cost.currency===reference!.currency&&cost.cost_basis===reference!.cost_basis);
      value=matching.length?matching.reduce((sum,cost)=>sum+Number(cost.amount),0):null;
      if(workflow.unknown_cost_events)note=`${workflow.unknown_cost_events} usage event${workflow.unknown_cost_events===1?'':'s'} with unknown cost`;
      if(!matching.length&&workflow.costs.length)note=`Other currencies or bases recorded${note?` · ${note}`:''}`;
    }
    return {id:workflow.workflow_id,label:runName(workflow,index),value,note,start};
  });
  let points:Point[]=rows;
  const untimed=workflows.filter(workflow=>rootStart(workflow)===null).length;
  if(visualization==='trend'){
    points=rows.map(row=>({...row,label:`${new Date(row.start!).toISOString().replace('T',' ').slice(0,16)} UTC · ${row.label}`}));
  }
  const missing=rows.filter(row=>row.value===null).length;
  const label=dataset==='usage_by_run'?'usage-event count':dataset==='duration_by_run'?'root workflow duration':'recorded cost';
  let caveat=`Showing ${rows.length} of ${workflows.length} report runs${workflows.length>20?' (last 20 in report order for bars; latest 20 timestamped runs for trend)':''}. ${label[0].toUpperCase()+label.slice(1)} comes from runs in this report window.`;
  if(dataset==='cost_by_run')caveat+=` Only ${reference!.currency} · ${reference!.cost_basis} costs are compared. ${missing} shown run${missing===1?'':'s'} ${missing===1?'lacks':'lack'} comparable priced usage; unknown and other costs are excluded, so amounts may be partial.`;
  if(dataset==='duration_by_run')caveat+=` ${missing} run${missing===1?'':'s'} have no recorded root duration.`;
  if(dataset==='usage_by_run')caveat+=` ${missing} run${missing===1?'':'s'} have no recorded usage-event count. This is not a token total.`;
  if(visualization==='trend')caveat+=` Ordered by recorded root start timestamp; ${untimed} run${untimed===1?'':'s'} without a start timestamp ${untimed===1?'is':'are'} excluded. Timestamps may be caller-supplied and sparse; gaps and missing values are not drawn as zero.`;
  return {points,unit:dataset==='cost_by_run'?`${reference!.currency} · ${reference!.cost_basis}`:dataset==='duration_by_run'?'ms':'usage events',caveat,missing,kind:dataset==='cost_by_run'?'money':dataset==='duration_by_run'?'duration':'count'};
}

function formatted(value:number|null,kind:ChartData['kind'],unit:string){
  if(value===null)return kind==='money'?'No comparable price':'Not recorded';
  if(kind==='money')return `${Number(value.toPrecision(9))} ${unit}`;
  if(kind==='duration')return `${value.toFixed(1)} ms`;
  return String(value);
}

export function ChartWidget({config,cohort,onInspectWorkflow}:{config:ChartConfig,cohort:ReportCohort,onInspectWorkflow?:(workflowId:string)=>void}){
  const [selected,setSelected]=useState<string|null>(null);
  const data=chartData(config,cohort);
  const points=data.points;
  const active=points.find(point=>point.id===selected)??null;
  const max=Math.max(0,...points.map(point=>point.value??0))||1;
  const total=points.reduce((sum,point)=>sum+(point.value??0),0);
  const title=chartDatasets[config.dataset].label;
  const chartLabel=`${title} · ${visualizationLabels[config.visualization]}`;
  const inspectable=config.dataset==='usage_by_run'||config.dataset==='cost_by_run'||config.dataset==='duration_by_run';
  function selectPoint(point:Point){setSelected(point.id);if(inspectable)onInspectWorkflow?.(point.id);}
  const trendSegments:string[]=[];
  let segment:string[]=[];
  points.forEach((point,index)=>{
    if(point.value===null){if(segment.length>1)trendSegments.push(segment.join(' '));segment=[];return;}
    const x=points.length===1?50:8+index/(points.length-1)*84;
    const y=90-point.value/max*78;
    segment.push(`${segment.length?'L':'M'} ${x} ${y}`);
  });
  if(segment.length>1)trendSegments.push(segment.join(' '));
  if(!points.length)return <div className="chart-widget"><p className="builder-no-data">No chartable values in this report window.</p><p className="chart-caveat">{data.caveat}</p></div>;
  return <div className="chart-widget">
    <div className="chart-heading"><strong>{title}</strong><span>{visualizationLabels[config.visualization]}</span></div>
    {config.visualization==='horizontal_bar'&&<div className="chart-horizontal" role="group" aria-label={chartLabel}>{points.map((point,index)=><button type="button" key={point.id} className={'chart-horizontal-row'+(active?.id===point.id?' active':'')} onClick={()=>selectPoint(point)} aria-pressed={active?.id===point.id} aria-label={`${onInspectWorkflow&&inspectable?'Inspect ':''}${point.label}: ${formatted(point.value,data.kind,data.unit)}${point.note?`; ${point.note}`:''}`}><span className="chart-row-label">{point.label}</span><span className="chart-bar-track" aria-hidden="true">{point.value!==null&&point.value>0&&<i style={{width:`${point.value/max*100}%`,background:colors[index%colors.length]}}/>}</span><b>{formatted(point.value,data.kind,data.unit)}</b></button>)}</div>}
    {config.visualization==='vertical_bar'&&<>{points.length>6&&<p className="chart-scroll-hint" id={`${config.id}-scroll-hint`}>Swipe or scroll sideways to see all {points.length} bars →</p>}<div className="chart-vertical" role="group" aria-label={chartLabel} aria-describedby={points.length>6?`${config.id}-scroll-hint`:undefined} tabIndex={0}>{points.map((point,index)=><button type="button" key={point.id} className={'chart-vertical-item'+(active?.id===point.id?' active':'')} onClick={()=>selectPoint(point)} aria-pressed={active?.id===point.id} aria-label={`${onInspectWorkflow&&inspectable?'Inspect ':''}${point.label}: ${formatted(point.value,data.kind,data.unit)}${point.note?`; ${point.note}`:''}`}><span className="chart-vertical-value">{formatted(point.value,data.kind,data.unit)}</span><span className="chart-vertical-track" aria-hidden="true">{point.value!==null&&point.value>0&&<i style={{height:`${point.value/max*100}%`,background:colors[index%colors.length]}}/>}</span><span className="chart-vertical-label">{point.label}</span></button>)}</div></>}
    {config.visualization==='pie'&&<div className="chart-pie-wrap" role="group" aria-label={chartLabel}><div className="chart-pie" role="img" aria-label={points.map(point=>`${point.label}: ${point.value}`).join(', ')} style={{background:total?`conic-gradient(${points.map((point,index)=>`${colors[index%colors.length]} ${points.slice(0,index).reduce((sum,item)=>sum+(item.value??0),0)/total*100}% ${points.slice(0,index+1).reduce((sum,item)=>sum+(item.value??0),0)/total*100}%`).join(',')})`:'#edf2e9'}}><span>{total}<small>{data.unit}</small></span></div><div className="chart-pie-legend">{points.map((point,index)=><button type="button" key={point.id} onClick={()=>setSelected(point.id)} aria-pressed={active?.id===point.id}><i style={{background:colors[index%colors.length]}}/><span>{point.label}</span><b>{point.value}</b></button>)}</div></div>}
    {config.visualization==='trend'&&<div className="chart-trend-wrap" role="group" aria-label={chartLabel}><div className="chart-trend"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{trendSegments.map((path,index)=><path key={index} d={path} fill="none" stroke="#527b5d" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>)}</svg>{points.map((point,index)=>point.value!==null&&<button type="button" key={point.id} className={'chart-trend-point'+(active?.id===point.id?' active':'')} style={{left:`${points.length===1?50:8+index/(points.length-1)*84}%`,bottom:`${10+point.value/max*78}%`}} onClick={()=>selectPoint(point)} aria-pressed={active?.id===point.id} aria-label={`${onInspectWorkflow&&inspectable?'Inspect ':''}${point.label}: ${formatted(point.value,data.kind,data.unit)}`}/>)}</div><div className="chart-trend-axis"><span>{points[0]?.label}</span><span>{points.length>1?points.at(-1)?.label:''}</span></div></div>}
    {active&&<div className="chart-selection" role="status"><strong>{active.label}</strong><span>{formatted(active.value,data.kind,data.unit)}{active.note?` · ${active.note}`:''}</span></div>}
    <p className="chart-caveat">{data.caveat}</p>
    <details className="chart-data-table"><summary>View chart data</summary><div tabIndex={0} role="region" aria-label={`${title} data table`}><table><thead><tr><th>Category</th><th>Recorded value</th></tr></thead><tbody>{points.map(point=><tr key={point.id}><td>{point.label}</td><td>{formatted(point.value,data.kind,data.unit)}{point.note&&<small>{point.note}</small>}</td></tr>)}</tbody></table></div></details>
  </div>;
}
