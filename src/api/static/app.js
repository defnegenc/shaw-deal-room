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
  agentResults: document.getElementById("agentResults"),
  companyName: document.getElementById("companyName"),
  dealStage: document.getElementById("dealStage"),
  dealStatus: document.getElementById("dealStatus"),
  dealContact: document.getElementById("dealContact"),
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
  els.pipelineView.classList.add("hidden");
  els.dealWorkspace.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderSelectedDeal() {
  const deal = currentDeal();
  if (!deal) return;
  els.companyName.textContent = deal.company_name;
  els.dealStage.textContent = deal.stage;
  els.dealStatus.textContent = deal.status;
  els.dealContact.textContent = deal.initial_contact || "-";
  els.editDealForm.elements.company_name.value = deal.company_name || "";
  els.editDealForm.elements.website.value = deal.website || "";
  els.editDealForm.elements.stage.value = deal.stage || "Sourced";
  els.editDealForm.elements.status.value = deal.status || "Active";
  els.editDealForm.elements.initial_contact.value = deal.initial_contact || "";
}

function clearWorkspace() {
  els.dealWorkspace.classList.add("hidden");
  els.pipelineView.classList.remove("hidden");
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
  els.runMessage.textContent = "";
  els.runMessage.classList.remove("warn");
  els.runButton.disabled = true;

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
    }
  } catch (error) {
    stopLiveSteps();
    if (state.selectedDealId === startDealId) {
      els.agentActions.className = "action-timeline";
      els.agentActions.innerHTML = actionItem("Agent run failed", error.message, "danger");
    }
  } finally {
    state.agentRunning = null;
    els.runButton.disabled = false;
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

function renderResult(result) {
  els.planCount.textContent = result.plan.length;
  els.citationCount.textContent = result.citations.length;
  els.factCount.textContent = result.accepted_facts.length;
  els.reviewCount.textContent = result.review_items.length;
  els.metricCount.textContent = result.computed_metrics.length;

  els.agentActions.className = "action-timeline";
  els.agentActions.innerHTML = result.plan.length
    ? result.plan.map((step, index) => actionItem(`${index + 1}. ${labelAction(step.action)}`, step.reason, "done")).join("")
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
    : empty("No computed metrics yet.");
}

function reviewCard(item) {
  return `
    <div class="item warn review-card" data-review-id="${escapeHtml(item.review_id || "")}">
      <div class="item-title"><span>${escapeHtml(item.field_name)}</span><span>${escapeHtml(item.priority)}</span></div>
      <p>${escapeHtml(item.reason ?? "")}</p>
      ${
        item.review_id
          ? `<form class="resolve-form">
              <input name="raw_value" placeholder="Type correction, e.g. $12.4M as of Q1 2026" required />
              <input name="as_of_text" placeholder="Optional date, e.g. Q1 2026" />
              <button type="submit">Save Resolution</button>
            </form>`
          : ""
      }
    </div>
  `;
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
    const resolved = await apiFetch(`/review-items/${reviewId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    card.classList.remove("warn");
    card.innerHTML = `<div class="item-title"><span>${escapeHtml(resolved.fact.field_name)}</span><span>Resolved</span></div><p>${escapeHtml(resolved.resolution_outcome)}</p>`;
    await loadEvents();
  } catch (error) {
    card.querySelector("p").textContent = error.message;
  }
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
els.editDealForm.addEventListener("submit", updateDeal);
els.deleteDealButton.addEventListener("click", deleteDeal);
els.uploadForm.addEventListener("submit", uploadDocument);
els.runButton.addEventListener("click", runAgent);
els.reviewItems.addEventListener("submit", resolveReview);
window.addEventListener("popstate", routeFromUrl);
els.pipelineBoard.addEventListener("click", (event) => {
  const button = event.target.closest("[data-deal-id]");
  if (button) {
    navigateToDeal(button.dataset.dealId);
  }
});

init();
