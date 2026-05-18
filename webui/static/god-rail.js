/* ── Pantheon God Rail ──
 * Standalone component: left sidebar with god circles (Discord server list style).
 * Injects into DOM outside React. Fetches from /api/gods.
 */
(function() {
  'use strict';

  const API_BASE = '';
  const RAIL_WIDTH = '56px';

  function createGodRail() {
    // Create rail container
    const rail = document.createElement('div');
    rail.id = 'god-rail';
    rail.innerHTML = `
      <div class="god-rail-inner">
        <div class="god-rail-gods" id="god-rail-list"></div>
        <div class="god-rail-bottom">
          <button class="god-rail-btn" id="god-rail-settings" title="Settings">⚙</button>
        </div>
      </div>
    `;

    // Inject before the React root
    const root = document.getElementById('root');
    if (root) root.parentNode.insertBefore(rail, root);

    return rail;
  }

  function fetchGods() {
    return fetch(API_BASE + '/api/gods')
      .then(r => r.json())
      .then(data => {
        const gods = data.gods || data || [];
        return Array.isArray(gods) ? gods : [];
      })
      .catch(() => []);
  }

  function renderGodCircles(gods) {
    const list = document.getElementById('god-rail-list');
    if (!list) return;

    list.innerHTML = gods.map((god, i) => {
      const name = god.name || god.display_name || 'Unknown';
      const initial = name.charAt(0).toUpperCase();
      const iconUrl = god.icon_url || (API_BASE + '/api/gods/' + encodeURIComponent(name) + '/icon');
      const active = god.active ? ' active' : '';
      const statusDot = god.status === 'running' ? 'online' : 
                        god.status === 'error' ? 'error' : 'offline';

      return `
        <div class="god-rail-circle ${active}" data-god="${name}" title="${name}">
          <img src="${iconUrl}" alt="${name}" class="god-rail-icon" 
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
          <span class="god-rail-initial" style="display:none">${initial}</span>
          <span class="god-rail-status ${statusDot}"></span>
        </div>
      `;
    }).join('');

    // Click handlers
    list.querySelectorAll('.god-rail-circle').forEach(circle => {
      circle.addEventListener('click', function() {
        const godName = this.dataset.god;
        switchGod(godName);
      });
    });
  }

  // ── God Profile Chip (in composer) ──
  var activeGod = 'Pantheon';
  function updateProfileChip(name) {
    activeGod = name;
    var chip = document.getElementById('god-profile-chip');
    if (!chip) {
      chip = document.createElement('div');
      chip.id = 'god-profile-chip';
      chip.style.cssText = 'position:fixed;bottom:70px;left:68px;z-index:500;display:flex;align-items:center;gap:8px;background:var(--bg-secondary,#11100E);border:1px solid var(--border,#3B4A50);border-radius:8px;padding:5px 12px;font-size:12px;color:var(--text-secondary,#C6AC8F);font-family:system-ui,sans-serif;font-weight:500;cursor:pointer;transition:border-color 0.2s';
      chip.title = 'Active god — click to switch';
      chip.onclick = function() {
        // Open god management if available, else reload god rail
        var gmPanel = document.getElementById('god-management-panel');
        if (gmPanel && window.mountGodManagement) {
          gmPanel.style.display = 'block';
          window.mountGodManagement(gmPanel);
        }
      };
      document.body.appendChild(chip);
    }
    chip.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:var(--success,#86C08B)"></span>' + name;
  }

  function switchGod(godName) {
    activeGod = godName;
    updateProfileChip(godName);
    // Switch profile via API
    fetch(API_BASE + '/api/profile/enter?name=' + encodeURIComponent(godName))
      .then(r => {
        if (r.redirected || r.ok) {
          // Profile switch succeeded — reload to pick up new context
          window.location.reload();
        }
      })
      .catch(() => {
        // Fallback: try direct navigation
        window.location.href = API_BASE + '/api/profile/enter?name=' + encodeURIComponent(godName);
      });
  }

  // Inject CSS
  function injectStyles() {
    const style = document.createElement('style');
    style.textContent = `
      #god-rail {
        position: fixed;
        left: 0;
        top: 0;
        bottom: 0;
        width: ${RAIL_WIDTH};
        background: var(--bg-tertiary, #0d0d14);
        border-right: 1px solid var(--border, rgba(255,255,255,0.06));
        z-index: 1000;
        display: flex;
        flex-direction: column;
      }
      .god-rail-inner {
        display: flex;
        flex-direction: column;
        height: 100%;
        padding: 12px 0;
      }
      .god-rail-gods {
        flex: 1;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        padding: 4px;
      }
      .god-rail-circle {
        width: 42px;
        height: 42px;
        border-radius: 12px;
        background: var(--bg-secondary, #1a1a2e);
        border: 2px solid transparent;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        transition: border-radius 0.2s, border-color 0.2s, background 0.2s;
        overflow: hidden;
      }
      .god-rail-circle:hover {
        border-radius: 14px;
        border-color: var(--accent, #7c6fe0);
        background: var(--accent-dim, rgba(124,111,224,0.12));
      }
      .god-rail-circle.active {
        border-radius: 14px;
        border-color: var(--accent, #7c6fe0);
        background: var(--accent-dim, rgba(124,111,224,0.18));
      }
      .god-rail-icon {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: inherit;
      }
      .god-rail-initial {
        font-size: 18px;
        font-weight: 700;
        color: var(--text-primary, #eae0d5);
        font-family: system-ui, sans-serif;
      }
      .god-rail-status {
        position: absolute;
        bottom: -2px;
        right: -2px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        border: 2px solid var(--bg-tertiary, #0d0d14);
      }
      .god-rail-status.online { background: var(--success, #86c08b); }
      .god-rail-status.error { background: var(--error, #f87171); }
      .god-rail-status.offline { background: var(--text-muted, #666); }
      .god-rail-bottom {
        padding: 8px;
        display: flex;
        justify-content: center;
        border-top: 1px solid var(--border, rgba(255,255,255,0.06));
      }
      .god-rail-btn {
        width: 36px;
        height: 36px;
        border-radius: 12px;
        background: var(--bg-secondary, #1a1a2e);
        border: 1px solid var(--border, rgba(255,255,255,0.06));
        color: var(--text-secondary, #8888a0);
        cursor: pointer;
        font-size: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s, color 0.2s;
      }
      .god-rail-btn:hover {
        background: var(--accent-dim, rgba(124,111,224,0.12));
        color: var(--text-primary, #eae0d5);
      }

      /* Push main content right to make room for rail */
      #root {
        margin-left: ${RAIL_WIDTH} !important;
      }
      /* Adjust the existing sidebar if it also has a left edge */
      .sidebar {
        margin-left: 0 !important;
      }
    `;
    document.head.appendChild(style);
  }

  // Initialize
  function init() {
    if (document.getElementById('god-rail')) return; // already injected

    injectStyles();
    createGodRail();

    // Fetch gods and render
    fetchGods().then(gods => {
      if (gods.length) renderGodCircles(gods);
      // Poll every 30s for status updates
      setInterval(() => {
        fetchGods().then(g => { if (g.length) renderGodCircles(g); });
      }, 30000);
    });

    // Settings button
    setTimeout(() => {
      const btn = document.getElementById('god-rail-settings');
      if (btn) {
        btn.addEventListener('click', () => {
          // Trigger the existing settings modal in the React header
          const settingsBtn = document.querySelector('.toolbar-pill [title="Settings"], .header-controls [title="Settings"]');
          if (settingsBtn) settingsBtn.click();
        });
      }
    }, 2000);
  }

  // Wait for DOM + React to mount
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(init, 1500));
  } else {
    setTimeout(init, 1500);
  }
})();
