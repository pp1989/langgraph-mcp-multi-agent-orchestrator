/* TripMate AI — backend-connected interactions and structured report renderer */
(() => {
  "use strict";

  const form = document.getElementById("trip-form");
  const promptInput = document.getElementById("trip-prompt");
  const charCount = document.getElementById("char-count");
  const generateButton = document.getElementById("generate-button");
  const output = document.getElementById("plan-output");
  const chips = document.querySelectorAll("[data-prompt]");

  // Change these paths only if your FastAPI routes use different URLs.
  const API_ENDPOINT = "/api/travel";
  const APPROVAL_ENDPOINT = "/api/travel/approve";

  // Retain the thread returned by the backend for review / follow-up actions.
  let activeThreadId = null;

  if (!form || !promptInput || !generateButton || !output) {
    console.error("TripMate UI: required form/output elements were not found.");
    return;
  }

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);

  const formatLabel = (key) => String(key)
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());

  const asArray = (value) => {
    if (Array.isArray(value)) return value;
    if (value === null || value === undefined || value === "") return [];
    return [value];
  };

  function parseMaybeJson(value) {
    if (typeof value !== "string") return value;
    const trimmed = value.trim();
    if (!trimmed || !(trimmed.startsWith("{") || trimmed.startsWith("["))) return value;
    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return value;
    }
  }

  // MCP tools can return content blocks such as { type: "text", text: "{...}" }.
  // Normalize those blocks before rendering so the UI can handle either objects or text.
  function normalizeValue(value, depth = 0) {
    if (depth > 12 || value === null || value === undefined) return value;
    if (typeof value === "string") {
      const parsed = parseMaybeJson(value);
      return parsed === value ? value : normalizeValue(parsed, depth + 1);
    }
    if (Array.isArray(value)) {
      const normalized = value.map((item) => normalizeValue(item, depth + 1));
      // Unwrap a single MCP text block for a cleaner UI.
      if (normalized.length === 1 && normalized[0] && typeof normalized[0] === "object" &&
          normalized[0].type === "text" && typeof normalized[0].text === "string") {
        return normalizeValue(normalized[0].text, depth + 1);
      }
      return normalized.map((item) => {
        if (item && typeof item === "object" && item.type === "text" && typeof item.text === "string") {
          return normalizeValue(item.text, depth + 1);
        }
        return item;
      });
    }
    if (typeof value === "object") {
      if (value.type === "text" && typeof value.text === "string") {
        return normalizeValue(value.text, depth + 1);
      }
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [key, normalizeValue(item, depth + 1)])
      );
    }
    return value;
  }

  function inlineFormat(value) {
    // Escape first; only then add a small, safe subset of formatting.
    let text = escapeHtml(value);
    text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/\*(.+?)\*/g, "<em>$1</em>");
    text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    text = text.replace(/(https?:\/\/[^\s<]+)/g, (url) => {
      const cleanUrl = url.replace(/[),.;]+$/g, "");
      const trailing = url.slice(cleanUrl.length);
      return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer">${cleanUrl}</a>${trailing}`;
    });
    return text;
  }

  function renderMarkdown(text) {
    const normalized = String(text ?? "")
      .replace(/\\n/g, "\n")
      .replace(/\r\n?/g, "\n")
      .trim();
    if (!normalized) return '<p class="empty-result">No details available.</p>';

    const lines = normalized
      .replace(/^```(?:markdown|md|text)?\s*\n/i, "")
      .replace(/\n```\s*$/, "")
      .split("\n");

    const html = [];
    let paragraph = [];
    let listItems = [];
    let listType = null;

    const flushParagraph = () => {
      if (paragraph.length) {
        html.push(`<p>${inlineFormat(paragraph.join(" "))}</p>`);
        paragraph = [];
      }
    };

    const flushList = () => {
      if (listItems.length) {
        html.push(`<${listType} class="itinerary-list">${listItems.map((item) => `<li>${inlineFormat(item)}</li>`).join("")}</${listType}>`);
      }
      listItems = [];
      listType = null;
    };

    const flushAll = () => {
      flushParagraph();
      flushList();
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        flushAll();
        continue;
      }

      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      const bullet = line.match(/^[-*•]\s+(.+)$/);
      const numbered = line.match(/^\d+[.)]\s+(.+)$/);

      if (heading) {
        flushAll();
        const level = Math.min(heading[1].length + 1, 5);
        html.push(`<h${level}>${inlineFormat(heading[2])}</h${level}>`);
      } else if (bullet || numbered) {
        flushParagraph();
        const nextType = numbered ? "ol" : "ul";
        if (listType && listType !== nextType) flushList();
        listType = nextType;
        listItems.push((bullet || numbered)[1]);
      } else if (/^[-=_]{3,}$/.test(line)) {
        flushAll();
        html.push("<hr>");
      } else {
        flushList();
        paragraph.push(line);
      }
    }

    flushAll();
    return `<div class="itinerary-body">${html.join("\n")}</div>`;
  }

  function renderObject(value) {
    const entries = Object.entries(value || {}).filter(([, item]) =>
      item !== null && item !== undefined && item !== "" &&
      !(Array.isArray(item) && item.length === 0)
    );
    if (!entries.length) return '<p class="empty-result">No details available.</p>';

    return `<dl class="detail-grid">${entries.map(([key, item]) => `
      <div class="detail-row">
        <dt>${escapeHtml(formatLabel(key))}</dt>
        <dd>${renderValue(item)}</dd>
      </div>`).join("")}</dl>`;
  }

  function renderValue(value) {
    value = normalizeValue(value);
    if (value === null || value === undefined || value === "") {
      return '<span class="empty-result">Not available</span>';
    }
    if (typeof value === "string") return renderMarkdown(value);
    if (typeof value === "number" || typeof value === "boolean") {
      return `<span>${escapeHtml(value)}</span>`;
    }
    if (Array.isArray(value)) {
      if (!value.length) return '<p class="empty-result">No results found.</p>';
      const objectItems = value.every((item) => item && typeof item === "object" && !Array.isArray(item));
      if (objectItems) {
        return `<div class="result-list">${value.map((item, index) => {
          const title = item.name ?? item.hotel_name ?? item.airline ?? item.title ?? item.city ?? `${formatLabel(Object.keys(item)[0] || "Result")} ${index + 1}`;
          const copy = { ...item };
          ["name", "hotel_name", "airline", "title", "city"].forEach((key) => delete copy[key]);
          return `<article class="result-item"><div class="result-item-heading"><span class="result-index">${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(title)}</strong></div>${renderObject(copy)}</article>`;
        }).join("")}</div>`;
      }
      return `<ul class="nested-list">${value.map((item) => `<li>${renderValue(item)}</li>`).join("")}</ul>`;
    }
    if (typeof value === "object") {
      if (value.type === "text" && typeof value.text === "string") return renderValue(value.text);
      return renderObject(value);
    }
    return `<span>${escapeHtml(value)}</span>`;
  }

  function statusPill(status, source) {
    const safeStatus = String(status || "available").toLowerCase();
    const label = status ? formatLabel(status) : "Information";
    const sourceLabel = source ? ` · ${source}` : "";
    const className = ["success", "complete", "approved"].includes(safeStatus)
      ? "status-good"
      : ["error", "failed", "blocked"].includes(safeStatus)
        ? "status-bad"
        : ["mock", "pending", "paused"].includes(safeStatus)
          ? "status-warn"
          : "status-neutral";
    return `<span class="data-status ${className}">${escapeHtml(label + sourceLabel)}</span>`;
  }

  function renderSection(number, title, value, options = {}) {
    const normalized = normalizeValue(value);
    const status = options.status ?? (normalized && typeof normalized === "object" ? normalized.status : null);
    const source = options.source ?? (normalized && typeof normalized === "object" ? normalized.source : null);
    let body = normalized;

    if (body && typeof body === "object" && !Array.isArray(body)) {
      // Keep status/source/error metadata out of the generic field grid.
      const copy = { ...body };
      delete copy.status;
      delete copy.source;
      delete copy.is_live;
      delete copy.verified_booking_inventory;
      delete copy.error;

      // Prefer the useful payload field for standard agent envelopes.
      if (Object.prototype.hasOwnProperty.call(copy, "data")) body = copy.data;
      else if (Object.prototype.hasOwnProperty.call(copy, "results")) body = copy.results;
      else if (Object.prototype.hasOwnProperty.call(copy, "content")) body = copy.content;
      else body = copy;
    }

    const trustNote = normalized && typeof normalized === "object" && normalized.is_live === false
      ? '<p class="source-note">Demo / non-live information. Verify details with the provider before booking.</p>'
      : normalized && typeof normalized === "object" && normalized.verified_booking_inventory === false
        ? '<p class="source-note">Web research only — live room availability and booking prices have not been verified.</p>'
        : "";
    const error = normalized && typeof normalized === "object" ? normalized.error : null;

    return `<section class="report-section">
      <div class="report-section-heading">
        <h2><span class="section-number">${number}.</span> ${escapeHtml(title)}</h2>
        ${statusPill(status, source)}
      </div>
      <div class="section-content">${error ? `<p class="error-note">${escapeHtml(error)}</p>` : ""}${renderValue(body)}${trustNote}</div>
    </section>`;
  }

  function renderAgentWorkflow(data) {
    const selected = data.selected_agents ?? data.selected_agent ?? [];
    const agents = Array.isArray(selected) ? selected : selected ? [selected] : [];
    const labels = [
      ["flight_agent", "Flight research"],
      ["hotel_agent", "Hotel research"],
      ["weather_agent", "Weather research"],
      ["budget_agent", "Budget analysis"],
      ["itinerary_agent", "Itinerary planning"],
    ];
    if (!agents.length && !data.supervisor_reasoning && !data.supervisor_resoning) return "";

    return `<section class="workflow-panel">
      <div class="workflow-panel-heading"><div><span class="section-kicker">AGENT ACTIVITY</span><h3>Your travel crew</h3></div>
      ${data.guardrail_allowed === false ? '<span class="workflow-state state-blocked">Request blocked</span>' : '<span class="workflow-state state-active">Supervisor reviewed</span>'}</div>
      <div class="agent-chips">${labels.map(([key, label]) => {
        const active = agents.includes(key);
        return `<span class="agent-chip ${active ? "is-selected" : ""}"><i>${active ? "✓" : "–"}</i>${label}</span>`;
      }).join("")}</div>
      ${(data.supervisor_reasoning || data.supervisor_resoning) ? `<p class="workflow-reason">${renderValue(data.supervisor_reasoning ?? data.supervisor_resoning)}</p>` : ""}
    </section>`;
  }

  function renderApproval(data) {
    // if (!data.requires_approval) return "";
      const approvalSectionVisible =
        data.requires_approval === true;

    if (!approvalSectionVisible) {
        return "";
    }
    const request = data.approval_request || "Review the draft itinerary. Approve it or provide feedback for revision.";
    const threadId = data.thread_id || activeThreadId || "";
    return `<section class="approval-panel" data-thread-id="${escapeHtml(threadId)}">
      <div class="approval-icon" aria-hidden="true">✦</div>
      <div class="approval-copy"><span class="section-kicker">HUMAN REVIEW REQUIRED</span><h3>Review your draft itinerary</h3><p>${renderValue(request)}</p></div>
      <label class="approval-label" for="approval-feedback">FEEDBACK (OPTIONAL)</label>
      <textarea id="approval-feedback" class="approval-feedback" rows="3" placeholder="Suggest changes to the route, pace, budget or activities…"></textarea>
      <div class="approval-actions">
        <button class="approval-button approval-button-secondary" type="button" data-approval="revise">Request changes</button>
        <button class="approval-button approval-button-primary" type="button" data-approval="approve">Approve itinerary <span aria-hidden="true">→</span></button>
      </div>
      <p class="approval-hint">Your decision is sent to the backend to resume this paused LangGraph thread.</p>
    </section>`;
  }

  function renderTripResults(rawData) {
    const data = normalizeValue(rawData) || {};
    if (typeof data !== "object" || Array.isArray(data)) {
      return `<article class="itinerary-document"><div class="itinerary-content">${renderValue(data)}</div></article>`;
    }

    activeThreadId = data.thread_id || activeThreadId;

    if (data.success === false || data.guardrail_allowed === false) {
      const message = data.guardrail_reason || data.error || data.answer || "Your request could not be processed.";
      return `<article class="itinerary-document"><div class="document-topline"><span class="document-badge">TRIPMATE AI</span>${statusPill("blocked", "Supervisor")}</div><div class="itinerary-content"><h1>Let's refine your travel request</h1><div class="error-note">${renderValue(message)}</div>${data.guardrail_reason ? `<p>${renderValue(data.guardrail_reason)}</p>` : ""}</div></article>`;
    }

    const queryTitle = data.user_query || data.trip_summary?.destination || "Your personalized travel plan";
    const itinerary = data.itinerary ?? data.itinarary ?? data.itinerary_results ?? "";
    const constraints = data.trip_constraints ?? data.trip_constraintst ?? {};
    const supervisorReason = data.supervisor_reasoning ?? data.supervisor_resoning ?? "";
    const selectedAgents = data.selected_agents ?? data.selected_agent ?? [];

    const summaryContent = data.trip_summary ?? constraints;
    const hasSummary = summaryContent && Object.keys(summaryContent).length > 0;
    const budget = data.budget_results ?? data.budget ?? "";
    const answer = data.answer ?? data.final_response ?? "";

    return `<article class="itinerary-document">
      <div class="document-topline">
        <span class="document-badge">TRIPMATE AI</span>
        <span class="document-caption">YOUR PERSONALIZED TRAVEL BRIEF</span>
      </div>
      <div class="itinerary-content" id=itinerary-content>
        <div class="trip-report-intro"><span class="section-kicker">YOUR JOURNEY, MAPPED OUT</span><h1>${escapeHtml(queryTitle)}</h1>
          <div class="report-meta">${data.thread_id ? `<span>Ref: ${escapeHtml(data.thread_id)}</span>` : ""}<span>${data.mode === "mock" ? "Demo data" : "AI-generated plan"}</span></div>
        </div>
        <div class="itinerary-actions">
        <button id="copyItineraryBtn" class="btn btn-secondary">Copy</button>
       <button id="downloadPdfBtn" class="download-pdf-btn">Download PDF</button>
       </div>
        ${renderAgentWorkflow({ ...data, selected_agents: selectedAgents, supervisor_reasoning: supervisorReason })}
        ${answer ? renderSection(1, "Final Travel Brief", answer) : ""}
        ${data.human_feedback ? `<section class="report-section"><h2>Review feedback</h2><div class="section-content">${renderValue(data.human_feedback)}</div></section>` : ""}
      </div>
      ${renderApproval(data)}
      <div class="document-footer">Planning information is not a booking confirmation. Verify schedules, prices, weather and availability with the relevant providers before travelling.${data.llm_calls !== undefined ? ` · ${escapeHtml(data.llm_calls)} LLM calls` : ""}</div>
    </article>`;
  }

