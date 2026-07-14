// Pantheon Companion — Popup Script
import { getConfig, setConfig, clearConfig, ensureHostPermission } from '../config.js';

// ── State ──
let config = null;
let pollTimer = null;
let selectedGod = null;
let godSessions = {}; // { sessionId: { god, timestamp } }
let allSessions = []; // from API
let gods = [];

// ── DOM refs ──
const $ = (id) => document.getElementById(id);

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
  config = await getConfig();

  // Check if we're in setup mode (query param or no config)
  const isSetup = new URLSearchParams(location.search).get('setup') === '1' || !config;

  if (isSetup) {
    showView('setup');
    setupHandlers();
  } else {
    // Ensure we have host permission
    const ok = await ensureHostPermission(config.url);
    if (!ok) {
      showView('setup');
      $('setup-error').textContent = 'Host permission required. Please grant access to your Pantheon URL.';
      $('setup-error').hidden = false;
      setupHandlers();
      return;
    }
    showView('main');

    // Load god→session mapping
    try {
      const result = await chrome.storage.local.get('pantheon_god_sessions');
      godSessions = result.pantheon_god_sessions || {};
    } catch {}

    await loadMain();
  }
});

// ── View switching ──
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.hidden = true);
  const view = document.getElementById(`view-${name}`);
  if (view) view.hidden = false;
}

// ── Setup handlers ──
function setupHandlers() {
  const urlInput = $('setup-url');
  const connectBtn = $('setup-connect');
  const errorEl = $('setup-error');

  // Pre-fill if there's a saved URL
  if (config?.url) urlInput.value = config.url;

  connectBtn.addEventListener('click', async () => {
    let url = urlInput.value.trim();
    if (!url) {
      errorEl.textContent = 'Please enter a Pantheon URL';
      errorEl.hidden = false;
      return;
    }

    // Normalize: add protocol if missing
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }

    connectBtn.disabled = true;
    connectBtn.textContent = 'Connecting...';
    errorEl.hidden = true;

    try {
      // Test the connection
      const testUrl = `${url.replace(/\/+$/, '')}/api/gods`;
      const res = await fetch(testUrl, { mode: 'cors', credentials: 'include' });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const data = await res.json();
      if (!data.gods) {
        throw new Error('Not a Pantheon instance');
      }

      // Request host permission
      const granted = await ensureHostPermission(url);
      if (!granted) {
        throw new Error('Host permission denied');
      }

      // Save config
      await setConfig(url, '');
      config = await getConfig();

      // Refresh the god submenu in the background
      chrome.runtime.sendMessage({ action: 'refreshGodSubmenu' }).catch(() => {});

      // Switch to main view
      showView('main');
      await loadMain();

    } catch (e) {
      errorEl.textContent = `Connection failed: ${e.message}`;
      errorEl.hidden = false;
      connectBtn.disabled = false;
      connectBtn.textContent = 'Connect';
    }
  });

  // Allow Enter key
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') connectBtn.click();
  });
}

// ── Main View ──
async function loadMain() {
  await Promise.all([
    loadGodRoster(),
    loadSessions(),
    loadHealth(),
  ]);

  startPolling();
  setupMainHandlers();
}

