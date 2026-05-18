import { getConfig } from '../config.js';

const $ = (id) => document.getElementById(id);
let seed = null;

function buildPreview() {
  const template = $('template').value;
  const title = $('title').value.trim() || 'Web Clip';
  const url = $('url').value.trim();
  const tags = $('tags').value.split(',').map(s => s.trim()).filter(Boolean);
  const note = $('note').value.trim();
  const text = $('clipText').value.trim();

  const lines = [];
  lines.push(`# ${title}`);
  if (url) lines.push(`Source: ${url}`);
  lines.push('');
  lines.push(`Template: ${template}`);
  if (tags.length) lines.push(`Tags: ${tags.map(t => '#' + t.replace(/\s+/g,'-')).join(' ')}`);
  if (note) {
    lines.push('');
    lines.push('## Note');
    lines.push(note);
  }
  if (text) {
    lines.push('');
    lines.push('## Clip');
    lines.push(text);
  }
  $('preview').value = lines.join('\n');
}

async function save() {
  const status = $('status');
  status.className = '';
  status.textContent = 'Saving...';

  try {
    const cfg = await getConfig();
    if (!cfg?.url) throw new Error('Pantheon not configured');

    const payload = {
      url: $('url').value.trim(),
      title: $('title').value.trim() || 'Web Clip',
      text: $('preview').value,
    };

    const res = await fetch(`${cfg.url}/api/clip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      mode: 'cors',
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    status.className = 'ok';
    status.textContent = `Saved ${data.file || ''}`.trim();

    if (seed?.tabId) {
      chrome.tabs.sendMessage(seed.tabId, { action: 'showToast', message: `✨ Clipped to Athenaeum${data.file ? ' → ' + data.file : ''}` }).catch(() => {});
    }
    await chrome.storage.local.remove('pantheon_pending_clip');
    setTimeout(() => window.close(), 700);
  } catch (e) {
    status.className = 'err';
    status.textContent = `Save failed: ${e.message}`;
  }
}

async function init() {
  const result = await chrome.storage.local.get('pantheon_pending_clip');
  seed = result.pantheon_pending_clip || {};

  $('title').value = seed.title || 'Web Clip';
  $('url').value = seed.url || '';
  $('clipText').value = (seed.text || '').slice(0, 12000);
  buildPreview();

  ['template','title','url','tags','note','clipText'].forEach(id => {
    $(id).addEventListener('input', buildPreview);
  });

  $('save').addEventListener('click', save);
  $('cancel').addEventListener('click', () => window.close());
}

init();
