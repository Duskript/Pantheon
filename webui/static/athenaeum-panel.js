(() => {
'use strict';

// ── helpers ──────────────────────────────────────────────────────────────────

async function api(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'cls') e.className = v;
    else if (k === 'style') Object.assign(e.style, v);
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}

function renderMarkdown(md) {
  if (typeof marked !== 'undefined') return marked.parse(md);
  // minimal inline renderer
  const escaped = md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped
    .replace(/^#{6}\s(.+)$/gm, '<h6>$1</h6>')
    .replace(/^#{5}\s(.+)$/gm, '<h5>$1</h5>')
    .replace(/^#{4}\s(.+)$/gm, '<h4>$1</h4>')
    .replace(/^#{3}\s(.+)$/gm, '<h3>$1</h3>')
    .replace(/^#{2}\s(.+)$/gm, '<h2>$1</h2>')
    .replace(/^#\s(.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^[-*]\s(.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, s => `<ul>${s}</ul>`)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/^(?!<[hpuol])(.+)$/gm, '$1<br>')
    .replace(/^(.)/m, '<p>$&')
    .concat('</p>');
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ── styles ────────────────────────────────────────────────────────────────────

const CSS = `
#athenaeum-panel {
  display:flex; height:100%; overflow:hidden;
  background:var(--bg); color:var(--text);
  font-family:inherit; font-size:14px;
}
.ath-left {
  width:280px; min-width:160px; max-width:520px;
  display:flex; flex-direction:column;
  background:var(--sidebar); border-right:1px solid var(--border);
  overflow:hidden;
}
.ath-left-header {
  padding:12px 14px 10px; border-bottom:1px solid var(--border);
  font-size:11px; font-weight:600; letter-spacing:.06em;
  text-transform:uppercase; color:var(--muted); flex-shrink:0;
}
.ath-tree { flex:1; overflow-y:auto; padding:6px 0; }
.ath-tree-item {
  display:flex; align-items:center; gap:6px;
  padding:5px 14px; cursor:pointer; user-select:none;
  border-radius:0; transition:background .1s;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.ath-tree-item:hover { background:var(--accent-bg, rgba(128,128,128,.1)); }
.ath-tree-item.active { background:var(--accent-bg-strong, rgba(128,128,128,.18)); color:var(--accent); }
.ath-tree-item .icon { flex-shrink:0; font-size:12px; width:14px; text-align:center; }
.ath-tree-item .name { overflow:hidden; text-overflow:ellipsis; }
.ath-tree-children { display:none; }
.ath-tree-children.open { display:block; }
.ath-divider {
  width:4px; cursor:col-resize; background:transparent; flex-shrink:0;
  transition:background .15s;
}
.ath-divider:hover, .ath-divider.dragging { background:var(--accent); }
.ath-right {
  flex:1; display:flex; flex-direction:column; overflow:hidden;
}
.ath-search-bar {
  display:flex; gap:8px; padding:10px 14px;
  border-bottom:1px solid var(--border); flex-shrink:0;
}
.ath-search-input {
  flex:1; background:var(--code-bg, var(--bg));
  border:1px solid var(--border); border-radius:6px;
  padding:6px 10px; color:var(--text); font-size:13px; outline:none;
}
.ath-search-input:focus { border-color:var(--accent); }
.ath-btn {
  background:var(--accent-bg, rgba(128,128,128,.15));
  border:1px solid var(--border); border-radius:6px;
  padding:6px 12px; cursor:pointer; color:var(--text);
  font-size:12px; white-space:nowrap; transition:background .1s;
}
.ath-btn:hover { background:var(--accent-bg-strong, rgba(128,128,128,.25)); }
.ath-btn.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
.ath-btn.primary:hover { background:var(--accent-hover, var(--accent)); filter:brightness(1.1); }
.ath-breadcrumb {
  padding:6px 16px 4px; font-size:11px; color:var(--muted);
  flex-shrink:0; border-bottom:1px solid var(--border);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.ath-content { flex:1; overflow-y:auto; padding:20px 24px; }
.ath-content h1,h2,h3,h4,h5,h6 { color:var(--text); margin:1.2em 0 .5em; }
.ath-content h1 { font-size:1.5em; }
.ath-content h2 { font-size:1.25em; }
.ath-content p { line-height:1.65; margin:.6em 0; }
.ath-content code {
  background:var(--code-bg, rgba(128,128,128,.15)); padding:1px 5px;
  border-radius:3px; font-size:.9em;
}
.ath-content pre {
  background:var(--code-bg, rgba(128,128,128,.15)); padding:14px 16px;
  border-radius:8px; overflow-x:auto; font-size:.85em; line-height:1.55;
}
.ath-content ul,ol { padding-left:22px; }
.ath-content a { color:var(--accent); }
.ath-content a:hover { text-decoration:underline; }
.ath-state {
  display:flex; flex-direction:column; align-items:center;
  justify-content:center; height:100%; gap:10px;
  color:var(--muted); font-size:13px; text-align:center; padding:24px;
}
.ath-state .icon { font-size:28px; }
.ath-search-results {
  border-top:1px solid var(--border); background:var(--sidebar);
  flex-shrink:0; max-height:220px; overflow-y:auto;
}
.ath-result-item {
  padding:9px 16px; border-bottom:1px solid var(--border);
  cursor:pointer; transition:background .1s;
}
.ath-result-item:hover { background:var(--accent-bg, rgba(128,128,128,.1)); }
.ath-result-item .r-path { font-size:11px; color:var(--accent); margin-bottom:2px; }
.ath-result-item .r-snippet { font-size:12px; color:var(--muted); }
.ath-graph-panel {
  border-top:1px solid var(--border); background:var(--sidebar);
  flex-shrink:0; max-height:260px; overflow-y:auto; padding:12px 16px;
}
.ath-graph-panel h4 { margin:0 0 10px; font-size:12px; font-weight:600;
  text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
.ath-graph-node {
  display:flex; align-items:flex-start; gap:8px; padding:6px 0;
  border-bottom:1px solid var(--border);
}
.ath-graph-node:last-child { border-bottom:none; }
.ath-graph-node .gn-type {
  font-size:10px; padding:2px 6px; border-radius:10px; flex-shrink:0;
  background:var(--accent-bg, rgba(128,128,128,.15)); color:var(--accent);
  margin-top:1px;
}
.ath-graph-node .gn-name { font-size:13px; font-weight:500; }
.ath-graph-node .gn-desc { font-size:11px; color:var(--muted); margin-top:2px; }
.ath-spinner {
  width:20px; height:20px; border-radius:50%;
  border:2px solid var(--border); border-top-color:var(--accent);
  animation:ath-spin .6s linear infinite;
}
@keyframes ath-spin { to { transform:rotate(360deg); } }
`;

function injectStyles() {
  if (document.getElementById('athenaeum-styles')) return;
  const s = document.createElement('style');
  s.id = 'athenaeum-styles';
  s.textContent = CSS;
  document.head.appendChild(s);
}

// ── tree helpers ──────────────────────────────────────────────────────────────

function buildTree(node, depth, onFileClick) {
  if (!node) return null;
  const indent = depth * 14;

  if (node.type === 'file' && node.name.endsWith('.md')) {
    const item = el('div', { cls: 'ath-tree-item', style: { paddingLeft: `${14 + indent}px` } },
      el('span', { cls: 'icon' }, '📄'),
      el('span', { cls: 'name', title: node.name }, node.name)
    );
    item.addEventListener('click', () => onFileClick(node.path, item));
    return item;
  }

  if (node.type === 'directory' || node.children) {
    const children = el('div', { cls: 'ath-tree-children' });
    const toggle = el('span', { cls: 'icon' }, '▶');
    const header = el('div', {
      cls: 'ath-tree-item',
      style: { paddingLeft: `${14 + indent}px` }
    }, toggle, el('span', { cls: 'name', title: node.name }, node.name));

    let open = depth === 0;
    const refresh = () => {
      toggle.textContent = open ? '▼' : '▶';
      children.classList.toggle('open', open);
    };
    header.addEventListener('click', () => { open = !open; refresh(); });

    for (const child of (node.children || [])) {
      const c = buildTree(child, depth + 1, onFileClick);
      if (c) children.appendChild(c);
    }
    refresh();
    const wrap = document.createDocumentFragment();
    wrap.appendChild(header);
    wrap.appendChild(children);
    return wrap;
  }
  return null;
}

// ── main mount ────────────────────────────────────────────────────────────────

function mountAthenaeum(container) {
  injectStyles();
  container.id = 'athenaeum-panel';

  // ── state
  let activeFileItem = null;
  let searchResultsVisible = false;
  let graphPanelVisible = false;

  // ── left pane
  const treeEl = el('div', { cls: 'ath-tree' });
  const leftPane = el('div', { cls: 'ath-left' },
    el('div', { cls: 'ath-left-header' }, '📚 Codexes'),
    treeEl
  );

  // ── right pane pieces
  const searchInput = el('input', {
    cls: 'ath-search-input',
    type: 'text',
    placeholder: 'Search knowledge base…'
  });
  const graphBtn = el('button', { cls: 'ath-btn' }, '🕸 Graph');
  const searchBar = el('div', { cls: 'ath-search-bar' }, searchInput, graphBtn);
  const breadcrumb = el('div', { cls: 'ath-breadcrumb' }, ' ');
  const contentEl = el('div', { cls: 'ath-content' });
  const searchResults = el('div', { cls: 'ath-search-results', style: { display: 'none' } });
  const graphPanel = el('div', { cls: 'ath-graph-panel', style: { display: 'none' } });

  const rightPane = el('div', { cls: 'ath-right' },
    searchBar, breadcrumb, contentEl, searchResults, graphPanel
  );

  // ── resizable divider
  const divider = el('div', { cls: 'ath-divider' });
  let dragging = false;
  divider.addEventListener('mousedown', e => {
    dragging = true;
    divider.classList.add('dragging');
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const rect = container.getBoundingClientRect();
    const w = Math.max(160, Math.min(520, e.clientX - rect.left));
    leftPane.style.width = w + 'px';
  });
  document.addEventListener('mouseup', () => {
    dragging = false;
    divider.classList.remove('dragging');
  });

  container.append(leftPane, divider, rightPane);

  // ── content helpers
  function setContent(html, path) {
    contentEl.innerHTML = html;
    breadcrumb.textContent = path || ' ';
    hideSearchResults();
  }

  function showState(icon, msg) {
    contentEl.innerHTML = '';
    contentEl.appendChild(el('div', { cls: 'ath-state' },
      el('div', { cls: 'icon' }, icon),
      el('span', {}, msg)
    ));
  }

  function showSpinner() {
    contentEl.innerHTML = '';
    contentEl.appendChild(el('div', { cls: 'ath-state' }, el('div', { cls: 'ath-spinner' })));
  }

  function hideSearchResults() {
    searchResults.style.display = 'none';
    searchResultsVisible = false;
  }

  // ── load file
  async function loadFile(path, item) {
    if (activeFileItem) activeFileItem.classList.remove('active');
    activeFileItem = item;
    item?.classList.add('active');
    showSpinner();
    try {
      const data = await api(`/api/athenaeum/read?path=${encodeURIComponent(path)}`);
      const html = renderMarkdown(data.content || data.text || '');
      setContent(html, path);
    } catch (err) {
      showState('⚠️', `Failed to load: ${err.message}`);
    }
  }

  // ── load codex tree
  async function loadCodexTree(codexName) {
    const existing = treeEl.querySelector(`[data-codex="${codexName}"]`);
    if (existing) { existing._toggle?.(); return; }

    const placeholder = el('div', { cls: 'ath-state', style: { height: '60px' } },
      el('div', { cls: 'ath-spinner' })
    );
    treeEl.appendChild(placeholder);

    try {
      const data = await api(`/api/athenaeum/walk?path=${encodeURIComponent(codexName + '/INDEX.md')}`);
      placeholder.remove();
      const frag = buildTree(
        { type: 'directory', name: codexName, children: data.tree || data.children || [] },
        0,
        loadFile
      );
      if (frag) {
        const wrapper = el('div', { 'data-codex': codexName });
        wrapper.appendChild(frag);
        treeEl.appendChild(wrapper);
      }
    } catch (err) {
      placeholder.replaceWith(el('div', { cls: 'ath-state', style: { height: '60px', fontSize: '12px' } },
        `⚠️ ${err.message}`
      ));
    }
  }

  // ── populate codex list
  async function loadCodexList() {
    treeEl.innerHTML = '';
    treeEl.appendChild(el('div', { cls: 'ath-state', style: { height: '80px' } },
      el('div', { cls: 'ath-spinner' })
    ));
    try {
      const data = await api('/api/athenaeum/list');
      treeEl.innerHTML = '';
      const codexes = data.codexes || [];
      if (!codexes.length) {
        treeEl.appendChild(el('div', { cls: 'ath-state' }, el('div', { cls: 'icon' }, '📭'), 'No codexes found'));
        return;
      }
      for (const name of codexes) {
        const item = el('div', { cls: 'ath-tree-item' },
          el('span', { cls: 'icon' }, '📖'),
          el('span', { cls: 'name', title: name }, name)
        );
        item.addEventListener('click', () => loadCodexTree(name));
        treeEl.appendChild(item);
      }
    } catch (err) {
      treeEl.innerHTML = '';
      treeEl.appendChild(el('div', { cls: 'ath-state' }, el('div', { cls: 'icon' }, '⚠️'), err.message));
    }
  }

  // ── semantic search
  async function doSearch(query) {
    if (!query.trim()) { hideSearchResults(); return; }
    searchResults.innerHTML = '';
    searchResults.style.display = 'block';
    searchResultsVisible = true;
    searchResults.appendChild(el('div', { cls: 'ath-state', style: { height: '48px' } },
      el('div', { cls: 'ath-spinner' })
    ));
    try {
      const data = await api(`/api/athenaeum/search?query=${encodeURIComponent(query)}&n_results=5`);
      searchResults.innerHTML = '';
      const results = data.results || [];
      if (!results.length) {
        searchResults.appendChild(el('div', { cls: 'ath-state', style: { height: '48px', fontSize: '12px' } },
          'No results found'
        ));
        return;
      }
      for (const r of results) {
        const item = el('div', { cls: 'ath-result-item' },
          el('div', { cls: 'r-path' }, r.path || r.file || ''),
          el('div', { cls: 'r-snippet' }, r.snippet || r.text || r.content || '')
        );
        item.addEventListener('click', () => {
          if (r.path || r.file) loadFile(r.path || r.file, null);
          hideSearchResults();
          searchInput.value = '';
        });
        searchResults.appendChild(item);
      }
    } catch (err) {
      searchResults.innerHTML = '';
      searchResults.appendChild(el('div', { cls: 'ath-state', style: { height: '48px', fontSize: '12px' } },
        `⚠️ ${err.message}`
      ));
    }
  }

  searchInput.addEventListener('input', debounce(e => doSearch(e.target.value), 350));
  searchInput.addEventListener('keydown', e => {
    if (e.key === 'Escape') { hideSearchResults(); searchInput.value = ''; }
  });

  // ── graph search
  async function doGraphSearch(query) {
    if (!query.trim()) return;
    graphPanel.innerHTML = '';
    graphPanel.style.display = 'block';
    graphPanelVisible = true;
    graphPanel.appendChild(el('div', { cls: 'ath-state', style: { height: '60px' } },
      el('div', { cls: 'ath-spinner' })
    ));
    try {
      const data = await api(`/api/athenaeum/graph-search?query=${encodeURIComponent(query)}`);
      graphPanel.innerHTML = '';
      const nodes = data.nodes || data.results || [];
      graphPanel.appendChild(el('h4', {}, `Graph: "${query}"`));
      if (!nodes.length) {
        graphPanel.appendChild(el('div', { style: { color: 'var(--muted)', fontSize: '12px' } }, 'No graph results'));
        return;
      }
      for (const n of nodes) {
        graphPanel.appendChild(el('div', { cls: 'ath-graph-node' },
          el('span', { cls: 'gn-type' }, n.type || 'node'),
          el('div', {},
            el('div', { cls: 'gn-name' }, n.name || n.id || ''),
            el('div', { cls: 'gn-desc' }, n.description || n.summary || '')
          )
        ));
      }
    } catch (err) {
      graphPanel.innerHTML = '';
      graphPanel.appendChild(el('div', { cls: 'ath-state', style: { height: '60px', fontSize: '12px' } },
        `⚠️ ${err.message}`
      ));
    }
  }

  graphBtn.addEventListener('click', () => {
    if (graphPanelVisible) {
      graphPanel.style.display = 'none';
      graphPanelVisible = false;
    } else {
      const q = searchInput.value.trim() || breadcrumb.textContent.trim();
      doGraphSearch(q);
    }
  });

  // ── initial state
  showState('📚', 'Select a file from the tree');
  loadCodexList();
}

// ── auto-mount ────────────────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  window.mountAthenaeum = mountAthenaeum;
  const existing = document.getElementById('athenaeum-panel');
  if (existing) mountAthenaeum(existing);
}
})();
