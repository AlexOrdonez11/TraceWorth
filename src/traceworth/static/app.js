"use strict";
const $ = id => document.getElementById(id);
let dataset = null;
let cohortIndex = 0;
let costIndex = 0;
let busy = false;

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = String(text);
  return item;
}
function replace(id, ...children) { $(id).replaceChildren(...children); }
function setText(id, text) { $(id).textContent = text; }
function number(value) { return new Intl.NumberFormat(undefined, {maximumFractionDigits: 2}).format(value); }
function duration(value) {
  if (value == null) return "Not recorded";
  return value >= 1000 ? `${number(value / 1000)} s` : `${number(value)} ms`;
}
function money(cost) {
  // Preserve decimal strings; never turn a tiny nonzero measured cost into zero.
  return `${cost.amount} ${cost.currency}`;
}
function acceptance(value) { return value === true ? "Accepted" : value === false ? "Rejected" : "Not recorded"; }
function title(value) { return value.replaceAll("_", " ").replace(/^./, c => c.toUpperCase()); }
function activeCohort() { return dataset?.report.cohorts[cohortIndex]; }
function workflowName(workflow) { return workflow.steps.find(s => s.parent_step_id === null)?.name || "Unlinked workflow"; }
function setBusy(value, message = "") {
  busy = value;
  $("refresh").disabled = value;
  $("import-file").disabled = value;
  $("assess-pasted").disabled = value;
  $("export").disabled = value || !dataset;
  setText("message", message);
}
function showError(message) {
  $("error").hidden = false;
  setText("error", message + (dataset ? " Your previous report is still displayed." : ""));
  if ($("import-dialog").open) {
    $("import-error").hidden = false;
    setText("import-error", message);
  }
}
async function fetchReport(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Unable to load metrics.");
  return payload;
}
async function refreshSource() {
  if (busy) return;
  setBusy(true, "Reading your local metric source…");
  $("error").hidden = true;
  try {
    applyDataset(await fetchReport("/api/report"));
    setText("message", "Metrics refreshed from the server source.");
  } catch (error) {
    showError(error.message || "Could not connect. Check that the local server is running.");
    setText("message", "No new report loaded. Fix the source and try Refresh source again.");
  } finally { setBusy(false, $("message").textContent); }
}
async function importFile(file) {
  if (!file || busy) return;
  $("import-error").hidden = true;
  if (file.size > 10 * 1024 * 1024) { showError("Choose a JSONL file no larger than 10 MiB."); return; }
  setBusy(true, "Assessing your JSONL file locally…");
  $("error").hidden = true;
  try {
    const payload = await fetchReport("/api/assess", {method: "POST", headers: {"Content-Type": "text/plain; charset=utf-8"}, body: file});
    payload.source.name = file.name;
    applyDataset(payload);
    $("import-dialog").close();
    setText("message", `Imported ${file.name}. Your source file has not been changed.`);
  } catch (error) { showError(error.message || "This file could not be imported."); setText("message", "Import did not complete."); }
  finally { setBusy(false, $("message").textContent); $("import-file").value = ""; }
}
function applyDataset(payload) {
  dataset = payload;
  cohortIndex = 0; costIndex = 0;
  const source = payload.source;
  setText("source-badge", source.kind === "demo" ? "SYNTHETIC DEMO" : source.kind === "upload" ? "IMPORTED FILE" : "CONNECTED FILE");
  setText("source-name", source.name);
  setText("freshness", `Loaded ${new Date(payload.loaded_at).toLocaleTimeString()}`);
  setText("source-help", source.kind === "demo" ? "Simulated workflows and prices. Import your events, or start with traceworth serve --events events.jsonl." : source.kind === "upload" ? "Assessed in memory on this machine. Refresh source returns to the server’s configured file or demo; re-import to update this upload." : "Refresh source reads this file again. Record new SDK events here to see updated metrics. No automatic polling.");
  const cohorts = payload.report.cohorts;
  replace("cohort", ...cohorts.map((cohort, index) => {
    const option = node("option", "", `${cohort.application_id} / ${cohort.environment} / ${cohort.configuration_id || "No configuration"}`);
    option.value = index; return option;
  }));
  if (!cohorts.length) replace("cohort", node("option", "", "No applications recorded"));
  $("cohort").disabled = !cohorts.length;
  $("results").hidden = !cohorts.length;
  $("empty").hidden = !!cohorts.length;
  const info = payload.report.input;
  const diagnosticNodes = [node("p", "", `${info.valid_events} valid events · ${info.duplicate_events} duplicates · ${info.invalid_lines} invalid records`)];
  if (info.errors.length) {
    const errors = node("ul");
    info.errors.slice(0, 100).forEach(error => errors.append(node("li", "", `Line ${error.line}: ${error.message}`)));
    diagnosticNodes.push(errors);
    if (info.errors.length > 100) diagnosticNodes.push(node("p", "", "Showing the first 100 diagnostics. Download JSON for the full list."));
  }
  const assumptions = node("ul");
  payload.report.assumptions.forEach(text => assumptions.append(node("li", "", text)));
  diagnosticNodes.push(assumptions);
  replace("diagnostic-content", ...diagnosticNodes);
  $("diagnostics").open = info.invalid_lines > 0 || !cohorts.length;
  if (cohorts.length) renderCohort(); else {
    setText("window-label", "No observed time range");
    $("window-label").removeAttribute("title");
  }
}
function renderCohort() {
  const cohort = activeCohort();
  if (!cohort) return;
  const summary = cohort.summary;
  const window = cohort.observed_time_range;
  setText("window-label", `${new Date(window.start).toLocaleDateString()} · All supplied records`);
  $("window-label").title = `Observed ${window.start} to ${window.end}. Acceptance cutoff: ${cohort.acceptance_cutoff_at}`;
  setText("workflow-value", number(summary.workflows));
  setText("workflow-note", `${summary.completed_workflows} completed · ${summary.failed_workflows} failed`);
  setText("accepted-value", number(summary.accepted_workflows));
  setText("accepted-note", `${summary.outcome_workflows} of ${summary.workflows} have acceptance feedback`);
  setText("retry-value", number(summary.retry_steps));
  setText("retry-note", `${summary.failed_steps} failed steps recorded`);
  setText("coverage-value", `${summary.known_cost_events} / ${summary.usage_events}`);
  $("coverage-progress").value = summary.usage_events ? summary.known_cost_events / summary.usage_events * 100 : 0;
  replace("coverage-details", ...[
    ["Unknown cost", `${summary.unknown_cost_events} usage records`],
    ["Missing feedback", `${summary.workflows - summary.outcome_workflows} workflows`],
    ["Incomplete / orphan steps", `${summary.incomplete_steps} / ${summary.orphan_steps}`]
  ].map(([label, value]) => { const row = node("div"); row.append(node("span", "", label), node("strong", "", value)); return row; }));
  costIndex = Math.min(costIndex, Math.max(0, cohort.costs.length - 1));
  replace("cost-group", ...cohort.costs.map((cost, index) => { const option = node("option", "", `${cost.currency} · ${title(cost.cost_basis)}`); option.value = index; return option; }));
  $("cost-group").value = costIndex;
  $("cost-group").disabled = !cohort.costs.length;
  if (!cohort.costs.length) replace("cost-group", node("option", "", "No priced usage"));
  renderCosts();
  setText("workflow-count", `${cohort.workflows.length} workflows`);
  replace("workflow-rows", ...cohort.workflows.map(workflow => {
    const row = node("tr");
    const name = node("td"); name.append(node("span", "workflow-name", title(workflowName(workflow))), node("span", "workflow-id", workflow.workflow_id.slice(0, 8)));
    const status = node("td"); status.append(node("span", `status ${workflow.status}`, title(workflow.status)));
    const accepted = node("td"); accepted.append(node("span", `acceptance ${workflow.accepted === null ? "missing" : ""}`, acceptance(workflow.accepted)));
    const costs = node("td", "row-cost");
    if (!workflow.costs.length) costs.append(node("span", "", workflow.usage_events ? "Unknown" : "No usage recorded"));
    workflow.costs.forEach(cost => { const line = node("div", "", money(cost)); line.append(node("small", "", `${title(cost.cost_basis)}${cost.partial ? " · Partial" : ""}`)); costs.append(line); });
    const action = node("td"); const button = node("button", "inspect", "View ↗");
    button.setAttribute("aria-label", `Inspect ${title(workflowName(workflow))} ${workflow.workflow_id.slice(0, 8)}`);
    button.addEventListener("click", () => openWorkflow(workflow)); action.append(button);
    row.append(name, status, node("td", "", duration(workflow.duration_ms)), accepted, costs, action); return row;
  }));
  setText("finding-count", `${cohort.findings.length} findings`);
  replace("finding-list", ...cohort.findings.map(finding => {
    const card = node("article", "finding-card"); const content = node("div");
    content.append(node("h3", "", title(finding.code)), node("p", "", finding.message));
    const detail = node("details"); detail.append(node("summary", "", `${finding.evidence.length} evidence references`));
    finding.evidence.forEach(id => detail.append(node("span", "evidence-id", id)));
    content.append(detail); card.append(node("span", "finding-symbol", finding.code.includes("cost") ? "$" : "↳"), content); return card;
  }));
  if (!cohort.findings.length) replace("finding-list", node("p", "quiet", "No findings from the observed records. This does not establish complete capture or correct results."));
}
function renderCosts() {
  const cohort = activeCohort(); if (!cohort) return;
  const group = cohort.costs[costIndex];
  if (!group) {
    setText("cost-value", "Unknown"); setText("cost-note", "No priced usage records");
    replace("cost-chart", node("p", "empty-chart", "No known costs in this cohort. Record a cost and its basis to compare workflows."));
    setText("cost-ratio", "Cost per accepted result is unavailable without known costs."); return;
  }
  setText("cost-value", money(group));
  setText("cost-note", `${title(group.cost_basis)} · ${group.partial ? "Partial recorded total" : "Recorded amounts only"}`);
  const values = cohort.workflows.map(workflow => ({workflow, cost: workflow.costs.find(c => c.currency === group.currency && c.cost_basis === group.cost_basis)}));
  const finiteValues = values.map(row => Number(row.cost?.amount ?? 0)).filter(Number.isFinite);
  const max = Math.max(...finiteValues, 0);
  replace("cost-chart", ...values.map(({workflow, cost}) => {
    const row = node("div", "chart-row"); const button = node("button", "", workflow.workflow_id.slice(0, 8));
    button.title = title(workflowName(workflow)); button.setAttribute("aria-label", `Inspect workflow ${workflow.workflow_id}`); button.addEventListener("click", () => openWorkflow(workflow));
    const track = node("div", "chart-track"); const fill = node("div", "chart-fill");
    const amount = Number(cost?.amount ?? 0); fill.style.width = `${Number.isFinite(amount) && max > 0 ? Math.min(100, amount / max * 100) : 0}%`;
    track.append(fill); track.setAttribute("aria-hidden", "true");
    row.append(button, track, node("span", "", cost ? cost.amount : "—")); return row;
  }));
  setText("cost-ratio", `Per accepted result: ${group.cost_per_accepted_result === null ? "undefined (no accepted results)" : `${group.cost_per_accepted_result} ${group.currency}`}${group.partial ? " · Partial" : ""}. Dashes mean no recorded cost in this group.`);
}
function openWorkflow(workflow) {
  setText("detail-title", title(workflowName(workflow)));
  const content = [node("p", "detail-id", workflow.workflow_id)];
  const summary = node("div", "detail-summary"); summary.append(node("span", `status ${workflow.status}`, title(workflow.status)), node("span", "", duration(workflow.duration_ms)), node("span", "", acceptance(workflow.accepted))); content.push(summary);
  if (workflow.incomplete_telemetry) content.push(node("p", "step-meta", "This workflow has incomplete telemetry. Recorded amounts may be partial."));
  workflow.steps.forEach(step => {
    const card = node("article", "step-card"); card.style.marginLeft = `${Math.min(step.depth || 0, 4) * 14}px`;
    const head = node("div", "step-head"); head.append(node("strong", "", title(step.name)), node("span", `status ${step.status}`, title(step.status)));
    card.append(head, node("p", "step-meta", `Attempt ${step.attempt_number} · ${duration(step.duration_ms)}${step.started_at ? "" : " · Start time not recorded"}`), node("p", "detail-id", step.step_id));
    step.costs.forEach(cost => card.append(node("p", "step-cost", `${money(cost)} · ${title(cost.cost_basis)}${cost.partial ? " · Partial" : ""}`)));
    if (step.unknown_cost_events) card.append(node("p", "step-meta", `${step.unknown_cost_events} usage records have unknown cost`));
    if (step.orphan || step.incomplete || step.cycle) card.append(node("p", "step-meta", "Incomplete or unlinked execution — inspect input diagnostics."));
    content.push(card);
  });
  const usage = node("section", "detail-usage"); usage.append(node("h3", "", "Recorded usage"));
  workflow.usage.forEach(unit => usage.append(node("p", "", `${unit.provider} / ${unit.model_or_service} · ${unit.unit}: ${unit.value}`)));
  if (!workflow.usage.length) usage.append(node("p", "", "No usage records were observed for this workflow."));
  content.push(usage); replace("detail-content", ...content);
  $("workflow-dialog").showModal();
}
$("refresh").addEventListener("click", refreshSource);
$("open-import").addEventListener("click", () => { $("import-error").hidden = true; $("import-dialog").showModal(); });
$("close-import").addEventListener("click", () => $("import-dialog").close());
$("assess-pasted").addEventListener("click", () => {
  const file = new File([$("paste-events").value], "Pasted events.jsonl", {type: "text/plain"});
  importFile(file);
});
$("import-file").addEventListener("change", event => importFile(event.target.files[0]));
$("cohort").addEventListener("change", event => { cohortIndex = Number(event.target.value); costIndex = 0; renderCohort(); });
$("cost-group").addEventListener("change", event => { costIndex = Number(event.target.value); renderCosts(); });
$("close-dialog").addEventListener("click", () => $("workflow-dialog").close());
$("workflow-dialog").addEventListener("click", event => { if (event.target === $("workflow-dialog")) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
$("export").addEventListener("click", () => {
  if (!dataset) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(dataset.report, null, 2)], {type: "application/json"}));
  const link = node("a"); link.href = url; link.download = "traceworth-report.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  setText("message", "JSON report download started.");
});

