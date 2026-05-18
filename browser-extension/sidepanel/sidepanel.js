// Pantheon Companion — Side Panel (Toolbar + Chat)
import { getConfig, clearConfig, ensureHostPermission } from '../config.js';

// ── State ──
let config = null;
let gods = [];
let activeGod = null;
let sessionId = null;
let streaming = false;
let selectedGod = null;
let godSessions = {};
let allSessions = [];
let pollTimer = null;

// ── DOM refs ──
const $ = (id) => document.getElementById(id);

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
  config = await getConfig();
  if (!config || !config.url) {
    showView('chat'); // show message about setup
    addMessage('system', 'Not connected. Click the extension icon to set up.');
    disableInput(true);
    return;
  }

  // Load god→session mapping
  try {
    const result = await chrome.storage.local.get('pantheon_god_sessions');
    godSessions = result.pantheon_god_sessions || {};
  } catch {}

  // Start in dashboard view (unless we have a pending action)
  showView('dashboard');
  await loadDashboard();
  setupDashboardHandlers();
  setupChatHandlers();
  await loadGods();

  // Check for pending action — if present, switch to chat
  await handlePendingAction();

  startPolling();
});

// ── View Switching ──
function showView(name) {
  $('view-dashboard').hidden = name !== 'dashboard';
  $('view-chat').hidden = name !== 'chat';
}

// ── Polling ──
function startPolling() {
  setInterval(() => { if (!$('view-dashboard').hidden) loadSessions(); }, 15000);
}

// ═══════════════════════════════════════════════════════════════════
// DASHBOARD (Toolbar)
// ═══════════════════════════════════════════════════════════════════

async function loadDashboard() {
  await Promise.all([
    loadGodRoster(),
    loadSessions(),
    loadHealth(),
  ]);
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
        switchToChat(god.name);
      });

      list.appendChild(item);
    });
  } catch (e) {
    list.innerHTML = `<div class="loading" style="color:var(--error)">Failed to load: ${e.message}</div>`;
  }
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
  renderSessions();
}

