// Bulk Excel workflow: upload -> configure -> preview -> execute
let state = {
  savedFilename: null,
  originalFilename: null,
  sheets: [],
  columns: [],
  batchId: null,
  page: 1,
  perPage: 25,
  pollTimer: null,
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

  const res = await fetch("/bulk/upload", { method: "POST", body: formData });
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
  const sheetSelect = document.getElementById("sheetSelect");
  sheetSelect.innerHTML = state.sheets.map(s => `<option value="${s}" ${s === selectedSheet ? "selected" : ""}>${s}</option>`).join("");

  const columnSelect = document.getElementById("columnSelect");
  columnSelect.innerHTML = state.columns.map(c => `<option value="${c}" ${c === selectedColumn ? "selected" : ""}>${c}</option>`).join("");
}

function applyAnalysis(analysis) {
  document.getElementById("stat_total").textContent = analysis.total_rows;
  document.getElementById("stat_valid").textContent = analysis.valid_count;
  document.getElementById("stat_dup").textContent = analysis.duplicate_count;
  document.getElementById("stat_invalid").textContent = analysis.invalid_count + analysis.empty_count;
  document.getElementById("columnConfidence").textContent = analysis.confident
    ? "Column auto-detected with confidence."
    : "Could not confidently detect the GR column - please verify the selection above.";
}

document.getElementById("reanalyzeBtn").addEventListener("click", async () => {
  const sheet_name = document.getElementById("sheetSelect").value;
  const gr_column = document.getElementById("columnSelect").value;
  const data = await apiRequest("/bulk/analyze-sheet", {
    method: "POST",
    body: { saved_filename: state.savedFilename, sheet_name, gr_column },
  });
  if (!data.ok) { showToast(data.error, "danger"); return; }
  applyAnalysis(data.analysis);
});

document.getElementById("proceedToConfigureBtn").addEventListener("click", () => {
  document.getElementById("panelConfigure").style.display = "block";
  document.getElementById("panelConfigure").scrollIntoView({ behavior: "smooth" });
  setStep("configure");
});

// ---------- STEP 2: CONFIGURE ----------
document.getElementById("detectPartyBtn").addEventListener("click", async () => {
  const common_remark = document.getElementById("commonRemark").value;
  if (!common_remark.trim()) { showToast("Enter a remark first.", "danger"); return; }

  const data = await apiRequest("/bulk/detect-party", { method: "POST", body: { common_remark } });
  if (!data.ok) { showToast(data.error, "danger"); return; }

  const resultBox = document.getElementById("partyResult");
  if (!data.detected) {
    resultBox.style.display = "none";
    showToast(data.message, "warning");
    return;
  }
  resultBox.style.display = "block";
  document.getElementById("dp_code").textContent = data.party_code;
  document.getElementById("dp_name").textContent = data.party_name || "-";
  document.getElementById("dp_type").textContent = data.party_type || "-";
  document.getElementById("dp_loc").textContent = data.billing_location || "-";
  document.getElementById("dp_gst").textContent = data.gst || "-";
  document.getElementById("dp_verified").textContent = data.verified || "-";

  const confirmBox = document.getElementById("confirmRemarkBox");
  confirmBox.style.display = data.valid ? "block" : "none";
  document.getElementById("confirmRemarkText").textContent = common_remark;
});

document.getElementById("changeRemarkBtn").addEventListener("click", () => {
  document.getElementById("confirmRemarkBox").style.display = "none";
});

document.getElementById("continueToPreviewBtn").addEventListener("click", async () => {
  const common_remark = document.getElementById("commonRemark").value;
  const sheet_name = document.getElementById("sheetSelect").value;
  const gr_column = document.getElementById("columnSelect").value;

  const data = await apiRequest("/bulk/create-batch", {
    method: "POST",
    body: {
      saved_filename: state.savedFilename,
      original_filename: state.originalFilename,
      sheet_name, gr_column, common_remark,
    },
  });
  if (!data.ok) { showToast(data.error, "danger"); return; }

  state.batchId = data.batch_id;
  document.getElementById("panelPreview").style.display = "block";
  document.getElementById("panelPreview").scrollIntoView({ behavior: "smooth" });
  setStep("preview");

  showToast(`Batch ${data.batch_id} created with ${data.total_gr} GR numbers. Fetching details...`, "primary");
  await apiRequest(`/bulk/${state.batchId}/build-preview`, { method: "POST", body: {} });
  pollPreviewStatus();
});

