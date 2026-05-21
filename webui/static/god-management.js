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
    let exportState = new Map();

    container.innerHTML = `
      <div class="gm-panel">
        <div class="gm-header">
          <button class="gm-summon-btn" title="Summon a god from the Pantheon-Summons repo">✨ Summon God</button>
          <h2 class="gm-title">Gods</h2>
          <button class="gm-refresh-btn" title="Refresh">&#x21BB;</button>
        </div>
        <div class="gm-grid"></div>
      </div>`;

    injectStyles();

    const grid       = container.querySelector('.gm-grid');
    const refreshBtn = container.querySelector('.gm-refresh-btn');
    const summonBtn  = container.querySelector('.gm-summon-btn');

    refreshBtn.addEventListener('click', () => { refreshBtn.disabled = true; fetchGods().finally(() => { refreshBtn.disabled = false; }); });
    summonBtn.addEventListener('click', () => openSummonDrawer());

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
        grid.innerHTML = '<p class="gm-message">Loading&hellip;</p>';
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

        const exportBtn = card.querySelector('.gm-export-btn');
        if (exportBtn) exportBtn.addEventListener('click', e => { e.stopPropagation(); openExportDrawer(god); });

        const exileBtn = card.querySelector('.gm-exile-btn');
        if (exileBtn) exileBtn.addEventListener('click', e => { e.stopPropagation(); exileGod(god.name); });
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
          <span>${escHtml(god.model || '\u2014')}</span>
          <span class="gm-sep">·</span>
          <span>${escHtml(god.provider || '\u2014')}</span>
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
          <span class="gm-detail-value">${escHtml(god.gateway_state || '\u2014')}</span>
        </div>
        <div class="gm-detail-row">
          <span class="gm-detail-label">Skills</span>
          <span class="gm-detail-value">${escHtml(god.skill_count ?? '\u2014')}</span>
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
        <button class="gm-export-btn gm-btn">📦 Export</button>
        <div class="gm-exile-row">
          <button class="gm-exile-btn" data-name="${escHtml(god.name)}">🗑️ Exile</button>
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

    // ── Exile God ──

    async function exileGod(name) {
      if (!confirm(`Are you sure you want to exile ${name}?\n\nThis will permanently delete the god's profile and all associated data. This cannot be undone.`)) {
        return;
      }
      try {
        const res = await fetch(`/api/gods/${encodeURIComponent(name)}/exile`, { method: 'POST' });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
          alert(`Exile failed: ${err.error || 'Unknown error'}`);
          return;
        }
        const data = await res.json();
        alert(data.message || `${name} has been exiled.`);
      } catch (e) {
        alert(`Exile failed: ${e.message}`);
      }
      fetchGods();
    }

    // ── Summon Drawer ──

    function parseDescription(soulMd) {
      if (!soulMd) return '';
      const fm = soulMd.match(/^---\n([\s\S]*?)\n---/);
      if (fm) {
        const desc = fm[1].match(/description:\s*['"]?(.+?)['"]?$/m);
        if (desc) return desc[1].trim();
      }
      const body = soulMd.replace(/^---[\s\S]*?---\n*/, '').trim();
      const first = body.split('\n').find(l => l.trim().length > 0);
      return first ? first.trim().slice(0, 120) : '';
    }

    function openSummonDrawer() {
      const existing = document.getElementById('gm-summon-overlay');
      if (existing) existing.remove();

      const overlay = document.createElement('div');
      overlay.id = 'gm-summon-overlay';
      overlay.className = 'gm-summon-overlay';
      overlay.innerHTML = `
        <div class="gm-summon-panel">
          <div class="gm-summon-header">
            <h2>✨ Summon God</h2>
            <button class="gm-summon-close" title="Close">&times;</button>
          </div>
          <div class="gm-summon-toolbar">
            <input class="gm-summon-search" type="text" placeholder="Search gods..." spellcheck="false">
            <select class="gm-summon-sort">
              <option value="downloads">Most Downloaded</option>
              <option value="newest">Newest</option>
              <option value="name">Name A\u2013Z</option>
            </select>
          </div>
          <div class="gm-summon-body">
            <p class="gm-summon-loading">Loading available gods...</p>
          </div>
          <div class="gm-summon-footer">
            <span class="gm-summon-count">0 gods</span>
          </div>
        </div>`;

      document.body.appendChild(overlay);
      overlay.querySelector('.gm-summon-close').addEventListener('click', () => overlay.remove());
      overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

      const body    = overlay.querySelector('.gm-summon-body');
      const search  = overlay.querySelector('.gm-summon-search');
      const sort    = overlay.querySelector('.gm-summon-sort');
      const countEl = overlay.querySelector('.gm-summon-count');

      let allGods = [];

      function renderList() {
        const query = search.value.toLowerCase().trim();
        const sortBy = sort.value;

        let filtered = allGods.filter(g => {
          const n = (g.display_name || g.name || '').toLowerCase();
          const d = (g.description || parseDescription(g.soul || '')).toLowerCase();
          return n.includes(query) || d.includes(query);
        });

        filtered.sort((a, b) => {
          if (sortBy === 'downloads') return (b.downloads || 0) - (a.downloads || 0);
          if (sortBy === 'name') {
            const na = (a.display_name || a.name || '').toLowerCase();
            const nb = (b.display_name || b.name || '').toLowerCase();
            return na.localeCompare(nb);
          }
          // newest — reverse chronological by created_at
          const ca = a.created_at || '';
          const cb = b.created_at || '';
          return cb.localeCompare(ca) || (b.downloads || 0) - (a.downloads || 0);
        });

        countEl.textContent = `${filtered.length} god${filtered.length !== 1 ? 's' : ''}`;

        if (!filtered.length) {
          body.innerHTML = `<p class="gm-summon-empty">${query ? 'No gods match your search.' : 'No gods available in the Pantheon-Summons repo yet.'}</p>`;
          return;
        }
        body.innerHTML = `<div class="gm-summon-grid">${filtered.map(g => renderSummonCard(g)).join('')}</div>`;
        body.querySelectorAll('.gm-summon-card').forEach(card => {
          const name = card.dataset.god;
          const btn = card.querySelector('.gm-summon-install');
          btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = 'Summoning...';
            try {
              const res = await fetch('/api/gods/summon', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ god_name: name }),
              });
              const result = await res.json();
              if (result.ok) {
                card.innerHTML = '<div class="gm-summon-installed">✅ Installed!</div>';
                fetchGods();
              } else {
                btn.textContent = result.error || 'Failed';
                btn.disabled = false;
              }
            } catch (e) {
              btn.textContent = 'Error';
              btn.disabled = false;
            }
          });
        });
      }

      search.addEventListener('input', renderList);
      sort.addEventListener('change', renderList);

      fetch('/api/gods/summon/list')
        .then(r => r.json())
        .then(data => {
          allGods = data.gods || [];
          if (!allGods.length) {
            body.innerHTML = '<p class="gm-summon-empty">No gods available in the Pantheon-Summons repo yet.</p>';
            countEl.textContent = '0 gods';
            return;
          }
          renderList();
        })
        .catch(err => {
          body.innerHTML = `<p class="gm-summon-error">Failed to load: ${err.message}</p>`;
          countEl.textContent = '\u2014';
        });
    }

    function renderSummonCard(god) {
      const name = god.name || '?';
      const displayName = god.display_name || name.charAt(0).toUpperCase() + name.slice(1);
      const icon = god.icon_url || '';
      const desc = god.description || parseDescription(god.soul || '');
      const descShort = desc ? escHtml(desc.slice(0, 120)) : '';
      const dls = god.downloads || 0;
      const accent = god.color || 'var(--accent, #7c6fe0)';
      return `<div class="gm-summon-card" data-god="${escHtml(name)}" style="border-left:3px solid ${accent}">
        <div class="gm-summon-card-icon">${icon ? `<img src="${escHtml(icon)}" alt="" onerror="this.style.display='none'">` : '<span class="gm-summon-card-emoji">&#x1F31F;</span>'}</div>
        <div class="gm-summon-card-body">
          <div class="gm-summon-card-name">${escHtml(displayName)}</div>
          <div class="gm-summon-card-desc">${descShort || 'No description available'}</div>
          <div class="gm-summon-card-stats">
            <span class="gm-summon-dl" title="Downloads">&#x2B07; ${dls}</span>
            ${god.domain ? `<span class="gm-summon-domain">${escHtml(god.domain)}</span>` : ''}
          </div>
        </div>
        <button class="gm-summon-install">&#x2728; Summon</button>
      </div>`;
    }

    // ── Export Drawer ──

    function getExportState(god) {
      const name = god.name;
      if (!exportState.has(name)) {
        exportState.set(name, {
          skills: new Set(),
          mcp: new Set(),
          codexFolders: new Set(),
          editing: 'main',
        });
      }
      return exportState.get(name);
    }

    function openExportDrawer(god) {
      const existing = document.getElementById('gm-export-overlay');
      if (existing) existing.remove();

      const overlay = document.createElement('div');
      overlay.id = 'gm-export-overlay';
      overlay.className = 'gm-export-overlay';
      overlay.innerHTML = `
        <div class="gm-export-panel">
          <div class="gm-export-header">
            <h2>📦 Export ${escHtml(god.display_name || god.name)}</h2>
            <button class="gm-export-close" title="Close">&times;</button>
          </div>
          <div class="gm-export-body">
            <div class="gm-export-loading">Loading...</div>
          </div>
        </div>`;

      document.body.appendChild(overlay);
      overlay.querySelector('.gm-export-close').addEventListener('click', () => overlay.remove());
      overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

      renderExportMain(god, overlay);
    }

    function renderExportMain(god, overlay) {
      const st = getExportState(god);
      st.editing = 'main';
      const color = escHtml(god.color || 'var(--accent)');
      const body = overlay.querySelector('.gm-export-body');

      const skillsTotal = 0; // will be fetched
      const mcpTotal = 0;
      const codexTotal = 0;

      body.innerHTML = `
        <div class="gm-export-god-row">
          <img class="gm-export-icon" src="/api/gods/${escHtml(god.name)}/icon" alt=""
            onerror="this.style.visibility='hidden'" style="width:24px;height:24px;border-radius:5px;object-fit:cover;flex-shrink:0">
          <span class="gm-export-god-name"><strong>${escHtml(god.display_name || god.name)}</strong></span>
          <span class="gm-export-color-dot" style="background:${color}"></span>
        </div>
        <div class="gm-export-sections">
          <button class="gm-export-section-btn" data-section="skills">
            <span class="gm-export-section-label">Skills</span>
            <span class="gm-export-section-badge" id="gm-export-badge-skills">0/0</span>
          </button>
          <button class="gm-export-section-btn" data-section="codex">
            <span class="gm-export-section-label">Knowledge Bases</span>
            <span class="gm-export-section-badge" id="gm-export-badge-codex">0/0</span>
          </button>
          <button class="gm-export-section-btn" data-section="mcp">
            <span class="gm-export-section-label">MCPs</span>
            <span class="gm-export-section-badge" id="gm-export-badge-mcp">0/0</span>
          </button>
        </div>
        <div class="gm-export-actions">
          <button class="gm-export-btn-primary" id="gm-export-do-export">📦 Export</button>
          <button class="gm-export-btn-cancel">Cancel</button>
        </div>
        <div class="gm-export-footer">
          God export packages skills, knowledge bases, and MCP server configs for distribution.
        </div>`;

      // Section button clicks
      body.querySelectorAll('.gm-export-section-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const section = btn.dataset.section;
          if (section === 'skills') showExportSkills(god, overlay);
          else if (section === 'mcp') showExportMCP(god, overlay);
          else if (section === 'codex') showExportCodex(god, overlay);
        });
      });

      body.querySelector('#gm-export-do-export').addEventListener('click', () => doGodExport(god, overlay));
      body.querySelector('.gm-export-btn-cancel').addEventListener('click', () => overlay.remove());

      // Fetch counts to populate badges
      fetch(`/api/gods/${encodeURIComponent(god.name)}/skills`)
        .then(r => r.json())
        .then(data => {
          const skills = data.skills || data || [];
          const total = Array.isArray(skills) ? skills.length : 0;
          const selected = st.skills.size;
          const badge = body.querySelector('#gm-export-badge-skills');
          if (badge) badge.textContent = `${selected}/${total}`;
        })
        .catch(() => {});

      fetch(`/api/gods/${encodeURIComponent(god.name)}/mcp-servers`)
        .then(r => r.json())
        .then(data => {
          const servers = data.servers || data || [];
          const total = Array.isArray(servers) ? servers.length : 0;
          const selected = st.mcp.size;
          const badge = body.querySelector('#gm-export-badge-mcp');
          if (badge) badge.textContent = `${selected}/${total}`;
        })
        .catch(() => {});

      fetch(`/api/gods/${encodeURIComponent(god.name)}/codex-folders`)
        .then(r => r.json())
        .then(data => {
          const folders = data.folders || data || [];
          const total = Array.isArray(folders) ? folders.length : 0;
          const selected = st.codexFolders.size;
          const badge = body.querySelector('#gm-export-badge-codex');
          if (badge) badge.textContent = `${selected}/${total}`;
        })
        .catch(() => {});
    }

    function showExportSkills(god, overlay) {
      const st = getExportState(god);
      st.editing = 'skills';
      const body = overlay.querySelector('.gm-export-body');

      body.innerHTML = `
        <div class="gm-export-back-row">
          <button class="gm-export-back">← Skills</button>
        </div>
        <div class="gm-export-sub-header">
          <h3>Select Skills</h3>
        </div>
        <div class="gm-export-toggle-row">
          <button class="gm-export-toggle-all">Select All</button>
          <button class="gm-export-toggle-none">Select None</button>
        </div>
        <div class="gm-export-list" id="gm-export-skills-list">
          <p class="gm-export-loading">Loading skills...</p>
        </div>
        <div class="gm-export-actions">
          <button class="gm-export-btn-primary" id="gm-export-skills-save">Save & Close</button>
          <button class="gm-export-btn-cancel" id="gm-export-skills-close">Close</button>
        </div>`;

      body.querySelector('.gm-export-back').addEventListener('click', () => renderExportMain(god, overlay));
      body.querySelector('#gm-export-skills-save').addEventListener('click', () => renderExportMain(god, overlay));
      body.querySelector('#gm-export-skills-close').addEventListener('click', () => renderExportMain(god, overlay));

      const listEl = body.querySelector('#gm-export-skills-list');

      fetch(`/api/gods/${encodeURIComponent(god.name)}/skills`)
        .then(r => r.json())
        .then(data => {
          const skills = data.skills || data || [];
          const arr = Array.isArray(skills) ? skills : [];
          if (!arr.length) {
            listEl.innerHTML = '<p class="gm-export-empty">No skills found.</p>';
            return;
          }
          listEl.innerHTML = arr.map(skill => {
            const name = skill.name || skill;
            const checked = st.skills.has(name) || skill.in_profile ? ' checked' : '';
            const desc = skill.description ? `<span class="gm-export-item-desc">${escHtml(skill.description.slice(0, 80))}</span>` : '';
            const badge = skill.in_profile ? '<span class="gm-export-item-badge">profile</span>' : '';
            return `<label class="gm-export-item${checked ? ' gm-export-item--checked' : ''}"><input type="checkbox" value="${escHtml(name)}"${checked}> <span class="gm-export-item-name">${escHtml(name)}${badge}</span>${desc}</label>`;
          }).join('');

          // Toggle all/none
          const checkboxes = () => listEl.querySelectorAll('input[type=checkbox]');
          body.querySelector('.gm-export-toggle-all').addEventListener('click', () => {
            checkboxes().forEach(cb => cb.checked = true);
          });
          body.querySelector('.gm-export-toggle-none').addEventListener('click', () => {
            checkboxes().forEach(cb => cb.checked = false);
          });

          // Save saves selections
          body.querySelector('#gm-export-skills-save').addEventListener('click', () => {
            st.skills.clear();
            checkboxes().forEach(cb => { if (cb.checked) st.skills.add(cb.value); });
            renderExportMain(god, overlay);
          });
        })
        .catch(err => {
          listEl.innerHTML = `<p class="gm-export-error">Failed to load: ${err.message}</p>`;
        });
    }

    function showExportMCP(god, overlay) {
      const st = getExportState(god);
      st.editing = 'mcp';
      const body = overlay.querySelector('.gm-export-body');

      body.innerHTML = `
        <div class="gm-export-back-row">
          <button class="gm-export-back">← MCPs</button>
        </div>
        <div class="gm-export-sub-header">
          <h3>Select MCP Servers</h3>
        </div>
        <div class="gm-export-toggle-row">
          <button class="gm-export-toggle-all">Select All</button>
          <button class="gm-export-toggle-none">Select None</button>
        </div>
        <div class="gm-export-list" id="gm-export-mcp-list">
          <p class="gm-export-loading">Loading MCP servers...</p>
        </div>
        <div class="gm-export-actions">
          <button class="gm-export-btn-primary" id="gm-export-mcp-save">Save & Close</button>
          <button class="gm-export-btn-cancel" id="gm-export-mcp-close">Close</button>
        </div>`;

      body.querySelector('.gm-export-back').addEventListener('click', () => renderExportMain(god, overlay));
      body.querySelector('#gm-export-mcp-close').addEventListener('click', () => renderExportMain(god, overlay));

      const listEl = body.querySelector('#gm-export-mcp-list');

      fetch(`/api/gods/${encodeURIComponent(god.name)}/mcp-servers`)
        .then(r => r.json())
        .then(data => {
          const servers = data.servers || data || [];
          const arr = Array.isArray(servers) ? servers : [];
          if (!arr.length) {
            listEl.innerHTML = '<p class="gm-export-empty">No MCP servers found.</p>';
            return;
          }
          listEl.innerHTML = arr.map(srv => {
            const name = srv.name || srv;
            const checked = st.mcp.has(name) ? ' checked' : '';
            return `<label class="gm-export-item"><input type="checkbox" value="${escHtml(name)}"${checked}> ${escHtml(name)}</label>`;
          }).join('');

          const checkboxes = () => listEl.querySelectorAll('input[type=checkbox]');
          body.querySelector('.gm-export-toggle-all').addEventListener('click', () => {
            checkboxes().forEach(cb => cb.checked = true);
          });
          body.querySelector('.gm-export-toggle-none').addEventListener('click', () => {
            checkboxes().forEach(cb => cb.checked = false);
          });

          body.querySelector('#gm-export-mcp-save').addEventListener('click', () => {
            st.mcp.clear();
            checkboxes().forEach(cb => { if (cb.checked) st.mcp.add(cb.value); });
            renderExportMain(god, overlay);
          });
        })
        .catch(err => {
          listEl.innerHTML = `<p class="gm-export-error">Failed to load: ${err.message}</p>`;
        });
    }

    function showExportCodex(god, overlay) {
      const st = getExportState(god);
      st.editing = 'codex';
      const body = overlay.querySelector('.gm-export-body');

      body.innerHTML = `
        <div class="gm-export-back-row">
          <button class="gm-export-back">← Knowledge Bases</button>
        </div>
        <div class="gm-export-sub-header">
          <h3>Select Knowledge Bases</h3>
        </div>
        <div class="gm-export-list" id="gm-export-codex-list">
          <p class="gm-export-loading">Loading knowledge bases...</p>
        </div>
        <div class="gm-export-actions">
          <button class="gm-export-btn-primary" id="gm-export-codex-other">Other Knowledge Bases</button>
        </div>
        <div class="gm-export-actions" style="margin-top:8px">
          <button class="gm-export-btn-primary" id="gm-export-codex-save">Save & Close</button>
          <button class="gm-export-btn-cancel" id="gm-export-codex-close">Close</button>
        </div>`;

      body.querySelector('.gm-export-back').addEventListener('click', () => renderExportMain(god, overlay));
      body.querySelector('#gm-export-codex-close').addEventListener('click', () => renderExportMain(god, overlay));

      const listEl = body.querySelector('#gm-export-codex-list');

      // Fetch god's own codex folders
      fetch(`/api/gods/${encodeURIComponent(god.name)}/codex-folders`)
        .then(r => r.json())
        .then(data => {
          const codexes = data.codexes || [];
          const arr = Array.isArray(codexes) ? codexes : [];
          if (!arr.length) {
            listEl.innerHTML = '<p class="gm-export-empty">No knowledge bases assigned.</p>';
          } else {
            listEl.innerHTML = arr.map(c => {
              const checked = st.codexFolders.has(c) ? ' checked' : '';
              return `<label class="gm-export-item${checked ? ' gm-export-item--checked' : ''}"><input type="checkbox" value="${escHtml(c)}"${checked}> <span class="gm-export-item-name">📚 ${escHtml(c)}</span></label>`;
            }).join('');
          }

          const checkboxes = () => listEl.querySelectorAll('input[type=checkbox]');

          body.querySelector('#gm-export-codex-save').addEventListener('click', () => {
            st.codexFolders.clear();
            checkboxes().forEach(cb => { if (cb.checked) st.codexFolders.add(cb.value); });
            renderExportMain(god, overlay);
          });

          // "Other Knowledge Bases" button opens Athenaeum browser
          body.querySelector('#gm-export-codex-other').addEventListener('click', () => {
            showAthenaeumBrowser(god, overlay);
          });
        })
        .catch(err => {
          listEl.innerHTML = `<p class="gm-export-error">Failed to load: ${err.message}</p>`;
        });
    }

    function showAthenaeumBrowser(god, overlay) {
      const st = getExportState(god);
      const body = overlay.querySelector('.gm-export-body');

      body.innerHTML = `
        <div class="gm-export-back-row">
          <button class="gm-export-back">← Knowledge Bases</button>
        </div>
        <div class="gm-export-sub-header">
          <h3>Browse Athenaeum</h3>
        </div>
        <div class="gm-export-athenaeum-grid" id="gm-export-athenaeum-grid">
          <p class="gm-export-loading">Loading codexes...</p>
        </div>
        <div class="gm-export-actions">
          <button class="gm-export-btn-primary" id="gm-export-athenaeum-save">Save & Close</button>
          <button class="gm-export-btn-cancel" id="gm-export-athenaeum-close">Close</button>
        </div>`;

      body.querySelector('.gm-export-back').addEventListener('click', () => showExportCodex(god, overlay));
      body.querySelector('#gm-export-athenaeum-close').addEventListener('click', () => showExportCodex(god, overlay));

      const gridEl = body.querySelector('#gm-export-athenaeum-grid');

      fetch('/api/athenaeum/list?details=1')
        .then(r => r.json())
        .then(data => {
          const codexes = data.codexes || data || [];
          const arr = Array.isArray(codexes) ? codexes : [];
          if (!arr.length) {
            gridEl.innerHTML = '<p class="gm-export-empty">No codexes found.</p>';
            return;
          }
          gridEl.innerHTML = arr.map(c => {
            const name = c.name || c;
            const desc = c.description || '';
            const checked = st.codexFolders.has(name) ? ' checked' : '';
            return `<label class="gm-export-athenaeum-card">
              <input type="checkbox" value="${escHtml(name)}"${checked}>
              <span class="gm-export-athenaeum-card-name">${escHtml(name)}</span>
              ${desc ? `<span class="gm-export-athenaeum-card-desc">${escHtml(desc)}</span>` : ''}
            </label>`;
          }).join('');

          // When checkbox changes, optionally fetch sub-folders
          gridEl.querySelectorAll('input[type=checkbox]').forEach(cb => {
            cb.addEventListener('change', async function() {
              if (this.checked) {
                // Try to browse sub-folders
                try {
                  const res = await fetch(`/api/athenaeum/walk?path=${encodeURIComponent(this.value)}/INDEX.md`);
                  if (res.ok) {
                    // Successfully browsed — this codex exists
                  }
                } catch (e) {
                  // Ignore walk errors
                }
              }
            });
          });

          body.querySelector('#gm-export-athenaeum-save').addEventListener('click', () => {
            st.codexFolders.clear();
            gridEl.querySelectorAll('input[type=checkbox]').forEach(cb => {
              if (cb.checked) st.codexFolders.add(cb.value);
            });
            showExportCodex(god, overlay);
          });
        })
        .catch(err => {
          gridEl.innerHTML = `<p class="gm-export-error">Failed to load: ${err.message}</p>`;
        });
    }

    async function doGodExport(god, overlay) {
      const st = getExportState(god);
      const body = overlay.querySelector('.gm-export-body');
      const exportBtn = overlay.querySelector('#gm-export-do-export');
      if (exportBtn) {
        exportBtn.disabled = true;
        exportBtn.textContent = '⏳ Bundling...';
      }

      const payload = {
        selected_skills: Array.from(st.skills),
        selected_mcp: Array.from(st.mcp),
        codex_folders: Array.from(st.codexFolders),
      };

      try {
        const res = await fetch(`/api/gods/${encodeURIComponent(god.name)}/export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const errText = await res.text().catch(() => `HTTP ${res.status}`);
          throw new Error(errText);
        }
        const blob = await res.blob();
        const disposition = res.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^";\n]+)"?/);
        const filename = match ? match[1] : `god-${god.name}.tar.gz`;
        const url = URL.createObjectURL(blob);

        // Replace the modal body with a persistent success view
        if (body) {
          const downloadUrl = url;
          const fileName = filename;
          const fileSize = blob.size;
          body.innerHTML = `
            <div style="text-align:center;padding:20px 0">
              <div style="font-size:42px;margin-bottom:10px">✅</div>
              <div style="font-size:16px;font-weight:700;color:var(--text-primary,#e2e8f0)">Bundle exported!</div>
              <div style="font-size:13px;color:var(--text-muted,#94a3b8);margin-top:6px">${escHtml(fileName)} (${Math.round(fileSize / 1024)} KB)</div>
            </div>
            <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">
              <a href="${downloadUrl}" download="${fileName}" style="
                display:block;text-align:center;padding:10px 16px;border-radius:8px;
                background:var(--accent-bg-strong,#7c6fe0);color:#fff;
                text-decoration:none;font-weight:600;font-size:14px;
              ">📥 Download Bundle</a>
              <button id="gm-export-submit-summons" style="
                display:block;width:100%;text-align:center;padding:10px 16px;border-radius:8px;
                background:var(--accent,#22c55e);color:#fff;border:none;
                font-weight:600;font-size:14px;cursor:pointer;
              ">🌟 Submit to Pantheon-Summons</button>
              <button class="gm-export-btn-cancel" onclick="this.closest('#gm-export-overlay').remove()" style="width:100%;margin-top:4px">Close</button>
            </div>
          `;
          // Wire up submit-to-summons
          const submitBtn = body.querySelector('#gm-export-submit-summons');
          if (submitBtn) {
            submitBtn.addEventListener('click', async () => {
              submitBtn.disabled = true;
              submitBtn.innerHTML = '⏳ Submitting...';
              try {
                const payload = {
                  include_skills: st.skills.size > 0,
                  codex_folders: Array.from(st.codexFolders).length > 0 ? Array.from(st.codexFolders) : null
                };
                const res = await fetch(`/api/gods/${encodeURIComponent(god.name)}/submit-to-summons`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(payload),
                });
                const data = await res.json().catch(() => ({}));
                if (data.error) {
                  submitBtn.innerHTML = `⚠️ ${escHtml(data.error)}`;
                  submitBtn.disabled = false;
                } else if (data.pr_url) {
                  submitBtn.innerHTML = '✅ PR Created!';
                  body.innerHTML += `
                    <div style="text-align:center;padding:12px;margin-top:8px;background:var(--bg-tertiary,#1e1e36);border-radius:8px;font-size:13px">
                      🌟 <a href="${escHtml(data.pr_url)}" target="_blank" style="color:var(--accent,#22d3ee);text-decoration:underline">View PR on GitHub</a>
                    </div>
                  `;
                } else {
                  submitBtn.innerHTML = '✅ Submitted!';
                }
              } catch (e) {
                submitBtn.innerHTML = '⚠️ Network error';
                submitBtn.disabled = false;
              }
            });
          }
        }
      } catch (e) {
        console.error('[god-management] export failed:', e);
        if (exportBtn) {
          exportBtn.textContent = '❌ Failed';
          exportBtn.disabled = false;
        }
        if (body) {
          body.innerHTML = `
            <div style="text-align:center;padding:20px 0;color:var(--error,#ef4444)">
              <div style="font-size:42px;margin-bottom:10px">❌</div>
              <div style="font-size:15px;font-weight:600">Export failed</div>
              <div style="font-size:12px;color:var(--text-muted,#94a3b8);margin-top:6px">${escHtml(e.message)}</div>
              <button class="gm-export-btn-cancel" onclick="this.closest('#gm-export-overlay').remove()" style="margin-top:12px">Close</button>
            </div>
          `;
        }
      }
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

.gm-summon-btn {
  background: var(--accent, #7c6fe0); border: none; color: #fff; border-radius: 6px;
  padding: 6px 13px; cursor: pointer; font-size: .82rem; font-weight: 600; line-height: 1;
  transition: background .15s, transform .1s; white-space: nowrap; margin-right: 10px;
}
.gm-summon-btn:hover { background: var(--accent-hover, #9488f0); transform: scale(1.03); }
.gm-summon-btn:active { transform: scale(0.97); }

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

.gm-exile-row {
  display: flex; justify-content: flex-start; margin-top: 4px; padding-top: 8px;
  border-top: 1px solid var(--border, #3B4A50);
}
.gm-exile-btn {
  background: none; border: none; cursor: pointer;
  color: var(--text-muted, #888); font-size: .75rem; padding: 4px 6px;
  border-radius: 4px; transition: color .15s, background .15s;
}
.gm-exile-btn:hover {
  color: #ff4d4d; background: rgba(255,77,77,0.1);
}

@media (max-width: 600px) { .gm-grid { grid-template-columns: 1fr; } }

/* ── Summon Drawer ── */
.gm-summon-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 9500;
  display: flex; align-items: center; justify-content: center;
}
.gm-summon-panel {
  background: var(--bg-primary, #0a0908); border: 1px solid var(--border, #3B4A50);
  border-radius: 12px; width: 700px; max-width: 94vw; max-height: 85vh;
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.gm-summon-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid var(--border, #3B4A50);
}
.gm-summon-header h2 { margin: 0; font-size: 1.1rem; font-weight: 600; color: var(--text-primary); }
.gm-summon-close {
  background: none; border: none; color: var(--text-muted, #666);
  font-size: 1.4rem; cursor: pointer; padding: 4px 8px; line-height: 1;
}
.gm-summon-close:hover { color: var(--text-primary); }

/* Toolbar: search + sort side by side */
.gm-summon-toolbar {
  display: flex; gap: 10px; padding: 10px 20px;
  border-bottom: 1px solid var(--border, #3B4A50);
  background: var(--bg-tertiary, #0d0c0a);
}
.gm-summon-search {
  flex: 1; background: var(--bg-secondary, #11100E);
  border: 1px solid var(--border, #3B4A50); border-radius: 7px;
  color: var(--text-primary); padding: 8px 12px; font-size: .85rem;
  outline: none; transition: border-color .15s;
}
.gm-summon-search:focus { border-color: var(--accent, #7c6fe0); }
.gm-summon-search::placeholder { color: var(--text-muted, #666); }
.gm-summon-sort {
  background: var(--bg-secondary, #11100E);
  border: 1px solid var(--border, #3B4A50); border-radius: 7px;
  color: var(--text-primary); padding: 8px 28px 8px 12px; font-size: .82rem;
  cursor: pointer; outline: none; appearance: auto; min-width: 155px;
}

.gm-summon-body {
  flex: 1; overflow-y: auto; padding: 12px 20px;
}
.gm-summon-loading { color: var(--text-muted); text-align: center; padding: 40px 0; margin: 0; }
.gm-summon-empty { color: var(--text-muted); text-align: center; padding: 40px 0; margin: 0; font-size: .9rem; }
.gm-summon-error { color: var(--error); text-align: center; padding: 40px 0; margin: 0; }

/* Footer with god count */
.gm-summon-footer {
  padding: 10px 20px; border-top: 1px solid var(--border, #3B4A50);
  text-align: right; font-size: .78rem; color: var(--text-muted);
}

.gm-summon-grid { display: flex; flex-direction: column; gap: 10px; }
.gm-summon-card {
  display: flex; align-items: center; gap: 14px;
  background: var(--bg-secondary, #11100E); border: 1px solid var(--border, #3B4A50);
  border-radius: 10px; padding: 14px 16px; transition: border-color .15s;
}
.gm-summon-card:hover { border-color: var(--accent, #7c6fe0); }
.gm-summon-card-icon {
  width: 48px; height: 48px; border-radius: 8px; overflow: hidden;
  flex-shrink: 0; background: var(--bg-tertiary); display: flex;
  align-items: center; justify-content: center; font-size: 24px;
}
.gm-summon-card-icon img { width: 100%; height: 100%; object-fit: cover; }
.gm-summon-card-body { flex: 1; min-width: 0; }
.gm-summon-card-name { font-weight: 600; font-size: .95rem; color: var(--text-primary); margin-bottom: 3px; }
.gm-summon-card-desc { font-size: .78rem; color: var(--text-muted); line-height: 1.4; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }

/* Stats row: download count + domain tag */
.gm-summon-card-stats {
  display: flex; align-items: center; gap: 10px;
  margin-top: 5px; font-size: .75rem; color: var(--text-muted);
}
.gm-summon-dl { font-weight: 600; color: var(--text-secondary); }
.gm-summon-domain {
  background: var(--bg-tertiary); padding: 1px 6px; border-radius: 4px;
  color: var(--text-muted); font-size: .7rem;
}

.gm-summon-install {
  flex-shrink: 0; background: var(--accent, #7c6fe0); color: #fff;
  border: none; border-radius: 7px; padding: 8px 18px; font-size: .82rem;
  font-weight: 600; cursor: pointer; transition: background .15s, transform .1s;
}
.gm-summon-install:hover:not(:disabled) { background: var(--accent-hover, #9488f0); transform: scale(1.03); }
.gm-summon-install:disabled { opacity: .5; cursor: not-allowed; transform: none; }
.gm-summon-installed { color: var(--success, #86C08B); font-weight: 600; font-size: .9rem; text-align: center; padding: 8px; }

/* ── Export Drawer ── */
.gm-export-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 9510;
  display: flex; align-items: center; justify-content: center;
}
.gm-export-panel {
  background: var(--bg-primary, #0a0908); border: 1px solid var(--border, #3B4A50);
  border-radius: 12px; width: 600px; max-width: 94vw; max-height: 85vh;
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.gm-export-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid var(--border, #3B4A50);
}
.gm-export-header h2 { margin: 0; font-size: 1.1rem; font-weight: 600; color: var(--text-primary); }
.gm-export-close {
  background: none; border: none; color: var(--text-muted, #666);
  font-size: 1.4rem; cursor: pointer; padding: 4px 8px; line-height: 1;
}
.gm-export-close:hover { color: var(--text-primary); }

.gm-export-body { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.gm-export-loading { color: var(--text-muted); text-align: center; padding: 20px 0; margin: 0; font-size: .9rem; }
.gm-export-empty { color: var(--text-muted); text-align: center; padding: 20px 0; margin: 0; font-size: .85rem; }
.gm-export-error { color: var(--error); text-align: center; padding: 20px 0; margin: 0; }

.gm-export-god-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 0; border-bottom: 1px solid var(--border, #3B4A50);
}
.gm-export-god-name { font-size: .95rem; color: var(--text-primary); flex: 1; }
.gm-export-color-dot {
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
  border: 1px solid rgba(255,255,255,0.15);
}

.gm-export-sections { display: flex; flex-direction: column; gap: 8px; }
.gm-export-section-btn {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--bg-secondary, #11100E); border: 1px solid var(--border, #3B4A50);
  border-radius: 10px; padding: 14px 16px; cursor: pointer;
  color: var(--text-primary); font-size: .95rem; font-weight: 500;
  transition: border-color .15s, background .15s; text-align: left;
}
.gm-export-section-btn:hover { border-color: var(--accent, #7c6fe0); background: var(--bg-tertiary, #0d0c0a); }
.gm-export-section-label { flex: 1; }
.gm-export-section-badge {
  background: var(--accent, #7c6fe0); color: #fff;
  padding: 3px 10px; border-radius: 12px; font-size: .75rem; font-weight: 600;
  white-space: nowrap;
}

.gm-export-actions {
  display: flex; gap: 8px; align-items: center;
}
.gm-export-btn-primary {
  flex: 1; background: var(--accent, #7c6fe0); color: #fff;
  border: none; border-radius: 8px; padding: 10px 16px; font-size: .9rem;
  font-weight: 600; cursor: pointer; transition: background .15s, transform .1s;
}
.gm-export-btn-primary:hover:not(:disabled) { background: var(--accent-hover, #9488f0); transform: scale(1.02); }
.gm-export-btn-primary:disabled { opacity: .5; cursor: not-allowed; transform: none; }
.gm-export-btn-cancel {
  background: none; border: none; color: var(--text-muted, #666);
  font-size: .85rem; cursor: pointer; padding: 8px 12px;
}
.gm-export-btn-cancel:hover { color: var(--text-primary); }

.gm-export-footer {
  font-size: .75rem; color: var(--text-muted); text-align: center;
  padding: 8px 0 0; border-top: 1px solid var(--border, #3B4A50);
  line-height: 1.4;
}

/* Selection sub-views */
.gm-export-back-row { padding: 0 0 4px; }
.gm-export-back {
  background: none; border: none; color: var(--accent, #7c6fe0);
  font-size: .88rem; cursor: pointer; padding: 4px 0;
}
.gm-export-back:hover { text-decoration: underline; }

.gm-export-sub-header { }
.gm-export-sub-header h3 { margin: 0; font-size: 1rem; font-weight: 600; color: var(--text-primary); }

.gm-export-toggle-row { display: flex; gap: 8px; }
.gm-export-toggle-all, .gm-export-toggle-none {
  background: var(--bg-secondary, #11100E); border: 1px solid var(--border, #3B4A50);
  color: var(--text-primary); border-radius: 6px; padding: 5px 12px;
  font-size: .78rem; cursor: pointer; transition: border-color .15s;
}
.gm-export-toggle-all:hover, .gm-export-toggle-none:hover { border-color: var(--accent, #7c6fe0); }

.gm-export-list {
  display: flex; flex-direction: column; gap: 4px;
  max-height: 300px; overflow-y: auto; padding: 4px 0;
}
.gm-export-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; border-radius: 6px; font-size: .85rem;
  cursor: pointer; color: var(--text-primary); transition: background .1s;
}
.gm-export-item:hover { background: var(--bg-tertiary, #0d0c0a); }
.gm-export-item input[type=checkbox] {
  accent-color: var(--accent, #7c6fe0); flex-shrink: 0;
  width: 16px; height: 16px; cursor: pointer;
}
.gm-export-item--checked { background: var(--bg-tertiary, #0d0c0a); border-left: 2px solid var(--accent, #7c6fe0); }
.gm-export-item-name { font-weight: 500; }
.gm-export-item-badge {
  display: inline-block; font-size: .65rem; font-weight: 600;
  background: var(--accent, #7c6fe0); color: #fff;
  padding: 1px 6px; border-radius: 4px; margin-left: 6px; vertical-align: middle;
  text-transform: uppercase; letter-spacing: .03em;
}
.gm-export-item-desc {
  display: block; font-size: .72rem; color: var(--text-muted);
  margin-top: 2px; line-height: 1.3;
}
.gm-export-section-label {
  font-size: .78rem; font-weight: 600; color: var(--text-muted);
  padding: 8px 10px 4px; text-transform: uppercase; letter-spacing: .05em;
}

/* Athenaeum browser grid */
.gm-export-athenaeum-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  max-height: 350px; overflow-y: auto; padding: 4px 0;
}
.gm-export-athenaeum-card {
  display: flex; flex-direction: column; gap: 4px;
  background: var(--bg-secondary, #11100E); border: 1px solid var(--border, #3B4A50);
  border-radius: 8px; padding: 12px; cursor: pointer;
  transition: border-color .15s; position: relative;
}
.gm-export-athenaeum-card:hover { border-color: var(--accent, #7c6fe0); }
.gm-export-athenaeum-card input[type=checkbox] {
  accent-color: var(--accent, #7c6fe0); position: absolute; top: 10px; right: 10px;
  width: 16px; height: 16px; cursor: pointer;
}
.gm-export-athenaeum-card-name {
  font-weight: 600; font-size: .88rem; color: var(--text-primary);
  padding-right: 24px;
}
.gm-export-athenaeum-card-desc {
  font-size: .72rem; color: var(--text-muted); line-height: 1.3;
}

.gm-export-btn {
  flex: 1; padding: 6px 0; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg-secondary);
  color: var(--text-primary); cursor: pointer; font-size: .81rem;
  transition: background .15s, border-color .15s, color .15s;
}
.gm-export-btn:hover:not(:disabled) { background: var(--accent); border-color: var(--accent); color: #fff; }
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