// ── God Roster ──
async function loadGodRoster() {
  const list = $('god-list');
  const count = $('god-count');

  try {
    const res = await apiFetch('/api/gods');
    const data = await res.json();
    gods = data.gods || [];

    count.textContent = gods.length;
    list.innerHTML = '';

    if (gods.length === 0) {
      list.innerHTML = '<div class="loading">No gods registered</div>';
      return;
    }

    gods.forEach(god => {
      const item = document.createElement('div');
      item.className = 'god-item';
      if (selectedGod === god.name) item.classList.add('selected');

      const iconVal = typeof god.icon === 'string' && (god.icon.startsWith('http') || god.icon.startsWith('/api/'))
        ? `<img src="${config.url}${god.icon}" alt="" style="width:24px;height:24px;border-radius:50%">`
        : (god.icon || '🧑‍💻');

      const state = god.gateway_state || 'sleeping';

      item.innerHTML = `
        <div class="god-icon">
          ${iconVal}
          <span class="god-dot ${state}"></span>
        </div>
        <div class="god-info">
          <div class="god-name">${god.display_name || god.name}</div>
          <div class="god-domain">${god.domain || ''}</div>
          <div class="god-model">${god.model || ''}</div>
        </div>
        <span class="god-arrow">→</span>
      `;

      item.addEventListener('click', () => {
        // Toggle selection
        if (selectedGod === god.name) {
          selectedGod = null;
        } else {
          selectedGod = god.name;
        }
        // Re-render with filter
        renderGodRoster();
        filterSessionsByGod(selectedGod);

        // If no god was previously selected, also open side panel
        if (selectedGod) {
          chrome.runtime.sendMessage({
            action: 'switchGod',
            godName: god.name,
          });
        }
      });

      list.appendChild(item);
    });
  } catch (e) {
    list.innerHTML = `<div class="loading" style="color:var(--error)">Failed to load: ${e.message}</div>`;
  }
}

function renderGodRoster() {
  const items = $('god-list').querySelectorAll('.god-item');
  items.forEach(item => {
    const nameEl = item.querySelector('.god-name');
    if (!nameEl) return;
    const name = nameEl.textContent;
    item.classList.toggle('selected', selectedGod === name);
  });
}

// ── Sessions ──
async function loadSessions() {
  try {
    const res = await apiFetch('/api/sessions');
    const data = await res.json();
    allSessions = data.sessions || [];
  } catch (e) {
    console.error('[Pantheon] Failed to load sessions:', e);
    allSessions = [];
  }
  filterSessionsByGod(selectedGod);
}

