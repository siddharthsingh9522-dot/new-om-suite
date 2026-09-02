// Shared front-end helpers used across all pages.

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showToast(message, variant = "primary") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast align-items-center text-bg-${variant} border-0`;
  el.setAttribute("role", "alert");
  el.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(el);
  const toast = new bootstrap.Toast(el, { delay: 4500 });
  toast.show();
  el.addEventListener("hidden.bs.toast", () => el.remove());
}

async function apiRequest(url, options = {}) {
  const opts = Object.assign({ headers: { "Content-Type": "application/json" } }, options);
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, opts);
  let data;
  try {
    data = await res.json();
  } catch (e) {
    data = { ok: false, error: "Unexpected server response." };
  }
  if (!res.ok && data.ok === undefined) {
    data.ok = false;
    data.error = data.error || `Request failed (${res.status})`;
  }
  return data;
}

function refreshSystemStatus() {
  const badge = document.getElementById("systemStatusBadge");
  if (!badge) return;
  apiRequest("/api/system-status").then((data) => {
    if (!data.ok) {
      badge.className = "badge text-bg-danger";
      badge.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Status unknown';
      return;
    }
    if (data.api_reachable) {
      badge.className = "badge text-bg-success";
      badge.innerHTML = '<i class="bi bi-wifi"></i> API Connected';
    } else {
      badge.className = "badge text-bg-danger";
      badge.innerHTML = '<i class="bi bi-wifi-off"></i> API Unreachable';
    }
  }).catch(() => {
    badge.className = "badge text-bg-secondary";
    badge.innerHTML = '<i class="bi bi-question-circle"></i> Unknown';
  });
}

document.addEventListener("DOMContentLoaded", () => {
  refreshSystemStatus();
  setInterval(refreshSystemStatus, 30000);

  const toggle = document.getElementById("sidebarToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      document.querySelector(".sidebar").classList.toggle("show");
    });
  }
});
