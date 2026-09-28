import {useEffect, useRef, useState} from 'react';
import {Brand} from '../../../packages/ui/Brand';
import fixture from './demo-report.json';
import {initialWidgets,WidgetCanvas,WidgetEditor,type DashboardWidget} from './DashboardCreator';
import {OverviewVisuals} from './OverviewVisuals';

type Cost = {amount:string,currency:string,cost_basis:string,partial:boolean,cost_per_accepted_result:string|null};
type Usage = {provider:string,model_or_service:string,unit:string,value:string};
type Step = {step_id:string,name:string,kind:string,started_at:string|null,attempt_number:number,status:string,depth:number,duration_ms:number|null,costs:Cost[],unknown_cost_events:number};
type Workflow = {workflow_id:string,status:string,accepted:boolean|null,duration_ms:number|null,incomplete_telemetry:boolean,usage_events:number,unknown_cost_events:number,steps:Step[],costs:Cost[],usage:Usage[]};
type Finding = {code:string,message:string,evidence:string[]};
type Cohort = {application_id:string,environment:string,configuration_id:string,summary:Record<string,number>,costs:Cost[],workflows:Workflow[],findings:Finding[]};
type Organization = {id:string,name:string};
type ClientGroup = {id:string,name:string,organization_id:string};
type SampleUser = {id:string,name:string,client_group_id:string};
type Context = {organization_id:string,client_group_id:string,user_id:string};
type Slice = {workflow_ids:string[],summary:Record<string,number>,costs:Cost[],findings:Finding[]};
type DemoFixture = {applications:{id:string,name:string,slug:string}[],organizations:Organization[],client_groups:ClientGroup[],users:SampleUser[],workflow_contexts:Record<string,Context>,slices:Record<string,Slice>,report:{cohorts:Cohort[],assumptions:string[]}};
const sample = fixture as DemoFixture;
const showMoney = (cost:Cost)=>`${cost.amount} ${cost.currency} · ${cost.cost_basis}${cost.partial?' · partial':''}`;
const costPerAccepted=(cost:Cost)=>{
  if(cost.cost_per_accepted_result===null)return 'Unavailable';
  const amount=Number(cost.cost_per_accepted_result);
  if(!Number.isFinite(amount))return 'Unavailable';
  const displayed=Number(amount.toPrecision(3));
  return `${displayed===amount?'':'≈'}${displayed} ${cost.currency}`;
};
const accepted = (value:boolean|null)=>value===null?'Not recorded':value?'Yes':'No';
const sliceKey=(application:string,organization:string,group:string,user:string)=>[application,organization||'*',group||'*',user||'*'].join('|');
function contextLabel(workflowId:string){
  const context=sample.workflow_contexts[workflowId];
  if(!context)return 'Fictional context unavailable';
  return [sample.organizations.find(item=>item.id===context.organization_id)?.name,sample.client_groups.find(item=>item.id===context.client_group_id)?.name,sample.users.find(item=>item.id===context.user_id)?.name].filter(Boolean).join(' / ');
}