// download and copy event 
  document.addEventListener("click", function (event) {

    const button = event.target.closest("button");

    if (!button) return;

    switch (button.id) {

        case "downloadPdfBtn":
            downloadItineraryPdf();
            break;

        case "copyItineraryBtn":
            copyText(button);
            break;


    }
});
  
/**
 * Convert itinerary content blocks into readable text.
 * Handles both strings and Gemini/LangChain content arrays.
 */
function extractText(content) {
    if (typeof content === "string") {
        return content;
    }

    if (Array.isArray(content)) {
        return content
            .map(item => {
                if (typeof item === "string") return item;
                return item?.text || "";
            })
            .filter(Boolean)
            .join("\n");
    }

    return "";
}


/**
 * copy function.
 */

async function copyText(button) {

    // Find the complete travel plan content
    const itinerary = document.getElementById("itinerary-content");

    if (!itinerary) {
        alert("Travel plan not found!");
        return;
    }

    try {

        // Clone the rendered travel plan
        const clonedContent = itinerary.cloneNode(true);

        // Remove action buttons from copied content
        const actions = clonedContent.querySelector(".itinerary-actions");

        if (actions) {
            actions.remove();
        }

        // Capture HTML and readable text
        const htmlContent = clonedContent.innerHTML;
        const textContent = clonedContent.innerText;

        // Copy formatted HTML and plain text
        const clipboardItem = new ClipboardItem({
            "text/html": new Blob([htmlContent], {
                type: "text/html"
            }),

            "text/plain": new Blob([textContent], {
                type: "text/plain"
            })
        });

        await navigator.clipboard.write([clipboardItem]);

        // Show success feedback
        const originalText = button.textContent;

        button.textContent = "Copied!";

        setTimeout(() => {
            button.textContent = originalText;
        }, 2000);

    } catch (error) {

        console.error("Copy failed:", error);

        alert("Unable to copy travel plan. Please try again.");
    }
}



