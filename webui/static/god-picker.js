/* ── Pantheon God Picker (Sidebar Grid) ──
 * 2x3 god grid above chat in sidebar, under logo.
 * Scrollable if >6 gods. Replaces the old fixed left rail.
 */
(function() {
  'use strict';

  var API_BASE = '';

  function createGodPicker() {
    var picker = document.createElement('div');
    picker.id = 'god-picker';
    picker.innerHTML = '<div class="gp-grid" id="gp-grid"></div>' +
      '<div class="gp-active" id="gp-active">Pantheon</div>';
    return picker;
  }

  function fetchGods() {
    return fetch(API_BASE + '/api/gods')
      .then(function(r) { return r.json(); })
      .then(function(data) { return data.gods || data || []; })
      .catch(function() { return []; });
  }

  function renderGodGrid(gods) {
    var grid = document.getElementById('gp-grid');
    var active = document.getElementById('gp-active');
    if (!grid) return;

    var activeGod = null;
    grid.innerHTML = gods.map(function(god) {
      var name = god.display_name || god.name || '?';
      var initial = name.charAt(0).toUpperCase();
      var icon = '/api/gods/' + encodeURIComponent(god.name || name) + '/icon';
      var activeCls = god.is_active ? ' active' : '';
      if (god.is_active) activeGod = name;
      return '<div class="gp-circle' + activeCls + '" data-god="' + (god.name || name) + '" title="' + name + '">' +
        '<img src="' + icon + '" class="gp-icon" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">' +
        '<span class="gp-initial" style="display:none">' + initial + '</span>' +
        '</div>';
    }).join('');

    if (activeGod) active.textContent = activeGod;
    else if (gods.length) active.textContent = gods[0].display_name || gods[0].name || 'Pantheon';

    // Click handlers
    grid.querySelectorAll('.gp-circle').forEach(function(c) {
      c.addEventListener('click', function() {
        switchGod(this.dataset.god);
      });
    });
  }

  function switchGod(godName) {
    fetch(API_BASE + '/api/profile/enter?name=' + encodeURIComponent(godName))
      .then(function(r) {
        if (r.redirected || r.ok) window.location.reload();
      })
      .catch(function() {
        window.location.href = API_BASE + '/api/profile/enter?name=' + encodeURIComponent(godName);
      });
  }

  function injectStyles() {
    if (document.getElementById('gp-styles')) return;
    var style = document.createElement('style');
    style.id = 'gp-styles';
    style.textContent = ''
      + '#god-picker { padding: 8px 10px 6px; border-bottom: 1px solid var(--border,#3B4A50); }'
      + '.gp-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; max-height: 120px; overflow-y: auto; }'
      + '.gp-grid::-webkit-scrollbar { width: 4px; }'
      + '.gp-grid::-webkit-scrollbar-thumb { background: var(--border,#3B4A50); border-radius: 2px; }'
      + '.gp-circle { width: 100%; aspect-ratio: 1; border-radius: 10px; background: var(--bg-secondary,#11100E); border: 2px solid transparent; cursor: pointer; display: flex; align-items: center; justify-content: center; overflow: hidden; transition: border-radius 0.15s, border-color 0.15s; position: relative; }'
      + '.gp-circle:hover { border-radius: 12px; border-color: var(--accent,#C6AC8F); }'
      + '.gp-circle.active { border-color: var(--accent,#C6AC8F); border-radius: 12px; }'
      + '.gp-icon { width: 100%; height: 100%; object-fit: cover; border-radius: inherit; }'
      + '.gp-initial { font-size: 14px; font-weight: 700; color: var(--text-primary,#EAE0D5); font-family: system-ui, sans-serif; }'
      + '.gp-active { font-size: 11px; color: var(--text-muted,#6b7c84); text-align: center; margin-top: 4px; font-weight: 500; }';
    document.head.appendChild(style);
  }

  function inject() {
    injectStyles();

    // Find the sidebar and insert the picker at the top
    function tryPlace() {
      var sidebar = document.querySelector('.sidebar');
      if (!sidebar) return false;

      var existing = document.getElementById('god-picker');
      if (existing) return true;

      var picker = createGodPicker();
      sidebar.insertBefore(picker, sidebar.firstChild);

      fetchGods().then(function(gods) {
        if (gods.length) renderGodGrid(gods);
        setInterval(function() {
          fetchGods().then(function(g) { if (g.length) renderGodGrid(g); });
        }, 30000);
      });
      return true;
    }

    // Retry until sidebar exists
    if (!tryPlace()) {
      var attempts = 0;
      var interval = setInterval(function() {
        attempts++;
        if (tryPlace() || attempts > 20) clearInterval(interval);
      }, 500);
    }
  }

  // Start after DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { setTimeout(inject, 1000); });
  } else {
    setTimeout(inject, 1000);
  }
})();
