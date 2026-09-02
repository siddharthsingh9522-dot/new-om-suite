// Generic bulk Review & Confirm Center shared by Consignor/Consignee/
// Freight Mode/Transport Mode. Relies on window.MODULE_KEY/MODULE_KIND/
// VALUE_LABEL/SAVE_API_READY set by module_bulk.html.
const BASE = `/modify/${window.MODULE_KEY}`;

let state = {
  savedFilename: null, originalFilename: null, sheets: [], columns: [],
  batchId: null, page: 1, perPage: 25, pollTimer: null, execTimer: null,
};

function setStep(active) {
  const steps = ["upload", "configure", "preview", "execute"];
  const activeIdx = steps.indexOf(active);
  steps.forEach((s, idx) => {
    const el = document.getElementById("step-" + s);
    el.classList.remove("active", "done");
    if (idx < activeIdx) el.classList.add("done");
    if (idx === activeIdx) el.classList.add("active");
  });
}

// ---------- STEP 1: UPLOAD ----------
document.getElementById("uploadBtn").addEventListener("click", async () => {
  const fileInput = document.getElementById("fileInput");
  if (!fileInput.files.length) { showToast("Choose a file first.", "danger"); return; }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  const res = await fetch(`${BASE}/bulk/upload`, { method: "POST", body: formData });
  const data = await res.json();
  if (!data.ok) { showToast(data.error, "danger"); return; }

  state.savedFilename = data.saved_filename;
  state.originalFilename = data.original_filename;
  state.sheets = data.sheets;
  state.columns = data.columns;
  document.getElementById("uploadResult").style.display = "block";
  populateSheetsAndColumns(data.selected_sheet, data.analysis.column);
  applyAnalysis(data.analysis);
});

function populateSheetsAndColumns(selectedSheet, selectedColumn) {
  document.getElementById("sheetSelect").innerHTML = state.sheets.map(s =>
    `<option value="${s}" ${s === selectedSheet ? "selected" : ""}>${s}</option>`).join("");
  document.getElementById("columnSelect").innerHTML = state.columns.map(c =>
    `<option value="${c}" ${c === selectedColumn ? "selected" : ""}>${c}</option>`).join("");
}

function applyAnalysis(a) {
  document.getElementById("stat_total").textContent = a.total_rows;
  document.getElementById("stat_valid").textContent = a.valid_count;
  document.getElementById("stat_dup").textContent = a.duplicate_count;
  document.getElementById("stat_invalid").textContent = a.invalid_count + a.empty_count;
  document.getElementById("columnConfidence").textContent = a.confident
    ? "Column auto-detected with confidence." : "Please verify the column selection above.";
}

document.getElementById("reanalyzeBtn").addEventListener("click", async () => {
  const sheet_name = document.getElementById("sheetSelect").value;
  const gr_column = document.getElementById("columnSelect").value;
  const data = await apiRequest(`${BASE}/bulk/analyze-sheet`, { method: "POST", body: { saved_filename: state.savedFilename, sheet_name, gr_column } });
  if (!data.ok) { showToast(data.error, "danger"); return; }
  applyAnalysis(data.analysis);
});

document.getElementById("proceedToConfigureBtn").addEventListener("click", () => {
  document.getElementById("panelConfigure").style.display = "block";
  document.getElementById("panelConfigure").scrollIntoView({ behavior: "smooth" });
  setStep("configure");
});

// ---------- STEP 2: CONFIGURE ----------
function refreshConfirmBox() {
  const value = document.getElementById("commonNewValue").value.trim();
  const remark = document.getElementById("commonRemark").value;
  document.getElementById("confirmValueText").textContent = value || "(no change)";
  document.getElementById("confirmRemarkText").textContent = remark || "(no remark)";
}
document.getElementById("commonNewValue").addEventListener("input", refreshConfirmBox);
document.getElementById("commonNewValue").addEventListener("change", refreshConfirmBox);
document.getElementById("commonRemark").addEventListener("input", refreshConfirmBox);

