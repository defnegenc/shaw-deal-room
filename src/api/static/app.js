const STAGES = ["Sourced", "Screening", "Due Diligence", "IC Review", "Term Sheet", "Closed", "Passed"];

const state = {
  deals: [],
  selectedDealId: null,
  agentRunning: null,
  runTimer: null,
};

const RUN_STAGES = [
  ["Inspecting deal state", "Reading stage, documents on file, and which fields are still missing."],
  ["Reading source documents", "Extracting cited facts from uploaded diligence materials."],
  ["Enriching company profile", "Pulling sector, geography, and profile fields from the provider."],
  ["Researching the web", "Searching public sources for founders, investors, and the latest round."],
  ["Detecting conflicts", "Comparing new values against existing facts for contradictions."],
  ["Computing metrics", "Deriving valuation multiples and burn ratios from accepted facts."],
  ["Finalizing report", "Scoring confidence, flagging review items, and assembling citations."],
];

const els = {
  toggleCreateButton: document.getElementById("toggleCreateButton"),
  createDealForm: document.getElementById("createDealForm"),
  createDealMessage: document.getElementById("createDealMessage"),
  pipelineView: document.getElementById("pipelineView"),
  pipelineBoard: document.getElementById("pipelineBoard"),
  dealWorkspace: document.getElementById("dealWorkspace"),
  postRunArea: document.getElementById("postRunArea"),
  runMessage: document.getElementById("runMessage"),
  runSummary: document.getElementById("runSummary"),
  agentResults: document.getElementById("agentResults"),
  companyName: document.getElementById("companyName"),
  dealStage: document.getElementById("dealStage"),
  dealStatus: document.getElementById("dealStatus"),
  dealWebsite: document.getElementById("dealWebsite"),
  dealContact: document.getElementById("dealContact"),
  editDealButton: document.getElementById("editDealButton"),
  editDealForm: document.getElementById("editDealForm"),
  editDealMessage: document.getElementById("editDealMessage"),
  deleteDealButton: document.getElementById("deleteDealButton"),
  materialsSummary: document.getElementById("materialsSummary"),
  sourceDocuments: document.getElementById("sourceDocuments"),
  documentCount: document.getElementById("documentCount"),
  uploadForm: document.getElementById("uploadForm"),
  uploadMessage: document.getElementById("uploadMessage"),
  documentFile: document.getElementById("documentFile"),
  runButton: document.getElementById("runButton"),
  agentActions: document.getElementById("agentActions"),
  citations: document.getElementById("citations"),
  factsTable: document.getElementById("factsTable"),
  reviewItems: document.getElementById("reviewItems"),
  computedMetrics: document.getElementById("computedMetrics"),
  planCount: document.getElementById("planCount"),
  citationCount: document.getElementById("citationCount"),
  factCount: document.getElementById("factCount"),
  reviewCount: document.getElementById("reviewCount"),
  metricCount: document.getElementById("metricCount"),
  eventLog: document.getElementById("eventLog"),
  eventCount: document.getElementById("eventCount"),
};

async function init() {
  state.deals = await apiFetch("/deals");
  renderPipeline();
  routeFromUrl();
}

function renderPipeline() {
  els.pipelineBoard.innerHTML = STAGES.map((stage) => {
    const deals = state.deals.filter((deal) => deal.stage === stage);
    return `
      <div class="stage-column">
        <div class="stage-head">
          <strong>${escapeHtml(stage)}</strong>
          <span>${deals.length}</span>
        </div>
        <div class="stage-chips">
          ${
            deals.length
              ? deals.map((deal) => companyChip(deal)).join("")
              : `<span class="empty tiny">No companies</span>`
          }
        </div>
      </div>
    `;
  }).join("");
}

function companyChip(deal) {
  const active = deal.deal_id === state.selectedDealId ? "active" : "";
  return `<button class="company-chip ${active}" data-deal-id="${escapeHtml(deal.deal_id)}">${escapeHtml(deal.company_name)}</button>`;
}

function navigateToDeal(dealId) {
  history.pushState({ dealId }, "", `/ui/deals/${encodeURIComponent(dealId)}`);
  selectDeal(dealId);
}

