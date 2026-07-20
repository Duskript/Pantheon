(function () {
  const form = document.getElementById('login-form')
  const usernameInput = document.getElementById('username')
  const passwordInput = document.getElementById('pw')
  const errorBox = document.getElementById('err')

  function showError(message) {
    if (!errorBox) return
    errorBox.textContent = message
    errorBox.style.display = 'block'
  }

  function safeNextPath() {
    const params = new URLSearchParams(window.location.search)
    const next = params.get('next') || '/olympus/'
    if (!next.startsWith('/') || next.startsWith('//')) return '/olympus/'
    return next
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (errorBox) errorBox.style.display = 'none'

    const username = usernameInput?.value?.trim()
    const password = passwordInput?.value ?? ''
    const invalid = form.dataset.invalidPw || 'Invalid password'
    const failed = form.dataset.connFailed || 'Connection failed'

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username, password }),
      })
      if (!response.ok) {
        let message = invalid
        try {
          const body = await response.json()
          message = body.error || message
        } catch {}
        showError(message)
        return
      }
      window.location.assign(safeNextPath())
    } catch {
      showError(failed)
    }
  })
})()
