/* ── Pantheon Forge Wizard ──
 * Step-by-step god creation via Hephaestus backend.
 * Mount: window.mountForgeWizard(container) or auto-mount #forge-wizard-panel
 */
(function() {
  'use strict';

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'cls') e.className = v;
      else if (k === 'style') Object.assign(e.style, v);
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    });
    children.flat().forEach(c => { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }

  function ForgeWizard(container) {
    let step = 0;
    let godName = '';
    let questions = [];
    let answers = {};
    let state = 'name'; // name | questions | summary | forging | done | error

    const root = el('div', { cls: 'fw-overlay', style: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 9500, display: 'flex', alignItems: 'center', justifyContent: 'center' } });
    const panel = el('div', { cls: 'fw-panel', style: { background: 'var(--bg-primary, #0a0908)', border: '1px solid var(--border, #3B4A50)', borderRadius: '12px', width: '600px', maxWidth: '95vw', maxHeight: '85vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' } });

    function render() {
      panel.innerHTML = '';
      panel.appendChild(header());
      panel.appendChild(body());
      panel.appendChild(footer());
    }

    function header() {
      return el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid var(--border, #3B4A50)' } },
        el('h2', { style: { margin: 0, fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary, #EAE0D5)' } }, '⚒️ Forge a God'),
        el('button', { cls: 'fw-close', style: { background: 'none', border: 'none', color: 'var(--text-muted, #666)', fontSize: '1.3rem', cursor: 'pointer', padding: '4px 8px' }, onClick: close }, '✕')
      );
    }

    function body() {
      const b = el('div', { style: { flex: 1, overflow: 'auto', padding: '24px' } });

      if (state === 'name') {
        b.appendChild(el('p', { style: { color: 'var(--text-secondary, #C6AC8F)', fontSize: '14px', marginBottom: '16px', lineHeight: 1.6 } },
          'Name your god. This will be used as the profile name and appear throughout Pantheon.'));
        const input = el('input', { type: 'text', placeholder: 'e.g. athena, thoth, caduceus', value: godName, style: { width: '100%', boxSizing: 'border-box', background: 'var(--bg-secondary, #11100E)', border: '1px solid var(--border, #3B4A50)', borderRadius: '8px', padding: '12px 16px', color: 'var(--text-primary, #EAE0D5)', fontSize: '1rem', outline: 'none' },
          onInput: e => { godName = e.target.value.trim(); },
          onKeyDown: e => { if (e.key === 'Enter' && godName) startForge(); }
        });
        b.appendChild(input);
      }

      if (state === 'questions' && questions.length) {
        const q = questions[step];
        if (q) {
          b.appendChild(el('div', { style: { marginBottom: '20px' } },
            el('div', { style: { fontSize: '12px', color: 'var(--text-muted, #666)', marginBottom: '4px' } }, `Step ${step + 1} of ${questions.length}`),
            el('div', { style: { height: '4px', background: 'var(--bg-secondary, #11100E)', borderRadius: '2px', overflow: 'hidden' } },
              el('div', { style: { height: '100%', width: `${((step + 1) / questions.length) * 100}%`, background: 'var(--accent, #7c6fe0)', borderRadius: '2px', transition: 'width 0.3s' } })
            )
          ));
          b.appendChild(el('label', { style: { display: 'block', fontSize: '15px', fontWeight: 600, color: 'var(--text-primary, #EAE0D5)', marginBottom: '8px' } }, q.question || q.label || q.prompt || ''));
          if (q.description) b.appendChild(el('p', { style: { fontSize: '12px', color: 'var(--text-muted, #666)', marginBottom: '12px' } }, q.description));

          const existing = answers[q.key || `step_${step}`] || '';
          const isLong = q.type === 'textarea' || (q.question || '').length > 80;
          const field = isLong
            ? el('textarea', { value: existing, placeholder: q.placeholder || '', rows: 4, style: { width: '100%', boxSizing: 'border-box', background: 'var(--bg-secondary, #11100E)', border: '1px solid var(--border, #3B4A50)', borderRadius: '8px', padding: '12px', color: 'var(--text-primary, #EAE0D5)', fontSize: '14px', resize: 'vertical', outline: 'none' },
              onInput: e => { answers[q.key || `step_${step}`] = e.target.value; }
            })
            : el('input', { type: 'text', value: existing, placeholder: q.placeholder || '', style: { width: '100%', boxSizing: 'border-box', background: 'var(--bg-secondary, #11100E)', border: '1px solid var(--border, #3B4A50)', borderRadius: '8px', padding: '10px 14px', color: 'var(--text-primary, #EAE0D5)', fontSize: '14px', outline: 'none' },
              onInput: e => { answers[q.key || `step_${step}`] = e.target.value; },
              onKeyDown: e => { if (e.key === 'Enter' && !isLong) nextStep(); }
            });
          b.appendChild(field);
        }
      }

      if (state === 'summary') {
        b.appendChild(el('p', { style: { color: 'var(--text-secondary, #C6AC8F)', fontSize: '14px', marginBottom: '16px' } }, 'Review the answers below, then click Forge to create your god.'));
        b.appendChild(el('div', { style: { background: 'var(--bg-secondary, #11100E)', border: '1px solid var(--border, #3B4A50)', borderRadius: '8px', padding: '16px' } },
          el('div', { style: { fontWeight: 600, color: 'var(--accent, #7c6fe0)', marginBottom: '12px' } }, godName),
          ...Object.entries(answers).map(([k, v]) =>
            el('div', { style: { display: 'flex', gap: '8px', padding: '6px 0', borderBottom: '1px solid var(--border, #3B4A50)', fontSize: '13px' } },
              el('span', { style: { color: 'var(--text-muted, #666)', minWidth: '100px' } }, k),
              el('span', { style: { color: 'var(--text-primary, #EAE0D5)' } }, String(v || ''))
            )
          )
        ));
      }

      if (state === 'forging') {
        b.appendChild(el('div', { style: { textAlign: 'center', padding: '40px' } },
          el('div', { style: { fontSize: '32px', marginBottom: '12px' } }, '⚒️'),
          el('p', { style: { color: 'var(--text-primary, #EAE0D5)', fontSize: '15px', fontWeight: 600 } }, 'Forging...'),
          el('p', { style: { color: 'var(--text-muted, #666)', fontSize: '13px' } }, `Creating ${godName} via Hephaestus`)
        ));
      }

      if (state === 'done') {
        b.appendChild(el('div', { style: { textAlign: 'center', padding: '40px' } },
          el('div', { style: { fontSize: '40px', marginBottom: '12px' } }, '✅'),
          el('p', { style: { color: 'var(--success, #86C08B)', fontSize: '16px', fontWeight: 600, marginBottom: '8px' } }, `${godName} has been forged!`),
          el('p', { style: { color: 'var(--text-secondary, #C6AC8F)', fontSize: '13px' } }, 'Your new god is now available in the God Rail.'),
          el('button', { style: { marginTop: '16px', background: 'var(--accent, #7c6fe0)', color: 'white', border: 'none', borderRadius: '8px', padding: '10px 24px', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }, onClick: close }, 'View in Pantheon')
        ));
      }

      if (state === 'error') {
        b.appendChild(el('div', { style: { textAlign: 'center', padding: '40px' } },
          el('div', { style: { fontSize: '32px', marginBottom: '8px' } }, '⚠️'),
          el('p', { style: { color: 'var(--error, #F87171)', fontSize: '14px', fontWeight: 600 } }, 'Forge failed'),
          el('p', { style: { color: 'var(--text-muted, #666)', fontSize: '13px' } }, 'Check that Hephaestus is running and try again.')
        ));
      }

      return b;
    }

    function footer() {
      const f = el('div', { style: { display: 'flex', gap: '10px', justifyContent: 'flex-end', padding: '16px 24px', borderTop: '1px solid var(--border, #3B4A50)' } });

      if (state === 'name') {
        f.appendChild(el('button', { style: { background: 'var(--accent, #7c6fe0)', color: 'white', border: 'none', borderRadius: '8px', padding: '10px 24px', fontSize: '14px', fontWeight: 600, cursor: godName ? 'pointer' : 'not-allowed', opacity: godName ? 1 : 0.5 }, onClick: startForge, disabled: !godName }, 'Begin Forge →'));
      }

      if (state === 'questions') {
        f.appendChild(el('button', { style: { background: 'var(--bg-secondary, #11100E)', color: 'var(--text-secondary, #C6AC8F)', border: '1px solid var(--border, #3B4A50)', borderRadius: '8px', padding: '10px 20px', fontSize: '14px', cursor: 'pointer' }, onClick: prevStep }, '← Back'));
        f.appendChild(el('button', { style: { background: 'var(--accent, #7c6fe0)', color: 'white', border: 'none', borderRadius: '8px', padding: '10px 24px', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }, onClick: nextStep }, step < questions.length - 1 ? 'Next →' : 'Review'));
      }

      if (state === 'summary') {
        f.appendChild(el('button', { style: { background: 'var(--bg-secondary, #11100E)', color: 'var(--text-secondary, #C6AC8F)', border: '1px solid var(--border, #3B4A50)', borderRadius: '8px', padding: '10px 20px', fontSize: '14px', cursor: 'pointer' }, onClick: () => { state = 'questions'; render(); } }, '← Back'));
        f.appendChild(el('button', { style: { background: 'var(--success, #86C08B)', color: '#0A0908', border: 'none', borderRadius: '8px', padding: '10px 24px', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }, onClick: forgeGod }, '⚒️ Forge God'));
      }

      return f;
    }

    async function startForge() {
      if (!godName) return;
      state = 'questions';
      step = 0;
      render();
      try {
        const r = await fetch(`/api/gods/${encodeURIComponent(godName)}/forge`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const data = await r.json();
        questions = data.questions || data.steps || [];
        if (!questions.length) { state = 'error'; render(); }
        else render();
      } catch (e) { state = 'error'; render(); }
    }

    function prevStep() { if (step > 0) { step--; render(); } }
    function nextStep() {
      if (step < questions.length - 1) { step++; render(); }
      else { state = 'summary'; render(); }
    }

    async function forgeGod() {
      state = 'forging'; render();
      try {
        const r = await fetch(`/api/gods/${encodeURIComponent(godName)}/forge`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers, confirm: true })
        });
        if (r.ok) { state = 'done'; render(); }
        else { state = 'error'; render(); }
      } catch (e) { state = 'error'; render(); }
    }

    function close() { root.remove(); }
    root.addEventListener('click', e => { if (e.target === root) close(); });
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') close(); }, { once: true });

    render();
    container.appendChild(root);
  }

  window.mountForgeWizard = function(container) {
    new ForgeWizard(container || document.body);
  };

  window.openForgeWizard = function() {
    var existing = document.getElementById('forge-wizard-overlay');
    if (existing) { existing.remove(); return; }
    var overlay = document.createElement('div');
    overlay.id = 'forge-wizard-overlay';
    Object.assign(overlay.style, {
      position: 'fixed', inset: '0', zIndex: '9998',
      background: 'rgba(0,0,0,0.7)', display: 'flex',
      alignItems: 'center', justifyContent: 'center'
    });
    overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
    var panel = document.createElement('div');
    panel.style.cssText = 'background:var(--bg-primary,#0A0908);border:1px solid var(--border);border-radius:12px;width:650px;max-width:95vw;max-height:85vh;overflow:auto';
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    new ForgeWizard(panel);
  };

  // Auto-mount
  setTimeout(() => {
    const existing = document.getElementById('forge-wizard-panel');
    if (existing && existing.style.display !== 'none') {
      window.mountForgeWizard(existing);
    }
  }, 500);
})();