document.getElementById("continueToPreviewBtn").addEventListener("click", async () => {
  const sheet_name = document.getElementById("sheetSelect").value;
  const gr_column = document.getElementById("columnSelect").value;
  const new_value = document.getElementById("commonNewValue").value.trim() || null;
  const new_remark = document.getElementById("commonRemark").value;

  const data = await apiRequest(`${BASE}/bulk/create-batch`, {
    method: "POST",
    body: { saved_filename: state.savedFilename, original_filename: state.originalFilename, sheet_name, gr_column, new_value, new_remark },
  });
  if (!data.ok) { showToast(data.error, "danger"); return; }

  state.batchId = data.batch_id;
  document.getElementById("cfg_value").textContent = new_value || "(no change)";
  document.getElementById("cfg_remark").textContent = new_remark || "-";
  document.getElementById("panelPreview").style.display = "block";
  document.getElementById("panelPreview").scrollIntoView({ behavior: "smooth" });
  setStep("preview");

  showToast(`Batch ${data.batch_id} created with ${data.total_gr} GR numbers. Fetching details...`, "primary");
  await apiRequest(`${BASE}/bulk/${state.batchId}/build-preview`, { method: "POST", body: {} });
  pollPreviewStatus();
});

// ---------- STEP 3: REVIEW & CONFIRM ----------
function pollPreviewStatus() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    const data = await apiRequest(`${BASE}/bulk/${state.batchId}/preview-status`);
    if (!data.ok) return;
    renderSummary(data.counts, data.status, data.config_error_message);
    if (data.status !== "FETCHING") {
      clearInterval(state.pollTimer);
      loadItems();
      loadErrorCenter();
      if (data.status === "CONFIGURATION_ERROR") {
        showToast("Configuration error - see details above.", "danger");
      } else {
        showToast("Preview completed for all records.", "success");
      }
    }
  }, 1500);
}

function renderSummary(counts, status, configErrorMessage) {
  document.getElementById("sum_total").textContent = counts.total;
  document.getElementById("sum_ready").textContent = counts.ready;
  document.getElementById("sum_selected").textContent = counts.selected;
  document.getElementById("sum_already").textContent = counts.already_applied;
  document.getElementById("sum_errors").textContent = counts.invalid + counts.error;
  document.getElementById("sum_skipped").textContent = counts.skipped;
  document.getElementById("selectedCountBadge").textContent = `${counts.selected} CN SELECTED`;

  const errBox = document.getElementById("configErrorBox");
  if (status === "CONFIGURATION_ERROR") {
    errBox.style.display = "block";
    errBox.textContent = configErrorMessage || "Configuration error - nothing is ready to modify.";
  } else {
    errBox.style.display = "none";
  }
}

async function loadItems(page = 1) {
  state.page = page;
  const params = new URLSearchParams({
    page, per_page: state.perPage,
    q: document.getElementById("searchBox").value,
    status: document.getElementById("filterStatus").value,
    only_changes: document.getElementById("onlyChangesToggle").checked ? "1" : "0",
  });
  const data = await apiRequest(`${BASE}/bulk/${state.batchId}/items?${params.toString()}`);
  if (!data.ok) return;
  renderSummary(data.counts, "PREVIEW_READY", null);
  renderItemsCards(data.items);
  renderPagination(data.page, data.total_pages);
}

function changeTypeBadge(item) {
  const map = { VALUE_ONLY: "primary", REMARK_ONLY: "info", VALUE_AND_REMARK: "warning", NO_CHANGE: "secondary" };
  const variant = map[item.change_type] || "secondary";
  return `<span class="badge text-bg-${variant}">${item.change_type_label}</span>`;
}