function filterSessionsByGod(godName) {
  const list = $('session-list');
  const count = $('sessions-count');

  let filtered;
  if (godName) {
    // Filter by locally-tracked god→session mapping
    const trackedIds = new Set(
      Object.entries(godSessions)
        .filter(([, v]) => v.god === godName)
        .map(([k]) => k)
    );
    filtered = allSessions.filter(s => trackedIds.has(s.session_id));
    // Also show untracked sessions that might belong to this god (fuzzy match by model)
    // Better to just show "no tracked sessions" + option to see all
    $('sessions-title').textContent = `${godName}'s Sessions`;
  } else {
    filtered = allSessions.slice(0, 15);
    $('sessions-title').textContent = 'Recent Sessions';
  }

  count.textContent = filtered.length;

  if (filtered.length === 0) {
    if (godName) {
      list.innerHTML = `<div class="session-empty">No sessions tracked for ${godName} yet.<br><a href="#" id="show-all-sessions" style="color:var(--accent);text-decoration:none;font-size:11px;">Show all sessions →</a></div>`;
      list.querySelector('#show-all-sessions')?.addEventListener('click', (e) => {
        e.preventDefault();
        selectedGod = null;
        renderGodRoster();
        filterSessionsByGod(null);
      });
    } else {
      list.innerHTML = '<div class="session-empty">No sessions yet. Start chatting!</div>';
    }
    return;
  }

  list.innerHTML = '';
  filtered.forEach(s => {
    const item = document.createElement('div');
    item.className = 'session-item';

    const godName = godSessions[s.session_id]?.god || '';
    const title = s.title || 'Untitled';
    const date = s.last_message_at
      ? new Date(s.last_message_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      : '';
    const model = s.model ? s.model.split('/').pop()?.split('-').slice(0, 2).join('-') || s.model : '';
    const icon = s.active_stream_id ? '🔴' : '💬';

    item.innerHTML = `
      <span class="session-icon">${icon}</span>
      <div class="session-info">
        <div class="session-title">${title}</div>
        <div class="session-meta">${model ? model + ' · ' : ''}${date || 'just now'}${s.message_count ? ' · ' + s.message_count + ' msgs' : ''}</div>
      </div>
      ${godName ? `<span class="session-god-tag">${godName}</span>` : ''}
    `;

    item.addEventListener('click', () => {
      // Open side panel with this session
      chrome.runtime.sendMessage({
        action: 'openSession',
        sessionId: s.session_id,
        god: godName || undefined,
      });
      // Also store pending action so side panel picks it up
      chrome.storage.local.set({
        pantheon_pending_action: {
          type: 'resume',
          session_id: s.session_id,
          god: godName || undefined,
          timestamp: Date.now(),
        },
      });
      chrome.sidePanel.open();
    });

    list.appendChild(item);
  });
}

// ── Health ──
async function loadHealth() {
  const dot = $('health-dot');
  const gateway = $('health-gateway');
  const godsEl = $('health-gods');

  try {
    const res = await apiFetch('/api/health/agent');
    const data = await res.json();

    const status = data.alive ? 'ok' : 'error';
    dot.dataset.status = status;
    gateway.textContent = data.alive ? 'Online' : 'Offline';
    godsEl.textContent = data.gods_online || '—';

  } catch (e) {
    dot.dataset.status = 'error';
    gateway.textContent = 'Error';
    godsEl.textContent = '—';
  }
}

// ── Main handlers ──
function setupMainHandlers() {
  $('open-pantheon').addEventListener('click', () => {
    chrome.tabs.create({ url: config.url });
    window.close();
  });

  $('open-sidepanel').addEventListener('click', () => {
    chrome.sidePanel.open();
    window.close();
  });

  $('btn-settings').addEventListener('click', () => {
    showView('setup');
    $('setup-url').value = config.url;
    setupHandlers();
  });

  $('idea-send').addEventListener('click', captureIdea);
  $('idea-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') captureIdea();
  });

  $('btn-reconnect').addEventListener('click', async () => {
    $('btn-reconnect').textContent = '⏳ Testing...';
    await Promise.all([loadHealth(), loadGodRoster(), loadSessions()]);
    $('btn-reconnect').textContent = '🔄 Reconnect';
  });

  $('btn-forget').addEventListener('click', async () => {
    if (confirm('Disconnect from Pantheon? Your config will be cleared.')) {
      await clearConfig();
      showView('setup');
      $('setup-url').value = '';
      setupHandlers();
    }
  });
}

async function captureIdea() {
  const input = $('idea-input');
  const text = input.value.trim();
  if (!text) return;

  input.disabled = true;
  try {
    await apiPost('/api/ideas/add', { text });
    input.value = '';
    showToast('Idea captured! ✨');
  } catch (e) {
    showToast(`Failed: ${e.message}`);
  }
  input.disabled = false;
  input.focus();
}

// ── Polling ──
function startPolling() {
  // Update sessions periodically
  setInterval(() => {
    loadSessions();
  }, 15000);
}

// ── Toast ──
function showToast(msg) {
  const el = document.createElement('div');
  el.textContent = msg;
  Object.assign(el.style, {
    position: 'fixed',
    bottom: '48px',
    left: '50%',
    transform: 'translateX(-50%)',
    background: 'var(--accent)',
    color: '#000',
    padding: '6px 14px',
    borderRadius: '8px',
    fontSize: '11px',
    fontWeight: '600',
    zIndex: '100',
    opacity: '0',
    transition: 'opacity 0.2s',
  });
  document.body.appendChild(el);
  requestAnimationFrame(() => el.style.opacity = '1');
  setTimeout(() => {
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 200);
  }, 2000);
}

// ── API helpers ──
function apiUrl(path) {
  const base = (config?.url || '').replace(/\/+$/, '');
  return `${base}${path}`;
}

async function apiFetch(path, options = {}) {
  const url = apiUrl(path);
  const headers = { ...options.headers };
  if (config?.token) headers['Authorization'] = `Bearer ${config.token}`;

  const res = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
    mode: 'cors',
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${text.slice(0, 100)}`);
  }
  return res;
}

async function apiPost(path, body) {
  return apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