function renderSessions() {
  const list = $('session-list');
  const count = $('sessions-count');
  const filtered = allSessions.slice(0, 15);

  count.textContent = allSessions.length;

  if (filtered.length === 0) {
    list.innerHTML = '<div class="session-empty">No sessions yet. Start chatting!</div>';
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
      // Store pending action to resume this session
      chrome.storage.local.set({
        pantheon_pending_action: {
          type: 'resume',
          session_id: s.session_id,
          god: godName || undefined,
          timestamp: Date.now(),
        },
      });
      if (godName) {
        switchToChat(godName, s.session_id);
      } else {
        showView('chat');
        handlePendingAction();
      }
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

// ── Dashboard Handlers ──
function setupDashboardHandlers() {
  $('open-pantheon-dash').addEventListener('click', () => {
    chrome.tabs.create({ url: config.url });
  });

  $('open-chat').addEventListener('click', () => {
    showView('chat');
  });

  $('dash-settings').addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('popup/popup.html?setup=1') });
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
      chrome.tabs.create({ url: chrome.runtime.getURL('popup/popup.html?setup=1') });
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

// ═══════════════════════════════════════════════════════════════════
// SWITCH TO CHAT
// ═══════════════════════════════════════════════════════════════════

function switchToChat(godName, existingSessionId) {
  showView('chat');
  activeGod = godName;
  sessionId = existingSessionId || null;

  // Select god in dropdown
  const select = $('chat-god-select');
  for (const opt of select.options) {
    if (opt.value === godName) {
      opt.selected = true;
      break;
    }
  }

  $('chat-input').placeholder = `Message ${activeGod}...`;
  disableInput(false);
  $('chat-input').focus();
}

// ═══════════════════════════════════════════════════════════════════
// PENDING ACTION ROUTER
// ═══════════════════════════════════════════════════════════════════

async function handlePendingAction() {
  try {
    const result = await chrome.storage.local.get('pantheon_pending_action');
    const pending = result.pantheon_pending_action;
    if (!pending) return;

    await chrome.storage.local.remove('pantheon_pending_action');

    // Stale after 60 seconds
    if (Date.now() - pending.timestamp > 60000) return;

    // Switch to chat view
    showView('chat');
    await loadGodsIfNeeded();

    // Remove empty state
    const empty = $('chat-messages').querySelector('.chat-empty');
    if (empty) empty.remove();

    switch (pending.type) {
      case 'ask':
        await handleAskAction(pending);
        break;
      case 'summarize':
        await handleSummarizeAction(pending);
        break;
      case 'workflow':
        await handleWorkflowAction(pending);
        break;
      case 'improve':
        await handleImproveAction(pending);
        break;
      case 'sendto':
        await handleSendToAction(pending);
        break;
      case 'resume':
        await handleResumeAction(pending);
        break;
      default:
        console.warn('[Pantheon] Unknown pending action type:', pending.type);
    }
  } catch (e) {
    console.error('[Pantheon] Pending action failed:', e);
  }
}

async function loadGodsIfNeeded() {
  if (gods.length > 0 && $('chat-god-select')?.options?.length > 0) return;
  await loadGods();
}

async function handleAskAction(pending) {
  const contextMsg = pending.selection.slice(0, 2000);
  addMessage('user', `About this: "${contextMsg}"`);
  if (pending.pageTitle) {
    addMessage('system', `From: ${pending.pageTitle}`);
  }
  await sendToGod(contextMsg);
}

async function handleSummarizeAction(pending) {
  const text = pending.text.slice(0, 5000);
  const prompt = [
    `Please summarize the following page concisively.`,
    `Highlight key takeaways, main arguments, and notable details.`,
    ``,
    `Title: ${pending.pageTitle || 'Untitled'}`,
    `URL: ${pending.pageUrl || ''}`,
    ``,
    `Content:`,
    text,
  ].join('\n');

  addMessage('system', `📄 **Summarizing:** ${pending.pageTitle || 'this page'}`);
  if (pending.pageUrl) {
    addMessage('system', `Source: ${pending.pageUrl}`);
  }
  await sendToGod(prompt);
}

async function handleImproveAction(pending) {
  pending.workflow = 'rewrite';
  await handleWorkflowAction(pending);
}

async function handleWorkflowAction(pending) {
  const workflow = pending.workflow || 'rewrite';
  const selection = (pending.selection || '').slice(0, 3000);

  const prompts = {
    rewrite: [
      'Rewrite the following text to be clearer and more polished while preserving meaning and intent.',
      'Keep it concise and natural.',
      '',
      'Text:',
      selection,
    ].join('\n'),
    explain: [
      'Explain the following text in plain language.',
      'If it contains jargon, decode it. Keep it practical.',
      '',
      'Text:',
      selection,
    ].join('\n'),
    action_items: [
      'Extract concrete action items from the following text.',
      'Return a short checklist with owner suggestions if inferable.',
      '',
      'Text:',
      selection,
    ].join('\n'),
  };

  const labels = {
    rewrite: '✏️ **Rewrite**',
    explain: '🧠 **Explain Clearly**',
    action_items: '✅ **Action Items**',
  };

  addMessage('system', labels[workflow] || '⚡ **Workflow**');
  if (pending.pageTitle) addMessage('system', `From: ${pending.pageTitle}`);
  if (selection) addMessage('user', selection.slice(0, 500));

  await sendToGod(prompts[workflow] || prompts.rewrite);
}

async function handleSendToAction(pending) {
  const selection = pending.selection.slice(0, 2000);
  const godName = pending.god;

  if (godName) {
    activeGod = godName;
    const select = $('chat-god-select');
    for (const opt of select.options) {
      if (opt.value === godName) {
        opt.selected = true;
        break;
      }
    }
    sessionId = null;
    $('chat-input').placeholder = `Message ${activeGod}...`;
  }

  addMessage('system', `📨 **Sent to ${godName || activeGod || 'Pantheon'}**`);
  if (pending.pageTitle) {
    addMessage('system', `From: ${pending.pageTitle}`);
  }
  addMessage('user', selection.slice(0, 500));
  await sendToGod(selection);
}

async function handleResumeAction(pending) {
  if (!pending.session_id) {
    addMessage('system', 'Session not found.');
    return;
  }

  sessionId = pending.session_id;

  try {
    const res = await fetch(
      `${config.url}/api/session?session_id=${encodeURIComponent(sessionId)}&messages=1&msg_limit=30`,
      { credentials: 'include' }
    );
    const data = await res.json();

    if (pending.god) {
      activeGod = pending.god;
      const select = $('chat-god-select');
      for (const opt of select.options) {
        if (opt.value === pending.god) {
          opt.selected = true;
          break;
        }
      }
      $('chat-input').placeholder = `Message ${activeGod}...`;
    }

    addMessage('system', `📋 **Resuming session**`);

    const msgs = data.messages || [];
    if (msgs.length > 0) {
      for (const m of msgs) {
        const role = m.role === 'assistant' ? 'assistant' : 'user';
        const content = m.content || '';
        if (typeof content === 'string' && content.trim()) {
          addMessage(role, content.slice(0, 2000));
        }
      }
      addMessage('system', `📝 **${msgs.length} messages loaded** — keep chatting!`);
    } else {
      addMessage('system', 'This session has no messages yet.');
    }
  } catch (e) {
    addMessage('system', `Failed to load session: ${e.message}`);
    sessionId = null;
  }
}

// ═══════════════════════════════════════════════════════════════════
// CHAT VIEW
// ═══════════════════════════════════════════════════════════════════

async function loadGods() {
  try {
    const res = await fetch(`${config.url}/api/gods`, { credentials: 'include' });
    const data = await res.json();
    gods = data.gods || [];

    const select = $('chat-god-select');
    select.innerHTML = '';
    gods.forEach((g) => {
      const opt = document.createElement('option');
      opt.value = g.name;
      opt.textContent = g.display_name || g.name;
      select.appendChild(opt);
    });

    const hasGods = gods.length > 0;
    disableInput(!hasGods);
    if (!hasGods) {
      addMessage('system', 'No gods available.');
    } else {
      if (!activeGod && gods[0]) activeGod = gods[0].name;
      $('chat-input').placeholder = `Message ${activeGod || 'Pantheon'}...`;
    }
  } catch (e) {
    addMessage('system', `Failed to connect: ${e.message}`);
  }
}

function setupChatHandlers() {
  $('chat-back').addEventListener('click', () => {
    showView('dashboard');
    loadDashboard();
  });

  $('chat-god-select').addEventListener('change', () => {
    activeGod = $('chat-god-select').value;
    sessionId = null;
    $('chat-input').placeholder = `Message ${activeGod}...`;
  });

  $('chat-send').addEventListener('click', () => {
    const text = $('chat-input').value.trim();
    if (text) sendToGod(text);
  });

  $('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const text = $('chat-input').value.trim();
      if (text) sendToGod(text);
    }
  });

  $('chat-clear').addEventListener('click', () => {
    $('chat-messages').innerHTML = `
      <div class="chat-empty">
        <p>Ask a god anything...</p>
        <p class="chat-empty-hint">Select a god above and start chatting.</p>
      </div>
    `;
    sessionId = null;
  });
}