function renderItemsCards(items) {
  const container = document.getElementById("itemsCardList");
  container.innerHTML = items.map(item => `
    <div class="mod-card" data-item-id="${item.id}">
      <div class="mod-card-top">
        <div class="mod-card-select">
          <input type="checkbox" class="form-check-input row-check" ${item.selected ? "checked" : ""}>
          <span class="mod-card-title"><i class="bi bi-file-earmark-text"></i> #${item.serial_no} &middot; <span class="mono">${item.gr_number}</span></span>
          <span class="status-pill status-${item.status}">${item.status}</span>
          ${changeTypeBadge(item)}
          ${item.is_manually_edited ? '<span class="badge text-bg-dark">MANUALLY EDITED</span>' : ""}
        </div>
        <div class="mod-card-actions">
          <button class="btn btn-success btn-sm" data-action="modify" title="Modify This CN" ${item.status === "READY" ? "" : "disabled"}><i class="bi bi-lightning-charge"></i></button>
          <button class="btn btn-outline-secondary btn-sm" data-action="refresh" title="Refresh"><i class="bi bi-arrow-clockwise"></i></button>
          <button class="btn btn-outline-secondary btn-sm" data-action="edit" title="Edit Final Remark"><i class="bi bi-pencil"></i></button>
          <button class="btn btn-outline-secondary btn-sm" data-action="reset" title="Reset to Auto Generated"><i class="bi bi-arrow-counterclockwise"></i></button>
          <button class="btn btn-outline-secondary btn-sm" data-action="skip" title="Skip"><i class="bi bi-slash-circle"></i></button>
        </div>
      </div>
      <div class="field-grid mb-2">
        <div class="field-box"><div class="field-label">Current ${window.VALUE_LABEL}</div><div class="field-value">${item.existing_value || "-"}</div></div>
        <div class="field-box"><div class="field-label">New ${window.VALUE_LABEL}</div><div class="field-value">${item.new_value || "-"}</div></div>
        <div class="field-box span-2"><div class="field-label">${window.VALUE_LABEL} Name/Label</div><div class="field-value">${item.new_value_label || item.existing_value_label || "-"}</div></div>
      </div>
      <div class="field-grid mb-2">
        <div class="field-box"><div class="field-label">Existing Remark</div><div class="field-value diff-old">${item.existing_remark || "(none)"}</div></div>
        <div class="field-box"><div class="field-label">Final Remark</div><div class="field-value diff-new">${item.final_remark || "-"}</div></div>
      </div>
      ${item.validation_message ? `<div class="small text-muted">${item.validation_message}</div>` : ""}
    </div>`).join("");

  container.querySelectorAll(".mod-card").forEach(card => {
    const itemId = card.getAttribute("data-item-id");
    const item = items.find(i => String(i.id) === itemId);
    card.querySelector(".row-check").addEventListener("change", (e) => {
      apiRequest(`${BASE}/bulk/${state.batchId}/item/${itemId}`, { method: "PATCH", body: { action: e.target.checked ? "select" : "deselect" } });
    });
    card.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", () => handleRowAction(itemId, btn.getAttribute("data-action"), item));
    });
  });
}

async function handleRowAction(itemId, action, item) {
  if (action === "refresh") {
    await apiRequest(`${BASE}/bulk/${state.batchId}/item/${itemId}/refresh`, { method: "POST" });
    loadItems(state.page);
  } else if (action === "skip") {
    await apiRequest(`${BASE}/bulk/${state.batchId}/item/${itemId}`, { method: "PATCH", body: { action: "skip" } });
    loadItems(state.page);
  } else if (action === "reset") {
    await apiRequest(`${BASE}/bulk/${state.batchId}/item/${itemId}`, { method: "PATCH", body: { action: "reset_to_auto" } });
    loadItems(state.page);
  } else if (action === "edit") {
    const newVal = prompt("Edit final remark:", item ? item.final_remark : "");
    if (newVal !== null) {
      await apiRequest(`${BASE}/bulk/${state.batchId}/item/${itemId}`, { method: "PATCH", body: { final_remark: newVal } });
      loadItems(state.page);
    }
  } else if (action === "modify") {
    if (!item) return;
    const ok = confirm(
      `CONFIRM SINGLE CN MODIFICATION\n\nCN: ${item.gr_number}\n\n` +
      `${window.VALUE_LABEL} change: ${item.existing_value || "-"} -> ${item.new_value || item.existing_value || "-"}\n\n` +
      `Remark change:\nOLD: ${item.existing_remark || "(none)"}\nFINAL: ${item.final_remark || "-"}`
    );
    if (!ok) return;
    await apiRequest(`${BASE}/bulk/${state.batchId}/execute`, {
      method: "POST",
      body: { dry_run: !window.SAVE_API_READY, item_ids: [parseInt(itemId, 10)], confirmation_text: "MODIFY 1" },
    });
    showToast("Modification started for this CN.", "primary");
    setTimeout(() => loadItems(state.page), 2000);
  }
}

