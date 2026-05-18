(function () {
  const CSS = `
    .sd-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9000;display:flex;align-items:center;justify-content:center;animation:sd-fade .15s ease}
    @keyframes sd-fade{from{opacity:0}to{opacity:1}}
    .sd-panel{background:var(--bg-primary,#0f1117);border:1px solid var(--border,#2a2d3a);border-radius:12px;width:700px;max-width:95vw;max-height:85vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.6)}
    .sd-header{display:flex;align-items:center;justify-content:space-between;padding:20px 24px;border-bottom:1px solid var(--border,#2a2d3a)}
    .sd-header h2{margin:0;font-size:1.2rem;font-weight:600;color:var(--text-primary,#e8eaf0);letter-spacing:.02em}
    .sd-close{background:none;border:none;cursor:pointer;color:var(--text-muted,#6b7280);font-size:1.4rem;line-height:1;padding:4px 8px;border-radius:6px;transition:color .15s,background .15s}
    .sd-close:hover{color:var(--text-primary,#e8eaf0);background:var(--bg-secondary,#1a1d27)}
    .sd-search-wrap{padding:16px 24px;border-bottom:1px solid var(--border,#2a2d3a)}
    .sd-search{width:100%;box-sizing:border-box;background:var(--bg-secondary,#1a1d27);border:1px solid var(--border,#2a2d3a);border-radius:8px;padding:10px 14px;color:var(--text-primary,#e8eaf0);font-size:.9rem;outline:none;transition:border-color .15s}
    .sd-search::placeholder{color:var(--text-muted,#6b7280)}
    .sd-search:focus{border-color:var(--accent,#7c6af7)}
    .sd-body{flex:1;overflow-y:auto;padding:20px 24px}
    .sd-body::-webkit-scrollbar{width:6px}.sd-body::-webkit-scrollbar-track{background:transparent}.sd-body::-webkit-scrollbar-thumb{background:var(--border,#2a2d3a);border-radius:3px}
    .sd-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    @media(max-width:540px){.sd-grid{grid-template-columns:1fr}}
    .sd-card{background:var(--bg-secondary,#1a1d27);border:1px solid var(--border,#2a2d3a);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px;transition:border-color .15s}
    .sd-card:hover{border-color:var(--accent,#7c6af7)}
    .sd-card-name{font-weight:600;font-size:.95rem;color:var(--text-primary,#e8eaf0);margin:0}
    .sd-card-desc{font-size:.82rem;color:var(--text-secondary,#9ca3af);margin:0;flex:1;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
    .sd-card-footer{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
    .sd-tag{font-size:.72rem;background:var(--bg-tertiary,#252836);color:var(--text-muted,#6b7280);border:1px solid var(--border,#2a2d3a);border-radius:4px;padding:2px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px}
    .sd-btn{background:var(--accent,#7c6af7);color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:.82rem;font-weight:600;cursor:pointer;transition:opacity .15s,transform .1s;white-space:nowrap}
    .sd-btn:hover{opacity:.85}.sd-btn:active{transform:scale(.97)}
    .sd-btn:disabled{opacity:.5;cursor:default}
    .sd-btn-success{background:var(--success,#22c55e)}
    .sd-msg{font-size:.78rem;margin-top:4px}
    .sd-msg.ok{color:var(--success,#22c55e)}.sd-msg.err{color:var(--warning,#f59e0b)}
    .sd-link{color:var(--accent,#7c6af7);text-decoration:none;font-size:.78rem}.sd-link:hover{text-decoration:underline}
    .sd-empty{color:var(--text-muted,#6b7280);font-size:.9rem;text-align:center;padding:40px 0}
    .sd-spinner{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:sd-spin .6s linear infinite;vertical-align:middle;margin-right:4px}
    @keyframes sd-spin{to{transform:rotate(360deg)}}
  `;

  function injectStyles() {
    if (document.getElementById('sd-styles')) return;
    const s = document.createElement('style');
    s.id = 'sd-styles';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2).toLowerCase(), v);
      else node.setAttribute(k, v);
    });
    children.flat().forEach(c => c && node.append(typeof c === 'string' ? document.createTextNode(c) : c));
    return node;
  }

  function renderCard(god, onSummon) {
    const msg = el('div', { className: 'sd-msg' });
    const link = el('a', { className: 'sd-link', href: '#god-rail', style: 'display:none' }, 'View in God Rail');
    const btn = el('button', {
      className: 'sd-btn',
      onClick: () => onSummon(god, btn, msg, link)
    }, 'Summon');

    return el('div', { className: 'sd-card' },
      el('p', { className: 'sd-card-name' }, god.name || god.id || ''),
      el('p', { className: 'sd-card-desc' }, god.description || 'No description provided.'),
      el('div', { className: 'sd-card-footer' },
        el('span', { className: 'sd-tag' }, god.author || god.domain || 'unknown'),
        el('div', { style: 'display:flex;flex-direction:column;align-items:flex-end;gap:4px' },
          btn, msg, link
        )
      )
    );
  }

  async function summonGod(god, btn, msg, link) {
    btn.disabled = true;
    btn.innerHTML = '<span class="sd-spinner"></span>Summoning…';
    msg.className = 'sd-msg';
    msg.textContent = '';
    link.style.display = 'none';
    try {
      const res = await fetch('/api/gods/summon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: god.name || god.id })
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
      btn.className = 'sd-btn sd-btn-success';
      btn.textContent = 'Summoned';
      msg.className = 'sd-msg ok';
      msg.textContent = 'God installed successfully.';
      link.style.display = 'inline';
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Retry';
      msg.className = 'sd-msg err';
      msg.textContent = e.message || 'Summon failed.';
    }
  }

  function buildPanel(container) {
    injectStyles();
    let gods = [], filtered = [];

    const grid = el('div', { className: 'sd-grid' });
    const empty = el('div', { className: 'sd-empty' }, 'No gods found.');
    const body = el('div', { className: 'sd-body' }, grid, empty);
    empty.style.display = 'none';

    function renderGrid(list) {
      grid.innerHTML = '';
      if (!list.length) { empty.style.display = ''; return; }
      empty.style.display = 'none';
      list.forEach(g => grid.append(renderCard(g, summonGod)));
    }

    const search = el('input', {
      className: 'sd-search', type: 'search', placeholder: 'Search gods…',
      onInput: e => {
        const q = e.target.value.toLowerCase().trim();
        filtered = q ? gods.filter(g =>
          (g.name || '').toLowerCase().includes(q) ||
          (g.description || '').toLowerCase().includes(q) ||
          (g.author || '').toLowerCase().includes(q) ||
          (g.domain || '').toLowerCase().includes(q)
        ) : gods;
        renderGrid(filtered);
      }
    });

    const close = el('button', { className: 'sd-close', title: 'Close' }, '×');
    const overlay = el('div', { className: 'sd-overlay', onClick: e => { if (e.target === overlay) destroy(); } },
      el('div', { className: 'sd-panel' },
        el('div', { className: 'sd-header' },
          el('h2', {}, 'Summon a God'),
          close
        ),
        el('div', { className: 'sd-search-wrap' }, search),
        body
      )
    );

    function destroy() {
      overlay.remove();
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Escape') destroy(); }
    close.addEventListener('click', destroy);
    document.addEventListener('keydown', onKey);

    container.append(overlay);
    search.focus();

    grid.innerHTML = '<div class="sd-empty" style="display:block">Loading…</div>';
    fetch('/api/gods/summon/list')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => {
        gods = Array.isArray(data) ? data : (data.gods || data.items || []);
        filtered = gods;
        renderGrid(filtered);
      })
      .catch(e => {
        grid.innerHTML = '';
        empty.textContent = 'Failed to load gods: ' + (e.message || 'unknown error');
        empty.style.display = '';
      });

    return { destroy };
  }

  window.mountSummonDrawer = function (container) {
    return buildPanel(container || document.body);
  };

  document.addEventListener('DOMContentLoaded', () => {
    const panel = document.getElementById('summon-drawer-panel');
    if (panel) window.mountSummonDrawer(panel);
  });
})();
