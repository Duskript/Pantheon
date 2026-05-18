/* ── Boon Manager — Promote, View, Pin, Export ──
 * Watches DOM for artifacts and adds "Promote to Boon" buttons.
 * Also provides a full boon management panel.
 */
(function() {
  'use strict';

  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Boon Management Panel ──
  function openBoonManager() {
    var existing = document.getElementById('boon-manager-overlay');
    if (existing) { existing.remove(); return; }

    var overlay = document.createElement('div');
    overlay.id = 'boon-manager-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:9999;display:flex;align-items:center;justify-content:center';
    overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

    var panel = document.createElement('div');
    panel.style.cssText = 'background:var(--bg-primary,#0a0908);border:1px solid var(--border,#3B4A50);border-radius:12px;width:650px;max-width:95vw;max-height:80vh;display:flex;flex-direction:column;overflow:hidden';

    panel.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border,#3B4A50)">' +
      '<h2 style="margin:0;font-size:1.1rem;color:var(--text-primary,#EAE0D5)">📌 Boons</h2>' +
      '<button id="bm-close" style="background:none;border:none;color:var(--text-muted);font-size:1.2rem;cursor:pointer">✕</button>' +
      '</div>' +
      '<div id="bm-body" style="flex:1;overflow:auto;padding:16px 20px;color:var(--text-muted);text-align:center">Loading boons...</div>' +
      '<div style="padding:12px 20px;border-top:1px solid var(--border,#3B4A50);display:flex;gap:8px;justify-content:flex-end">' +
      '<button id="bm-refresh" style="background:var(--bg-secondary,#11100E);color:var(--text-secondary);border:1px solid var(--border);border-radius:6px;padding:6px 14px;cursor:pointer;font-size:12px">Refresh</button>' +
      '<button id="bm-export" style="background:var(--accent,#7c6fe0);color:white;border:none;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:12px;font-weight:600">Export All</button>' +
      '</div>';

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    document.getElementById('bm-close').onclick = function() { overlay.remove(); };
    document.getElementById('bm-refresh').onclick = loadBoons;
    document.getElementById('bm-export').onclick = exportBoons;

    var boonsCache = [];

    function loadBoons() {
      var body = document.getElementById('bm-body');
      if (!body) return;
      body.innerHTML = 'Loading...';
      fetch('/api/boons/list')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          boonsCache = data.boons || data || [];
          if (!boonsCache.length) {
            body.innerHTML = '<div style="padding:40px">No boons yet. Promote an artifact to create one.</div>';
            return;
          }
          body.innerHTML = boonsCache.map(function(b, i) {
            var type = b.type || 'text';
            var icon = type === 'html' || type === 'svg' ? '🌐' : type === 'csv' ? '📊' : type === 'code' ? '💻' : '📄';
            var name = esc(b.fileName || b.title || 'Boon ' + i);
            var snippet = esc((b.content || '').slice(0, 80));
            var pinned = b.pinned ? ' 📌' : '';
            return '<div style="background:var(--bg-secondary,#11100E);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px;display:flex;gap:10px;align-items:flex-start">' +
              '<span style="font-size:20px">' + icon + '</span>' +
              '<div style="flex:1;min-width:0">' +
              '<div style="font-weight:600;color:var(--text-primary);font-size:13px;margin-bottom:4px">' + name + pinned + '</div>' +
              '<div style="font-size:11px;color:var(--text-muted)">' + type + ' · ' + snippet + '</div>' +
              '</div>' +
              '<div style="display:flex;gap:4px;flex-shrink:0">' +
              '<button data-action="view" data-idx="' + i + '" style="background:var(--bg-tertiary);color:var(--text-secondary);border:1px solid var(--border);border-radius:4px;padding:3px 8px;cursor:pointer;font-size:10px">View</button>' +
              '<button data-action="pin" data-idx="' + i + '" style="background:var(--bg-tertiary);color:var(--text-secondary);border:1px solid var(--border);border-radius:4px;padding:3px 8px;cursor:pointer;font-size:10px">' + (b.pinned ? 'Unpin' : 'Pin') + '</button>' +
              '<button data-action="delete" data-idx="' + i + '" style="background:var(--bg-tertiary);color:var(--error,#F87171);border:1px solid var(--border);border-radius:4px;padding:3px 8px;cursor:pointer;font-size:10px">✕</button>' +
              '</div></div>';
          }).join('');

          body.querySelectorAll('button[data-action]').forEach(function(btn) {
            btn.onclick = function() {
              var idx = parseInt(btn.dataset.idx);
              var boon = boonsCache[idx];
              if (!boon) return;
              if (btn.dataset.action === 'view') viewBoon(boon);
              if (btn.dataset.action === 'pin') togglePin(boon.boon_id);
              if (btn.dataset.action === 'delete') deleteBoon(boon.boon_id);
            };
          });
        })
        .catch(function() {
          body.innerHTML = '<div style="color:var(--error);padding:20px">Failed to load boons.</div>';
        });
    }

    function viewBoon(boon) {
      var w = window.open('', '_blank', 'width=800,height=600');
      if (!w) return;
      if (boon.type === 'html' || boon.type === 'svg') {
        w.document.write(boon.content);
      } else {
        w.document.write('<pre style="padding:20px;font-family:monospace;white-space:pre-wrap">' + esc(boon.content || '') + '</pre>');
      }
    }

    function togglePin(id) {
      fetch('/api/boons/toggle-pin', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boon_id: id }) })
        .then(loadBoons).catch(loadBoons);
    }

    function deleteBoon(id) {
      if (!confirm('Delete this boon?')) return;
      fetch('/api/boons/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boon_id: id }) })
        .then(loadBoons).catch(loadBoons);
    }

    function exportBoons() {
      var blob = new Blob([JSON.stringify(boonsCache, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'pantheon-boons-' + new Date().toISOString().slice(0, 10) + '.json';
      a.click();
    }

    loadBoons();
  }

  // ── Promote button on artifacts ──
  function promoteToBoon(artifact) {
    fetch('/api/boons/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: artifact.content || '',
        type: artifact.type || 'text',
        source_message_id: artifact.messageId || '',
        metadata: JSON.stringify({
          fileName: artifact.fileName || '',
          filePath: artifact.filePath || '',
          promoted_at: new Date().toISOString()
        })
      })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      showToast(data.ok || data.boon_id ? '📌 Promoted to Boons' : 'Failed: ' + (data.error || 'unknown'), data.ok);
    })
    .catch(function(err) {
      showToast('Boon save failed: ' + err.message, false);
    });
  }

  function showToast(text, ok) {
    var toast = document.createElement('div');
    toast.textContent = text;
    Object.assign(toast.style, {
      position: 'fixed', bottom: '24px', right: '24px', zIndex: '99999',
      background: ok ? 'rgba(68,216,138,0.95)' : 'rgba(255,107,107,0.95)',
      color: '#0a0a14', padding: '10px 20px', borderRadius: '10px',
      fontSize: '13px', fontWeight: '600', fontFamily: 'system-ui, sans-serif',
      boxShadow: '0 4px 20px rgba(0,0,0,0.4)', transition: 'opacity 0.3s'
    });
    document.body.appendChild(toast);
    setTimeout(function() { toast.style.opacity = '0'; setTimeout(function() { toast.remove(); }, 300); }, 2500);
  }

  // ── Add buttons to artifact cards ──
  function addPromoteButtons() {
    var containers = document.querySelectorAll('[class*="artifact"]');
    containers.forEach(function(el) {
      if (el.dataset.boonButtonAdded) return;
      el.dataset.boonButtonAdded = '1';

      var btn = document.createElement('button');
      btn.textContent = '📌 Promote';
      Object.assign(btn.style, {
        position: 'absolute', top: '4px', right: '4px', zIndex: '100',
        background: 'rgba(69,136,224,0.15)', color: '#4588e0',
        border: '1px solid rgba(69,136,224,0.35)', borderRadius: '6px',
        padding: '3px 8px', fontSize: '10px', fontWeight: '600',
        cursor: 'pointer', fontFamily: 'system-ui, sans-serif',
        backdropFilter: 'blur(8px)'
      });
      btn.onclick = function(e) {
        e.stopPropagation();
        var dataEl = el.closest('[data-artifact]') || el;
        promoteToBoon({
          type: dataEl.dataset.type || 'html',
          content: dataEl.dataset.content || '',
          fileName: dataEl.dataset.filename || '',
          filePath: dataEl.dataset.filepath || ''
        });
      };
      el.style.position = el.style.position || 'relative';
      el.appendChild(btn);
    });
  }

  // ── Add Boons button to bottom bar ──
  function addBoonsButton() {
    if (document.getElementById('boons-nav-btn')) return;
    var btn = document.createElement('button');
    btn.id = 'boons-nav-btn';
    btn.textContent = '📌 Boons';
    btn.title = 'View and manage boons';
    btn.style.cssText = 'background:var(--bg-tertiary);color:var(--text-secondary);border:1px solid var(--border);border-radius:6px;padding:4px 10px;cursor:pointer;font-size:11px;font-weight:600;position:fixed;bottom:12px;left:68px;z-index:500';
    btn.onclick = openBoonManager;
    document.body.appendChild(btn);
  }

  // ── DOM watcher ──
  var observer = new MutationObserver(function(mutations) {
    for (var i = 0; i < mutations.length; i++) {
      if (mutations[i].addedNodes.length) addPromoteButtons();
    }
  });

  function start() {
    addPromoteButtons();
    addBoonsButton();
    observer.observe(document.getElementById('root') || document.body, { childList: true, subtree: true });
  }

  window.openBoonsManager = openBoonManager;

  if (document.readyState === 'loading') {
    setTimeout(start, 2000);
  } else {
    start();
  }
})();