function renderPagination(page, totalPages) {
  const nav = document.getElementById("paginationNav");
  if (totalPages <= 1) { nav.innerHTML = ""; return; }
  let html = '<ul class="pagination pagination-sm">';
  for (let i = 1; i <= totalPages; i++) html += `<li class="page-item ${i === page ? "active" : ""}"><a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
  html += "</ul>";
  nav.innerHTML = html;
  nav.querySelectorAll("[data-page]").forEach(a => a.addEventListener("click", (e) => { e.preventDefault(); loadItems(parseInt(a.getAttribute("data-page"), 10)); }));
}

["searchBox"].forEach(id => document.getElementById(id).addEventListener("input", () => loadItems(1)));
["filterStatus"].forEach(id => document.getElementById(id).addEventListener("change", () => loadItems(1)));
document.getElementById("onlyChangesToggle").addEventListener("change", () => loadItems(1));

document.querySelectorAll("[data-bulk-select]").forEach(btn => {
  btn.addEventListener("click", async () => {
    await apiRequest(`${BASE}/bulk/${state.batchId}/select-bulk`, { method: "POST", body: { mode: btn.getAttribute("data-bulk-select") } });
    loadItems(state.page);
  });
});

document.getElementById("downloadPreReportBtn").addEventListener("click", () => {
  window.location.href = `${BASE}/bulk/${state.batchId}/export`;
});

async function loadErrorCenter() {
  const data = await apiRequest(`${BASE}/bulk/${state.batchId}/items?status=ERROR&per_page=100`);
  const invalidData = await apiRequest(`${BASE}/bulk/${state.batchId}/items?status=INVALID_CN&per_page=100`);
  const invalidValueData = await apiRequest(`${BASE}/bulk/${state.batchId}/items?status=INVALID_VALUE&per_page=100`);
  const problems = [
    ...(data.ok ? data.items : []),
    ...(invalidData.ok ? invalidData.items : []),
    ...(invalidValueData.ok ? invalidValueData.items : []),
  ];
  const panel = document.getElementById("errorCenterPanel");
  if (!problems.length) { panel.style.display = "none"; return; }
  panel.style.display = "block";
  document.getElementById("errorCenterList").innerHTML = problems.map(p => `
    <div class="mod-card">
      <div class="mod-card-top">
        <span class="mono">${p.gr_number}</span>
        <span class="status-pill status-${p.status}">${p.status}</span>
      </div>
      <div class="small text-muted mb-2">${p.validation_message || "No further detail available."}</div>
      <div class="d-flex gap-2">
        <button class="btn btn-sm btn-outline-secondary" data-err-action="retry" data-id="${p.id}">Retry</button>
        <button class="btn btn-sm btn-outline-secondary" data-err-action="refresh" data-id="${p.id}">Refresh</button>
        <button class="btn btn-sm btn-outline-secondary" data-err-action="skip" data-id="${p.id}">Skip</button>
      </div>
    </div>`).join("");

  document.querySelectorAll("[data-err-action]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      const action = btn.getAttribute("data-err-action");
      if (action === "skip") {
        await apiRequest(`${BASE}/bulk/${state.batchId}/item/${id}`, { method: "PATCH", body: { action: "skip" } });
      } else {
        await apiRequest(`${BASE}/bulk/${state.batchId}/item/${id}/refresh`, { method: "POST" });
      }
      loadItems(state.page);
      loadErrorCenter();
    });
  });
}

document.getElementById("proceedToExecuteBtn").addEventListener("click", async () => {
  const data = await apiRequest(`${BASE}/bulk/${state.batchId}/preview-status`);
  const counts = data.counts;
  document.getElementById("executeSummary").innerHTML = `
    <p>You are about to modify:</p>
    <ul>
      <li><strong>${counts.selected}</strong> CN records</li>
      <li>New ${window.VALUE_LABEL}: <span class="mono">${document.getElementById("cfg_value").textContent}</span></li>
      <li>Common Remark: <span class="mono">${document.getElementById("cfg_remark").textContent}</span></li>
    </ul>`;
  document.getElementById("confirmationExpected").textContent = `MODIFY ${counts.selected}`;
  document.getElementById("panelExecute").style.display = "block";
  document.getElementById("panelExecute").scrollIntoView({ behavior: "smooth" });
  setStep("execute");
});

// ---------- STEP 4: TWO-LEVEL CONFIRMATION + EXECUTE ----------
function refreshExecuteGate() {
  const reviewed = document.getElementById("reviewedCheckbox").checked;
  const dryRun = document.getElementById("dryRunToggle").checked;
  const confirmWrap = document.getElementById("confirmationTextWrap");
  const btn = document.getElementById("executeBtn");
  confirmWrap.style.display = (reviewed && !dryRun) ? "block" : "none";

  if (dryRun) {
    btn.disabled = !reviewed;
    document.getElementById("executeBtnLabel").textContent = "Run Dry Run";
  } else {
    const expected = document.getElementById("confirmationExpected").textContent;
    const typed = document.getElementById("confirmationText").value.trim().toUpperCase();
    btn.disabled = !(reviewed && typed === expected);
    document.getElementById("executeBtnLabel").textContent = `Confirm & Modify (${expected.replace("MODIFY ", "")}) CN`;
  }
}
document.getElementById("reviewedCheckbox").addEventListener("change", refreshExecuteGate);
document.getElementById("dryRunToggle").addEventListener("change", refreshExecuteGate);
document.getElementById("confirmationText").addEventListener("input", refreshExecuteGate);

document.getElementById("executeBtn").addEventListener("click", async () => {
  const dry_run = document.getElementById("dryRunToggle").checked;
  const confirmation_text = document.getElementById("confirmationText").value;
  const data = await apiRequest(`${BASE}/bulk/${state.batchId}/execute`, { method: "POST", body: { dry_run, confirmation_text } });
  if (!data.ok) { showToast(data.error, "danger"); return; }
  document.getElementById("liveDashboard").style.display = "block";
  pollExecution();
});

function pollExecution() {
  if (state.execTimer) clearInterval(state.execTimer);
  state.execTimer = setInterval(async () => {
    const data = await apiRequest(`${BASE}/bulk/${state.batchId}/preview-status`);
    if (!data.ok) return;
    const c = data.counts;
    document.getElementById("live_total").textContent = c.total;
    document.getElementById("live_success").textContent = c.success;
    document.getElementById("live_failed").textContent = c.failed + (c.verification_failed || 0);
    document.getElementById("live_processing").textContent = c.processing;
    const done = c.success + c.failed + (c.verification_failed || 0) + c.skipped + c.already_applied;
    const pct = c.total ? Math.round((done / c.total) * 100) : 0;
    const bar = document.getElementById("liveProgressBar");
    bar.style.width = pct + "%"; bar.textContent = pct + "%";

    if (["COMPLETED", "COMPLETED_WITH_ERRORS", "STOPPED", "DRY_RUN_COMPLETED"].includes(data.status)) {
      clearInterval(state.execTimer);
      const variant = data.status === "COMPLETED" ? "success" : (data.status === "STOPPED" ? "warning" : "primary");
      showToast(`Execution finished: ${data.status.replace(/_/g, " ")}`, variant);
    }
  }, 1500);
}

document.getElementById("pauseBtn").addEventListener("click", () => apiRequest(`${BASE}/bulk/${state.batchId}/pause`, { method: "POST" }));
document.getElementById("resumeBtn").addEventListener("click", () => apiRequest(`${BASE}/bulk/${state.batchId}/resume`, { method: "POST" }));
document.getElementById("stopBtn").addEventListener("click", () => apiRequest(`${BASE}/bulk/${state.batchId}/stop`, { method: "POST" }));
document.getElementById("retryFailedBtn").addEventListener("click", async () => {
  const dry_run = document.getElementById("dryRunToggle").checked;
  await apiRequest(`${BASE}/bulk/${state.batchId}/retry-failed`, { method: "POST", body: { dry_run } });
  pollExecution();
});
document.getElementById("exportFinalBtn").addEventListener("click", () => { window.location.href = `${BASE}/bulk/${state.batchId}/export`; });
