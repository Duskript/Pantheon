/* ── Pantheon Boons Panel ──
 * Right-side slide-in panel for the Hermes UI.
 * Injects a 📦 button into the header toolbar, opens a glassmorphic
 * boons manager that lists/view/pins/deletes boons.
 */
(function() {
  'use strict';

  var boonsCache = [];
  var panelOpen = false;
  var currentView = 'list'; // 'list' | 'detail'
  var currentBoon = null;

  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Panel DOM ──

  function createPanel() {
    var existing = document.getElementById('boons-right-panel');
    if (existing) return existing;

    var panel = document.createElement('div');
    panel.id = 'boons-right-panel';
    panel.style.cssText = [
      'position:fixed;top:0;right:0;width:380px;max-width:92vw;height:100vh;',
      'z-index:9000;background:var(--bg-primary,#0a0908);',
      'border-left:1px solid var(--border,#3B4A50);',
      'box-shadow:-8px 0 32px rgba(0,0,0,0.5);',
      'display:flex;flex-direction:column;',
      'transform:translateX(100%);transition:transform 0.25s ease;',
      'font-family:system-ui,-apple-system,sans-serif;'
    ].join('');
    panel.innerHTML = [
      '<div style="display:flex;align-items:center;justify-content:space-between;',
      'padding:14px 18px;border-bottom:1px solid var(--border,#3B4A50);flex-shrink:0">',
        '<h2 style="margin:0;font-size:1rem;font-weight:600;color:var(--text-primary,#EAE0D5)">📌 Boons</h2>',
        '<button id="boons-panel-close" style="background:none;border:none;color:var(--text-muted);font-size:1.1rem;cursor:pointer;padding:4px 8px;border-radius:6px">✕</button>',
      '</div>',
      '<div id="boons-panel-body" style="flex:1;overflow:auto;padding:14px 18px"></div>',
      '<div id="boons-panel-footer" style="padding:10px 18px;border-top:1px solid var(--border,#3B4A50);display:flex;gap:8px;flex-shrink:0">',
        '<button id="boons-panel-refresh" style="background:var(--bg-secondary,#11100E);color:var(--text-secondary);border:1px solid var(--border);border-radius:6px;padding:6px 14px;cursor:pointer;font-size:12px">↻ Refresh</button>',
        '<div style="flex:1"></div>',
        '<button id="boons-panel-export" style="background:var(--accent,#7c6fe0);color:white;border:none;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:12px;font-weight:600">Export All</button>',
      '</div>'
    ].join('\n');

    document.body.appendChild(panel);

    document.getElementById('boons-panel-close').onclick = closePanel;
    document.getElementById('boons-panel-refresh').onclick = loadBoons;
    document.getElementById('boons-panel-export').onclick = exportBoons;

    // Close on Escape
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && panelOpen) closePanel();
    });

    return panel;
  }

  function openPanel() {
    var panel = createPanel();
    panel.style.transform = 'translateX(0)';
    panelOpen = true;
    currentView = 'list';
    currentBoon = null;
    loadBoons();
  }

  function closePanel() {
    var panel = document.getElementById('boons-right-panel');
    if (panel) panel.style.transform = 'translateX(100%)';
    panelOpen = false;
  }

  function togglePanel() {
    if (panelOpen) closePanel();
    else openPanel();
  }

  // ── Data ──

  function loadBoons() {
    var body = document.getElementById('boons-panel-body');
    if (!body) return;
    body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading boons...</div>';

    fetch('/api/boons/list')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        boonsCache = data.boons || data || [];
        renderList();
      })
      .catch(function(err) {
        body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--error,#F87171)">Failed to load: ' + esc(err.message) + '</div>';
      });
  }

  function renderList() {
    var body = document.getElementById('boons-panel-body');
    if (!body) return;
    currentView = 'list';
    currentBoon = null;

    if (!boonsCache.length) {
      body.innerHTML = [
        '<div style="text-align:center;padding:40px;color:var(--text-muted)">',
          '<div style="font-size:48px;margin-bottom:12px">📜</div>',
          '<div style="font-size:14px;font-weight:600;margin-bottom:6px">No boons yet</div>',
          '<div style="font-size:12px">Click 📜 on an assistant message to promote it to a boon.</div>',
        '</div>'
      ].join('\n');
      return;
    }

    body.innerHTML = boonsCache.map(function(b, i) {
      var type = b.type || 'text';
      var icon = type === 'html' || type === 'svg' ? '🌐' : type === 'csv' ? '📊' : type === 'code' ? '💻' : '📄';
      var title = esc(b.title || b.fileName || 'Boon ' + i);
      var snippet = esc((b.body || b.content || '').slice(0, 100));
      var pinned = b.pinned ? ' 📌' : '';
      var date = b.timestamp ? new Date(b.timestamp).toLocaleDateString() : '';

      return [
        '<div style="background:var(--bg-secondary,#11100E);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px;cursor:pointer" data-action="view" data-idx="' + i + '">',
          '<div style="display:flex;gap:10px;align-items:flex-start">',
            '<span style="font-size:22px;flex-shrink:0">' + icon + '</span>',
            '<div style="flex:1;min-width:0">',
              '<div style="font-weight:600;color:var(--text-primary);font-size:13px;margin-bottom:4px">' + title + pinned + '</div>',
              '<div style="font-size:11px;color:var(--text-muted)">' + type + (date ? ' · ' + date : '') + '</div>',
              '<div style="font-size:11px;color:var(--text-muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + snippet + '</div>',
            '</div>',
            '<div style="display:flex;gap:4px;flex-shrink:0;align-self:center" onclick="event.stopPropagation()">',
              '<button data-action="pin" data-idx="' + i + '" style="background:var(--bg-tertiary);color:var(--text-secondary);border:1px solid var(--border);border-radius:4px;padding:3px 8px;cursor:pointer;font-size:10px">' + (b.pinned ? '📌' : 'Pin') + '</button>',
              '<button data-action="delete" data-idx="' + i + '" style="background:var(--bg-tertiary);color:var(--error,#F87171);border:1px solid var(--border);border-radius:4px;padding:3px 8px;cursor:pointer;font-size:10px">✕</button>',
            '</div>',
          '</div>',
        '</div>'
      ].join('\n');
    }).join('\n');

    // Wire up clicks
    body.querySelectorAll('[data-action]').forEach(function(el) {
      el.onclick = function(e) {
        e.stopPropagation();
        var idx = parseInt(el.dataset.idx);
        var boon = boonsCache[idx];
        if (!boon) return;
        if (el.dataset.action === 'view') viewBoon(idx);
        if (el.dataset.action === 'pin') togglePin(boon.boon_id);
        if (el.dataset.action === 'delete') deleteBoon(boon.boon_id);
      };
    });
  }

  // ── View ──

  function viewBoon(idx) {
    var boon = boonsCache[idx];
    if (!boon) return;
    currentBoon = boon;
    currentView = 'detail';

    var body = document.getElementById('boons-panel-body');
    if (!body) return;

    var type = boon.type || 'text';
    var title = esc(boon.title || boon.fileName || 'Untitled');
    var content = boon.body || boon.content || '';

    var typeColor = { html: '#e67e22', svg: '#e67e22', csv: '#3498db', code: '#2ecc71', markdown: '#9b59b6', text: '#95a5a6' };
    var color = typeColor[type] || '#95a5a6';

    var contentHtml = '';
    if (type === 'html' || type === 'svg') {
      contentHtml = '<iframe srcdoc="' + content.replace(/&/g,'&amp;').replace(/"/g,'&quot;') + '" style="width:100%;height:100%;border:none;background:white;border-radius:6px" sandbox="allow-scripts"></iframe>';
    } else if (type === 'code') {
      contentHtml = '<pre style="margin:0;padding:12px;background:var(--bg-tertiary,#1a1a2e);border-radius:6px;font-family:Monaco,Menlo,monospace;font-size:12px;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;overflow:auto;max-height:100%">' + esc(content) + '</pre>';
    } else {
      contentHtml = '<pre style="margin:0;padding:12px;background:var(--bg-tertiary,#1a1a2e);border-radius:6px;font-family:system-ui,sans-serif;font-size:13px;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;overflow:auto;max-height:100%">' + esc(content) + '</pre>';
    }

    body.innerHTML = [
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">',
        '<button onclick="window._boonsPanelRenderList()" style="background:var(--bg-secondary,#11100E);color:var(--text-secondary);border:1px solid var(--border);border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">← Back</button>',
        '<span style="font-size:11px;background:' + color + '20;color:' + color + ';padding:2px 8px;border-radius:4px;font-weight:600">' + esc(type) + '</span>',
        '<div style="flex:1;font-weight:600;color:var(--text-primary);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + title + '</div>',
      '</div>',
      '<div style="flex:1;overflow:auto;border:1px solid var(--border);border-radius:8px;min-height:300px">',
        contentHtml,
      '</div>'
    ].join('\n');
  }

  // Expose for inline onclick
  window._boonsPanelRenderList = renderList;

  // ── Actions ──

  function togglePin(id) {
    fetch('/api/boons/toggle-pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boon_id: id })
    }).then(loadBoons).catch(loadBoons);
  }

  function deleteBoon(id) {
    if (!confirm('Delete this boon?')) return;
    fetch('/api/boons/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boon_id: id })
    }).then(loadBoons).catch(loadBoons);
  }

  function exportBoons() {
    var blob = new Blob([JSON.stringify(boonsCache, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'pantheon-boons-' + new Date().toISOString().slice(0, 10) + '.json';
    a.click();
  }

  // ── Header button injection ──

  function injectHeaderButton() {
    if (document.getElementById('boons-header-btn')) return;

    // Find the toolbar-pill in the Hermes UI header
    var toolbar = document.querySelector('.toolbar-pill');
    if (!toolbar) return;

    var btn = document.createElement('button');
    btn.id = 'boons-header-btn';
    btn.className = 'header-btn';
    btn.title = 'Boons';
    btn.innerHTML = '📦';
    btn.style.cssText = 'background:none;border:1px solid transparent;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:16px;color:var(--text-secondary);display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;transition:all 0.2s';
    btn.onmouseenter = function() { btn.style.background = 'var(--bg-tertiary)'; };
    btn.onmouseleave = function() { if (!panelOpen) btn.style.background = 'none'; };
    btn.onclick = function() {
      togglePanel();
      btn.style.background = panelOpen ? 'var(--bg-tertiary)' : 'none';
    };

    // Insert before the settings button (last child) or at end
    var settingsBtn = toolbar.querySelector('[title="Settings"]') || toolbar.lastElementChild;
    if (settingsBtn) {
      toolbar.insertBefore(btn, settingsBtn);
    } else {
      toolbar.appendChild(btn);
    }
  }

  // ── Startup ──

  // Poll for toolbar (React renders asynchronously)
  var pollCount = 0;
  var pollInterval = setInterval(function() {
    injectHeaderButton();
    pollCount++;
    if (document.getElementById('boons-header-btn') || pollCount > 30) {
      clearInterval(pollInterval);
    }
  }, 500);

  // Also try immediately after DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(injectHeaderButton, 1500);
    });
  } else {
    setTimeout(injectHeaderButton, 1500);
  }

  // Expose for sidebar-extras onclick
  window._boonsPanelToggle = togglePanel;
  window._boonsPanelOpen = function() { if (!panelOpen) openPanel(); };

})();
