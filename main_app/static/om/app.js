const PAGES = JSON.parse(document.getElementById("pages-data").textContent);
const app = document.getElementById("app");

let currentPoll = null;

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// ---------------- Routing ----------------

function showHome() {
    stopPolling();

    app.innerHTML = `
        <div class="home-title">Future Dashboard UI</div>
        <div class="panel">
            <div class="panel-header">
                <h2 class="panel-heading">Single Window<br>Control Panel</h2>
                <span class="pill pill-accent">Enterprise</span>
            </div>
            <div class="card-grid" id="card-grid"></div>
        </div>
    `;

    const grid = document.getElementById("card-grid");

    Object.entries(PAGES).forEach(([key, meta]) => {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `
            <div class="card-title">${escapeHtml(meta.title)}</div>
            <div class="card-desc">${escapeHtml(meta.subtitle)}</div>
        `;
        card.addEventListener("click", () => showPage(key));
        grid.appendChild(card);
    });
}

function showPage(key) {
    stopPolling();

    const meta = PAGES[key];
    const isGst = key === "gst";

    app.innerHTML = `
        <div class="page-topbar">
            <button class="back-btn" id="back-btn">&larr; Back</button>
            <div>
                <div class="page-title">${escapeHtml(meta.title)}</div>
                <div class="page-subtitle">${escapeHtml(meta.subtitle)}</div>
            </div>
        </div>

        <div class="tabs">
            <button class="tab-btn active" data-mode="manual">${isGst ? "Single GSTIN" : "Manual"}</button>
            <button class="tab-btn" data-mode="excel">Excel Sheet</button>
        </div>

        <div id="manual-panel"></div>
        <div id="excel-panel" style="display:none;"></div>
        ${isGst ? '<div id="gst-captcha-panel"></div>' : ''}
    `;

    document.getElementById("back-btn").addEventListener("click", showHome);

    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            const isManual = btn.dataset.mode === "manual";
            document.getElementById("manual-panel").style.display = isManual ? "block" : "none";
            document.getElementById("excel-panel").style.display = isManual ? "none" : "block";
        });
    });

    if (isGst) {
        // GST needs a captcha typed by a human for every search, so
        // it gets its own request/response loop instead of the
        // generic instant manual-fetch / background-job excel flow.
        renderGstManualStart(meta);
        renderGstExcelStart(meta);
        initGstCaptchaPanel();
    } else {
        renderManualPanel(key, meta);
        renderExcelPanel(key, meta);
    }
}

// ---------------- Manual mode ----------------

