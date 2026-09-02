// Generic single-CN workflow shared by Consignor/Consignee/Freight Mode/Transport Mode.
// Relies on window.MODULE_KEY / window.MODULE_KIND set by module_single.html.
let lastPreview = null;

function setStatus(status, message) {
  const pill = document.getElementById("statusPill");
  pill.textContent = status;
  pill.className = "status-pill status-" + status;
  document.getElementById("statusMessage").textContent = message || "";
}

function renderAI(ai) {
  const panel = document.getElementById("aiPanel");
  if (!ai) { panel.style.display = "none"; return; }
  panel.style.display = "block";
  const riskColor = { LOW: "success", MEDIUM: "warning", HIGH: "danger" }[ai.risk_level] || "secondary";
  let html = "";
  if (ai.risk_level) html += `<span class="badge text-bg-${riskColor} mb-2">Risk: ${ai.risk_level}</span><br>`;
  if (ai.warnings && ai.warnings.length) html += `<div class="mb-1"><strong>Warnings:</strong><ul class="mb-1">${ai.warnings.map(w => `<li>${w}</li>`).join("")}</ul></div>`;
  if (ai.errors && ai.errors.length) html += `<div class="mb-1 text-danger"><strong>Errors:</strong><ul class="mb-1">${ai.errors.map(w => `<li>${w}</li>`).join("")}</ul></div>`;
  if (ai.findings && ai.findings.length) html += `<div class="mb-1"><strong>Findings:</strong><ul class="mb-1">${ai.findings.map(w => `<li>${w}</li>`).join("")}</ul></div>`;
  if (ai.recommendation) html += `<div class="text-muted">${ai.recommendation}</div>`;
  document.getElementById("aiContent").innerHTML = html || "<span class='text-muted'>No issues found.</span>";
}

function renderBillingSuggestion(suggestion) {
  const box = document.getElementById("billingSuggestionBox");
  if (!box) return;
  if (!suggestion) { box.classList.add("d-none"); box.innerHTML = ""; return; }
  box.classList.remove("d-none");
  box.innerHTML = `
    <strong><i class="bi bi-lightbulb-fill"></i> Suggestion:</strong> ${escapeHtml(suggestion.reason)}<br>
    Billing Party could move from <strong>${escapeHtml(suggestion.current_billing_party_code)} - ${escapeHtml(suggestion.current_billing_party_name || "")}</strong>
    to <strong>${escapeHtml(suggestion.code)} - ${escapeHtml(suggestion.name || "")}</strong>.
    <div class="form-check mt-2">
      <input class="form-check-input" type="checkbox" id="applyBillingSuggestion">
      <label class="form-check-label" for="applyBillingSuggestion">Also update Billing Party to match (this is never done automatically - your choice)</label>
    </div>`;
}

function renderPreview(p) {
  lastPreview = p;
  document.getElementById("previewPanel").style.display = "block";
  setStatus(p.status, p.message);
  document.getElementById("pv_gr").textContent = p.gr_number || "-";
  document.getElementById("pv_old_value").textContent = p.existing_value || "-";
  document.getElementById("pv_new_value").textContent = p.new_value || "-";
  document.getElementById("pv_value_label").textContent = p.new_value_label || p.existing_value_label || "-";
  document.getElementById("pv_existing_remark").textContent = p.existing_remark || "(none)";
  document.getElementById("pv_new_remark").textContent = p.new_remark || "-";
  document.getElementById("pv_change_type").textContent = (p.change_type || "-").replace(/_/g, " ");
  document.getElementById("pv_final_remark").value = p.final_remark || "";
  renderBillingSuggestion(p.billing_party_suggestion);
}

async function runPreview() {
  const gr_number = document.getElementById("grNumber").value.trim();
  const new_value = document.getElementById("newValue").value.trim() || null;
  const new_remark = document.getElementById("newRemark").value;
  const includeAI = document.getElementById("aiToggle") && document.getElementById("aiToggle").checked;

  if (!gr_number) { showToast("Enter a GR/CN number first.", "danger"); return; }

  const data = await apiRequest(`/modify/${window.MODULE_KEY}/single/preview`, {
    method: "POST",
    body: { gr_number, new_value, new_remark, include_ai_analysis: includeAI },
  });

  if (!data.ok) { showToast(data.error, "danger"); return; }
  renderPreview(data.preview);
  renderAI(data.ai_analysis);
}

document.getElementById("previewBtn").addEventListener("click", runPreview);
document.getElementById("refreshBtn").addEventListener("click", runPreview);
document.getElementById("cancelBtn").addEventListener("click", () => {
  document.getElementById("previewPanel").style.display = "none";
});

document.getElementById("confirmBtn").addEventListener("click", () => {
  if (!lastPreview) return;
  document.getElementById("modal_gr").textContent = lastPreview.gr_number;
  document.getElementById("modal_value_change").textContent =
    `${lastPreview.existing_value || "-"} → ${lastPreview.new_value || lastPreview.existing_value || "-"}`;
  document.getElementById("modal_old_remark").textContent = lastPreview.existing_remark || "(none)";
  document.getElementById("modal_final_remark").textContent = document.getElementById("pv_final_remark").value;
});

document.getElementById("modalConfirmBtn").addEventListener("click", async () => {
  if (!lastPreview) return;
  const gr_number = document.getElementById("grNumber").value.trim();
  const new_value = document.getElementById("newValue").value.trim() || null;
  const new_remark = document.getElementById("newRemark").value;
  const final_remark = document.getElementById("pv_final_remark").value;
  const suggestionCheckbox = document.getElementById("applyBillingSuggestion");
  const apply_billing_suggestion = !!(suggestionCheckbox && suggestionCheckbox.checked);

  const data = await apiRequest(`/modify/${window.MODULE_KEY}/single/confirm`, {
    method: "POST",
    body: { gr_number, new_value, new_remark, final_remark, dry_run: !window.SAVE_API_READY, apply_billing_suggestion },
  });

  const modalEl = document.getElementById("confirmModal");
  const modal = bootstrap.Modal.getInstance(modalEl);
  if (modal) modal.hide();

  if (!data.ok) { showToast(data.error || "Modification blocked.", "danger"); return; }
  showToast(data.message, data.modified ? "success" : "warning");
});
