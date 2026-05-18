(() => {
  const CSS = `
    .pp-overlay { position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);z-index:9999;display:flex;align-items:center;justify-content:center; }
    .pp-panel { background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;width:600px;max-width:95vw;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.6); }
    .pp-header { display:flex;align-items:center;justify-content:space-between;padding:20px 24px;border-bottom:1px solid var(--border); }
    .pp-title { font-size:18px;font-weight:600;color:var(--text-primary);letter-spacing:.02em; }
    .pp-actions { display:flex;gap:8px; }
    .pp-btn { background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary);border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px;transition:all .15s; }
    .pp-btn:hover { border-color:var(--accent);color:var(--text-primary); }
    .pp-close { background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:20px;line-height:1;padding:4px 8px;border-radius:6px;transition:color .15s; }
    .pp-close:hover { color:var(--text-primary); }
    .pp-list { overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px; }
    .pp-card { background:var(--bg-tertiary);border:1px solid var(--border);border-radius:10px;padding:16px;display:flex;align-items:center;gap:14px;cursor:pointer;transition:all .15s; }
    .pp-card:hover { border-color:var(--accent);background:color-mix(in srgb,var(--bg-tertiary) 90%,var(--accent) 10%); }
    .pp-card.active { border-color:var(--accent);box-shadow:0 0 0 1px var(--accent); }
    .pp-icon { width:44px;height:44px;border-radius:10px;object-fit:cover;flex-shrink:0;background:var(--bg-secondary); }
    .pp-icon-fallback { width:44px;height:44px;border-radius:10px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:22px; }
    .pp-info { flex:1;min-width:0; }
    .pp-name { font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:4px; }
    .pp-meta { display:flex;align-items:center;gap:8px;flex-wrap:wrap; }
    .pp-tag { font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--border);color:var(--text-muted); }
    .pp-badge-active { font-size:11px;padding:2px 8px;border-radius:20px;background:color-mix(in srgb,var(--success) 15%,transparent);color:var(--success);border:1px solid color-mix(in srgb,var(--success) 40%,transparent); }
    .pp-badge-default { font-size:11px;padding:2px 8px;border-radius:20px;background:color-mix(in srgb,var(--accent) 15%,transparent);color:#a78bfa;border:1px solid color-mix(in srgb,var(--accent) 40%,transparent); }
    .pp-stats { display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0; }
    .pp-model { font-size:12px;color:var(--text-secondary);text-align:right; }
    .pp-skills { font-size:11px;color:var(--text-muted); }
    .pp-empty { text-align:center;padding:40px;color:var(--text-muted); }
    .pp-error { color:#f87171;font-size:13px;padding:12px 16px; }
  `;

  function injectStyles() {
    if (document.getElementById('pp-styles')) return;
    const s = document.createElement('style');
    s.id = 'pp-styles';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  async function fetchProfiles() {
    const r = await fetch('/api/profiles');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    return d.profiles || [];
  }

  async function switchProfile(name) {
    const r = await fetch(`/api/profile/enter?name=${encodeURIComponent(name)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    location.reload();
  }

  function renderCard(p) {
    const card = document.createElement('div');
    card.className = 'pp-card' + (p.is_active ? ' active' : '');
    card.title = p.path || '';

    const god = p.god || {};
    let iconEl;
    if (god.icon) {
      iconEl = document.createElement('img');
      iconEl.className = 'pp-icon';
      iconEl.src = `/api/gods/${encodeURIComponent(p.name)}/icon`;
      iconEl.alt = god.display_name || p.name;
      iconEl.onerror = () => { iconEl.replaceWith(fallback()); };
    } else {
      iconEl = fallback();
    }
    function fallback() {
      const d = document.createElement('div');
      d.className = 'pp-icon-fallback';
      d.style.background = god.color ? god.color + '22' : 'var(--bg-secondary)';
      d.style.border = `1px solid ${god.color || 'var(--border)'}`;
      d.textContent = god.icon || '?';
      return d;
    }

    const info = document.createElement('div');
    info.className = 'pp-info';

    const name = document.createElement('div');
    name.className = 'pp-name';
    name.textContent = god.display_name || p.name;

    const meta = document.createElement('div');
    meta.className = 'pp-meta';

    if (god.domain) {
      const tag = document.createElement('span');
      tag.className = 'pp-tag';
      tag.textContent = god.domain;
      if (god.color) { tag.style.borderColor = god.color + '66'; tag.style.color = god.color; }
      meta.appendChild(tag);
    }
    if (p.is_active) { const b = document.createElement('span'); b.className = 'pp-badge-active'; b.textContent = 'active'; meta.appendChild(b); }
    if (p.is_default) { const b = document.createElement('span'); b.className = 'pp-badge-default'; b.textContent = 'default'; meta.appendChild(b); }

    info.appendChild(name);
    info.appendChild(meta);

    const stats = document.createElement('div');
    stats.className = 'pp-stats';
    if (p.model || p.provider) {
      const m = document.createElement('div');
      m.className = 'pp-model';
      m.textContent = [p.provider, p.model].filter(Boolean).join(' · ');
      stats.appendChild(m);
    }
    if (p.skill_count != null) {
      const sk = document.createElement('div');
      sk.className = 'pp-skills';
      sk.textContent = `${p.skill_count} skill${p.skill_count !== 1 ? 's' : ''}`;
      stats.appendChild(sk);
    }

    card.appendChild(iconEl);
    card.appendChild(info);
    card.appendChild(stats);

    card.addEventListener('click', () => {
      if (!p.is_active) switchProfile(p.name).catch(e => alert('Failed: ' + e.message));
    });
    return card;
  }

  function mountProfilesPanel(container) {
    injectStyles();

    const overlay = document.createElement('div');
    overlay.className = 'pp-overlay';

    const panel = document.createElement('div');
    panel.className = 'pp-panel';

    const header = document.createElement('div');
    header.className = 'pp-header';
    const title = document.createElement('div');
    title.className = 'pp-title';
    title.textContent = 'Profiles';
    const actions = document.createElement('div');
    actions.className = 'pp-actions';
    const refresh = document.createElement('button');
    refresh.className = 'pp-btn';
    refresh.textContent = '↻ Refresh';
    const close = document.createElement('button');
    close.className = 'pp-close';
    close.innerHTML = '&times;';
    actions.appendChild(refresh);
    actions.appendChild(close);
    header.appendChild(title);
    header.appendChild(actions);

    const list = document.createElement('div');
    list.className = 'pp-list';

    panel.appendChild(header);
    panel.appendChild(list);
    overlay.appendChild(panel);
    container.appendChild(overlay);

    const load = async () => {
      list.innerHTML = '';
      try {
        const profiles = await fetchProfiles();
        if (!profiles.length) {
          list.innerHTML = '<div class="pp-empty">No profiles found.</div>';
        } else {
          profiles.forEach(p => list.appendChild(renderCard(p)));
        }
      } catch (e) {
        list.innerHTML = `<div class="pp-error">Error loading profiles: ${e.message}</div>`;
      }
    };

    const destroy = () => overlay.remove();
    close.addEventListener('click', destroy);
    overlay.addEventListener('click', e => { if (e.target === overlay) destroy(); });
    refresh.addEventListener('click', load);

    const onKey = e => { if (e.key === 'Escape') { destroy(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);

    load();
    return { destroy };
  }

  window.mountProfilesPanel = mountProfilesPanel;

  const auto = document.getElementById('profiles-panel');
  if (auto) mountProfilesPanel(auto);
})();
