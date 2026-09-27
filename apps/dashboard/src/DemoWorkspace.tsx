import {useEffect, useRef, useState} from 'react';
import {Brand} from '../../../packages/ui/Brand';
import fixture from './demo-report.json';

type Cost = {amount:string,currency:string,cost_basis:string,partial:boolean,cost_per_accepted_result:string|null};
type Usage = {provider:string,model_or_service:string,unit:string,value:string};
type Step = {step_id:string,name:string,attempt_number:number,status:string,depth:number,duration_ms:number|null,costs:Cost[],unknown_cost_events:number};
type Workflow = {workflow_id:string,status:string,accepted:boolean|null,incomplete_telemetry:boolean,usage_events:number,unknown_cost_events:number,steps:Step[],costs:Cost[],usage:Usage[]};
type Finding = {code:string,message:string,evidence:string[]};
type Cohort = {application_id:string,environment:string,configuration_id:string,summary:Record<string,number>,costs:Cost[],workflows:Workflow[],findings:Finding[]};
const sample = fixture as {applications:{id:string,name:string,slug:string}[],report:{cohorts:Cohort[],assumptions:string[]}};
const showMoney = (cost:Cost)=>`${cost.amount} ${cost.currency} · ${cost.cost_basis}${cost.partial?' · partial':''}`;
const accepted = (value:boolean|null)=>value===null?'Not recorded':value?'Yes':'No';
const compactMoney = (amount:number,currency:string)=>`${amount.toFixed(3)} ${currency}`;

