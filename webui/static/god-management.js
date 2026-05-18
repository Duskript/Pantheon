(function () {
  'use strict';

  const POLL_INTERVAL = 15000;
  const KNOWN_MODELS = [
    'claude-opus-4-7',
    'claude-sonnet-4-6',
    'claude-haiku-4-5',
    'gpt-4o',
    'gpt-4o-mini',
    'gpt-4-turbo',
    'gemini-1.5-pro',
  ];

  function escHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }

  function statusInfo(god) {
    if (god.gateway_running)  return { cls: 'gm-dot--green',  label: 'Running' };
    if (/asleep|sleeping/i.test(god.gateway_state || ''))
                              return { cls: 'gm-dot--yellow', label: 'Asleep' };
    return { cls: 'gm-dot--red', label: god.is_active ? 'Stopped' : 'Inactive' };
  }

  function createPanel(container) {
    let gods    = [];
    let expanded = new Set();
    let loading  = true;
    let error    = null;
    let pollTimer = null;

    container.innerHTML = `
      <div class="gm-panel">
        <div class="gm-header">
          <h2 class="gm-title">Gods</h2>
          <button class="gm-refresh-btn" title="Refresh">&#x21BB;</button>
        </div>
        <div class="gm-grid"></div>
      </div>`;

    injectStyles();

    const grid       = container.querySelector('.gm-grid');
    const refreshBtn = container.querySelector('.gm-refresh-btn');

    refreshBtn.addEventListener('click', () => { refreshBtn.disabled = true; fetchGods().finally(() => { refreshBtn.disabled = false; }); });

    async function fetchGods() {
      try {
        const res = await fetch('/api/gods');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        gods  = data.gods || [];
        error = null;
      } catch (e) {
        error = e.message;
      } finally {
        loading = false;
        render();
      }
    }

    function render() {
      if (loading) {
        grid.innerHTML = '<p class="gm-message">Loading&#8230;</p>';
        return;
      }
      if (error) {
        grid.innerHTML = `<p class="gm-message gm-message--error">Unavailable: ${escHtml(error)}</p>`;
        return;
      }
      if (!gods.length) {
        grid.innerHTML = '<p class="gm-message">No gods configured.</p>';
        return;
      }

      const prev = grid.innerHTML;
      const next = gods.map(buildCard).join('');
      if (prev !== next) grid.innerHTML = next;

      grid.querySelectorAll('.gm-card').forEach(card => {
        const name = card.dataset.name;
        const god  = gods.find(g => g.name === name);
        if (!god) return;

        card.querySelector('.gm-card-header').addEventListener('click', () => toggleExpand(name));

        const startBtn    = card.querySelector('.gm-action-start');
        const stopBtn     = card.querySelector('.gm-action-stop');
        const modelSelect = card.querySelector('.gm-model-select');

        if (startBtn)    startBtn.addEventListener('click',    e => { e.stopPropagation(); godAction(name, 'start'); });
        if (stopBtn)     stopBtn.addEventListener('click',     e => { e.stopPropagation(); godAction(name, 'stop'); });
        if (modelSelect) modelSelect.addEventListener('change', e => { e.stopPropagation(); changeModel(name, e.target.value); });
      });
    }

    function buildCard(god) {
      const { cls, label } = statusInfo(god);
      const isOpen = expanded.has(god.name);
      const accent = escHtml(god.color || 'var(--accent)');

      return `<div class="gm-card${isOpen ? ' gm-card--open' : ''}" data-name="${escHtml(god.name)}">
        <div class="gm-card-header" style="border-left:3px solid ${accent}">
          <img class="gm-icon" src="/api/gods/${escHtml(god.name)}/icon" alt=""
            onerror="this.style.visibility='hidden'">
          <div class="gm-card-info">
            <div class="gm-card-name">${escHtml(god.display_name)}</div>
            ${god.domain ? `<span class="gm-domain">${escHtml(god.domain)}</span>` : ''}
          </div>
          <span class="gm-dot ${escHtml(cls)}" title="${escHtml(label)}"></span>
          <span class="gm-chevron">${isOpen ? '&#x25B4;' : '&#x25BE;'}</span>
        </div>
        <div class="gm-card-meta">
          <span>${escHtml(god.model || '—')}</span>
          <span class="gm-sep">·</span>
          <span>${escHtml(god.provider || '—')}</span>
        </div>
        ${isOpen ? buildDetails(god) : ''}
      </div>`;
    }

    function buildDetails(god) {
      const modelOpts = buildModelOptions(god.model);
      const running   = !!god.gateway_running;
      return `<div class="gm-details">
        <div class="gm-detail-row">
          <span class="gm-detail-label">Gateway state</span>
          <span class="gm-detail-value">${escHtml(god.gateway_state || '—')}</span>
        </div>
        <div class="gm-detail-row">
          <span class="gm-detail-label">Skills</span>
          <span class="gm-detail-value">${escHtml(god.skill_count ?? '—')}</span>
        </div>
        <div class="gm-detail-row">
          <span class="gm-detail-label">Status</span>
          <span class="gm-detail-value">${escHtml(running ? 'Running' : (god.gateway_state || 'Stopped'))}</span>
        </div>
        <div class="gm-detail-actions">
          <button class="gm-btn gm-action-start"${running ? ' disabled' : ''}>Start</button>
          <button class="gm-btn gm-btn--danger gm-action-stop"${!running ? ' disabled' : ''}>Stop</button>
        </div>
        <div class="gm-model-row">
          <span class="gm-detail-label">Model</span>
          <select class="gm-model-select">${modelOpts}</select>
        </div>
      </div>`;
    }

    function buildModelOptions(current) {
      const list = current && !KNOWN_MODELS.includes(current)
        ? [current, ...KNOWN_MODELS]
        : KNOWN_MODELS;
      return list.map(m =>
        `<option value="${escHtml(m)}"${m === current ? ' selected' : ''}>${escHtml(m)}</option>`
      ).join('');
    }

    function toggleExpand(name) {
      expanded.has(name) ? expanded.delete(name) : expanded.add(name);
      render();
    }

    async function godAction(name, action) {
      try {
        const res = await fetch(`/api/gods/${encodeURIComponent(name)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (e) {
        console.error(`[god-management] ${action} failed for ${name}:`, e);
      }
      fetchGods();
    }

    async function changeModel(name, model) {
      try {
        const res = await fetch(`/api/gods/${encodeURIComponent(name)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'set_model', model }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (e) {
        console.error(`[god-management] set_model failed for ${name}:`, e);
      }
      fetchGods();
    }

    fetchGods();
    pollTimer = setInterval(fetchGods, POLL_INTERVAL);

    return {
      destroy() {
        clearInterval(pollTimer);
        container.innerHTML = '';
      },
    };
  }

  // ---------- styles ----------

  let stylesInjected = false;
  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    const s = document.createElement('style');
    s.textContent = `
.gm-panel { color: var(--text-primary); font-family: inherit; }

.gm-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.gm-title  { margin: 0; font-size: 1.25rem; font-weight: 600; }

.gm-refresh-btn {
  background: var(--bg-tertiary); border: 1px solid var(--border);
  color: var(--text-secondary); border-radius: 6px; padding: 5px 11px;
  cursor: pointer; font-size: 1rem; line-height: 1; transition: background .15s, color .15s;
}
.gm-refresh-btn:hover:not(:disabled) { background: var(--bg-secondary); color: var(--text-primary); }
.gm-refresh-btn:disabled { opacity: .5; cursor: not-allowed; }

.gm-message { color: var(--text-muted); text-align: center; padding: 48px 0; margin: 0; }
.gm-message--error { color: var(--error); }

.gm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 12px;
}

.gm-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color .15s, box-shadow .15s;
}
.gm-card:hover   { border-color: var(--accent); box-shadow: 0 2px 14px rgba(0,0,0,.25); }
.gm-card--open   { border-color: var(--accent); }

.gm-card-header {
  display: flex; align-items: center; gap: 11px;
  padding: 13px 14px; cursor: pointer; user-select: none;
}
.gm-icon { width: 34px; height: 34px; border-radius: 7px; object-fit: cover; flex-shrink: 0; }
.gm-card-info { flex: 1; min-width: 0; }
.gm-card-name {
  font-weight: 600; font-size: .93rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.gm-domain {
  display: inline-block; margin-top: 3px;
  font-size: .72rem; color: var(--text-muted);
  background: var(--bg-tertiary); padding: 1px 6px; border-radius: 4px;
}

.gm-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.gm-dot--green  { background: var(--success); box-shadow: 0 0 6px var(--success); }
.gm-dot--yellow { background: var(--warning); box-shadow: 0 0 6px var(--warning); }
.gm-dot--red    { background: var(--error); }

.gm-chevron { color: var(--text-muted); font-size: .75rem; flex-shrink: 0; }

.gm-card-meta {
  display: flex; align-items: center; gap: 6px;
  padding: 0 14px 12px; font-size: .77rem; color: var(--text-muted);
}
.gm-sep { color: var(--border); }

.gm-details {
  border-top: 1px solid var(--border);
  background: var(--bg-tertiary);
  backdrop-filter: blur(6px);
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.gm-detail-row  { display: flex; justify-content: space-between; align-items: center; font-size: .81rem; }
.gm-detail-label { color: var(--text-muted); }
.gm-detail-value { color: var(--text-secondary); font-family: monospace; font-size: .78rem; }

.gm-detail-actions { display: flex; gap: 8px; }
.gm-btn {
  flex: 1; padding: 6px 0; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg-secondary);
  color: var(--text-primary); cursor: pointer; font-size: .81rem;
  transition: background .15s, border-color .15s, color .15s;
}
.gm-btn:hover:not(:disabled) { background: var(--accent); border-color: var(--accent); color: #fff; }
.gm-btn--danger:hover:not(:disabled) { background: var(--error); border-color: var(--error); }
.gm-btn:disabled { opacity: .38; cursor: not-allowed; }

.gm-model-row { display: flex; align-items: center; gap: 10px; }
.gm-model-select {
  flex: 1; background: var(--bg-secondary); border: 1px solid var(--border);
  color: var(--text-primary); border-radius: 6px; padding: 4px 8px;
  font-size: .79rem; cursor: pointer;
}

@media (max-width: 600px) { .gm-grid { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(s);
  }

  // ---------- public API ----------

  function mountGodManagement(container) {
    return createPanel(container);
  }

  function autoMount() {
    const el = document.getElementById('god-management-panel');
    if (el) mountGodManagement(el);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoMount);
  } else {
    autoMount();
  }

  window.mountGodManagement = mountGodManagement;
})();
