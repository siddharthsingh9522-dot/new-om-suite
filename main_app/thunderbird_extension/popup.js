function timeAgo(ts) {
  if (!ts) return "never";
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
}

async function render() {
  const s = await messenger.storage.local.get({
    apiBase: 'http://127.0.0.1:5000', username: '', enabled: false, autoSend: false
  });
  const state = await messenger.runtime.sendMessage({ type: 'getState' }) || {};

  document.getElementById('state').textContent =
    `Web app: ${s.apiBase}\nUser: ${s.username || '(not set)'}\nBridge: ${s.enabled ? 'ON' : 'OFF'}\nAuto-send: ${s.autoSend ? 'ON' : 'OFF'}`;

  const dot = document.getElementById('dot');
  const errBox = document.getElementById('err');
  if (!s.enabled) {
    dot.className = 'dot off';
  } else if (state.connected === true) {
    dot.className = 'dot ok';
  } else if (state.connected === false) {
    dot.className = 'dot bad';
  } else {
    dot.className = 'dot off';
  }

  if (state.lastError) {
    errBox.style.display = 'block';
    errBox.textContent = state.lastError;
  } else {
    errBox.style.display = 'none';
  }

  const bits = [];
  bits.push(`Last check: ${timeAgo(state.lastPollAt)}`);
  if (state.lastOkAt) bits.push(`last success: ${timeAgo(state.lastOkAt)}`);
  if (state.lastCycleSummary) bits.push(state.lastCycleSummary);
  document.getElementById('meta').textContent = bits.join(' · ');
}

document.getElementById('poll').onclick = async () => {
  document.getElementById('state').textContent = 'Syncing...';
  await messenger.runtime.sendMessage({ type: 'pollNow' });
  await render();
};
document.getElementById('options').onclick = () => messenger.runtime.openOptionsPage();

render();