function disableInput(disabled) {
  $('chat-input').disabled = disabled;
  $('chat-send').disabled = disabled;
}

async function sendToGod(text) {
  if (!text || !config || streaming) return;

  const input = $('chat-input');
  input.value = '';
  disableInput(true);

  // Remove empty state
  const empty = $('chat-messages').querySelector('.chat-empty');
  if (empty) empty.remove();

  addMessage('user', text);

  // Show typing indicator
  const typing = document.createElement('div');
  typing.className = 'typing';
  typing.id = 'typing-indicator';
  $('chat-messages').appendChild(typing);
  scrollToBottom();

  streaming = true;

  try {
    // Step 1: Create session if needed
    if (!sessionId) {
      const godName = activeGod || gods[0]?.name || 'default';
      const newSess = await apiPost('/api/session/new', {
        profile: godName,
      });
      sessionId = newSess.session?.session_id;
      if (!sessionId) throw new Error('Failed to create session');

      // Record god→session mapping
      await recordGodSession(godName, sessionId);
    }

    // Step 2: Send message via synchronous chat API
    const data = await apiPost('/api/chat', {
      session_id: sessionId,
      message: text,
    });

    // Remove typing indicator
    const typingEl = document.getElementById('typing-indicator');
    if (typingEl) typingEl.remove();

    const answer = data.answer || data.response || '';
    if (answer) {
      addMessage('assistant', answer);
    } else if (data.error) {
      addMessage('system', `Error: ${data.error}`);
    }
  } catch (e) {
    const typingEl = document.getElementById('typing-indicator');
    if (typingEl) typingEl.remove();
    addMessage('system', `Error: ${e.message}`);
  }

  streaming = false;
  disableInput(false);
  $('chat-input').focus();
  scrollToBottom();
}

async function recordGodSession(godName, sid) {
  try {
    const result = await chrome.storage.local.get('pantheon_god_sessions');
    const map = result.pantheon_god_sessions || {};
    map[sid] = { god: godName, timestamp: Date.now() };
    await chrome.storage.local.set({ pantheon_god_sessions: map });
  } catch (e) {
    console.error('[Pantheon] Failed to record god session:', e);
  }
}

// ── UI Helpers ──
function addMessage(role, content) {
  const empty = $('chat-messages').querySelector('.chat-empty');
  if (empty) empty.remove();

  const el = document.createElement('div');
  el.className = `msg ${role}`;

  if (role === 'assistant' || role === 'system') {
    el.innerHTML = content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  } else {
    el.textContent = content;
  }

  $('chat-messages').appendChild(el);
  scrollToBottom();
}

function scrollToBottom() {
  const container = $('chat-messages');
  container.scrollTop = container.scrollHeight;
}

// ═══════════════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════════════

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
    throw new Error(`API error ${res.status}: ${text.slice(0, 200)}`);
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
