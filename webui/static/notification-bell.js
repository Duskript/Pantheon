/* ── Pantheon Notification Bell ──
 * Standalone component: fixed top-right bell with polling, badge, dropdown.
 */
(function () {
  'use strict';

  const POLL_INTERVAL = 30000;
  const BODY_PREVIEW = 120;

  let state = { notifications: [], open: false, expanded: new Set() };
  let pollTimer = null;
  let els = {};

  function api(path, opts) {
    return fetch(new URL('api' + path, document.baseURI || location.href).href,
      Object.assign({ credentials: 'include', headers: { 'Content-Type': 'application/json' } }, opts))
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .catch(() => null);
  }

  async function poll() {
    const data = await api('/notifications/poll');
    if (!data) return;
    const prev = state.notifications.length;
    const prevIds = new Set(state.notifications.map(n => n.id));
    state.notifications = data.notifications || [];
    const hasNew = state.notifications.some(n => !n.dismissed && !prevIds.has(n.id));
    if (hasNew && prev > 0) pulseBadge();
    render();
  }

  function unreadCount() {
    return state.notifications.filter(n => !n.dismissed).length;
  }

  function pulseBadge() {
    els.badge && els.badge.classList.remove('nb-pulse');
    requestAnimationFrame(() => els.badge && els.badge.classList.add('nb-pulse'));
  }

  async function dismiss(id) {
    await api('/notifications/dismiss', { method: 'POST', body: JSON.stringify({ id }) });
    const n = state.notifications.find(n => n.id === id);
    if (n) n.dismissed = true;
    render();
  }

  async function clearAll() {
    await api('/notifications/clear', { method: 'POST' });
    state.notifications.forEach(n => n.dismissed = true);
    render();
  }

  function toggleExpand(id) {
    state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
    render();
  }

  function timeAgo(ts) {
    const diff = (Date.now() - new Date(ts)) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function typeColor(type) {
    return type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--error)' : 'var(--warning)';
  }

  function renderNotification(n) {
    const expanded = state.expanded.has(n.id);
    const body = n.body || '';
    const preview = body.length > BODY_PREVIEW ? body.slice(0, BODY_PREVIEW) + '…' : body;
    const div = document.createElement('div');
    div.className = 'nb-item' + (n.dismissed ? ' nb-dismissed' : '');
    div.dataset.id = n.id;
    div.innerHTML = `
      <div class="nb-item-header">
        <span class="nb-icon" style="color:${typeColor(n.type)}">${n.icon || (n.type === 'success' ? '✓' : n.type === 'error' ? '✕' : '⚠')}</span>
        <span class="nb-title">${esc(n.title || '')}</span>
        <span class="nb-time">${timeAgo(n.timestamp)}</span>
        <button class="nb-dismiss" title="Dismiss" data-dismiss="${esc(n.id)}">✕</button>
      </div>
      <div class="nb-body">${esc(expanded ? body : preview)}</div>
      ${body.length > BODY_PREVIEW ? `<button class="nb-expand" data-expand="${esc(n.id)}">${expanded ? 'Show less' : 'Show more'}</button>` : ''}
    `;
    return div;
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function render() {
    const count = unreadCount();
    if (els.badge) {
      els.badge.textContent = count;
      els.badge.style.display = count > 0 ? 'flex' : 'none';
    }
    if (!state.open || !els.panel) return;

    els.panel.innerHTML = '';
    const list = state.notifications;
    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'nb-empty';
      empty.textContent = 'No notifications';
      els.panel.appendChild(empty);
      return;
    }
    list.forEach(n => els.panel.appendChild(renderNotification(n)));

    const footer = document.createElement('div');
    footer.className = 'nb-footer';
    footer.innerHTML = '<button class="nb-clear-all">Clear all</button>';
    els.panel.appendChild(footer);

    els.panel.querySelectorAll('[data-dismiss]').forEach(btn =>
      btn.addEventListener('click', e => { e.stopPropagation(); dismiss(btn.dataset.dismiss); }));
    els.panel.querySelectorAll('[data-expand]').forEach(btn =>
      btn.addEventListener('click', e => { e.stopPropagation(); toggleExpand(btn.dataset.expand); }));
    els.panel.querySelector('.nb-clear-all')?.addEventListener('click', clearAll);
  }

  function togglePanel() {
    state.open = !state.open;
    els.panel.style.display = state.open ? 'flex' : 'none';
    if (state.open) render();
  }

  function injectStyles() {
    const style = document.createElement('style');
    style.textContent = `
      #nb-root { position:fixed; top:52px; right:16px; z-index:800; font-family:inherit; }
      #nb-bell-btn { background:var(--bg-secondary,#1e1e2e); border:1px solid var(--border,#333); border-radius:8px;
        color:var(--text-primary,#cdd6f4); cursor:pointer; font-size:18px; width:38px; height:38px;
        display:flex; align-items:center; justify-content:center; position:relative; transition:background .15s; }
      #nb-bell-btn:hover { background:var(--bg-primary,#181825); }
      #nb-badge { position:absolute; top:-5px; right:-5px; background:var(--error,#f38ba8); color:#fff;
        border-radius:50%; min-width:18px; height:18px; font-size:11px; font-weight:700;
        display:flex; align-items:center; justify-content:center; padding:0 3px; pointer-events:none; }
      @keyframes nb-scale-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.45)} }
      #nb-badge.nb-pulse { animation:nb-scale-pulse .4s ease; }
      #nb-panel { position:absolute; top:calc(100% + 8px); right:0; width:340px; max-height:460px;
        background:var(--bg-secondary,#1e1e2e); border:1px solid var(--border,#333); border-radius:10px;
        box-shadow:0 8px 32px rgba(0,0,0,.45); flex-direction:column; overflow:hidden; display:none; }
      #nb-panel-header { padding:10px 14px; font-size:13px; font-weight:600; color:var(--text-secondary,#a6adc8);
        border-bottom:1px solid var(--border,#333); flex-shrink:0; }
      .nb-list { overflow-y:auto; flex:1; }
      .nb-item { padding:10px 14px; border-bottom:1px solid var(--border,#333); cursor:default;
        transition:background .12s; }
      .nb-item:hover { background:var(--bg-primary,#181825); }
      .nb-item.nb-dismissed { opacity:.45; }
      .nb-item-header { display:flex; align-items:center; gap:7px; }
      .nb-icon { font-size:14px; flex-shrink:0; }
      .nb-title { flex:1; font-size:13px; font-weight:600; color:var(--text-primary,#cdd6f4); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .nb-time { font-size:11px; color:var(--text-muted,#6c7086); flex-shrink:0; }
      .nb-dismiss { background:none; border:none; color:var(--text-muted,#6c7086); cursor:pointer; font-size:12px;
        padding:2px 4px; border-radius:4px; flex-shrink:0; line-height:1; }
      .nb-dismiss:hover { color:var(--error,#f38ba8); background:rgba(243,139,168,.12); }
      .nb-body { font-size:12px; color:var(--text-secondary,#a6adc8); margin-top:5px; line-height:1.5;
        white-space:pre-wrap; word-break:break-word; }
      .nb-expand { background:none; border:none; color:var(--accent,#89b4fa); font-size:11px; cursor:pointer;
        padding:3px 0 0; display:block; }
      .nb-expand:hover { text-decoration:underline; }
      .nb-empty { padding:24px 14px; text-align:center; color:var(--text-muted,#6c7086); font-size:13px; }
      .nb-footer { padding:8px 14px; border-top:1px solid var(--border,#333); flex-shrink:0; }
      .nb-clear-all { background:none; border:1px solid var(--border,#333); border-radius:6px;
        color:var(--text-secondary,#a6adc8); font-size:12px; cursor:pointer; padding:5px 12px; width:100%; }
      .nb-clear-all:hover { border-color:var(--accent,#89b4fa); color:var(--accent,#89b4fa); }
    `;
    document.head.appendChild(style);
  }

  function mount() {
    injectStyles();

    const root = document.createElement('div');
    root.id = 'nb-root';

    const btn = document.createElement('button');
    btn.id = 'nb-bell-btn';
    btn.title = 'Notifications';
    btn.innerHTML = '🔔<span id="nb-badge" style="display:none">0</span>';

    const panel = document.createElement('div');
    panel.id = 'nb-panel';
    const header = document.createElement('div');
    header.id = 'nb-panel-header';
    header.textContent = 'Notifications';
    const list = document.createElement('div');
    list.className = 'nb-list';
    panel.appendChild(header);
    panel.appendChild(list);

    root.appendChild(btn);
    root.appendChild(panel);
    document.body.appendChild(root);

    els = { badge: root.querySelector('#nb-badge'), panel: list, root };

    btn.addEventListener('click', e => { e.stopPropagation(); togglePanel(); });
    document.addEventListener('click', e => {
      if (state.open && !root.contains(e.target)) { state.open = false; panel.style.display = 'none'; }
    });

    poll();
    pollTimer = setInterval(poll, POLL_INTERVAL);
  }

  window.toggleNotificationBell = () => togglePanel();

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
