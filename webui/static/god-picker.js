/* ── Pantheon God Picker (Sidebar Grid) ──
 * 2xN responsive god grid between logo and Chat in sidebar.
 * Gods max 50x50px. Responsive columns. Includes +New God button.
 */
(function() {
  'use strict';

  function createGodPicker() {
    var picker = document.createElement('div');
    picker.id = 'god-picker';
    picker.innerHTML = 
      '<div class="gp-label">Gods</div>' +
      '<div class="gp-grid" id="gp-grid"></div>';
    return picker;
  }

  function fetchGods() {
    return fetch('/api/gods')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var gods = data.gods || data || [];
        // Filter out hidden gods (like cachyOS sub-profile)
        return gods.filter(function(g) {
          return !(g.god && g.god.hidden) && !g.hidden;
        });
      })
      .catch(function() { return []; });
  }

  function renderGodGrid(gods) {
    var grid = document.getElementById('gp-grid');
    if (!grid) return;

    var activeGod = gods.find(function(g) { return g.is_active; });
    var activeName = activeGod ? (activeGod.display_name || activeGod.name) : 'Pantheon';

    grid.innerHTML = gods.map(function(god) {
      var name = god.display_name || god.name || '?';
      var initial = name.charAt(0).toUpperCase();
      var icon = '/api/gods/' + encodeURIComponent(god.name || name) + '/icon';
      var activeCls = god.is_active ? ' active' : '';
      return '<div class="gp-circle' + activeCls + '" data-god="' + (god.name || name) + '" title="' + name + '">' +
        '<img src="' + icon + '" class="gp-icon" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">' +
        '<span class="gp-initial" style="display:none">' + initial + '</span>' +
        '</div>';
    }).join('') +
    // +New God button
    '<div class="gp-circle gp-new" title="Create new god">' +
      '<span class="gp-new-icon">+</span>' +
    '</div>';

    // Click handlers for god circles
    grid.querySelectorAll('.gp-circle:not(.gp-new)').forEach(function(c) {
      c.addEventListener('click', function() {
        switchGod(this.dataset.god);
      });
    });

    // New god button
    var newBtn = grid.querySelector('.gp-new');
    if (newBtn) {
      newBtn.addEventListener('click', function() {
        window.openForgeWizard && window.openForgeWizard();
      });
    }
  }

  function switchGod(godName) {
    fetch('/api/profile/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: godName })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data && !data.error) {
        window.location.reload();
      }
    })
    .catch(function() {
      // Fallback: try GET
      window.location.href = '/api/profile/switch?name=' + encodeURIComponent(godName);
    });
  }

  function injectStyles() {
    if (document.getElementById('gp-styles')) return;
    var style = document.createElement('style');
    style.id = 'gp-styles';
    style.textContent = ''
      + '#god-picker { padding: 8px 12px 4px; }'
      + '.gp-label { font-size: 10px; text-transform: uppercase; color: var(--text-muted,#6b7c84); margin-bottom: 6px; font-weight: 600; letter-spacing: 0.5px; }'
      + '.gp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(44px, 1fr)); gap: 6px; max-height: 130px; overflow-y: auto; }'
      + '.gp-grid::-webkit-scrollbar { width: 3px; }'
      + '.gp-grid::-webkit-scrollbar-thumb { background: var(--border,#3B4A50); border-radius: 2px; }'
      + '.gp-circle { width: 100%; max-width: 50px; aspect-ratio: 1; border-radius: 10px; background: var(--bg-secondary,#11100E); border: 2px solid transparent; cursor: pointer; display: flex; align-items: center; justify-content: center; overflow: hidden; transition: border-radius 0.15s, border-color 0.15s; position: relative; margin: 0 auto; }'
      + '.gp-circle:hover { border-radius: 12px; border-color: var(--accent,#C6AC8F); }'
      + '.gp-circle.active { border-color: var(--accent,#C6AC8F); border-radius: 12px; }'
      + '.gp-icon { width: 100%; height: 100%; object-fit: cover; border-radius: inherit; }'
      + '.gp-initial { font-size: 14px; font-weight: 700; color: var(--text-primary,#EAE0D5); font-family: system-ui, sans-serif; }'
      + '.gp-new { border: 2px dashed var(--border,#3B4A50); }'
      + '.gp-new:hover { border-color: var(--accent,#C6AC8F); border-style: solid; }'
      + '.gp-new-icon { font-size: 20px; color: var(--text-muted,#6b7c84); font-weight: 300; }'
      + '.gp-new:hover .gp-new-icon { color: var(--accent,#C6AC8F); }';
    document.head.appendChild(style);
  }

  function inject() {
    injectStyles();

    function tryPlace() {
      // Find the sidebar-nav and insert BEFORE it (after logo/close, before Chat)
      var sidebarNav = document.querySelector('.sidebar-nav');
      if (!sidebarNav) return false;

      var existing = document.getElementById('god-picker');
      if (existing) return true;

      var picker = createGodPicker();
      sidebarNav.parentNode.insertBefore(picker, sidebarNav);

      fetchGods().then(function(gods) {
        if (gods.length) renderGodGrid(gods);
        // Refresh every 30s
        setInterval(function() {
          fetchGods().then(function(g) { if (g.length) renderGodGrid(g); });
        }, 30000);
      });
      return true;
    }

    if (!tryPlace()) {
      var attempts = 0;
      var interval = setInterval(function() {
        attempts++;
        if (tryPlace() || attempts > 30) clearInterval(interval);
      }, 400);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { setTimeout(inject, 1000); });
  } else {
    setTimeout(inject, 1000);
  }
})();