function renderManualPanel(key, meta) {
    const panel = document.getElementById("manual-panel");

    panel.innerHTML = `
        <div class="manual-row">
            <input type="text" id="manual-input" placeholder="Enter ${escapeHtml(meta.input_label)}">
            <button class="btn" id="manual-fetch-btn">Fetch</button>
        </div>
        <div class="result-box" id="manual-result">
            <div class="result-hint">Result will appear here.</div>
        </div>
    `;

    const input = document.getElementById("manual-input");
    const btn = document.getElementById("manual-fetch-btn");
    const resultBox = document.getElementById("manual-result");

    async function doFetch() {
        const value = input.value.trim();

        if (!value) {
            resultBox.innerHTML = `<div class="result-error">Please enter a ${escapeHtml(meta.input_label)}.</div>`;
            return;
        }

        btn.disabled = true;
        resultBox.innerHTML = `<div class="result-hint">Fetching...</div>`;

        try {
            const res = await fetch(`/om/api/manual/${key}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ value })
            });

            const payload = await res.json();
            renderResult(resultBox, payload, key);

        } catch (err) {
            resultBox.innerHTML = `<div class="result-error">Network error: ${escapeHtml(err.message)}</div>`;
        } finally {
            btn.disabled = false;
        }
    }

    btn.addEventListener("click", doFetch);
    input.addEventListener("keydown", e => { if (e.key === "Enter") doFetch(); });
}

// ---------------- WhatsApp-style tracking card (CN / Master) ----------------

const TRACKING_FIELDS = [
    { icon: "📦", label: "CN No.",       key: "CN" },
    { icon: "🧾", label: "Bill No.",     key: "Bill No" },
    { icon: "👤", label: "Party Name",   key: "Party Name" },
    { icon: "📍", label: "Source",       key: "Source" },
    { icon: "📍", label: "Destination",  key: "Destination" },
    { icon: "📅", label: "Booking Date", key: "CN Date" },
    { icon: "🚛", label: "Vehicle",      key: "Lorry No" },
    { icon: "📦", label: "Packages",     key: "Package" },
    { icon: "⚖️", label: "Weight",       key: "__weight" },
    { icon: "🚦", label: "Status",       key: "__status" },
];

function shortStatus(status) {
    if (!status) return "UNKNOWN";
    const head = String(status).split(" - ")[0].split(",")[0];
    return head.trim().toUpperCase();
}

// CN Status text doesn't carry a numeric percentage, so this maps the
// known status vocabulary to a rough delivery-progress estimate for
// the progress bar. Unrecognized status text falls back to 40%
// rather than 0%, since "unknown" isn't the same as "just booked".
function estimateProgress(status) {
    const s = String(status || "").toLowerCase();
    if (s.includes("delivered")) return 100;
    if (s.includes("out for delivery")) return 88;
    if (s.includes("in transit") || s.includes("transit")) return 55;
    if (s.includes("reached") || s.includes("arrived") || s.includes("hub")) return 65;
    if (s.includes("picked") || s.includes("pickup")) return 25;
    if (s.includes("booked") || s.includes("booking")) return 12;
    if (s.includes("cancel")) return 0;
    return 40;
}

function trackingFieldValue(data, key) {
    if (key === "__weight") {
        const w = data["Charged Weight"] ?? data["Actual Weight"];
        return (w === undefined || w === null || w === "") ? "" : `${w} KG`;
    }
    if (key === "__status") {
        return data["CN Status"] ? shortStatus(data["CN Status"]) : "";
    }
    const v = data[key];
    return (v === undefined || v === null || v === "") ? "" : v;
}

// Rule-based one-line summary built from the fetched fields - not a
// live model call, just a readable rollup of what's already in `data`.
function buildAiSummary(data) {
    const parts = [];
    const cn = data["CN"];
    const src = data["Source"];
    const dest = data["Destination"];
    const status = data["CN Status"];

    let s1 = cn ? `CN ${cn}` : "This shipment";
    if (src && dest) s1 += ` is moving from ${src} to ${dest}`;
    if (status) s1 += `, currently ${shortStatus(status).toLowerCase()}`;
    parts.push(s1 + ".");

    if (data["Party Name"]) {
        let s2 = `Billed to ${data["Party Name"]}`;
        if (data["GST Status"]) s2 += ` — GST ${data["GST Status"]}`;
        else if (data["Pipeline Stage"] === "Customer Found") s2 += " — GST verification pending";
        parts.push(s2 + ".");
    }

    return parts.join(" ");
}

function formatTrackingMessage(data) {
    return TRACKING_FIELDS.map(f => {
        const val = trackingFieldValue(data, f.key) || "-";
        const label = (f.label + " ".repeat(16)).slice(0, 16);
        return `${f.icon} ${label}: ${val}`;
    }).join("\n");
}

function renderTrackingCard(box, data) {
    const progress = estimateProgress(data["CN Status"]);
    const status = shortStatus(data["CN Status"]);

    const rowsHtml = TRACKING_FIELDS.map(f => {
        const val = trackingFieldValue(data, f.key);
        if (!val) return "";
        return `
            <div class="tracking-row">
                <span class="t-icon">${f.icon}</span>
                <span class="t-label">${escapeHtml(f.label)}</span>
                <span class="t-value">${escapeHtml(val)}</span>
            </div>
        `;
    }).join("");

    box.innerHTML = `
        <div class="tracking-card">
            <div class="tracking-head">
                <div class="tracking-head-title"><span class="status-emoji">📦</span> Shipment Snapshot</div>
                <span class="tracking-status-pill">${escapeHtml(status)}</span>
            </div>
            <div class="tracking-progress-wrap">
                <div class="tracking-progress-label">
                    <span>Delivery Progress</span>
                    <span class="pct">${progress}%</span>
                </div>
                <div class="tracking-progress-track">
                    <div class="tracking-progress-fill" style="width:${progress}%"></div>
                </div>
            </div>
            <div class="tracking-rows">${rowsHtml}</div>
            <div class="ai-summary">
                <div class="ai-summary-eyebrow">✨ AI SUMMARY</div>
                <div class="ai-summary-text">${escapeHtml(buildAiSummary(data))}</div>
            </div>
            <div class="tracking-copy-row">
                <button class="copy-btn" id="copy-tracking-btn">Copy as WhatsApp message</button>
            </div>
        </div>
    `;

    const copyBtn = box.querySelector("#copy-tracking-btn");
    copyBtn.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(formatTrackingMessage(data));
            copyBtn.textContent = "Copied ✓";
            copyBtn.classList.add("copied");
        } catch (err) {
            copyBtn.textContent = "Copy failed";
        } finally {
            setTimeout(() => {
                copyBtn.textContent = "Copy as WhatsApp message";
                copyBtn.classList.remove("copied");
            }, 1800);
        }
    });
}

function renderResult(box, payload, key) {
    const data = payload.data || {};
    const entries = Object.entries(data).filter(([k, v]) => v !== null && v !== "" && v !== undefined);

    if (entries.length === 0) {
        box.innerHTML = `<div class="result-hint">No data found.</div>`;
        return;
    }

    const hasError = "Error" in data;

    if (!hasError && (key === "cn" || key === "master")) {
        renderTrackingCard(box, data);
        return;
    }

    let html = "";

    if (hasError) {
        html += `<div class="result-error" style="margin-bottom:12px;">${escapeHtml(data.Error)}</div>`;
    }

    entries.forEach(([k, v]) => {
        if (k === "Error") return;
        html += `
            <div class="result-row">
                <span class="result-label">${escapeHtml(k)}</span>
                <span class="result-value">${escapeHtml(v)}</span>
            </div>
        `;
    });

    box.innerHTML = html || `<div class="result-hint">No data found.</div>`;
}

// ---------------- Excel mode ----------------

function renderExcelPanel(key, meta) {
    const panel = document.getElementById("excel-panel");

    panel.innerHTML = `
        <div class="excel-upload-row">
            <label class="file-label" id="file-label" for="file-input">Choose an Excel file (.xlsx / .xls)</label>
            <input type="file" id="file-input" accept=".xlsx,.xls" style="display:none;">
            <button class="btn" id="start-btn">Start</button>
            <button class="btn btn-danger" id="stop-btn" disabled>Stop</button>
        </div>

        <div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div>
        <div class="status-line" id="status-line">Ready</div>

        <div class="log-box" id="log-box"></div>
        <div class="download-row" id="download-row"></div>
    `;

    const fileInput = document.getElementById("file-input");
    const fileLabel = document.getElementById("file-label");
    const startBtn = document.getElementById("start-btn");
    const stopBtn = document.getElementById("stop-btn");
    const progressFill = document.getElementById("progress-fill");
    const statusLine = document.getElementById("status-line");
    const logBox = document.getElementById("log-box");
    const downloadRow = document.getElementById("download-row");

    let currentJobId = null;
    let logCount = 0;

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            fileLabel.textContent = fileInput.files[0].name;
            fileLabel.classList.add("has-file");
        }
    });

    function appendLogLine(line) {
        const div = document.createElement("div");
        div.className = "log-line " + (
            line.includes("FAIL") ? "fail" : line.includes("OK") ? "ok" : "info"
        );
        div.textContent = line;
        logBox.appendChild(div);
        logBox.scrollTop = logBox.scrollHeight;
    }

    async function pollStatus() {
        if (!currentJobId) return;

        try {
            const res = await fetch(`/om/api/excel/status/${currentJobId}?log_from=${logCount}`);
            const payload = await res.json();

            if (!payload.success) {
                statusLine.textContent = "Error checking status";
                stopPolling();
                return;
            }

            (payload.log || []).forEach(appendLogLine);
            logCount = payload.log_count;

            if (payload.total) {
                const percent = Math.round((payload.current / payload.total) * 100);
                progressFill.style.width = percent + "%";
                statusLine.textContent = `Processing ${payload.current}/${payload.total}`;
            }

            if (payload.status === "done" || payload.status === "stopped" || payload.status === "error") {
                statusLine.textContent =
                    payload.status === "done" ? "Completed" :
                    payload.status === "stopped" ? "Stopped" : "Failed";

                stopPolling();
                startBtn.disabled = false;
                stopBtn.disabled = true;

                if (payload.output_filename) {
                    downloadRow.innerHTML = `
                        <a class="download-btn" href="/om/download/${encodeURIComponent(payload.output_filename)}">
                            Download Report
                        </a>
                    `;
                }
            }

        } catch (err) {
            statusLine.textContent = "Network error while checking status";
        }
    }

    function stopPollingLocal() {
        if (currentPoll) {
            clearInterval(currentPoll);
            currentPoll = null;
        }
    }

    startBtn.addEventListener("click", async () => {
        if (!fileInput.files.length) {
            statusLine.textContent = "Please choose an Excel file first.";
            return;
        }

        startBtn.disabled = true;
        stopBtn.disabled = false;
        logBox.innerHTML = "";
        downloadRow.innerHTML = "";
        progressFill.style.width = "0%";
        statusLine.textContent = "Uploading...";
        logCount = 0;

        const formData = new FormData();
        formData.append("file", fileInput.files[0]);

        try {
            const res = await fetch(`/om/api/excel/${key}/start`, {
                method: "POST",
                body: formData
            });

            const payload = await res.json();

            if (!payload.success) {
                statusLine.textContent = payload.message || "Failed to start";
                startBtn.disabled = false;
                stopBtn.disabled = true;
                return;
            }

            currentJobId = payload.job_id;
            statusLine.textContent = "Starting...";

            stopPollingLocal();
            currentPoll = setInterval(pollStatus, 1000);

        } catch (err) {
            statusLine.textContent = "Network error: " + err.message;
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }
    });

    stopBtn.addEventListener("click", async () => {
        if (!currentJobId) return;
        stopBtn.disabled = true;
        statusLine.textContent = "Stopping...";

        try {
            await fetch(`/om/api/excel/stop/${currentJobId}`, { method: "POST" });
        } catch (err) {
            // ignore; polling will still reflect final state
        }
    });
}

function stopPolling() {
    if (currentPoll) {
        clearInterval(currentPoll);
        currentPoll = null;
    }
}

// ---------------- GST captcha flow ----------------
// The real GST portal makes you solve a captcha for every search, so
// this can't be a single silent fetch like CN / Party Code. Both the
// "Single GSTIN" and "Excel Sheet" tabs just start a session; the
// same captcha panel below handles typing + submitting for whichever
// one started it.

let gstSessionActive = false;

function renderGstManualStart(meta) {
    const panel = document.getElementById("manual-panel");

    panel.innerHTML = `
        <div class="manual-row">
            <input type="text" id="gst-manual-input" placeholder="Enter 15-character GSTIN">
            <button class="btn" id="gst-manual-start-btn">Start</button>
        </div>
        <div id="gst-manual-hint"></div>
    `;

    const input = document.getElementById("gst-manual-input");
    const btn = document.getElementById("gst-manual-start-btn");
    const hint = document.getElementById("gst-manual-hint");

    async function start() {
        const gstin = input.value.trim().toUpperCase();

        if (!gstin) {
            hint.innerHTML = `<div class="result-error">Please enter a GSTIN.</div>`;
            return;
        }

        resetGstCaptchaPanel();
        btn.disabled = true;
        hint.innerHTML = `<div class="result-hint">Starting...</div>`;

        try {
            const res = await fetch("/om/api/gst/captcha/start_manual", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ gstin })
            });
            const payload = await res.json();

            if (!payload.success) {
                hint.innerHTML = `<div class="result-error">${escapeHtml(payload.message || "Could not start.")}</div>`;
                btn.disabled = false;
                return;
            }

            hint.innerHTML = "";
            onGstSessionUpdate(payload);

        } catch (err) {
            hint.innerHTML = `<div class="result-error">Network error: ${escapeHtml(err.message)}</div>`;
            btn.disabled = false;
        }
    }

    btn.addEventListener("click", start);
    input.addEventListener("keydown", e => { if (e.key === "Enter") start(); });
}

function renderGstExcelStart(meta) {
    const panel = document.getElementById("excel-panel");

    panel.innerHTML = `
        <div class="excel-upload-row">
            <label class="file-label" id="gst-file-label" for="gst-file-input">Choose an Excel file (.xlsx / .xls) with a GSTIN column</label>
            <input type="file" id="gst-file-input" accept=".xlsx,.xls" style="display:none;">
            <button class="btn" id="gst-excel-start-btn">Start</button>
        </div>
        <div id="gst-excel-hint"></div>
    `;

    const fileInput = document.getElementById("gst-file-input");
    const fileLabel = document.getElementById("gst-file-label");
    const btn = document.getElementById("gst-excel-start-btn");
    const hint = document.getElementById("gst-excel-hint");

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            fileLabel.textContent = fileInput.files[0].name;
            fileLabel.classList.add("has-file");
        }
    });

    btn.addEventListener("click", async () => {
        if (!fileInput.files.length) {
            hint.innerHTML = `<div class="result-error">Please choose an Excel file first.</div>`;
            return;
        }

        resetGstCaptchaPanel();
        btn.disabled = true;
        hint.innerHTML = `<div class="result-hint">Uploading...</div>`;

        const formData = new FormData();
        formData.append("file", fileInput.files[0]);

        try {
            const res = await fetch("/om/api/gst/captcha/start_excel", { method: "POST", body: formData });
            const payload = await res.json();

            if (!payload.success) {
                hint.innerHTML = `<div class="result-error">${escapeHtml(payload.message || "Could not start.")}</div>`;
                btn.disabled = false;
                return;
            }

            hint.innerHTML = "";
            onGstSessionUpdate(payload);

        } catch (err) {
            hint.innerHTML = `<div class="result-error">Network error: ${escapeHtml(err.message)}</div>`;
            btn.disabled = false;
        }
    });
}

function initGstCaptchaPanel() {
    const panel = document.getElementById("gst-captcha-panel");

    panel.innerHTML = `
        <div class="captcha-box" id="captcha-box" style="display:none;">
            <div class="captcha-gst-label" id="captcha-gst-label"></div>
            <img class="captcha-img" id="captcha-img" alt="captcha">
            <div class="manual-row">
                <input type="text" id="captcha-input" placeholder="Type the captcha text">
                <button class="btn" id="captcha-submit-btn">Submit &amp; Next</button>
            </div>
        </div>
        <div class="progress-track" id="gst-progress-track" style="display:none;"><div class="progress-fill" id="gst-progress-fill"></div></div>
        <div class="status-line" id="gst-status-line"></div>
        <div class="log-box" id="gst-log-box" style="display:none;"></div>
        <div class="excel-upload-row" id="gst-stop-row" style="display:none; justify-content:flex-end;">
            <button class="btn btn-danger" id="captcha-stop-btn">Stop</button>
        </div>
        <div class="download-row" id="gst-download-row"></div>
    `;

    document.getElementById("captcha-submit-btn").addEventListener("click", submitGstCaptcha);
    document.getElementById("captcha-input").addEventListener("keydown", e => { if (e.key === "Enter") submitGstCaptcha(); });
    document.getElementById("captcha-stop-btn").addEventListener("click", stopGstSession);

    gstSessionActive = false;
}

// Clears out whatever the previous GST session left behind (old log
// lines, an old "Download Report" link, a half-full progress bar) so
// starting a new single-GSTIN or Excel-batch run always begins from
// a clean screen instead of showing stale results mixed with new ones.
function resetGstCaptchaPanel() {
    const logBox = document.getElementById("gst-log-box");
    logBox.innerHTML = "";
    logBox.style.display = "none";

    document.getElementById("gst-download-row").innerHTML = "";
    document.getElementById("gst-progress-fill").style.width = "0%";
    document.getElementById("gst-progress-track").style.display = "none";
    document.getElementById("gst-status-line").textContent = "";
    document.getElementById("captcha-box").style.display = "none";
    document.getElementById("gst-stop-row").style.display = "none";

    gstSessionActive = false;
}

function gstLogLine(text, cls) {
    const logBox = document.getElementById("gst-log-box");
    if (!logBox) return;
    logBox.style.display = "block";
    const div = document.createElement("div");
    div.className = "log-line " + (cls || "info");
    div.textContent = text;
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
}

function onGstSessionUpdate(payload) {
    gstSessionActive = true;
    document.getElementById("gst-stop-row").style.display = "flex";

    if (payload.last_result) {
        const r = payload.last_result;
        gstLogLine(`${r.gst}: ${r.remarks}`, r.remarks === "OK" ? "ok" : "fail");
    }

    if (payload.status === "done") {
        finishGstSession(payload, "Completed");
        return;
    }

    if (payload.status === "retry_captcha") {
        gstLogLine(`Captcha didn't match, retrying ${payload.gst}`, "fail");
    }

    const total = payload.total || 0;

    if (total) {
        document.getElementById("gst-progress-track").style.display = "block";
        const percent = Math.round((payload.index / total) * 100);
        document.getElementById("gst-progress-fill").style.width = percent + "%";
    }

    document.getElementById("gst-status-line").textContent =
        `GSTIN ${payload.index + 1} / ${total}: ${payload.gst}`;

    document.getElementById("captcha-box").style.display = "block";
    document.getElementById("captcha-gst-label").textContent = payload.gst;
    document.getElementById("captcha-img").src = "/om/api/gst/captcha/image?t=" + Date.now();

    const captchaInput = document.getElementById("captcha-input");
    captchaInput.value = "";
    captchaInput.disabled = false;
    document.getElementById("captcha-submit-btn").disabled = false;
    captchaInput.focus();
}

async function submitGstCaptcha() {
    const input = document.getElementById("captcha-input");
    const btn = document.getElementById("captcha-submit-btn");
    const captcha = input.value.trim();

    if (!captcha) return;

    btn.disabled = true;
    input.disabled = true;

    try {
        const res = await fetch("/om/api/gst/captcha/submit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ captcha })
        });
        const payload = await res.json();

        if (!payload.success) {
            gstLogLine(payload.message || "Error submitting captcha", "fail");
            btn.disabled = false;
            input.disabled = false;
            return;
        }

        onGstSessionUpdate(payload);

    } catch (err) {
        gstLogLine("Network error: " + err.message, "fail");
        btn.disabled = false;
        input.disabled = false;
    }
}

async function stopGstSession() {
    if (!gstSessionActive) return;

    document.getElementById("captcha-stop-btn").disabled = true;

    try {
        const res = await fetch("/om/api/gst/captcha/stop", { method: "POST" });
        const payload = await res.json();
        finishGstSession(payload, "Stopped");
    } catch (err) {
        document.getElementById("gst-status-line").textContent = "Network error while stopping.";
    }
}

function finishGstSession(payload, label) {
    gstSessionActive = false;
    document.getElementById("captcha-box").style.display = "none";
    document.getElementById("gst-stop-row").style.display = "none";
    document.getElementById("gst-status-line").textContent =
        `${label} \u2014 ${payload.processed || 0}/${payload.total || 0} processed`;

    if (payload.output_filename) {
        document.getElementById("gst-download-row").innerHTML = `
            <a class="download-btn" href="/om/download/${encodeURIComponent(payload.output_filename)}">
                Download Report
            </a>
        `;
    }

    const manualBtn = document.getElementById("gst-manual-start-btn");
    if (manualBtn) manualBtn.disabled = false;

    const excelBtn = document.getElementById("gst-excel-start-btn");
    if (excelBtn) excelBtn.disabled = false;
}

showHome();
