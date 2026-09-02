const D = {
  apiBase: 'http://127.0.0.1:5000', token: '', username: '', enabled: true, autoSend: false,
  searchDays: 365, matchLimit: 250, pollSeconds: 5, searchFolders: []
};

let currentSelectedFolders = [];

async function load() {
  const s = { ...D, ...await messenger.storage.local.get(D) };
  for (const k of Object.keys(D)) {
    if (k === 'searchFolders') continue;
    const e = document.getElementById(k);
    if (!e) continue;
    if (e.type === 'checkbox') e.checked = !!s[k]; else e.value = s[k] || '';
  }
  currentSelectedFolders = s.searchFolders || [];
  await refreshFolderList();
}

function flattenWithPath(folder, accountName, parentPath, out) {
  if (!folder) return out;
  const path = parentPath ? parentPath + ' / ' + folder.name : folder.name;
  out.push({ id: folder.id, name: path, accountName });
  for (const child of (folder.subFolders || [])) flattenWithPath(child, accountName, path, out);
  return out;
}

async function listAllFolders() {
  const accounts = await messenger.accounts.list(true);
  const out = [];
  for (const account of accounts) {
    flattenWithPath(account.rootFolder, account.name, '', out);
  }
  return out;
}

async function refreshFolderList() {
  const box = document.getElementById('folderBox');
  box.textContent = 'Loading folders...';
  try {
    const folders = await listAllFolders();
    if (!folders.length) { box.textContent = 'Koi folder nahi mila.'; return; }
    box.innerHTML = '';
    const selectedIds = new Set(currentSelectedFolders.map(f => f.id));
    for (const f of folders) {
      const div = document.createElement('div');
      div.className = 'folder-item';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.id = f.id;
      cb.dataset.name = f.name;
      cb.dataset.acc = f.accountName;
      cb.checked = selectedIds.has(f.id);
      const label = document.createElement('span');
      label.innerHTML = `${f.name} <span class="acc">(${f.accountName})</span>`;
      div.appendChild(cb);
      div.appendChild(label);
      box.appendChild(div);
    }
    updateSelectedCount();
    box.querySelectorAll('input[type=checkbox]').forEach(cb => cb.onchange = updateSelectedCount);
  } catch (e) {
    box.textContent = 'Folder list load nahi ho payi: ' + e;
  }
}

function updateSelectedCount() {
  const n = document.querySelectorAll('#folderBox input[type=checkbox]:checked').length;
  document.getElementById('selectedCount').textContent =
    n === 0 ? '0 folders selected — default "Sent folder auto-detect" chalega.' : `${n} folder(s) selected.`;
}

function collectSelectedFolders() {
  const out = [];
  document.querySelectorAll('#folderBox input[type=checkbox]:checked').forEach(cb => {
    out.push({ id: cb.dataset.id, name: cb.dataset.name, accountName: cb.dataset.acc });
  });
  return out;
}

async function save() {
  const data = {
    apiBase: document.getElementById('apiBase').value.trim().replace(/\/$/, ''),
    token: document.getElementById('token').value.trim(),
    username: document.getElementById('username').value.trim().toLowerCase(),
    enabled: document.getElementById('enabled').checked,
    autoSend: document.getElementById('autoSend').checked,
    searchDays: Number(document.getElementById('searchDays').value || 365),
    matchLimit: Number(document.getElementById('matchLimit').value || 250),
    searchFolders: collectSelectedFolders()
  };
  await messenger.storage.local.set(data);
  currentSelectedFolders = data.searchFolders;
  status('Saved. (' + data.searchFolders.length + ' search folder(s) configured)');
}

function status(x) { document.getElementById('status').textContent = x; }

document.getElementById('save').onclick = save;
document.getElementById('refreshFolders').onclick = refreshFolderList;
document.getElementById('test').onclick = async () => { await save(); const r = await messenger.runtime.sendMessage({ type: 'testConnection' }); status(JSON.stringify(r, null, 2)); };
document.getElementById('poll').onclick = async () => { await save(); await messenger.runtime.sendMessage({ type: 'pollNow' }); status('Poll triggered. Check web app status/history.'); };

load();