// Optional structured access mirrors the visible cohort picker; no data is sent elsewhere.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  const register = tool => { try { Promise.resolve(document.modelContext.registerTool(tool, {signal: lifecycle.signal})).catch(() => {}); } catch {} };
  register({name: "read_traceworth_overview", description: "Read the currently selected local metrics cohort and source.", inputSchema: {type: "object", properties: {}, additionalProperties: false}, annotations: {readOnlyHint: true, untrustedContentHint: true}, execute: () => ({source: dataset?.source ?? null, cohort: activeCohort() ?? null})});
  register({name: "select_traceworth_cohort", description: "Select an application cohort in the visible dashboard.", inputSchema: {type: "object", properties: {index: {type: "integer", minimum: 0}}, required: ["index"], additionalProperties: false}, annotations: {readOnlyHint: false}, execute: input => {
    if (!Number.isInteger(input?.index) || input.index < 0 || !dataset?.report.cohorts[input.index]) throw new Error("Select an existing cohort index.");
    cohortIndex = input.index; costIndex = 0; $("cohort").value = cohortIndex; renderCohort(); return {application_id: activeCohort().application_id, summary: activeCohort().summary};
  }});
  window.addEventListener("pagehide", () => lifecycle.abort(), {once: true});
}
refreshSource();
