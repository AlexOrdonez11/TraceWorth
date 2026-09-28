import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Brand} from '../../../packages/ui/Brand';
import '../../../packages/ui/styles.css';
import './website.css';

const dashboard = (import.meta.env.VITE_DASHBOARD_URL || 'http://127.0.0.1:18767').replace(/\/+$/, '');

type SampleWorkflow = {
  name: string;
  cost: number | null;
  unknown: number;
  outcome: string;
  description: string;
};

// This compact marketing snapshot is separate from the richer generated
// dashboard fixture. It is illustrative, never connected telemetry.
const sampleApps: {name: string; workflows: SampleWorkflow[]}[] = [
  {
    name: 'Assistant service',
    workflows: [
      {name: 'Answer request 01', cost: 0.014, unknown: 1, outcome: 'Accepted', description: 'One priced model call and one usage event without a price.'},
      {name: 'Answer request 02', cost: 0.035, unknown: 1, outcome: 'Not accepted', description: 'A retry raised the recorded cost; one other usage event remains unpriced.'},
      {name: 'Answer request 03', cost: null, unknown: 1, outcome: 'No outcome recorded', description: 'Usage was recorded, but no price or acceptance signal was provided.'},
    ],
  },
  {
    name: 'Document indexer',
    workflows: [
      {name: 'Index document 01', cost: 0.011, unknown: 1, outcome: 'Accepted', description: 'One estimated model cost and one unpriced parsing event.'},
      {name: 'Index document 02', cost: null, unknown: 2, outcome: 'No outcome recorded', description: 'Two usage events have no recorded price; the cost is unknown.'},
    ],
  },
];

const sdkCode = `import os
from traceworth import TraceWorth, HttpExporter

with TraceWorth(
    "my-application",
    HttpExporter(
        "https://your-api.example/api/events",
        os.environ["TRACEWORTH_API_KEY"],
    ),
) as telemetry:
    with telemetry.span("answer_request", workflow=True):
        # Run the application and record measured usage.
        ...`;