function DemoVisuals({cohort,onInspect}:{cohort:Cohort,onInspect:(workflow:Workflow)=>void}){
  const [measure,setMeasure]=useState<'cost'|'usage'>('cost');
  const priced=cohort.costs[0];
  const currency=priced?.currency??'USD';
  const basis=priced?.cost_basis??'estimated';
  const rows=cohort.workflows.map((workflow,index)=>{
    const comparableCosts=workflow.costs.filter(item=>item.currency===currency&&item.cost_basis===basis);
    return {
      workflow,
      label:`Run ${index+1}`,
      cost:comparableCosts.reduce((total,item)=>total+Number(item.amount),0),
      hasPricedCost:comparableCosts.length>0,
      usage:workflow.usage_events,
    };
  });
  const maxValue=Math.max(0,...rows.map(row=>measure==='cost'?row.cost:row.usage))||1;
  const outcomeKnown=cohort.workflows.filter(workflow=>workflow.accepted!==null).length;
  const outcomeAccepted=cohort.workflows.filter(workflow=>workflow.accepted===true).length;
  const outcomeRejected=cohort.workflows.filter(workflow=>workflow.accepted===false).length;
  const outcomeMissing=cohort.workflows.length-outcomeKnown;
  const knownCost=cohort.summary.known_cost_events??0;
  const unknownCost=cohort.summary.unknown_cost_events??0;
  const costEvents=knownCost+unknownCost;
  return <div className="demo-visual-grid">
    <section className="panel demo-plot" aria-labelledby="demo-plot-title">
      <div className="panel-heading demo-plot-heading"><div><span className="eyebrow">WORKFLOW COMPARISON</span><h2 id="demo-plot-title">What did each run record?</h2><p>Switch the measure and select a run to inspect its steps and usage.</p></div><div className="demo-measure" role="group" aria-label="Compare workflows by"><button type="button" className={measure==='cost'?'active':''} aria-pressed={measure==='cost'} onClick={()=>setMeasure('cost')}>Recorded cost</button><button type="button" className={measure==='usage'?'active':''} aria-pressed={measure==='usage'} onClick={()=>setMeasure('usage')}>Usage events</button></div></div>
      <div className="demo-plot-rows">
        {rows.map(({workflow,label,cost,hasPricedCost,usage})=>{
          const value=measure==='cost'?cost:usage;
          const hasBar=value>0;
          const costLabel=hasPricedCost?compactMoney(cost,currency):workflow.costs.length?'Other price basis':'Unpriced';
          return <button type="button" className="demo-plot-row" key={workflow.workflow_id} onClick={()=>onInspect(workflow)} aria-label={`Inspect ${label}, ${workflow.steps[0]?.name||'workflow'}: ${measure==='cost'?(hasPricedCost?`${costLabel} recorded ${basis} cost`:workflow.costs.length?'priced usage recorded in a different currency or basis':'no priced usage recorded'):`${usage} recorded usage event${usage===1?'':'s'}`}; ${workflow.unknown_cost_events} unknown cost event${workflow.unknown_cost_events===1?'':'s'}`}>
            <span className="demo-plot-label"><strong>{label}</strong><small>{workflow.steps[0]?.name||'Missing root'}</small></span>
            <span className="demo-plot-track" aria-hidden="true">{hasBar&&<span className="demo-plot-fill" style={{width:`${Math.max(3,value/maxValue*100)}%`}}/>}</span>
            <span className="demo-plot-value">{measure==='cost'?costLabel:usage}</span>
            {workflow.unknown_cost_events>0&&<span className="demo-plot-unknown">{workflow.unknown_cost_events} cost event{workflow.unknown_cost_events===1?'':'s'} unknown</span>}
          </button>;
        })}
      </div>
      <p className="demo-plot-foot">{measure==='cost'?`Only ${currency} ${basis} costs recorded in this sample are plotted. Unpriced usage is excluded, so these are partial amounts.`:'Usage events count recorded calls; they do not represent tokens or prices. Open a run for its recorded units.'}</p>
    </section>
    <section className="panel demo-coverage" aria-labelledby="demo-coverage-title"><div className="panel-heading"><div><span className="eyebrow">EVIDENCE COVERAGE</span><h2 id="demo-coverage-title">What can we actually conclude?</h2><p>Coverage describes only the generated sample workflows and usage.</p></div></div>
      <div className="demo-coverage-block"><div className="demo-coverage-head"><strong>Recorded outcomes</strong><span>{outcomeKnown} of {cohort.workflows.length} workflows</span></div><div className="demo-segments" role="img" aria-label={`${outcomeAccepted} accepted, ${outcomeRejected} not accepted, ${outcomeMissing} without a recorded outcome`}>{cohort.workflows.length>0&&<><span className="accepted" style={{width:`${outcomeAccepted/cohort.workflows.length*100}%`}}/><span className="rejected" style={{width:`${outcomeRejected/cohort.workflows.length*100}%`}}/><span className="missing" style={{width:`${outcomeMissing/cohort.workflows.length*100}%`}}/></>}</div><div className="demo-legend"><span><i className="accepted"/> {outcomeAccepted} accepted</span><span><i className="rejected"/> {outcomeRejected} not accepted</span><span><i className="missing"/> {outcomeMissing} not recorded</span></div></div>
      <div className="demo-coverage-block"><div className="demo-coverage-head"><strong>Cost evidence</strong><span>{knownCost} of {costEvents} usage events priced</span></div><div className="demo-segments" role="img" aria-label={`${knownCost} priced usage events, ${unknownCost} usage events with unknown cost`}>{costEvents>0&&<><span className="priced" style={{width:`${knownCost/costEvents*100}%`}}/><span className="unpriced" style={{width:`${unknownCost/costEvents*100}%`}}/></>}</div><div className="demo-legend"><span><i className="priced"/> {knownCost} priced</span><span><i className="unpriced"/> {unknownCost} unknown cost</span></div></div>
      <p className="demo-coverage-note">Unknown cost is missing price evidence, not a zero-dollar event. Neither measure estimates coverage outside this sample.</p>
    </section>
  </div>;
}

