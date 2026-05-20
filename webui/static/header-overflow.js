/* ── Pantheon Header Overflow Menu ──
 * Injects a ⋮ (three-dot) button into the Hermes UI header toolbar.
 * Shows a dropdown with overflow items: Search, Terminal, Settings,
 * User Profile, and God Management — freeing toolbar space.
 * Also provides a right-slide User Profile panel.
 */
(function() {
  'use strict';

  var menuOpen = false;
  var menuEl = null;
  var profilePanelOpen = false;

  // ── User Profile Panel (right-slide, like Boons) ──

  function createProfilePanel() {
    var existing = document.getElementById('user-profile-panel');
    if (existing) return existing;

    var panel = document.createElement('div');
    panel.id = 'user-profile-panel';
    panel.style.cssText = [
      'position:fixed;top:0;right:0;width:380px;max-width:92vw;height:100vh;',
      'z-index:9000;background:var(--bg-primary,#0a0908);',
      'border-left:1px solid var(--border,#3B4A50);',
      'box-shadow:-8px 0 32px rgba(0,0,0,0.5);',
      'display:flex;flex-direction:column;',
      'transform:translateX(100%);transition:transform 0.25s ease;',
      'font-family:system-ui,-apple-system,sans-serif;'
    ].join('');

    var userIcon = '';
    var userColor = '#6050b0';
    try {
      userIcon = localStorage.getItem('hermes-user-icon') || '';
      userColor = localStorage.getItem('hermes-user-color') || '#6050b0';
    } catch(e) {}

    panel.innerHTML = [
      '<div style="display:flex;align-items:center;justify-content:space-between;',
        'padding:14px 18px;border-bottom:1px solid var(--border,#3B4A50);flex-shrink:0">',
        '<h2 style="margin:0;font-size:1rem;font-weight:600;color:var(--text-primary,#EAE0D5)">👤 User Profile</h2>',
        '<button id="profile-panel-close" style="background:none;border:none;color:var(--text-muted);font-size:1.1rem;cursor:pointer;padding:4px 8px;border-radius:6px">✕</button>',
      '</div>',
      '<div id="profile-panel-body" style="flex:1;overflow:auto;padding:18px;display:flex;flex-direction:column;gap:16px">',
        // Icon upload section
        '<div style="border-bottom:1px solid var(--border,#3B4A50);padding-bottom:16px">',
          '<label style="display:block;font-size:13px;font-weight:600;color:var(--text-primary,#EAE0D5);margin-bottom:10px">Profile Icon</label>',
          '<div style="display:flex;gap:12px;align-items:center">',
            '<div id="profile-icon-preview" style="width:56px;height:56px;border-radius:10px;border:2px solid var(--accent,#7c6fe0);display:flex;align-items:center;justify-content:center;font-size:28px;background:var(--bg-secondary,#11100E);overflow:hidden;flex-shrink:0">',
              userIcon
                ? '<img src="' + userIcon.replace(/"/g,'&quot;') + '" style="width:100%;height:100%;object-fit:cover">'
                : '<span style="color:' + userColor + '">👤</span>',
            '</div>',
            '<label style="display:inline-flex;align-items:center;gap:4px;background:var(--bg-secondary,#11100E);border:1px solid var(--border,#3B4A50);border-radius:6px;padding:7px 14px;font-size:12px;color:var(--text-secondary,#C6AC8F);cursor:pointer;white-space:nowrap">',
              '📁 Upload',
              '<input type="file" accept="image/*" style="display:none" id="profile-icon-input">',
            '</label>',
            '<button id="profile-icon-clear" style="background:var(--bg-tertiary,#1a1a2e);color:var(--text-muted);border:1px solid var(--border,#3B4A50);border-radius:6px;padding:7px 10px;cursor:pointer;font-size:11px">Clear</button>',
          '</div>',
        '</div>',
        // Color picker section
        '<div style="border-bottom:1px solid var(--border,#3B4A50);padding-bottom:16px">',
          '<label style="display:block;font-size:13px;font-weight:600;color:var(--text-primary,#EAE0D5);margin-bottom:10px">Accent Color</label>',
          '<div style="display:flex;gap:12px;align-items:center">',
            '<input type="color" id="profile-color-input" value="' + userColor + '" style="width:44px;height:44px;border:none;border-radius:8px;cursor:pointer;padding:0;background:none">',
            '<span id="profile-color-hex" style="font-size:13px;color:var(--text-muted);font-family:monospace">' + userColor + '</span>',
            '<div id="profile-color-swatch" style="width:28px;height:28px;border-radius:6px;background:' + userColor + ';border:1px solid var(--border,#3B4A50)"></div>',
          '</div>',
        '</div>',
        // Info text
        '<div style="font-size:11px;color:var(--text-secondary,#a6adc8);line-height:1.5;padding:4px 0">',
          'Your profile icon and color are saved locally and appear on your messages.',
        '</div>',
      '</div>'
    ].join('\n');

    document.body.appendChild(panel);

    // Wire up events
    document.getElementById('profile-panel-close').onclick = closeProfilePanel;

    var fileInput = document.getElementById('profile-icon-input');
    fileInput.onchange = function() {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function(ev) {
        var dataUrl = ev.target.result;
        try { localStorage.setItem('hermes-user-icon', dataUrl); } catch(e) {}
        updateProfilePreview();
      };
      reader.readAsDataURL(file);
    };

    document.getElementById('profile-icon-clear').onclick = function() {
      try { localStorage.removeItem('hermes-user-icon'); } catch(e) {}
      updateProfilePreview();
    };

    var colorInput = document.getElementById('profile-color-input');
    colorInput.oninput = function() {
      var c = colorInput.value;
      try { localStorage.setItem('hermes-user-color', c); } catch(e) {}
      updateProfilePreview();
    };

    // Close on Escape
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && profilePanelOpen) closeProfilePanel();
    });

    return panel;
  }

  function updateProfilePreview() {
    var icon = '';
    var color = '#6050b0';
    try {
      icon = localStorage.getItem('hermes-user-icon') || '';
      color = localStorage.getItem('hermes-user-color') || '#6050b0';
    } catch(e) {}

    var preview = document.getElementById('profile-icon-preview');
    if (preview) {
      preview.innerHTML = icon
        ? '<img src="' + icon.replace(/"/g,'&quot;') + '" style="width:100%;height:100%;object-fit:cover">'
        : '<span style="color:' + color + '">👤</span>';
    }

    var colorInput = document.getElementById('profile-color-input');
    var colorHex = document.getElementById('profile-color-hex');
    var swatch = document.getElementById('profile-color-swatch');
    if (colorInput) colorInput.value = color;
    if (colorHex) colorHex.textContent = color;
    if (swatch) swatch.style.background = color;
  }

  function openProfilePanel() {
    var panel = createProfilePanel();
    panel.style.transform = 'translateX(0)';
    profilePanelOpen = true;
    updateProfilePreview();
  }

  function closeProfilePanel() {
    var panel = document.getElementById('user-profile-panel');
    if (panel) panel.style.transform = 'translateX(100%)';
    profilePanelOpen = false;
  }

  // ── Overflow Menu ──

  function createMenu() {
    if (menuEl) return menuEl;

    menuEl = document.createElement('div');
    menuEl.id = 'header-overflow-menu';
    menuEl.style.cssText = [
      'position:fixed;z-index:11000;',
      'background:var(--bg-panel,#1a1a1f);',
      'border:1px solid var(--border,rgba(255,255,255,0.1));',
      'border-radius:8px;padding:4px;min-width:190px;',
      'box-shadow:0 4px 20px rgba(0,0,0,0.4);',
      'display:none;',
      'font-family:system-ui,-apple-system,sans-serif;'
    ].join('');

    var items = [
      { icon: '🔍', label: 'Search', action: function() {
        var ev = new KeyboardEvent('keydown', { key: 'k', metaKey: true, ctrlKey: true, bubbles: true });
        document.dispatchEvent(ev);
      }},
      { icon: '📟', label: 'Terminal / Logs', action: function() {
        var termBtn = document.querySelector('.toolbar-pill button[title="Live terminal logs"]');
        if (termBtn) {
          termBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }
      }},
      { icon: '⚙️', label: 'Settings', action: function() {
        var ev = new KeyboardEvent('keydown', { key: ',', metaKey: true, ctrlKey: false, bubbles: true });
        document.dispatchEvent(ev);
        var settingsBtn = document.querySelector('.toolbar-pill [title="Settings"]');
        if (settingsBtn) {
          settingsBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }
      }},
      { type: 'separator' },
      { icon: '👤', label: 'User Profile', action: function() {
        closeMenu();
        openProfilePanel();
      }},
      { icon: '🤖', label: 'God Management', action: function() {
        closeMenu();
        var panel = document.getElementById('god-management-panel');
        if (!panel) return;
        var isVisible = panel.style.display !== 'none';
        if (isVisible) {
          panel.style.display = 'none';
          return;
        }
        panel.style.display = 'block';
        // Mount if not yet mounted
        if (!panel._mounted && typeof window.mountGodManagement === 'function') {
          window.mountGodManagement(panel);
          panel._mounted = true;
        }
        // Add close button to header
        var header = panel.querySelector('.gm-header');
        if (header && !header.querySelector('.gm-close-btn')) {
          var closeBtn = document.createElement('button');
          closeBtn.className = 'gm-close-btn';
          closeBtn.innerHTML = '✕';
          closeBtn.title = 'Close';
          closeBtn.style.cssText = 'background:none;border:none;color:var(--text-muted);font-size:1.1rem;cursor:pointer;padding:4px 8px;border-radius:6px;margin-left:auto';
          closeBtn.onclick = function() { panel.style.display = 'none'; };
          header.appendChild(closeBtn);
        }
        // Close on overlay click
        panel.onclick = function(e) {
          if (e.target === panel) panel.style.display = 'none';
        };
        // Close on Escape
        var escHandler = function(e) {
          if (e.key === 'Escape') {
            panel.style.display = 'none';
            document.removeEventListener('keydown', escHandler);
          }
        };
        document.addEventListener('keydown', escHandler);
      }}
    ];

    menuEl.innerHTML = items.map(function(item) {
      if (item.type === 'separator') {
        return '<div style="height:1px;background:var(--border,rgba(255,255,255,0.08));margin:4px 8px"></div>';
      }
      return '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:13px;color:var(--text-primary,#EAE0D5);transition:background 0.15s" ' +
        'onmouseenter="this.style.background=\'rgba(255,255,255,0.06)\'" ' +
        'onmouseleave="this.style.background=\'none\'">' +
        '<span style="font-size:16px;width:22px;text-align:center;flex-shrink:0">' + item.icon + '</span>' +
        '<span>' + item.label + '</span>' +
        '</div>';
    }).join('\n');

    menuEl.querySelectorAll('div').forEach(function(el, i) {
      // Only non-separator items
      var item = items[i];
      if (!item || item.type === 'separator') return;
      el.onclick = function(e) {
        e.stopPropagation();
        if (item.action) item.action();
      };
    });

    document.body.appendChild(menuEl);
    return menuEl;
  }

  function positionMenu() {
    var btn = document.getElementById('header-overflow-btn');
    var menu = createMenu();
    if (!btn || !menu) return;

    var rect = btn.getBoundingClientRect();
    menu.style.top = (rect.bottom + 6) + 'px';
    menu.style.right = (window.innerWidth - rect.right) + 'px';
    menu.style.display = 'block';
  }

  function openMenu() {
    positionMenu();
    menuOpen = true;
  }

  function closeMenu() {
    if (menuEl) menuEl.style.display = 'none';
    menuOpen = false;
  }

  function toggleMenu(e) {
    e.stopPropagation();
    if (menuOpen) closeMenu();
    else openMenu();
  }

  // Close on outside click
  document.addEventListener('click', function(e) {
    if (!menuOpen) return;
    var btn = document.getElementById('header-overflow-btn');
    if (btn && btn.contains(e.target)) return;
    if (menuEl && menuEl.contains(e.target)) return;
    closeMenu();
  });

  // ── Hide original buttons (moved into overflow menu) ──

  var HIDE_SELECTORS = [
    '.toolbar-pill button[title="Live terminal logs"]',
    '.toolbar-pill button[title="Search (⌘K)"]',
    '.toolbar-pill button[title*="Search"]',
    '.toolbar-pill button[title="Settings"]'
  ];

  function hideOriginalButtons() {
    if (document.getElementById('header-overflow-style')) return;
    var style = document.createElement('style');
    style.id = 'header-overflow-style';
    style.textContent = HIDE_SELECTORS.join(',\n') + ' { display: none !important; }';
    document.head.appendChild(style);
  }

  // ── Button injection ──

  function injectOverflowButton() {
    if (document.getElementById('header-overflow-btn')) return;

    var toolbar = document.querySelector('.toolbar-pill');
    if (!toolbar) return;

    hideOriginalButtons();

    var btn = document.createElement('button');
    btn.id = 'header-overflow-btn';
    btn.className = 'header-btn';
    btn.title = 'More';
    btn.innerHTML = '⋮';
    btn.style.cssText = 'background:none;border:1px solid transparent;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:18px;color:var(--text-secondary);display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;transition:all 0.2s;font-weight:700;letter-spacing:1px';
    btn.onmouseenter = function() { btn.style.background = 'var(--bg-tertiary)'; };
    btn.onmouseleave = function() { if (!menuOpen) btn.style.background = 'none'; };
    btn.onclick = toggleMenu;

    // Insert as the last item in the toolbar
    toolbar.appendChild(btn);
  }

  // ── Startup ──

  var pollCount = 0;
  var pollInterval = setInterval(function() {
    injectOverflowButton();
    pollCount++;
    if (document.getElementById('header-overflow-btn') || pollCount > 40) {
      clearInterval(pollInterval);
    }
  }, 400);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(injectOverflowButton, 1600);
    });
  } else {
    setTimeout(injectOverflowButton, 1600);
  }

})();
