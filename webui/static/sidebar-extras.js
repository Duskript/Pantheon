/* ── Pantheon Sidebar Extras ──
 * Injects Boons, Ideas, Athenaeum into the sidebar "More tools" (nav-extra).
 */
(function() {
  'use strict';

  function injectExtras() {
    var navExtra = document.querySelector('.nav-extra');
    if (!navExtra) {
      setTimeout(injectExtras, 500);
      return;
    }

    // Remove existing injections
    document.querySelectorAll('.pantheon-extra').forEach(function(el) { el.remove(); });

    var existingLabels = [];
    navExtra.querySelectorAll('.nav-item-label').forEach(function(el) {
      existingLabels.push(el.textContent.trim());
    });

    // 1. Boons
    if (!existingLabels.includes('Boons')) {
      var boonsBtn = document.createElement('div');
      boonsBtn.className = 'nav-item pantheon-extra';
      boonsBtn.style.cssText = '';
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
  }

  // Watch for nav-extra appearing (it's conditional on sidebarToolsExpanded)
  var observer = new MutationObserver(function() {
    injectExtras();
  });

  function start() {
    injectExtras();
    var sidebar = document.querySelector('.sidebar');
    if (sidebar) {
      observer.observe(sidebar, { childList: true, subtree: true });
    } else {
      setTimeout(start, 500);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { setTimeout(start, 1500); });
  } else {
    setTimeout(start, 1500);
  }
})();