// ---------- STEP 3: PREVIEW ----------
function pollPreviewStatus() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    const data = await apiRequest(`/bulk/${state.batchId}/preview-status`);
    if (!data.ok) return;
    renderCounts(data.counts);
    if (data.status === "PREVIEWED") {
      clearInterval(state.pollTimer);
      loadItems();
      showToast("Preview completed for all records.", "success");
    }
  }, 1500);
}

function renderCounts(counts) {
  const el = document.getElementById("previewCounts");
  const parts = [
    ["total", "secondary"], ["ready", "success"], ["already_applied", "primary"],
    ["invalid", "danger"], ["error", "danger"], ["success", "success"],
    ["failed", "danger"], ["skipped", "secondary"], ["processing", "warning"], ["pending", "secondary"],
  ];
  el.innerHTML = parts
    .filter(([k]) => counts[k] !== undefined && counts[k] > 0 || k === "total")
    .map(([k, variant]) => `<span class="badge text-bg-${variant}">${k}: ${counts[k]}</span>`)
    .join("");
}

async function loadItems(page = 1) {
  state.page = page;
  const params = new URLSearchParams({
    page, per_page: state.perPage,
    gr: document.getElementById("searchGr").value,
    party: document.getElementById("searchParty").value,
    status: document.getElementById("filterStatus").value,
  });
  const data = await apiRequest(`/bulk/${state.batchId}/items?${params.toString()}`);
  if (!data.ok) return;
  renderCounts(data.counts);
  renderItemsTable(data.items);
  renderPagination(data.page, data.total_pages);
}

function renderItemsTable(items) {
  const container = document.getElementById("itemsCardList");
  container.innerHTML = items.map(item => `
    <div class="mod-card" data-item-id="${item.id}">
      <div class="mod-card-top">
        <div class="mod-card-select">
          <input type="checkbox" class="form-check-input row-check" ${item.selected ? "checked" : ""}>
          <span class="mod-card-title"><i class="bi bi-file-earmark-text"></i> #${item.serial_no} &middot; <span class="mono">${item.gr_number}</span></span>
          <span class="status-pill status-${item.status}">${item.status}</span>
        </div>
        <div class="mod-card-actions">
          <button class="btn btn-outline-secondary btn-sm" data-action="refresh" title="Refresh"><i class="bi bi-arrow-clockwise"></i></button>
          <button class="btn btn-outline-secondary btn-sm" data-action="edit" title="Edit Final Remark"><i class="bi bi-pencil"></i></button>
          <button class="btn btn-outline-secondary btn-sm" data-action="skip" title="Skip"><i class="bi bi-slash-circle"></i></button>
        </div>
      </div>

      <div class="field-grid mb-2">
        <div class="field-box">
          <div class="field-label">Current Party Code</div>
          <div class="field-value">${item.existing_party_code || "-"}</div>
        </div>
        <div class="field-box">
          <div class="field-label">New Party Code</div>
          <div class="field-value">${item.new_party_code || "-"}</div>
        </div>
        <div class="field-box">
          <div class="field-label">Party Name</div>
          <div class="field-value">${item.party_name || "-"}</div>
        </div>
        <div class="field-box">
          <div class="field-label">Billing Location</div>
          <div class="field-value">${item.billing_location || "-"}</div>
        </div>
      </div>

      <div class="field-grid mb-2">
        <div class="field-box">
          <div class="field-label">Existing Remark</div>
          <div class="field-value diff-old">${item.existing_remark || "(none)"}</div>
        </div>
        <div class="field-box">
          <div class="field-label">Final Remark</div>
          <div class="field-value diff-new">${item.final_remark || "-"}</div>
        </div>
      </div>

      ${item.validation_message ? `<div class="small text-muted">${item.validation_message}</div>` : ""}
    </div>`).join("");

  container.querySelectorAll(".mod-card").forEach(card => {
    const itemId = card.getAttribute("data-item-id");
    card.querySelector(".row-check").addEventListener("change", (e) => {
      apiRequest(`/bulk/${state.batchId}/item/${itemId}`, {
        method: "PATCH", body: { action: e.target.checked ? "select" : "deselect" },
      });
    });
    card.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", () => handleRowAction(itemId, btn.getAttribute("data-action")));
    });
  });
}

async function handleRowAction(itemId, action) {
  if (action === "refresh") {
    await apiRequest(`/bulk/${state.batchId}/item/${itemId}/refresh`, { method: "POST" });
    loadItems(state.page);
  } else if (action === "skip") {
    await apiRequest(`/bulk/${state.batchId}/item/${itemId}`, { method: "PATCH", body: { action: "skip" } });
    loadItems(state.page);
  } else if (action === "edit") {
    const newVal = prompt("Edit final remark:");
    if (newVal !== null) {
      await apiRequest(`/bulk/${state.batchId}/item/${itemId}`, { method: "PATCH", body: { final_remark: newVal } });
      loadItems(state.page);
    }
  }
}

