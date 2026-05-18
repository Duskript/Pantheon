// Pantheon Companion — Background Service Worker
import { getConfig } from './config.js';

// ── Install / Update ──────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === 'install') {
    chrome.tabs.create({ url: chrome.runtime.getURL('popup/popup.html?setup=1') });
  }
  await rebuildContextMenus();
});

// Rebuild menus when SW wakes fresh (Firefox fires, Chrome may not)
chrome.runtime.onStartup?.addListener(async () => {
  await rebuildContextMenus();
});

async function rebuildContextMenus() {
  return new Promise((resolve) => {
    chrome.contextMenus.removeAll(async () => {
      await createStaticMenus();
      await updateGodSubmenu();
      resolve();
    });
  });
}

// ── Static Context Menus ──────────────────────────────────────────
async function createStaticMenus() {
  // ── Selection menus (only when text selected) ──

  chrome.contextMenus.create({
    id: 'pantheon-ask',
    title: 'Ask Pantheon about this',
    contexts: ['selection'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-improve',
    title: 'Improve / Rewrite this',
    contexts: ['selection'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-explain',
    title: 'Explain this clearly',
    contexts: ['selection'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-action-items',
    title: 'Extract action items',
    contexts: ['selection'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-sendto-parent',
    title: 'Send to God…',
    contexts: ['selection'],
    // Children added dynamically by updateGodSubmenu()
  });

  chrome.contextMenus.create({
    id: 'pantheon-sep-1',
    type: 'separator',
    contexts: ['page', 'selection'],
  });

  // ── Page-level menus ──

  chrome.contextMenus.create({
    id: 'pantheon-summarize',
    title: '📄 Summarize this page',
    contexts: ['page'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-capture',
    title: 'Save to Pantheon',
    contexts: ['page', 'selection', 'link', 'image'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-idea',
    title: '💡 Capture as Idea',
    contexts: ['page', 'selection'],
  });

  chrome.contextMenus.create({
    id: 'pantheon-sep-2',
    type: 'separator',
    contexts: ['page', 'selection'],
  });

  // ── Toolbar icon menu ──

  chrome.contextMenus.create({
    id: 'pantheon-open',
    title: '🏛️ Open Pantheon Dashboard',
    contexts: ['action'],
  });
}

// ── Dynamic God Submenu ──────────────────────────────────────────
let godSubmenuItems = [];

async function updateGodSubmenu() {
  // Remove old god items
  for (const id of godSubmenuItems) {
    try { await chrome.contextMenus.remove(id); } catch {}
  }
  godSubmenuItems = [];

  const config = await getConfig();
  if (!config || !config.url) return;

  try {
    const res = await fetch(`${config.url}/api/gods`, {
      signal: AbortSignal.timeout(5000),
      credentials: 'include',
    });
    const data = await res.json();
    const gods = data.gods || [];

    if (gods.length === 0) {
      const id = 'pantheon-sendto-empty';
      chrome.contextMenus.create({
        id,
        parentId: 'pantheon-sendto-parent',
        title: '(no gods available)',
        contexts: ['selection'],
        enabled: false,
      });
      godSubmenuItems.push(id);
      return;
    }

    gods.forEach((g) => {
      const id = `pantheon-sendto-${g.name}`;
      chrome.contextMenus.create({
        id,
        parentId: 'pantheon-sendto-parent',
        title: g.display_name || g.name,
        contexts: ['selection'],
      });
      godSubmenuItems.push(id);
    });
  } catch (e) {
    console.log('[Pantheon] Could not load gods for submenu:', e.message);
    const id = 'pantheon-sendto-unavailable';
    chrome.contextMenus.create({
      id,
      parentId: 'pantheon-sendto-parent',
      title: '⚠️ Connect Pantheon first',
      contexts: ['selection'],
      enabled: false,
    });
    godSubmenuItems.push(id);
  }
}

// NOTE: action.default_popup is set in manifest, so action.onClicked does not fire.
// Side panel is opened explicitly from popup buttons and context-menu actions.

// ── Message Router ─────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'refreshGodSubmenu') {
    updateGodSubmenu().then(() => sendResponse({ ok: true }));
    return true;
  }

  if (msg.action === 'switchGod') {
    // Popup wants to switch god — store preference for side panel
    chrome.storage.local.set({
      pantheon_active_god: msg.godName,
    }).catch(() => {});
    // Open side panel
    chrome.sidePanel.open({ tabId: sender.tab?.id }).catch(() => {
      chrome.sidePanel.open().catch(() => {});
    });
    sendResponse({ ok: true });
    return false;
  }

  if (msg.action === 'openSession') {
    // Pending action is already set by popup — just open side panel
    chrome.sidePanel.open({ tabId: sender.tab?.id }).catch(() => {
      chrome.sidePanel.open().catch(() => {});
    });
    sendResponse({ ok: true });
    return false;
  }
});

// ── Context Menu Click Handler ──────────────────────────────────
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const config = await getConfig();
  if (!config || !config.url) {
    chrome.tabs.create({ url: chrome.runtime.getURL('popup/popup.html?setup=1') });
    return;
  }

  const menuId = info.menuItemId;

  // ── Ask Pantheon about this ──
  if (menuId === 'pantheon-ask') {
    await storePendingAction({
      type: 'ask',
      selection: info.selectionText || '',
      pageUrl: info.pageUrl || tab?.url || '',
      pageTitle: tab?.title || '',
    });
    await chrome.sidePanel.open({ tabId: tab?.id });
    return;
  }

  // ── Improve / Rewrite ──
  if (menuId === 'pantheon-improve') {
    await storePendingAction({
      type: 'workflow',
      workflow: 'rewrite',
      selection: info.selectionText || '',
      pageUrl: info.pageUrl || tab?.url || '',
      pageTitle: tab?.title || '',
    });
    await chrome.sidePanel.open({ tabId: tab?.id });
    return;
  }

  // ── Explain selection ──
  if (menuId === 'pantheon-explain') {
    await storePendingAction({
      type: 'workflow',
      workflow: 'explain',
      selection: info.selectionText || '',
      pageUrl: info.pageUrl || tab?.url || '',
      pageTitle: tab?.title || '',
    });
    await chrome.sidePanel.open({ tabId: tab?.id });
    return;
  }

  // ── Extract action items ──
  if (menuId === 'pantheon-action-items') {
    await storePendingAction({
      type: 'workflow',
      workflow: 'action_items',
      selection: info.selectionText || '',
      pageUrl: info.pageUrl || tab?.url || '',
      pageTitle: tab?.title || '',
    });
    await chrome.sidePanel.open({ tabId: tab?.id });
    return;
  }

  // ── Send to a specific god ──
  if (menuId.startsWith('pantheon-sendto-')) {
    const godName = menuId.replace('pantheon-sendto-', '');
    await storePendingAction({
      type: 'sendto',
      god: godName,
      selection: info.selectionText || '',
      pageUrl: info.pageUrl || tab?.url || '',
      pageTitle: tab?.title || '',
    });
    await chrome.sidePanel.open({ tabId: tab?.id });
    return;
  }

  // ── Summarize this page ──
  if (menuId === 'pantheon-summarize') {
    try {
      const pageContent = await chrome.tabs.sendMessage(tab.id, { action: 'getPageContent' });
      const text = pageContent?.text || pageContent?.selection || '';

      await storePendingAction({
        type: 'summarize',
        text,
        pageUrl: info.pageUrl || tab?.url || '',
        pageTitle: tab?.title || '',
      });
      await chrome.sidePanel.open({ tabId: tab?.id });
    } catch (e) {
      console.error('[Pantheon] Summarize failed — page may not support content scripts:', e);
      // Fallback: summarize with just the URL
      await storePendingAction({
        type: 'summarize',
        text: `[Could not read page content directly. URL: ${info.pageUrl || tab?.url || ''}]`,
        pageUrl: info.pageUrl || tab?.url || '',
        pageTitle: tab?.title || '',
      });
      await chrome.sidePanel.open({ tabId: tab?.id });
    }
    return;
  }

  // ── Save to Pantheon (Obsidian-style clip modal) ──
  if (menuId === 'pantheon-capture') {
    try {
      let pageText = info.selectionText || '';
      if (!pageText && tab?.id) {
        try {
          const pageContent = await chrome.tabs.sendMessage(tab.id, { action: 'getPageContent' });
          pageText = (pageContent?.selection || pageContent?.text || '').slice(0, 12000);
        } catch {
          pageText = '';
        }
      }

      const seed = {
        tabId: tab?.id,
        url: info.pageUrl || tab?.url || info.linkUrl || info.srcUrl || '',
        title: tab?.title || 'Web Clip',
        text: pageText || info.linkUrl || info.srcUrl || '',
        createdAt: Date.now(),
      };

      await chrome.storage.local.set({ pantheon_pending_clip: seed });
      await chrome.windows.create({
        url: chrome.runtime.getURL('clipper/clipper.html'),
        type: 'popup',
        width: 840,
        height: 820,
      });
    } catch (e) {
      console.error('[Pantheon] Capture failed:', e);
      if (tab?.id) {
        chrome.tabs.sendMessage(tab.id, { action: 'showToast', message: `❌ Clip failed: ${e.message}` }).catch(() => {});
      }
    }
    return;
  }

  // ── Capture as Idea ──
  if (menuId === 'pantheon-idea') {
    try {
      const text = info.selectionText || `Idea from: ${tab?.title || 'web'}`;
      await apiPost(config, '/api/ideas/add', { text });
      if (tab?.id) {
        chrome.tabs.sendMessage(tab.id, { action: 'showToast', message: '💡 Idea captured!' }).catch(() => {});
      }
    } catch (e) {
      console.error('[Pantheon] Idea capture failed:', e);
    }
    return;
  }

  // ── Open Dashboard ──
  if (menuId === 'pantheon-open') {
    chrome.tabs.create({ url: config.url });
    return;
  }
});

// ── Pending Action Store ──────────────────────────────────────────
async function storePendingAction(data) {
  await chrome.storage.local.set({
    pantheon_pending_action: {
      ...data,
      timestamp: Date.now(),
    },
  });
}

// ── API Helper ────────────────────────────────────────────────────
async function apiPost(config, path, body) {
  const url = `${config.url.replace(/\/+$/, '')}${path}`;
  const headers = { 'Content-Type': 'application/json' };
  if (config.token) headers['Authorization'] = `Bearer ${config.token}`;

  const res = await fetch(url, {
    method: 'POST',
    headers,
    credentials: 'include',
    mode: 'cors',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
