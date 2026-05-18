/* ── Pantheon Ideas Panel ──
 * Reads from /api/ideas (project-ideas.md) and shows sections.
 */
(function() {
  'use strict';

  function openIdeasPanel() {
    var existing = document.getElementById('ideas-overlay');
    if (existing) { existing.remove(); return; }

    var overlay = document.createElement('div');
    overlay.id = 'ideas-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center';
    overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

    var panel = document.createElement('div');
    panel.style.cssText = 'background:var(--bg-primary,#0A0908);border:1px solid var(--border,#3B4A50);border-radius:12px;width:600px;max-width:95vw;max-height:80vh;display:flex;flex-direction:column;overflow:hidden';

    panel.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border)">' +
      '<h2 style="margin:0;font-size:1.1rem;color:var(--text-primary)">💡 Ideas</h2>' +
      '<button id="ideas-close" style="background:none;border:none;color:var(--text-muted);font-size:1.2rem;cursor:pointer">✕</button>' +
      '</div>' +
      '<div id="ideas-body" style="flex:1;overflow:auto;padding:16px 20px;color:var(--text-muted);text-align:center">Loading...</div>';

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    document.getElementById('ideas-close').onclick = function() { overlay.remove(); };

    fetch('/api/ideas')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var body = document.getElementById('ideas-body');
        if (!body) return;
        var sections = data.sections || [];
        if (!sections.length) {
          body.innerHTML = '<div style="padding:40px">No ideas recorded yet. Add to ~/pantheon/project-ideas.md</div>';
          return;
        }
        body.innerHTML = sections.map(function(s) {
          var title = s.title || 'Untitled';
          var items = s.items || [];
          return '<div style="margin-bottom:16px">' +
            '<h3 style="color:var(--text-primary);font-size:14px;margin-bottom:8px;border-bottom:1px solid var(--border);padding-bottom:6px">' + title + '</h3>' +
            items.map(function(item) {
              return '<div style="font-size:12px;color:var(--text-secondary);padding:4px 0;line-height:1.5">• ' + (item.content || item.text || item || '') + '</div>';
            }).join('') +
            '</div>';
        }).join('');
      })
      .catch(function() {
        var body = document.getElementById('ideas-body');
        if (body) body.innerHTML = '<div style="color:var(--error);padding:20px">Failed to load ideas.</div>';
      });
  }

  window.openIdeasPanel = openIdeasPanel;
})();