function renderPagination(page, totalPages) {
  const nav = document.getElementById("paginationNav");
  if (totalPages <= 1) { nav.innerHTML = ""; return; }
  let html = '<ul class="pagination pagination-sm">';
  for (let i = 1; i <= totalPages; i++) {
    html += `<li class="page-item ${i === page ? "active" : ""}"><a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
  }
  html += "</ul>";
  nav.innerHTML = html;
  nav.querySelectorAll("[data-page]").forEach(a => {
    a.addEventListener("click", (e) => { e.preventDefault(); loadItems(parseInt(a.getAttribute("data-page"), 10)); });
  });
}

["searchGr", "searchParty", "filterStatus"].forEach(id => {
  document.getElementById(id).addEventListener("input", () => loadItems(1));
  document.getElementById(id).addEventListener("change", () => loadItems(1));
});

document.querySelectorAll("[data-bulk-select]").forEach(btn => {
  btn.addEventListener("click", async () => {
    await apiRequest(`/bulk/${state.batchId}/select-bulk`, {
      method: "POST", body: { mode: btn.getAttribute("data-bulk-select") },
    });
    loadItems(state.page);
  });
});

document.getElementById("exportPreviewBtn").addEventListener("click", () => {
  window.location.href = `/bulk/${state.batchId}/export`;
});

document.getElementById("proceedToExecuteBtn").addEventListener("click", async () => {
  const data = await apiRequest(`/bulk/${state.batchId}/preview-status`);
  const counts = data.counts;
  document.getElementById("executeSummary").innerHTML = `
    <p>You are about to modify selected GR records.</p>
    <ul>
      <li>Total: ${counts.total}</li>
      <li>Ready: ${counts.ready}</li>
      <li>Already Applied: ${counts.already_applied}</li>
      <li>Invalid: ${counts.invalid}</li>
      <li>Errors: ${counts.error}</li>
    </ul>`;
  document.getElementById("confirmationExpected").textContent = `MODIFY ${counts.ready}`;
  document.getElementById("panelExecute").style.display = "block";
  document.getElementById("panelExecute").scrollIntoView({ behavior: "smooth" });
  setStep("execute");
});

// ---------- STEP 4: EXECUTE ----------
document.getElementById("executeBtn").addEventListener("click", async () => {
  const dry_run = document.getElementById("dryRunToggle").checked;
  const confirmation_text = document.getElementById("confirmationText").value;

  const data = await apiRequest(`/bulk/${state.batchId}/execute`, {
    method: "POST", body: { dry_run, confirmation_text },
  });
  if (!data.ok) { showToast(data.error, "danger"); return; }

  document.getElementById("liveDashboard").style.display = "block";
  pollExecution();
});

function pollExecution() {
  const timer = setInterval(async () => {
    const data = await apiRequest(`/bulk/${state.batchId}/preview-status`);
    if (!data.ok) return;
    const c = data.counts;
    document.getElementById("live_total").textContent = c.total;
    document.getElementById("live_success").textContent = c.success;
    document.getElementById("live_failed").textContent = c.failed;
    document.getElementById("live_processing").textContent = c.processing;

    const done = c.success + c.failed + c.skipped + c.already_applied;
    const pct = c.total ? Math.round((done / c.total) * 100) : 0;
    const bar = document.getElementById("liveProgressBar");
    bar.style.width = pct + "%";
    bar.textContent = pct + "%";

    if (data.status === "COMPLETED" || data.status === "STOPPED") {
      clearInterval(timer);
      showToast(`Execution ${data.status.toLowerCase()}.`, data.status === "COMPLETED" ? "success" : "warning");
    }
  }, 1500);
}

document.getElementById("pauseBtn").addEventListener("click", () => apiRequest(`/bulk/${state.batchId}/pause`, { method: "POST" }));
document.getElementById("resumeBtn").addEventListener("click", () => apiRequest(`/bulk/${state.batchId}/resume`, { method: "POST" }));
document.getElementById("stopBtn").addEventListener("click", () => apiRequest(`/bulk/${state.batchId}/stop`, { method: "POST" }));
document.getElementById("retryFailedBtn").addEventListener("click", async () => {
  const dry_run = document.getElementById("dryRunToggle").checked;
  await apiRequest(`/bulk/${state.batchId}/retry-failed`, { method: "POST", body: { dry_run } });
  pollExecution();
});
document.getElementById("exportFinalBtn").addEventListener("click", () => {
  window.location.href = `/bulk/${state.batchId}/export`;
});
