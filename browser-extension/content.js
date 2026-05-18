// Pantheon Companion — Content Script
// Captures page context for the right-click "Send to Pantheon" feature

// Listen for messages from the background script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getPageContent') {
    const content = {
      url: location.href,
      title: document.title,
      selection: window.getSelection()?.toString() || '',
      html: document.body?.innerHTML?.slice(0, 50000) || '', // cap at 50KB
      text: document.body?.innerText?.slice(0, 10000) || '', // cap at 10KB
    };
    sendResponse(content);
  }

  if (request.action === 'showToast') {
    showToast(request.message);
  }
});

// Forward selection changes to background (for context menu enrichment)
document.addEventListener('mouseup', () => {
  const sel = window.getSelection()?.toString();
  if (sel) {
    chrome.runtime.sendMessage({
      action: 'selectionChanged',
      text: sel.slice(0, 500),
    }).catch(() => {}); // popup may not be open
  }
});

function showToast(message) {
  const toast = document.createElement('div');
  toast.textContent = message;
  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '24px',
    right: '24px',
    padding: '10px 18px',
    background: '#FFD700',
    color: '#000',
    borderRadius: '8px',
    fontSize: '13px',
    fontWeight: '600',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    zIndex: '2147483647',
    boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
    opacity: '0',
    transform: 'translateY(8px)',
    transition: 'opacity 0.2s, transform 0.2s',
    maxWidth: '320px',
  });
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
  });
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    setTimeout(() => toast.remove(), 200);
  }, 2500);
}
