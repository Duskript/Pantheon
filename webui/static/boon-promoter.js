/* ── Promote-to-Boon Injector ──
 * Watches the DOM for artifact cards and adds "Promote to Boon" buttons.
 * Runs after React mounts — attaches to .artifact-card elements.
 */
(function() {
  'use strict';

  function promoteToBoon(artifact) {
    const payload = {
      content: artifact.content || '',
      type: artifact.type || 'text',
      source_message_id: artifact.messageId || '',
      metadata: JSON.stringify({
        fileName: artifact.fileName || '',
        filePath: artifact.filePath || '',
        promoted_at: new Date().toISOString()
      })
    };

    fetch('/api/boons/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(data => {
      if (data.ok || data.boon_id) {
        showToast('📌 Promoted to Boons', 'success');
      } else {
        showToast('Failed: ' + (data.error || 'unknown'), 'error');
      }
    })
    .catch(err => {
      showToast('Boon save failed: ' + err.message, 'error');
    });
  }

  function showToast(text, type) {
    const toast = document.createElement('div');
    toast.textContent = text;
    Object.assign(toast.style, {
      position: 'fixed', bottom: '24px', right: '24px', zIndex: '99999',
      background: type === 'success' ? 'rgba(68,216,138,0.95)' : 'rgba(255,107,107,0.95)',
      color: '#0a0a14', padding: '10px 20px', borderRadius: '10px',
      fontSize: '13px', fontWeight: '600', fontFamily: 'system-ui, sans-serif',
      boxShadow: '0 4px 20px rgba(0,0,0,0.4)', transition: 'opacity 0.3s'
    });
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 2500);
  }

  function addPromoteButtons() {
    // Find all artifact iframes and cards
    const containers = document.querySelectorAll('[class*="artifact"]');
    containers.forEach(el => {
      if (el.dataset.boonButtonAdded) return;
      el.dataset.boonButtonAdded = '1';

      const btn = document.createElement('button');
      btn.textContent = '📌 Promote to Boon';
      Object.assign(btn.style, {
        position: 'absolute', top: '4px', right: '4px', zIndex: '100',
        background: 'rgba(69,136,224,0.15)', color: '#4588e0',
        border: '1px solid rgba(69,136,224,0.35)', borderRadius: '6px',
        padding: '3px 8px', fontSize: '10px', fontWeight: '600',
        cursor: 'pointer', fontFamily: 'system-ui, sans-serif',
        backdropFilter: 'blur(8px)'
      });
      btn.onclick = function(e) {
        e.stopPropagation();
        // Try to find the artifact data from a parent or sibling
        const dataEl = el.closest('[data-artifact]') || el;
        const artifact = {
          type: dataEl.dataset.type || 'html',
          content: dataEl.dataset.content || '',
          fileName: dataEl.dataset.filename || '',
          filePath: dataEl.dataset.filepath || ''
        };
        promoteToBoon(artifact);
      };
      el.style.position = el.style.position || 'relative';
      el.appendChild(btn);
    });
  }

  // Watch for new artifacts (DOM mutation observer)
  const observer = new MutationObserver(function(mutations) {
    for (const m of mutations) {
      if (m.addedNodes.length) addPromoteButtons();
    }
  });

  // Start after React mounts
  function start() {
    addPromoteButtons();
    observer.observe(document.getElementById('root') || document.body, {
      childList: true, subtree: true
    });
  }

  if (document.readyState === 'loading') {
    // Wait for React to render (Babel compiles async)
    setTimeout(start, 2000);
  } else {
    start();
  }
})();
