import {useEffect, useRef, useState} from 'react';
import {Brand} from '../../../packages/ui/Brand';
import fixture from './demo-report.json';

type Cost = {amount:string,currency:string,cost_basis:string,partial:boolean,cost_per_accepted_result:string|null};
type Usage = {provider:string,model_or_service:string,unit:string,value:string};
type Step = {step_id:string,name:string,attempt_number:number,status:string,depth:number,duration_ms:number|null,costs:Cost[],unknown_cost_events:number};
type Workflow = {workflow_id:string,status:string,accepted:boolean|null,incomplete_telemetry:boolean,unknown_cost_events:number,steps:Step[],costs:Cost[],usage:Usage[]};
type Finding = {code:string,message:string,evidence:string[]};
type Cohort = {application_id:string,environment:string,configuration_id:string,summary:Record<string,number>,costs:Cost[],workflows:Workflow[],findings:Finding[]};
const sample = fixture as {applications:{id:string,name:string,slug:string}[],report:{cohorts:Cohort[],assumptions:string[]}};
const showMoney = (cost:Cost)=>`${cost.amount} ${cost.currency} · ${cost.cost_basis}${cost.partial?' · partial':''}`;
const accepted = (value:boolean|null)=>value===null?'Not recorded':value?'Yes':'No';

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
          <section className="panel setup-panel"><h2>Recorded sample costs</h2><p>Only priced sample usage is included. Unknown costs are omitted from these totals, so they are partial; no provider price is inferred.</p><div className="cost-grid">{cohort.costs.length?cohort.costs.map((cost,index)=><article key={index}><strong>{showMoney(cost)}</strong><p>Recorded cost per accepted result: {cost.cost_per_accepted_result??'Unavailable'} {cost.cost_per_accepted_result?cost.currency:''}</p></article>):<p>No priced usage recorded. Cost is unknown, not zero.</p>}</div></section>
          <section className="panel"><div className="panel-heading"><h2>Sample workflows</h2><span>{cohort.workflows.length} generated</span></div><div className="table-scroll"><table><thead><tr><th>Workflow</th><th>Status</th><th>Accepted</th><th>Recorded cost</th><th>Inspect</th></tr></thead><tbody>{cohort.workflows.map(workflow=><tr key={workflow.workflow_id}><td><span className="workflow-name">{workflow.steps[0]?.name||'Missing root'}</span><span className="workflow-id">{workflow.workflow_id}</span></td><td><span className={'status '+workflow.status}>{workflow.status}</span></td><td>{accepted(workflow.accepted)}</td><td>{workflow.costs.map(showMoney).join(', ')||'No priced usage'}{workflow.unknown_cost_events>0&&<small className="demo-unknown"> + {workflow.unknown_cost_events} unknown cost event{workflow.unknown_cost_events===1?'':'s'}</small>}</td><td><button className="inspect" onClick={()=>setDetail(workflow)} aria-label={`Inspect ${workflow.steps[0]?.name||'workflow'} ${workflow.workflow_id}`}>Inspect</button></td></tr>)}</tbody></table></div></section>
          <section className="findings-section"><h2>What to investigate in this sample</h2><p className="demo-context">These are assessment findings from generated data, not verified improvement recommendations.</p><div className="finding-list">{cohort.findings.map((finding,index)=><article className="finding-card" key={index}><span className="finding-symbol" aria-hidden="true">↗</span><div><h3>{finding.code.replaceAll('_',' ')}</h3><p>{finding.message}</p><details><summary>Evidence</summary>{finding.evidence.map(id=><span className="evidence-id" key={id}>{id}</span>)}</details></div></article>)}</div></section>
          <details className="diagnostics"><summary>Assessment assumptions</summary>{sample.report.assumptions.map(note=><p key={note}>{note}</p>)}</details>
        </>}
      </>}
      <footer className="dashboard-footer"><span>TraceWorth · Synthetic demo · No account data</span><button className="link-button" onClick={exit}>Exit to sign in</button></footer>
    </main>
    {detail&&<dialog ref={dialogRef} onClose={()=>setDetail(null)} aria-modal="true" aria-labelledby="demo-workflow-heading" className="workflow-dialog"><div className="dialog-header"><div><span className="eyebrow">SYNTHETIC DEMO · NO LIVE TELEMETRY</span><h2 id="demo-workflow-heading">Workflow details</h2></div><button className="button secondary" autoFocus onClick={closeDetail}>Close</button></div><div className="detail-body"><p className="detail-id">{detail.workflow_id}</p><p><strong>Status:</strong> {detail.status} · <strong>Accepted:</strong> {accepted(detail.accepted)}</p><p><strong>Recorded cost:</strong> {detail.costs.map(showMoney).join(', ')||'No priced usage'} · <strong>Unknown cost events:</strong> {detail.unknown_cost_events}</p><h3>Recorded steps</h3>{detail.steps.map(step=><article className="step-card" key={step.step_id} style={{marginLeft:Math.min(step.depth,4)*12}}><strong>{step.name}</strong><p className="detail-id">{step.step_id} · Attempt {step.attempt_number}</p><p>{step.status} · {step.duration_ms===null?'Duration unknown':step.duration_ms.toFixed(2)+' ms'}</p><p>{step.costs.map(showMoney).join(', ')||'No directly priced usage'}{step.unknown_cost_events>0?` · ${step.unknown_cost_events} unknown cost event(s)`:''}</p></article>)}<h3>Recorded usage</h3>{detail.usage.length?detail.usage.map((item,index)=><p key={index}>{item.provider} / {item.model_or_service} · {item.unit}: {item.value}</p>):<p>No usage recorded.</p>}</div></dialog>}
  </div>;
}