function DemoFilters({prefix,selected,setSelected,organization,setOrganization,group,setGroup,user,setUser}:{prefix:string,selected:string,setSelected:(id:string)=>void,organization:string,setOrganization:(id:string)=>void,group:string,setGroup:(id:string)=>void,user:string,setUser:(id:string)=>void}){
  const groups=sample.client_groups.filter(item=>!organization||item.organization_id===organization);
  const users=sample.users.filter(item=>(!group||item.client_group_id===group)&&(!organization||groups.some(candidate=>candidate.id===item.client_group_id)));
  return <fieldset className="demo-context-filters"><legend>Explore the fictional sample</legend><div className="demo-filter-grid">
    <label htmlFor={`${prefix}-application`}>Sample application<select id={`${prefix}-application`} value={selected} onChange={event=>setSelected(event.target.value)}>{sample.applications.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
    <label htmlFor={`${prefix}-organization`}>Fictional organization<select id={`${prefix}-organization`} value={organization} onChange={event=>{setOrganization(event.target.value);setGroup('');setUser('');}}><option value="">All organizations</option>{sample.organizations.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
    <label htmlFor={`${prefix}-client`}>Client group<select id={`${prefix}-client`} value={group} onChange={event=>{setGroup(event.target.value);setUser('');}}><option value="">All client groups</option>{groups.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
    <label htmlFor={`${prefix}-user`}>Sample user<select id={`${prefix}-user`} value={user} onChange={event=>setUser(event.target.value)}><option value="">All sample users</option>{users.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
  </div><p>Organization, client group, and user are invented labels for exploring this generated sample. They are not TraceWorth account roles or connected customers.</p></fieldset>;
}

export function DemoWorkspace({website}:{website:string}){
  const [selected,setSelected]=useState(sample.applications[0].id);
  const [organization,setOrganization]=useState('');
  const [group,setGroup]=useState('');
  const [user,setUser]=useState('');
  const [page,setPage]=useState<'Overview'|'Build a view'|'Applications'>('Overview');
  const [demoWidgets,setDemoWidgets]=useState<DashboardWidget[]>(initialWidgets);
  const [detail,setDetail]=useState<Workflow|null>(null);
  const dialogRef=useRef<HTMLDialogElement>(null);
  const baseCohort=sample.report.cohorts.find(item=>item.application_id===selected);
  const slice=sample.slices[sliceKey(selected,organization,group,user)];
  const included=new Set(slice?.workflow_ids??[]);
  const cohort:Cohort|undefined=baseCohort&&slice?{...baseCohort,summary:slice.summary,costs:slice.costs,findings:slice.findings,workflows:baseCohort.workflows.filter(workflow=>included.has(workflow.workflow_id))}:undefined;
  const app=sample.applications.find(item=>item.id===selected);
  const selectedContext=[sample.organizations.find(item=>item.id===organization)?.name,sample.client_groups.find(item=>item.id===group)?.name,sample.users.find(item=>item.id===user)?.name].filter(Boolean).join(' / ')||'All fictional contexts';
  const detailContextLabel=detail?contextLabel(detail.workflow_id):'';
  function clearContext(){setOrganization('');setGroup('');setUser('');}
  useEffect(()=>{if(detail)dialogRef.current?.showModal();},[detail]);
  function closeDetail(){dialogRef.current?.close();setDetail(null);}
  function exit(){window.location.hash='login';}
  return <div className="dashboard-shell demo-shell">
    <aside className="sidebar"><Brand href={website}/><p className="workspace-label">EXPLORE DEMO</p><nav aria-label="Demo navigation">
      {(['Overview','Build a view','Applications'] as const).map((name,i)=><button key={name} className={'side-link '+(page===name?'active':'')} aria-current={page===name?'page':undefined} onClick={()=>setPage(name)}><b aria-hidden="true">{['◫','▤','▦'][i]}</b> {name}</button>)}
    </nav><div className="sidebar-bottom"><strong>Sample workspace</strong><p>Synthetic examples only</p><button className="link-button" onClick={exit}>Exit demo</button></div></aside>
    <main className="dashboard-main"><div className="dashboard-top"><span className="breadcrumb">Demo / {page}</span><span className="local-label">● Synthetic example</span><button className="mobile-logout link-button" onClick={exit}>Exit demo</button></div>
      <header className="page-title"><div><span className="eyebrow">SAMPLE WORKSPACE</span><h1>{page==='Overview'?'Explore a sample assessment':page==='Build a view'?'Shape the sample into your view':'Sample applications'}</h1><p>{page==='Overview'?'Follow an example from recorded work to the questions it raises.':page==='Build a view'?'Try the dashboard composer with generated evidence. Changes reset when you leave or reload.':'Three fictional applications illustrate separate assessments.'}</p></div><button className="button secondary" onClick={exit}>Exit demo →</button></header>
      <div className="demo-banner" role="status"><strong>Synthetic demo — no live telemetry</strong><p>These sample events were generated locally and assessed by TraceWorth. They are not from an account, an API, or a connected application. Figures, timestamps, and durations are illustrative; unknown costs remain unknown.</p></div>
      {page==='Overview'&&cohort&&<section className="demo-story-hero" aria-label="Sample assessment highlights"><div className="demo-story-copy"><span className="eyebrow">THE SAMPLE STORY / {app?.name.toUpperCase()}</span><h2>{cohort.summary.unknown_cost_events>0?'A useful assessment starts with what’s missing.':'Make every recorded run easier to read.'}</h2><p>{cohort.summary.workflows} generated runs connect workflow outcomes to usage{cohort.costs.length?' and recorded cost':''}. {!cohort.costs.length?'Usage was recorded without price evidence, so cost remains unknown.':cohort.summary.unknown_cost_events>0?`${cohort.summary.unknown_cost_events} usage events still have unknown cost, so the amounts shown below are partial.`:'The visible amounts cover only priced usage in this sample.'}</p><div className="demo-story-actions"><button className="button primary" onClick={()=>setPage('Build a view')}>Build a sample view →</button><a href="#demo-evidence" className="button secondary">Explore the evidence ↓</a></div></div></section>}
      {page==='Applications'?<div className="app-grid">{sample.applications.map(item=><article className="panel app-card" key={item.id}><span className="app-symbol" aria-hidden="true">▦</span><h2>{item.name}</h2><code>{item.slug}</code><p>Fictional application · synthetic demo</p><button className="button secondary" onClick={()=>{setSelected(item.id);setPage('Overview');}}>Explore assessment →</button></article>)}</div>:page==='Build a view'?<section className="demo-builder"><DemoFilters prefix="demo-builder" selected={selected} setSelected={setSelected} organization={organization} setOrganization={setOrganization} group={group} setGroup={setGroup} user={user} setUser={setUser}/><div className="demo-builder-intro"><span className="eyebrow">PLAY WITH THE LAYOUT</span><h2>Put the evidence you need in focus.</h2><p>Add widgets, move them, and change their size. This preview reads only the sample fixture and never creates an account dashboard.</p><button className="button secondary" onClick={()=>setDemoWidgets(initialWidgets)}>Reset layout</button></div><div className="demo-builder-grid"><WidgetEditor widgets={demoWidgets} onChange={setDemoWidgets}/><div><div className="builder-preview-head"><span className="eyebrow">YOUR SAMPLE VIEW / {app?.name}</span><span className="quiet">{selectedContext} · Synthetic data</span></div>{!cohort?<p className="demo-filter-empty">No generated workflows match this combination. Clear context filters to preview populated widgets.</p>:<WidgetCanvas widgets={demoWidgets} cohort={cohort} preview/>}{demoWidgets.length===0&&<div className="builder-empty"><h2>Add a widget to start</h2><p>Choose from the catalog to preview this application's generated evidence.</p></div>}</div></div><div className="demo-builder-cta"><div><h2>Ready to make it yours?</h2><p>Sign in to save dashboards for applications you connect.</p></div><button className="button primary" onClick={exit}>Sign in to save dashboards →</button></div></section>:<>
        <div id="demo-evidence"><DemoFilters prefix="demo" selected={selected} setSelected={setSelected} organization={organization} setOrganization={setOrganization} group={group} setGroup={setGroup} user={user} setUser={setUser}/></div>
        {!cohort&&<section className="empty-panel"><h2>No generated workflows match</h2><p>This fictional combination has no sample events. It does not say anything about real application activity.</p><button className="button secondary" onClick={clearContext}>Clear context filters</button></section>}
        {cohort&&<><div className="source-panel"><span className="status">Synthetic demo</span> <strong>{app?.name}</strong><p>{cohort.environment} · {cohort.configuration_id} · {selectedContext}. Coverage outside these generated events is unknown.</p></div>
          <OverviewVisuals key={sliceKey(selected,organization,group,user)} cohort={cohort} synthetic onInspectWorkflow={id=>setDetail(cohort.workflows.find(workflow=>workflow.workflow_id===id)??null)} onBuild={()=>setPage('Build a view')} buildLabel="Build a view"/>
          <section className="panel setup-panel"><h2>Recorded sample costs</h2><p>{!cohort.costs.length?'There is no price evidence for usage in these generated runs. Recorded cost remains unknown; no provider price is inferred.':cohort.summary.unknown_cost_events>0||cohort.costs.some(cost=>cost.partial)?'Only priced sample usage is included. Unknown costs are omitted from these totals, so they are partial; no provider price is inferred.':'These totals include priced usage in the selected generated runs. No unknown-cost usage appears in this slice. Coverage outside the generated sample is unknown.'}</p><div className="cost-grid">{cohort.costs.length?cohort.costs.map((cost,index)=><article key={index}><strong>{showMoney(cost)}</strong><p>Recorded cost per accepted result: {costPerAccepted(cost)}</p></article>):<p>No priced usage recorded. Cost is unknown, not zero.</p>}</div></section>
          <section className="panel"><div className="panel-heading"><h2>Sample workflows</h2><span>{cohort.workflows.length} generated</span></div><p className="demo-table-hint">Swipe table sideways for recorded cost and Inspect →</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Sample workflows table, scroll horizontally for more columns"><table><thead><tr><th>Workflow</th><th>Status</th><th>Accepted</th><th>Recorded cost</th><th>Inspect</th></tr></thead><tbody>{cohort.workflows.map(workflow=><tr key={workflow.workflow_id}><td><span className="workflow-name">{workflow.steps[0]?.name||'Missing root'}</span><span className="workflow-id">{workflow.workflow_id}</span><small className="workflow-context" title={contextLabel(workflow.workflow_id)}>{contextLabel(workflow.workflow_id)}</small></td><td><span className={'status '+workflow.status}>{workflow.status}</span></td><td>{accepted(workflow.accepted)}</td><td>{workflow.costs.map(showMoney).join(', ')||'No priced usage'}{workflow.unknown_cost_events>0&&<small className="demo-unknown"> + {workflow.unknown_cost_events} unknown cost event{workflow.unknown_cost_events===1?'':'s'}</small>}</td><td><button className="inspect" onClick={()=>setDetail(workflow)} aria-label={`Inspect ${workflow.steps[0]?.name||'workflow'} ${workflow.workflow_id}`}>Inspect</button></td></tr>)}</tbody></table></div></section>
          <section className="findings-section"><h2>What to investigate in this sample</h2><p className="demo-context">These are assessment findings from generated data, not verified improvement recommendations.</p><div className="finding-list">{cohort.findings.map((finding,index)=><article className="finding-card" key={index}><span className="finding-symbol" aria-hidden="true">↗</span><div><h3>{finding.code.replaceAll('_',' ')}</h3><p>{finding.message}</p><details><summary>Evidence</summary>{finding.evidence.map(id=><span className="evidence-id" key={id}>{id}</span>)}</details></div></article>)}</div></section>
          <details className="diagnostics"><summary>Assessment assumptions</summary>{sample.report.assumptions.map(note=><p key={note}>{note}</p>)}</details>
        </>}
      </>}
      <footer className="dashboard-footer"><span>TraceWorth · Synthetic demo · No account data</span><button className="link-button" onClick={exit}>Exit to sign in</button></footer>
    </main>
    {detail&&<dialog ref={dialogRef} onClose={()=>setDetail(null)} aria-modal="true" aria-labelledby="demo-workflow-heading" className="workflow-dialog"><div className="dialog-header"><div><span className="eyebrow">SYNTHETIC DEMO · NO LIVE TELEMETRY</span><h2 id="demo-workflow-heading">Workflow details</h2></div><button className="button secondary" autoFocus onClick={closeDetail}>Close</button></div><div className="detail-body"><p className="detail-id">{detail.workflow_id}</p><p><strong>Fictional context:</strong> {detailContextLabel}</p><p><strong>Status:</strong> {detail.status} · <strong>Accepted:</strong> {accepted(detail.accepted)}</p><p><strong>Recorded cost:</strong> {detail.costs.map(showMoney).join(', ')||'No priced usage'} · <strong>Unknown cost events:</strong> {detail.unknown_cost_events}</p><h3>Recorded steps</h3>{detail.steps.map(step=><article className="step-card" key={step.step_id} style={{marginLeft:Math.min(step.depth,4)*12}}><strong>{step.name}</strong><p className="detail-id">{step.step_id} · Attempt {step.attempt_number}</p><p>{step.status} · {step.duration_ms===null?'Duration unknown':step.duration_ms.toFixed(2)+' ms'}</p><p>{step.costs.map(showMoney).join(', ')||'No directly priced usage'}{step.unknown_cost_events>0?` · ${step.unknown_cost_events} unknown cost event(s)`:''}</p></article>)}<h3>Recorded usage</h3>{detail.usage.length?detail.usage.map((item,index)=><p key={index}>{item.provider} / {item.model_or_service} · {item.unit}: {item.value}</p>):<p>No usage recorded.</p>}</div></dialog>}
  </div>;
}
