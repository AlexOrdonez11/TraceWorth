import {createRoot} from 'react-dom/client';
import {Brand} from '../../../packages/ui/Brand';
import '../../../packages/ui/styles.css';

const dashboard = import.meta.env.VITE_DASHBOARD_URL || 'http://127.0.0.1:18767';
const code = `import os
from traceworth import TraceWorth, HttpExporter

trace = TraceWorth(
    application="my-application",
    exporter=HttpExporter(
        endpoint="http://127.0.0.1:18766/api/events",
        api_key=os.environ["TRACEWORTH_API_KEY"],
    ),
)

@trace.workflow("answer_request")
def answer_request():
    # Run your application and record usage.
    ...

# At application shutdown:
trace.close()`;

function Website() {
  return <div className="landing"><a className="skip" href="#main">Skip to content</a>
    <header className="site-header wrap"><Brand tag="PYTHON + REACT"/><nav aria-label="Main navigation"><a href="#how-it-works">How it works</a><a href="#get-started">Python SDK</a><a href={`${dashboard}/#login`}>Sign in</a><a className="button dark small" href={`${dashboard}/#register`}>Create workspace ↗</a></nav></header>
    <main id="main"><section className="hero wrap"><div className="hero-copy"><div className="eyebrow"><span className="small-line"/>EVIDENCE FOR BETTER AI</div><h1>Your workflows.<br/>Recorded costs.<br/><span>A clearer picture.</span></h1><p className="hero-description">Follow the work behind an AI result. Connect execution, recorded usage, and outcomes in a workspace built for your applications.</p><div className="hero-actions"><a className="button dark" href={`${dashboard}/#register`}>Start your workspace ↗</a><a className="text-link" href="#get-started">Explore the SDK →</a></div><p className="quiet">Local-first development. Your applications, your evidence.</p></div>
      <div className="hero-visual" aria-label="Illustrative workflow cost breakdown"><div className="visual-head"><span className="eyebrow">WORKFLOW / REPAIR REQUEST</span><span className="pill lime">Illustrative example</span></div><div className="visual-total"><span>Recorded cost</span><strong>$0.05<span>USD</span></strong><p>One request. A traceable cost breakdown.</p></div>{[['01','Understand the request','Input processing','$0.01'],['02','Generate repair steps','Model response','$0.02'],['↻','Try again','Cost that adds up','$0.02']].map(([icon,name,detail,cost])=><div className="trace-line" key={name}><span className={`trace-icon ${icon==='↻'?'orange':''}`}>{icon}</span><div><strong>{name}</strong><small>{detail}</small></div><span className="mono">{cost}</span></div>)}<div className="visual-note">↳ Completion is a signal. Acceptance is another.</div></div></section>
      <section className="principles wrap" aria-label="Product principles"><span>APPLICATION-INDEPENDENT BY DESIGN</span>{['Python workflows','Account-scoped data','Explicit outcomes','Evidence-based findings'].map(text=><p key={text}>{text}</p>)}</section>
      <section id="how-it-works" className="how wrap"><div className="section-intro"><div className="eyebrow">FROM EXECUTION TO EVIDENCE</div><h2>A shared library.<br/>A space of your own.</h2><p>Keep your applications together and your account separate. Build on the facts your application can actually measure.</p></div><div className="feature-list">{[['Create your workspace','Register applications and generate a dedicated ingestion key for each one.'],['Connect the recorded path','Use the Python SDK to send operations, usage, and outcomes to the FastAPI backend.'],['Investigate with evidence','Explore the metrics in your dashboard. Follow findings back to the steps behind them.']].map(([name,description],i)=><article key={name}><span className="feature-number">0{i+1}</span><div><h3>{name}</h3><p>{description}</p></div></article>)}</div></section>
      <section id="get-started" className="sdk-section wrap"><div><div className="eyebrow">BUILT AROUND YOUR APPLICATION</div><h2>A few boundaries.<br/>A better view.</h2><p>Instrument meaningful workflows and record usage from provider responses. The backend associates each event with the account and application that own its key.</p><p className="quiet">Automatic provider capture is planned. Usage recording is explicit today. Install from this repository with <code>pip install -e .</code>.</p><a className="text-link sdk-link" href={`${dashboard}/#register`}>Create an application key →</a></div><div className="code-card"><div className="code-title"><span>app.py</span><span>PYTHON</span></div><pre><code>{code}</code></pre><div className="code-footer">Keys belong in your application's environment, never in browser code.</div></div></section>
      <section className="bottom-cta wrap"><div><div className="eyebrow">YOUR NEXT CHANGE STARTS HERE</div><h2>Less guesswork.<br/>More recorded evidence.</h2></div><a className="button lime-button" href={`${dashboard}/#register`}>Create a local workspace ↗</a></section>
    </main><footer className="wrap footer"><Brand/><span>Local development foundation · Clear limits, useful evidence.</span><a href={dashboard}>Open dashboard ↗</a></footer>
  </div>;
}
createRoot(document.getElementById('root')!).render(<Website/>);
