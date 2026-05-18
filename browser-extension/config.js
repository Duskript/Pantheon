// Pantheon Companion — Config Storage
// Persists the Pantheon URL + optional token in chrome.storage.sync

const STORAGE_KEY = 'pantheon_config';

export async function getConfig() {
  const result = await chrome.storage.sync.get(STORAGE_KEY);
  return result[STORAGE_KEY] || null;
}

export async function setConfig(url, token) {
  const cleanUrl = url.replace(/\/+$/, '');
  await chrome.storage.sync.set({
    [STORAGE_KEY]: { url: cleanUrl, token: token || '' },
  });
}

export async function clearConfig() {
  await chrome.storage.sync.remove(STORAGE_KEY);
}

export async function isConfigured() {
  const config = await getConfig();
  return !!(config && config.url);
}

// ── Host permission management ────────────────────────────────────
export async function ensureHostPermission(url) {
  const origin = new URL(url).origin;
  const already = await chrome.permissions.contains({
    origins: [`${origin}/*`],
  });
  if (already) return true;

  return new Promise((resolve) => {
    chrome.permissions.request(
      { origins: [`${origin}/*`] },
      (granted) => resolve(granted)
    );
  });
}
