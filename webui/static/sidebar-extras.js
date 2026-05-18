/* ── Pantheon Sidebar Extras ──
 * Injects Boons, Ideas, Athenaeum into the sidebar "More tools" (nav-extra).
 * Uses polling instead of MutationObserver to avoid React reconciliation conflicts.
 */
(function() {
  'use strict';

  var injected = false;

  function injectExtras() {
    var navExtra = document.querySelector('.nav-extra');
    if (!navExtra) {
      injected = false;
      return;
    }

    if (injected) return; // Only inject once per appearance

    var existingLabels = [];
    navExtra.querySelectorAll('.nav-item-label').forEach(function(el) {
      existingLabels.push(el.textContent.trim());
    });

    // 1. Boons
    if (!existingLabels.includes('Boons')) {
      var boonsBtn = document.createElement('div');
      boonsBtn.className = 'nav-item pantheon-extra';
      boonsBtn.innerHTML = '<span class="nav-item-icon" style="color:#c9a754">📦</span><span class="nav-item-label">Boons</span>';
      boonsBtn.onclick = function() { window.openBoonsManager && window.openBoonsManager(); };
      boonsBtn.title = 'View saved boons';
      navExtra.appendChild(boonsBtn);
    }

    // 2. Ideas
    if (!existingLabels.includes('Ideas')) {
      var ideasBtn = document.createElement('div');
      ideasBtn.className = 'nav-item pantheon-extra';
      ideasBtn.innerHTML = '<span class="nav-item-icon" style="color:#e0c562">💡</span><span class="nav-item-label">Ideas</span>';
      ideasBtn.onclick = function() { window.openIdeasPanel && window.openIdeasPanel(); };
      ideasBtn.title = 'Project ideas and plans';
      navExtra.appendChild(ideasBtn);
    }

    // 3. Athenaeum
    if (!existingLabels.includes('Athenaeum')) {
      var athBtn = document.createElement('div');
      athBtn.className = 'nav-item pantheon-extra';
      athBtn.innerHTML = '<span class="nav-item-icon" style="color:#a589c5">📚</span><span class="nav-item-label">Athenaeum</span>';
      athBtn.onclick = function() { window.openAthenaeumPanel && window.openAthenaeumPanel(); };
      athBtn.title = 'Knowledge graph search';
      navExtra.appendChild(athBtn);
    }

    injected = true;
  }

  // Poll for nav-extra every 500ms. When gone, reset injected flag.
  setInterval(function() {
    var navExtra = document.querySelector('.nav-extra');
    if (navExtra) {
      injectExtras();
    } else {
      injected = false;
    }
  }, 500);

  // Initial injection after DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { setTimeout(injectExtras, 1500); });
  } else {
    setTimeout(injectExtras, 1500);
  }
})();