function navigateToPipeline() {
  history.pushState({}, "", "/ui");
  state.selectedDealId = null;
  renderPipeline();
  clearWorkspace();
}

function routeFromUrl() {
  const match = window.location.pathname.match(/^\/ui\/deals\/([^/]+)$/);
  const dealId = match ? decodeURIComponent(match[1]) : null;
  if (dealId && state.deals.some((deal) => deal.deal_id === dealId)) {
    selectDeal(dealId);
  } else {
    state.selectedDealId = null;
    renderPipeline();
    clearWorkspace();
  }
}

async function selectDeal(dealId) {
  state.selectedDealId = dealId;
  renderPipeline();
  renderSelectedDeal();
  resetAgentOutput();
  await loadSourceDocuments();
  await loadEvents();
  await loadIntelligence();
  els.pipelineView.classList.add("hidden");
  els.dealWorkspace.classList.remove("hidden");
  // A company is selected, so the top-bar Run Agent becomes clickable.
  if (!state.agentRunning) {
    els.runButton.disabled = false;
    els.runButton.title = "Run the agent on this company";
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderSelectedDeal() {
  const deal = currentDeal();
  if (!deal) return;
  els.companyName.textContent = deal.company_name;
  els.dealStage.textContent = deal.stage;
  els.dealStatus.textContent = deal.status;
  els.dealWebsite.textContent = deal.website || "—";
  els.dealContact.textContent = deal.initial_contact || "—";
  els.editDealForm.classList.add("hidden");
  els.editDealMessage.textContent = "";
  els.editDealForm.elements.company_name.value = deal.company_name || "";
  els.editDealForm.elements.website.value = deal.website || "";
  els.editDealForm.elements.stage.value = deal.stage || "Sourced";
  els.editDealForm.elements.status.value = deal.status || "Active";
  els.editDealForm.elements.initial_contact.value = deal.initial_contact || "";
}

function clearWorkspace() {
  els.dealWorkspace.classList.add("hidden");
  els.pipelineView.classList.remove("hidden");
  // No company selected -> Run Agent is not clickable.
  els.runButton.disabled = true;
  els.runButton.title = "Select a company first";
  els.runMessage.textContent = "";
  els.runMessage.classList.remove("warn");
}

async function loadSourceDocuments() {
  const deal = currentDeal();
  if (!deal) return;
  const docs = await apiFetch(`/deals/${deal.deal_id}/source-documents`);
  els.documentCount.textContent = docs.length;
  els.materialsSummary.textContent = docs.length
    ? `${docs.length} file${docs.length === 1 ? "" : "s"} available`
    : "No files yet";
  els.sourceDocuments.className = "doc-list";
  els.sourceDocuments.innerHTML = docs.length
    ? docs.map(documentCard).join("")
    : empty("No diligence materials found. Running the agent will start from enrichment and web research.");
}

async function loadEvents() {
  const deal = currentDeal();
  if (!deal) return;
  const events = await apiFetch(`/deals/${deal.deal_id}/events`);
  els.eventCount.textContent = events.length;
  els.eventLog.className = "stack";
  els.eventLog.innerHTML = events.length
    ? events.map(eventCard).join("")
    : empty("No field changes yet.");
}

async function runAgent() {
  const deal = currentDeal();
  if (!deal) return;

  // Only one run at a time. If a run is already in flight (possibly for a
  // different company), tell the user which one and bail.
  if (state.agentRunning) {
    els.runMessage.textContent = `The agent is currently running for ${state.agentRunning}. Please wait for it to finish.`;
    els.runMessage.classList.add("warn");
    return;
  }

  const startDealId = deal.deal_id;
  state.agentRunning = deal.company_name;
  els.runMessage.classList.remove("warn");
  els.runMessage.textContent = "Scroll down to see agent progress ↓";
  els.runButton.disabled = true;
  els.runButton.classList.add("running");
  els.runButton.innerHTML = `<span class="spinner spinner-light"></span> Agent Running…`;

  els.postRunArea.classList.remove("hidden");
  startLiveSteps();

  try {
    const result = await apiFetch("/agent-runs/update-deal-intelligence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deal_id: startDealId }),
    });
    stopLiveSteps();
    if (state.selectedDealId === startDealId) {
      renderResult(result);
      await loadEvents();
      els.runMessage.textContent = "";
    }
  } catch (error) {
    stopLiveSteps();
    if (state.selectedDealId === startDealId) {
      els.agentActions.className = "action-timeline";
      els.agentActions.innerHTML = actionItem("Agent run failed", error.message, "danger");
      els.runMessage.textContent = "";
    }
  } finally {
    state.agentRunning = null;
    els.runButton.disabled = false;
    els.runButton.classList.remove("running");
    els.runButton.textContent = "Run Agent";
  }
}

function startLiveSteps() {
  els.agentActions.className = "action-timeline";
  let current = 0;
  const render = () => {
    els.agentActions.innerHTML = RUN_STAGES.slice(0, current + 1)
      .map(([title, body], idx) => liveStepItem(title, body, idx < current ? "done" : "running", idx === current))
      .join("");
  };
  render();
  state.runTimer = setInterval(() => {
    if (current < RUN_STAGES.length - 1) {
      current += 1;
      render();
    }
  }, 750);
}

function stopLiveSteps() {
  if (state.runTimer) {
    clearInterval(state.runTimer);
    state.runTimer = null;
  }
}

function liveStepItem(title, body, tone, showSpinner) {
  const spinner = showSpinner ? '<span class="spinner" aria-hidden="true"></span>' : "";
  return `
    <div class="action-item ${tone}">
      <strong>${spinner}${escapeHtml(title)}</strong>
      <span>${escapeHtml(body)}</span>
    </div>
  `;
}

// Map each accepted fact back to the tool that produced it (via its citation
// source) so each pipeline step can show what it actually found, e.g.
// "web_research → Found founding year = 2023; founders = ...".
function actionForSource(label) {
  const value = (label || "").toLowerCase();
  if (value.includes("web") || value.includes("serper")) return "web_research";
  if (value.includes("enrich") || value.includes("company_provider")) return "enrich_company";
  if (value.includes("chunk") || /\.(txt|md|pdf|csv|xlsx|xlsm)/.test(value)) return "process_documents";
  return null;
}

function findingsByAction(result) {
  const valueByField = {};
  for (const fact of result.accepted_facts) {
    valueByField[fact.field_name] = formatValue(fact);
  }
  const byAction = {};
  for (const citation of result.citations) {
    const action = actionForSource(citation.source_label);
    if (!action || valueByField[citation.field_name] === undefined) continue;
    let value = String(valueByField[citation.field_name]);
    if (value.length > 60) value = `${value.slice(0, 57)}...`;
    (byAction[action] = byAction[action] || new Set()).add(`${labelAction(citation.field_name)} = ${value}`);
  }
  const out = {};
  for (const action of Object.keys(byAction)) out[action] = [...byAction[action]];
  return out;
}

async function loadIntelligence() {
  const deal = currentDeal();
  if (!deal) return;
  const data = await apiFetch(`/deals/${deal.deal_id}/intelligence`);
  if (data.has_run) {
    renderResult(data);
    els.postRunArea.classList.remove("hidden");
  }
}

function renderResult(result) {
  els.runSummary.textContent = result.summary || "The agent did not record a summary for this run.";
  els.planCount.textContent = result.plan.length;
  els.citationCount.textContent = result.citations.length;
  els.factCount.textContent = result.accepted_facts.length;
  els.reviewCount.textContent = result.review_items.length;
  els.metricCount.textContent = result.computed_metrics.length;

  const findings = findingsByAction(result);
  els.agentActions.className = "action-timeline";
  els.agentActions.innerHTML = result.plan.length
    ? result.plan
        .map((step, index) => {
          const found = findings[step.action];
          const body = found && found.length ? `${step.reason} → Found ${found.join("; ")}` : step.reason;
          return actionItem(`${index + 1}. ${labelAction(step.action)}`, body, "done");
        })
        .join("")
    : actionItem("No follow-up actions", "The agent did not find anything else to do.", "done");
  if (result.source_strategy?.length) {
    els.agentActions.innerHTML += result.source_strategy
      .map((item) => actionItem(`Source: ${labelAction(item.recommended_tool)}`, `${item.fields.join(", ")} | ${item.why}`, "done"))
      .join("");
  }
  if (result.coverage_gaps?.length) {
    els.agentActions.innerHTML += result.coverage_gaps
      .filter((item) => item.status !== "accepted")
      .map((item) => actionItem(`Coverage: ${item.field_name}`, `${item.status} | ${item.next_step}`, item.status === "missing" ? "running" : "done"))
      .join("");
  }

  els.citations.className = "citation-list";
  els.citations.innerHTML = result.citations.length
    ? result.citations.map(citationRow).join("")
    : empty("No citations.");

  els.factsTable.innerHTML = result.accepted_facts.length
    ? result.accepted_facts.map(factRow).join("")
    : `<tr><td colspan="4" class="empty">No accepted facts yet.</td></tr>`;

  els.reviewItems.className = "stack";
  els.reviewItems.innerHTML = result.review_items.length
    ? result.review_items.map(reviewCard).join("")
    : empty("No human review needed.");

  els.computedMetrics.className = "stack";
  els.computedMetrics.innerHTML = result.computed_metrics.length
    ? result.computed_metrics.map(metricCard).join("")
    : empty(
        "No computed metrics yet. These are ratios — ARR valuation multiple and annualized burn as a % of ARR — so they need both ARR and a valuation (or monthly burn) as numbers. Those typically come from a term sheet or financials; web research alone usually can't produce them. Upload diligence materials with those figures to compute them.",
      );
}

function reviewCard(item) {
  const candidate = item.candidate;
  const valueBlock = candidate
    ? `<div class="review-value">
         <span class="review-value-label">Best value found</span>
         <strong>${escapeHtml(formatCandidate(candidate))}</strong>
         <span class="review-source">${candidate.source_label ? `via ${escapeHtml(labelAction(candidate.source_label))}` : ""}${
           candidate.as_of_date ? ` · as of ${escapeHtml(candidate.as_of_date)}` : ""
         }${candidate.confidence_score != null ? ` · confidence ${escapeHtml(String(candidate.confidence_score))}` : ""}</span>
       </div>`
    : `<div class="review-value empty-value">No value found — supply one below.</div>`;
  const actions = item.review_id
    ? `<div class="review-actions">
         ${candidate ? `<button type="button" class="accept-btn" data-action="accept">Accept</button>` : ""}
         ${candidate ? `<button type="button" class="secondary-button" data-action="reject">Reject</button>` : ""}
         <button type="button" class="secondary-button" data-action="custom">${candidate ? "Custom" : "Enter value"}</button>
       </div>
       <form class="resolve-form hidden">
         <input name="raw_value" placeholder="Type a value, e.g. $12.4M" required />
         <input name="as_of_text" placeholder="Optional date, e.g. Q1 2026" />
         <button type="submit">Save</button>
       </form>`
    : "";
  return `
    <div class="item warn review-card" data-review-id="${escapeHtml(item.review_id || "")}">
      <div class="item-title"><span>${escapeHtml(labelAction(item.field_name))}</span><span>${escapeHtml(item.priority)}</span></div>
      <p class="review-reason">Flagged because: ${escapeHtml(item.reason ?? "")}</p>
      ${valueBlock}
      ${actions}
    </div>
  `;
}

function formatCandidate(candidate) {
  if (candidate.currency === "USD" && typeof candidate.value === "number") {
    return `$${Math.round(candidate.value).toLocaleString()}`;
  }
  if (candidate.unit && !String(candidate.value).includes(candidate.unit)) {
    return `${candidate.value} ${candidate.unit}`;
  }
  return String(candidate.value);
}

function metricCard(metric) {
  const flags = metric.quality_flags.length ? `Flags: ${metric.quality_flags.join(", ")}` : "Inputs accepted";
  const tone = metric.review_status === "review_required" ? "warn" : "";
  return itemCard(metric.metric_name, `${metric.value} | ${metric.formula}`, flags, tone);
}

function documentCard(doc) {
  return `
    <div class="doc-item">
      <div>
        <strong>${escapeHtml(doc.filename)}</strong>
        <span>${escapeHtml(doc.doc_type || "diligence_material")}</span>
      </div>
      <div class="doc-actions">
        <a href="${escapeHtml(doc.view_url)}" target="_blank" rel="noreferrer">View</a>
        <a href="${escapeHtml(doc.download_url)}">Download</a>
      </div>
    </div>
  `;
}

function actionItem(title, body, tone) {
  return `
    <div class="action-item ${tone}">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(body)}</span>
    </div>
  `;
}

function itemCard(title, body, badge, tone) {
  return `
    <div class="item ${tone}">
      <div class="item-title"><span>${escapeHtml(title)}</span><span>${escapeHtml(badge ?? "")}</span></div>
      <p>${escapeHtml(body ?? "")}</p>
    </div>
  `;
}

function factRow(fact) {
  return `
    <tr>
      <td>${escapeHtml(fact.field_name)}</td>
      <td>${escapeHtml(formatValue(fact))}</td>
      <td>${escapeHtml(fact.review_status)}</td>
      <td>${escapeHtml(fact.staleness_status)}</td>
    </tr>
  `;
}

function citationRow(citation) {
  return `
    <div class="citation">
      <strong>${escapeHtml(citation.field_name)}</strong>
      <span>${escapeHtml(citation.source_label)}</span>
      <span>${escapeHtml(citation.quoted_evidence)}</span>
    </div>
  `;
}

function resetAgentOutput() {
  stopLiveSteps();
  els.postRunArea.classList.add("hidden");
  els.runMessage.textContent = "";
  els.runMessage.classList.remove("warn");
  els.planCount.textContent = "0";
  els.citationCount.textContent = "0";
  els.factCount.textContent = "0";
  els.reviewCount.textContent = "0";
  els.metricCount.textContent = "0";
  els.agentActions.innerHTML = "";
  els.citations.innerHTML = "";
  els.factsTable.innerHTML = "";
  els.reviewItems.innerHTML = "";
  els.computedMetrics.innerHTML = "";
}

async function createDeal(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    company_name: String(form.get("company_name") || "").trim(),
    website: String(form.get("website") || "").trim() || null,
    stage: String(form.get("stage") || "Sourced"),
    status: String(form.get("status") || "Active"),
    initial_contact: String(form.get("initial_contact") || "").trim() || null,
  };
  if (!payload.company_name) return;

  try {
    const deal = await apiFetch("/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.deals = await apiFetch("/deals");
    els.createDealForm.reset();
    els.createDealForm.classList.add("hidden");
    els.createDealMessage.textContent = `Added ${deal.company_name}.`;
    navigateToDeal(deal.deal_id);
  } catch (error) {
    els.createDealMessage.textContent = error.message;
  }
}

async function updateDeal(event) {
  event.preventDefault();
  const deal = currentDeal();
  if (!deal) return;
  const form = new FormData(event.currentTarget);
  const payload = {
    company_name: String(form.get("company_name") || "").trim(),
    website: String(form.get("website") || "").trim() || null,
    stage: String(form.get("stage") || "Sourced"),
    status: String(form.get("status") || "Active"),
    initial_contact: String(form.get("initial_contact") || "").trim() || null,
  };
  try {
    const updated = await apiFetch(`/deals/${deal.deal_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.deals = await apiFetch("/deals");
    state.selectedDealId = updated.deal_id;
    renderPipeline();
    renderSelectedDeal();
    await loadEvents();
    els.editDealMessage.textContent = "Saved.";
  } catch (error) {
    els.editDealMessage.textContent = error.message;
  }
}

async function deleteDeal() {
  const deal = currentDeal();
  if (!deal) return;
  if (!confirm(`Delete ${deal.company_name}?`)) return;
  await apiFetch(`/deals/${deal.deal_id}`, { method: "DELETE" });
  state.deals = await apiFetch("/deals");
  navigateToPipeline();
}

async function uploadDocument(event) {
  event.preventDefault();
  const deal = currentDeal();
  if (!deal) return;
  const formData = new FormData(event.currentTarget);
  if (!formData.get("file") || !formData.get("file").name) {
    els.uploadMessage.textContent = "Choose a file first.";
    return;
  }
  try {
    const uploaded = await apiFetch(`/deals/${deal.deal_id}/source-documents`, {
      method: "POST",
      body: formData,
    });
    event.currentTarget.reset();
    els.uploadMessage.textContent = `Uploaded ${uploaded.filename}.`;
    await loadSourceDocuments();
    await loadEvents();
    resetAgentOutput();
  } catch (error) {
    els.uploadMessage.textContent = error.message;
  }
}

async function resolveReview(event) {
  event.preventDefault();
  const form = event.target.closest(".resolve-form");
  if (!form) return;
  const card = form.closest("[data-review-id]");
  const reviewId = card?.dataset.reviewId;
  if (!reviewId) return;
  const payload = {
    raw_value: String(new FormData(form).get("raw_value") || "").trim(),
    as_of_text: String(new FormData(form).get("as_of_text") || "").trim() || null,
  };
  if (!payload.raw_value) return;
  try {
    await apiFetch(`/review-items/${reviewId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshAfterReview();
  } catch (error) {
    const reason = card.querySelector(".review-reason");
    if (reason) reason.textContent = error.message;
  }
}

// Accept (lock the agent's value), Reject (dismiss it), or Custom (reveal the
// free-text form) — so the associate answers yes / no / custom in one click.
async function handleReviewAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const card = button.closest("[data-review-id]");
  const reviewId = card?.dataset.reviewId;
  if (!reviewId) return;
  const action = button.dataset.action;
  if (action === "custom") {
    const form = card.querySelector(".resolve-form");
    form?.classList.toggle("hidden");
    if (form && !form.classList.contains("hidden")) form.elements.raw_value.focus();
    return;
  }
  try {
    await apiFetch(`/review-items/${reviewId}/${action}`, { method: "POST" });
    await refreshAfterReview();
  } catch (error) {
    const reason = card.querySelector(".review-reason");
    if (reason) reason.textContent = error.message;
  }
}

async function refreshAfterReview() {
  // Re-render from the DB: the resolved item drops out of the review queue and
  // an accepted value appears in the facts table.
  await loadIntelligence();
  await loadEvents();
}

function eventCard(event) {
  return itemCard(
    event.field_name,
    `${event.old_value ?? "-"} -> ${event.new_value ?? "-"}`,
    new Date(event.changed_at).toLocaleString(),
    "",
  );
}

function currentDeal() {
  return state.deals.find((deal) => deal.deal_id === state.selectedDealId);
}

function labelAction(action) {
  return action.replaceAll("_", " ");
}

function formatValue(fact) {
  if (fact.currency === "USD" && typeof fact.value === "number") {
    return `$${Math.round(fact.value).toLocaleString()}`;
  }
  if (fact.unit && !String(fact.value).includes(fact.unit)) {
    return `${fact.value} ${fact.unit}`;
  }
  return String(fact.value);
}

function empty(message) {
  return `<span class="empty">${escapeHtml(message)}</span>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function apiFetch(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("API server is unreachable. Start it with: python -m uvicorn src.api.main:app --port 8000");
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Use HTTP status fallback.
    }
    throw new Error(detail);
  }
  return response.json();
}

els.toggleCreateButton.addEventListener("click", () => {
  els.createDealForm.classList.toggle("hidden");
});
els.createDealForm.addEventListener("submit", createDeal);
els.editDealButton.addEventListener("click", () => {
  const hidden = els.editDealForm.classList.toggle("hidden");
  if (!hidden) els.editDealForm.elements.company_name.focus();
});
els.editDealForm.addEventListener("submit", updateDeal);
els.deleteDealButton.addEventListener("click", deleteDeal);
els.uploadForm.addEventListener("submit", uploadDocument);
els.runButton.addEventListener("click", runAgent);
els.reviewItems.addEventListener("submit", resolveReview);
els.reviewItems.addEventListener("click", handleReviewAction);
window.addEventListener("popstate", routeFromUrl);
els.pipelineBoard.addEventListener("click", (event) => {
  const button = event.target.closest("[data-deal-id]");
  if (button) {
    navigateToDeal(button.dataset.dealId);
  }
});

init();