export function DemoWorkspace({website}:{website:string}){
  const [selected,setSelected]=useState(sample.applications[0].id);
  const [page,setPage]=useState<'Overview'|'Applications'>('Overview');
  const [detail,setDetail]=useState<Workflow|null>(null);
  const dialogRef=useRef<HTMLDialogElement>(null);
  const cohort=sample.report.cohorts.find(item=>item.application_id===selected);
  const app=sample.applications.find(item=>item.id===selected);
  useEffect(()=>{if(detail)dialogRef.current?.showModal();},[detail]);
  function closeDetail(){dialogRef.current?.close();setDetail(null);}
  function exit(){window.location.hash='login';}
  return <div className="dashboard-shell demo-shell">
    <aside className="sidebar"><Brand href={website}/><p className="workspace-label">EXPLORE DEMO</p><nav aria-label="Demo navigation">
      {(['Overview','Applications'] as const).map((name,i)=><button key={name} className={'side-link '+(page===name?'active':'')} aria-current={page===name?'page':undefined} onClick={()=>setPage(name)}><b aria-hidden="true">{i?'▦':'◫'}</b> {name}</button>)}
    </nav><div className="sidebar-bottom"><strong>Sample workspace</strong><p>Synthetic examples only</p><button className="link-button" onClick={exit}>Exit demo</button></div></aside>
    <main className="dashboard-main"><div className="dashboard-top"><span className="breadcrumb">Demo / {page}</span><span className="local-label">● Synthetic example</span><button className="mobile-logout link-button" onClick={exit}>Exit demo</button></div>
      <header className="page-title"><div><span className="eyebrow">SAMPLE WORKSPACE</span><h1>{page==='Overview'?'Explore a sample assessment':'Sample applications'}</h1><p>{page==='Overview'?'See how recorded workflows, usage, outcomes, and findings fit together.':'Two fictional applications illustrate separate assessments.'}</p></div><button className="button secondary" onClick={exit}>Exit demo →</button></header>
      <div className="demo-banner" role="status"><strong>Synthetic demo — no live telemetry</strong><p>These sample events were generated locally and assessed by TraceWorth. They are not from an account, an API, or a connected application. Figures, timestamps, and durations are illustrative; unknown costs remain unknown.</p></div>
      {page==='Applications'?<div className="app-grid">{sample.applications.map(item=><article className="panel app-card" key={item.id}><span className="app-symbol" aria-hidden="true">▦</span><h2>{item.name}</h2><code>{item.slug}</code><p>Fictional application · synthetic demo</p><button className="button secondary" onClick={()=>{setSelected(item.id);setPage('Overview');}}>Explore assessment →</button></article>)}</div>:<>
        <div className="filter-row"><label htmlFor="demo-application">Sample application</label><select id="demo-application" value={selected} onChange={event=>setSelected(event.target.value)}>{sample.applications.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select><span className="quiet">Read-only synthetic assessment</span></div>
        {cohort&&<><div className="source-panel"><span className="status">Synthetic demo</span> <strong>{app?.name}</strong><p>{cohort.environment} · {cohort.configuration_id}. Coverage outside these generated events is unknown.</p></div>
          <div className="metric-grid">{[['Workflows',cohort.summary.workflows,'Generated executions'],['Accepted results',cohort.summary.accepted_workflows,'Explicit outcomes'],['Failed steps',cohort.summary.failed_steps,'Recorded failures'],['Unknown costs',cohort.summary.unknown_cost_events,'Usage without a price']].map(([label,value,note])=><article className="metric" key={label}><span className="metric-label">{label}</span><strong>{value}</strong><small>{note}</small></article>)}</div>
          <DemoVisuals key={cohort.application_id} cohort={cohort} onInspect={setDetail}/>
          <section className="panel setup-panel"><h2>Recorded sample costs</h2><p>Only priced sample usage is included. Unknown costs are omitted from these totals, so they are partial; no provider price is inferred.</p><div className="cost-grid">{cohort.costs.length?cohort.costs.map((cost,index)=><article key={index}><strong>{showMoney(cost)}</strong><p>Recorded cost per accepted result: {cost.cost_per_accepted_result??'Unavailable'} {cost.cost_per_accepted_result?cost.currency:''}</p></article>):<p>No priced usage recorded. Cost is unknown, not zero.</p>}</div></section>
          <section className="panel"><div className="panel-heading"><h2>Sample workflows</h2><span>{cohort.workflows.length} generated</span></div><p className="demo-table-hint">Swipe table sideways for recorded cost and Inspect →</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Sample workflows table, scroll horizontally for more columns"><table><thead><tr><th>Workflow</th><th>Status</th><th>Accepted</th><th>Recorded cost</th><th>Inspect</th></tr></thead><tbody>{cohort.workflows.map(workflow=><tr key={workflow.workflow_id}><td><span className="workflow-name">{workflow.steps[0]?.name||'Missing root'}</span><span className="workflow-id">{workflow.workflow_id}</span></td><td><span className={'status '+workflow.status}>{workflow.status}</span></td><td>{accepted(workflow.accepted)}</td><td>{workflow.costs.map(showMoney).join(', ')||'No priced usage'}{workflow.unknown_cost_events>0&&<small className="demo-unknown"> + {workflow.unknown_cost_events} unknown cost event{workflow.unknown_cost_events===1?'':'s'}</small>}</td><td><button className="inspect" onClick={()=>setDetail(workflow)} aria-label={`Inspect ${workflow.steps[0]?.name||'workflow'} ${workflow.workflow_id}`}>Inspect</button></td></tr>)}</tbody></table></div></section>
          <section className="findings-section"><h2>What to investigate in this sample</h2><p className="demo-context">These are assessment findings from generated data, not verified improvement recommendations.</p><div className="finding-list">{cohort.findings.map((finding,index)=><article className="finding-card" key={index}><span className="finding-symbol" aria-hidden="true">↗</span><div><h3>{finding.code.replaceAll('_',' ')}</h3><p>{finding.message}</p><details><summary>Evidence</summary>{finding.evidence.map(id=><span className="evidence-id" key={id}>{id}</span>)}</details></div></article>)}</div></section>
          <details className="diagnostics"><summary>Assessment assumptions</summary>{sample.report.assumptions.map(note=><p key={note}>{note}</p>)}</details>
        </>}
      </>}
      <footer className="dashboard-footer"><span>TraceWorth · Synthetic demo · No account data</span><button className="link-button" onClick={exit}>Exit to sign in</button></footer>
    </main>
    {detail&&<dialog ref={dialogRef} onClose={()=>setDetail(null)} aria-modal="true" aria-labelledby="demo-workflow-heading" className="workflow-dialog"><div className="dialog-header"><div><span className="eyebrow">SYNTHETIC DEMO · NO LIVE TELEMETRY</span><h2 id="demo-workflow-heading">Workflow details</h2></div><button className="button secondary" autoFocus onClick={closeDetail}>Close</button></div><div className="detail-body"><p className="detail-id">{detail.workflow_id}</p><p><strong>Status:</strong> {detail.status} · <strong>Accepted:</strong> {accepted(detail.accepted)}</p><p><strong>Recorded cost:</strong> {detail.costs.map(showMoney).join(', ')||'No priced usage'} · <strong>Unknown cost events:</strong> {detail.unknown_cost_events}</p><h3>Recorded steps</h3>{detail.steps.map(step=><article className="step-card" key={step.step_id} style={{marginLeft:Math.min(step.depth,4)*12}}><strong>{step.name}</strong><p className="detail-id">{step.step_id} · Attempt {step.attempt_number}</p><p>{step.status} · {step.duration_ms===null?'Duration unknown':step.duration_ms.toFixed(2)+' ms'}</p><p>{step.costs.map(showMoney).join(', ')||'No directly priced usage'}{step.unknown_cost_events>0?` · ${step.unknown_cost_events} unknown cost event(s)`:''}</p></article>)}<h3>Recorded usage</h3>{detail.usage.length?detail.usage.map((item,index)=><p key={index}>{item.provider} / {item.model_or_service} · {item.unit}: {item.value}</p>):<p>No usage recorded.</p>}</div></dialog>}
  </div>;
}