/**
 * Print itinerary and allow user to save as PDF.
 */
function downloadItineraryPdf() {
    const itinerary = document.getElementById("itinerary-content");

    if (!itinerary) {
        alert("Itinerary not found.");
        return;
    }

    const printWindow = window.open("", "_blank");

    if (!printWindow) {
        alert("Please allow pop-ups to download the PDF.");
        return;
    }

    printWindow.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>TripMate Travel Itinerary</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    padding: 30px;
                    line-height: 1.7;
                    color: #222;
                }

                h1, h2, h3 {
                    color: #172554;
                }

                ul, ol {
                    padding-left: 25px;
                }

                @page {
                    size: A4;
                    margin: 18mm;
                }

                @media print {
                    body {
                        print-color-adjust: exact;
                    }
                }
            </style>
        </head>
        <body>
            <h1>TripMate AI - Travel Itinerary</h1>
            ${itinerary.innerHTML}
        </body>
        </html>
    `);

    printWindow.document.close();

    printWindow.onload = () => {
        printWindow.focus();
        printWindow.print();
    };
}


  function setLoading(isLoading) {
    generateButton.disabled = isLoading;
    output.setAttribute("aria-busy", String(isLoading));
    if (isLoading) {
      generateButton.dataset.originalHtml = generateButton.innerHTML;
      generateButton.innerHTML = '<span class="button-copy"><strong>Building your travel plan…</strong><small>Your agents are researching</small></span><span class="button-arrow" aria-hidden="true">◌</span>';
      output.innerHTML = '<div class="plan-loading"><span class="loading-orb"></span><div><strong>Planning your next adventure</strong><p>The supervisor is reviewing your request and routing it to the right travel specialists…</p></div></div>';
    } else {
      generateButton.innerHTML = generateButton.dataset.originalHtml || '<span class="button-copy"><strong>Build my travel plan</strong><small>Let your AI crew get to work</small></span><span class="button-arrow" aria-hidden="true">↗</span>';
      delete generateButton.dataset.originalHtml;
    }
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body),
    });
    const responseText = await response.text();
    let data;
    try {
      data = responseText ? JSON.parse(responseText) : {};
    } catch (_) {
      throw new Error(`Server returned non-JSON content (HTTP ${response.status}).`);
    }
    if (!response.ok) {
      const detail = data.detail || data.error || data.message || `Request failed (${response.status})`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  async function submitApproval(button) {
    const panel = button.closest(".approval-panel");
    if (!panel) return;

    const approved = button.dataset.approval === "approve";
    const feedback = panel.querySelector("#approval-feedback")?.value.trim() || "";
    const threadId = panel.dataset.threadId || activeThreadId;

    if (!threadId) {
      output.insertAdjacentHTML("afterbegin", '<p class="error-note">The backend did not return a thread ID. Approval cannot resume the saved graph state.</p>');
      return;
    }

    const buttons = panel.querySelectorAll("button[data-approval]");
    buttons.forEach((item) => { item.disabled = true; });
    button.textContent = approved ? "Submitting approval…" : "Sending feedback…";

    try {
      // This route must call resume_travel_agent(thread_id, approved, feedback).
      const data = await postJson(APPROVAL_ENDPOINT, {
        thread_id: threadId,
        approved,
        feedback,
      });
      output.innerHTML = renderTripResults(data);
      output.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      console.error("TripMate approval error:", error);
      const hint = `Unable to submit review: ${error.message}. Confirm that FastAPI exposes ${APPROVAL_ENDPOINT} and resumes this thread.`;
      panel.insertAdjacentHTML("beforeend", `<p class="error-note">${escapeHtml(hint)}</p>`);
      buttons.forEach((item) => { item.disabled = false; });
      button.textContent = approved ? "Approve itinerary →" : "Request changes";
    }
  }

  const updateCount = () => {
    if (!charCount) return;
    const count = promptInput.value.length;
    charCount.textContent = `${count} character${count === 1 ? "" : "s"}`;
  };

  promptInput.addEventListener("input", updateCount);

  chips.forEach((chip) => chip.addEventListener("click", () => {
    promptInput.value = chip.dataset.prompt || "";
    updateCount();
    promptInput.focus();
  }));

  // Event delegation keeps approval controls working after report HTML is re-rendered.
  output.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-approval]");
    if (button && !button.disabled) submitApproval(button);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (generateButton.disabled) return;

    const message = promptInput.value.trim();
    if (!message) {
      promptInput.focus();
      return;
    }

    setLoading(true);

    try {
      const requestBody = { message };
      if (activeThreadId) requestBody.thread_id = activeThreadId;
      const data = await postJson(API_ENDPOINT, requestBody);
      output.innerHTML = renderTripResults(data);
      output.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      console.error("TripMate API or rendering error:", error);
      output.innerHTML = `<article class="itinerary-document"><div class="itinerary-content"><h2>Unable to generate your trip</h2><p class="error-note">${escapeHtml(error.message)}</p><p>Check that your FastAPI server is running, that <code>${escapeHtml(API_ENDPOINT)}</code> is correct, and that the request body uses the field expected by your API route.</p></div></article>`;
      output.scrollIntoView({ behavior: "smooth", block: "start" });
    } finally {
      setLoading(false);
    }
  });

  updateCount();
})();

/*
 * Human-in-the-Loop add-on.
 * Keep your existing scripts.js. After it receives/renders the first API response,
 * call: window.TripMateHITL.show(response, renderExistingResponse);
 */
(() => {
  "use strict";

  const RESUME_ENDPOINT = "/api/travel/approve";
  const STORAGE_KEY = "tripmate.pendingHumanReview";

  const panel = document.getElementById("hitl-approval-panel");
  const requestText = document.getElementById("hitl-approval-request");
  const feedbackInput = document.getElementById("hitl-approval-feedback");
  const approveButton = document.getElementById("hitl-approve-button");
  const reviseButton = document.getElementById("hitl-revise-button");
  const statusText = document.getElementById("hitl-approval-status");

  let activeThreadId = null;
  let renderResponseCallback = null;
  let requestInProgress = false;

  function setStatus(message, isError = false) {
    if (!statusText) return;
    statusText.textContent = message;
    statusText.classList.toggle("is-error", isError);
  }

  function setButtonsDisabled(disabled) {
    if (approveButton) approveButton.disabled = disabled;
    if (reviseButton) reviseButton.disabled = disabled;
  }

  function savePendingReview(response) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        thread_id: activeThreadId,
        response,
        saved_at: new Date().toISOString()
      }));
    } catch (error) {
      console.warn("Could not save pending TripMate review in session storage.", error);
    }
  }

  function clearPendingReview() {
    try { sessionStorage.removeItem(STORAGE_KEY); }
    catch (error) { console.warn("Could not clear pending review.", error); }
    activeThreadId = null;
  }

  function show(response, onResult) {
    if (!panel || !response || typeof response !== "object") return;

    if (typeof onResult === "function") renderResponseCallback = onResult;

    if (response.requires_approval !== true) {
      panel.hidden = true;
      if (response.answer || response.final_response) clearPendingReview();
      return;
    }

    activeThreadId = response.thread_id || activeThreadId;
    if (!activeThreadId) {
      panel.hidden = false;
      setStatus("The backend did not return a thread_id. This review cannot be resumed.", true);
      setButtonsDisabled(true);
      return;
    }

    requestText.textContent = response.approval_request ||
      "Please review the generated draft itinerary. Approve it or provide feedback for revision.";
    feedbackInput.value = "";
    panel.hidden = false;
    setButtonsDisabled(false);
    setStatus("Your decision will resume the paused LangGraph workflow using the same thread ID.");
    savePendingReview(response);
  }

  async function postResumeRequest(approved) {
    if (requestInProgress) return;

    const feedback = (feedbackInput?.value || "").trim();
    if (!activeThreadId) {
      setStatus("Missing thread_id. Start a new trip request to create a resumable workflow.", true);
      return;
    }
    if (!approved && !feedback) {
      feedbackInput?.focus();
      setStatus("Please describe the changes you want before requesting a revision.", true);
      return;
    }

    requestInProgress = true;
    setButtonsDisabled(true);
    setStatus(approved ? "Submitting your approval…" : "Sending your feedback and resuming the workflow…");

    try {
      const response = await fetch(RESUME_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        credentials: "same-origin",
        body: JSON.stringify({
          thread_id: activeThreadId,
          approved: approved,
          feedback: feedback
        })
      });

      const raw = await response.text();
      let data;
      try { data = raw ? JSON.parse(raw) : {}; }
      catch (_) { throw new Error(`Server returned non-JSON content (HTTP ${response.status}).`); }

      if (!response.ok) {
        const detail = data.detail || data.error || data.message || `HTTP ${response.status}`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      // Let the existing renderer update the same report/document area and retain its design.
      if (typeof renderResponseCallback === "function") {
        renderResponseCallback(data);
      }
      window.dispatchEvent(new CustomEvent("tripmate:resume-complete", { detail: data }));

      if (data.requires_approval === true) {
        show(data, renderResponseCallback);
      } else {
        panel.hidden = true;
        clearPendingReview();
      }
    } catch (error) {
      console.error("TripMate approval/resume request failed:", error);
      setStatus(`Unable to resume the trip: ${error.message}`, true);
      setButtonsDisabled(false);
    } finally {
      requestInProgress = false;
    }
  }

  approveButton?.addEventListener("click", () => postResumeRequest(true));
  reviseButton?.addEventListener("click", () => postResumeRequest(false));

  function restore(onResult) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
      if (saved?.response?.requires_approval && saved.thread_id) {
        activeThreadId = saved.thread_id;
        show(saved.response, onResult);
        return true;
      }
    } catch (error) {
      console.warn("Could not restore pending TripMate review.", error);
    }
    return false;
  }

  window.TripMateHITL = { show, restore, hide: () => { if (panel) panel.hidden = true; } };
})();