function Website() {
  const [applicationIndex, setApplicationIndex] = useState(0);
  const [workflowIndex, setWorkflowIndex] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const application = sampleApps[applicationIndex];
  const workflow = application.workflows[workflowIndex];
  const knownTotal = application.workflows.reduce((sum, item) => sum + (item.cost ?? 0), 0);
  const unknownEvents = application.workflows.reduce((sum, item) => sum + item.unknown, 0);
  const maxKnown = Math.max(...application.workflows.map(item => item.cost ?? 0), 0.001);

  function chooseApplication(index: number) {
    setApplicationIndex(index);
    setWorkflowIndex(0);
  }

  return <div className="landing-v2">
    <a className="skip" href="#main">Skip to content</a>
    <header className="site-header wrap landing-header">
      <Brand tag="PYTHON OBSERVABILITY"/>
      <button className="landing-menu-toggle" type="button" aria-label={menuOpen ? 'Close menu' : 'Open menu'} aria-expanded={menuOpen} aria-controls="landing-navigation" onClick={() => setMenuOpen(!menuOpen)}>
        <span/><span/><span/>
      </button>
      <nav id="landing-navigation" className={menuOpen ? 'landing-nav open' : 'landing-nav'} aria-label="Main navigation">
        <a href="#how-it-works" onClick={() => setMenuOpen(false)}>How it works</a>
        <a href="#insights" onClick={() => setMenuOpen(false)}>What you see</a>
        <a href="#get-started" onClick={() => setMenuOpen(false)}>Python SDK</a>
        <a href={`${dashboard}/#login`}>Sign in</a>
        <a className="button dark small" href={`${dashboard}/#demo`}>Explore demo <span aria-hidden="true">↗</span></a>
      </nav>
    </header>

    <main id="main">
      <section className="landing-hero">
        <div className="hero-glow" aria-hidden="true"/>
        <div className="wrap landing-hero-grid">
          <div className="landing-hero-copy">
            <div className="landing-kicker"><span className="pulse-dot"/> TRACEWORTH / APPLICATION EVIDENCE</div>
            <h1>See the recorded work behind <em>AI results.</em></h1>
            <p>Trace workflows, recorded usage, costs, and outcomes in one place. Find what deserves a closer look, with the evidence still attached.</p>
            <div className="landing-hero-actions">
              <a className="button lime-button" href={`${dashboard}/#demo`}>Explore the interactive demo <span aria-hidden="true">↗</span></a>
              <a className="landing-ghost-link" href="#how-it-works">See how it works <span aria-hidden="true">↓</span></a>
            </div>
            <div className="landing-hero-note"><span aria-hidden="true">✳</span> No account needed. This small preview is a separate synthetic snapshot; the full demo has more apps and fictional contexts.</div>
          </div>

          <div className="preview-window" role="region" aria-label="Interactive synthetic assessment preview">
            <div className="preview-toolbar"><div className="window-dots" aria-hidden="true"><i/><i/><i/></div><span>TRACEWORTH / SAMPLE ASSESSMENT</span><span className="preview-live">SYNTHETIC</span></div>
            <div className="preview-content">
              <div className="preview-heading"><div><span className="preview-overline">EXPLORE THE SIGNAL</span><h2>What did that workflow cost?</h2></div><span className="preview-badge">Read-only sample</span></div>
              <div className="preview-app-switch" role="group" aria-label="Sample application">
                {sampleApps.map((item, index) => <button key={item.name} type="button" aria-pressed={applicationIndex === index} className={applicationIndex === index ? 'active' : ''} onClick={() => chooseApplication(index)}>{item.name}</button>)}
              </div>
              <div className="preview-summary"><div><span>Known recorded cost</span><strong>${knownTotal.toFixed(3)} <small>USD</small></strong><em>Partial total</em></div><div><span>Unknown-cost events</span><strong>{unknownEvents}</strong><em>Never treated as $0</em></div></div>
              <div className="preview-plot" role="group" aria-label={`Recorded cost by workflow for ${application.name}`}>
                <div className="preview-plot-title"><strong>Recorded cost by workflow</strong><span>USD · estimated</span></div>
                {application.workflows.map((item, index) => <button key={item.name} type="button" className={workflowIndex === index ? 'preview-bar-row active' : 'preview-bar-row'} aria-pressed={workflowIndex === index} aria-label={`${item.name}: ${item.cost === null ? 'cost unknown' : `$${item.cost.toFixed(3)} recorded cost`}; ${item.unknown} unknown-cost ${item.unknown === 1 ? 'event' : 'events'}`} onClick={() => setWorkflowIndex(index)}>
                  <span className="preview-bar-label">{item.name}</span><span className="preview-bar-track">{item.cost === null ? <span className="preview-bar-unpriced">Unpriced</span> : <span className="preview-bar-fill" style={{width: `${Math.max(12, item.cost / maxKnown * 100)}%`}}/>}</span><span className="preview-bar-value">{item.cost === null ? 'Unknown' : `$${item.cost.toFixed(3)}`}</span>
                </button>)}
              </div>
              <div className="preview-detail" aria-live="polite"><span className="preview-detail-icon" aria-hidden="true">↳</span><div><strong>{workflow.name} · {workflow.outcome}</strong><p>{workflow.description}</p></div></div>
            </div>
            <div className="preview-footer"><span>Small generated snapshot · No connected account data</span><a href={`${dashboard}/#demo`}>Open full demo <span aria-hidden="true">↗</span></a></div>
          </div>
        </div>
      </section>

      <div className="landing-ribbon"><div className="wrap"><span>ONE VIEW FOR THE QUESTIONS THAT MATTER</span><strong>What ran?</strong><i/><strong>What did it use?</strong><i/><strong>Did it help?</strong></div></div>

      <section id="how-it-works" className="wrap landing-process">
        <div className="landing-section-intro"><span className="landing-eyebrow">FROM APPLICATION TO ASSESSMENT</span><h2>A clearer path from <em>execution</em> to evidence.</h2><p>Connect the signals your application can actually provide. TraceWorth organizes them into an assessment you can inspect.</p></div>
        <div className="process-grid">
          <article><span className="process-number">01 / CAPTURE</span><div className="process-symbol" aria-hidden="true">⌁</div><h3>Record the workflow</h3><p>Mark a meaningful request or job, then capture the operations and provider usage inside it.</p><span className="process-line"/></article>
          <article><span className="process-number">02 / CONNECT</span><div className="process-symbol" aria-hidden="true">◌</div><h3>Keep context together</h3><p>Associate events with the right application and add an outcome when your product has a real signal.</p><span className="process-line"/></article>
          <article><span className="process-number">03 / INVESTIGATE</span><div className="process-symbol" aria-hidden="true">↗</div><h3>Follow the evidence</h3><p>Compare recorded costs, inspect workflow steps, and see where data is missing before deciding what to improve.</p><span className="process-line"/></article>
        </div>
      </section>

      <section id="insights" className="landing-insights"><div className="wrap insights-grid"><div><span className="landing-eyebrow">HONEST BY DESIGN</span><h2>Missing data stays <em>visible.</em></h2><p>A recorded cost is only as complete as the usage and prices your application supplies. TraceWorth marks partial totals and keeps unknown costs separate.</p><a className="landing-inline-link" href={`${dashboard}/#demo`}>See it in the demo <span aria-hidden="true">↗</span></a></div><div className="insight-cards"><div><span className="insight-icon known" aria-hidden="true">●</span><span><strong>Recorded</strong><small>Measured usage and known prices</small></span></div><div><span className="insight-icon unknown" aria-hidden="true">?</span><span><strong>Unknown</strong><small>Usage with no recorded price</small></span></div><div><span className="insight-icon outcome" aria-hidden="true">✓</span><span><strong>Outcome</strong><small>An explicit result, when available</small></span></div></div></div></section>

      <section id="get-started" className="wrap landing-integration"><div className="integration-copy"><span className="landing-eyebrow">PYTHON FIRST / APPLICATION INDEPENDENT</span><h2>Start with one meaningful workflow.</h2><p>The core SDK records what you instrument. A separate opt-in Lambda adapter can capture returned model and token counts for tested OpenAI calls. You can explore the demo before connecting either.</p><div className="integration-actions"><a className="button dark" href={`${dashboard}/#demo`}>Explore demo <span aria-hidden="true">↗</span></a><a className="landing-inline-link" href={`${dashboard}/#register`}>Create workspace <span aria-hidden="true">→</span></a></div><p className="integration-caveat">Keys belong in your application's environment. Unknown prices and missing outcomes stay explicit.</p></div><div className="code-card landing-code"><div className="code-title"><span><i/> instrument.py</span><span>PYTHON SDK</span></div><pre><code>{sdkCode}</code></pre><div className="code-footer">A small start. A traceable picture of what was recorded.</div></div></section>

      <section className="wrap landing-final"><div><span className="landing-eyebrow">SEE WHAT YOUR APP CAN TELL YOU</span><h2>Better decisions start with better evidence.</h2><p>Walk through the synthetic example, then connect one application when you're ready.</p></div><a className="button lime-button" href={`${dashboard}/#demo`}>Explore the demo <span aria-hidden="true">↗</span></a></section>
    </main>
    <footer className="wrap landing-footer"><Brand/><p>TraceWorth · Workflow evidence for Python applications</p><a href={`${dashboard}/#login`}>Sign in <span aria-hidden="true">↗</span></a></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<Website/>);
