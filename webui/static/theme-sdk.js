/**
 * PantheonTheme SDK — JavaScript API for theme, icon pack, and visual customization.
 *
 * Provides a clean API for restyling the Pantheon WebUI without touching layout.
 * Integrates with the existing CSS variable system, setting.json persistence,
 * and the Appearance settings panel.
 *
 * Usage:
 *   PantheonTheme.setColors({ bg: '#0D0D1A', text: '#FFF8DC', accent: '#FFD700' });
 *   PantheonTheme.setIconPack('modern');
 *   PantheonTheme.setMode('dark');
 *   PantheonTheme.getCurrentConfig();
 *   PantheonTheme.onChange(callback);
 *   PantheonTheme.reset();
 *
 * @namespace PantheonTheme
 */
(function() {
  'use strict';

  // ── CSS Variable Map ──────────────────────────────────────────────────────
  // Mirrors the CSS custom properties used in style.css :root blocks.
  const CSS_VARS = {
    bg:            '--bg',
    sidebar:       '--sidebar',
    border:        '--border',
    border2:       '--border2',
    text:          '--text',
    muted:         '--muted',
    accent:        '--accent',
    blue:          '--blue',
    gold:          '--gold',
    codeBg:        '--code-bg',
    surface:       '--surface',
    topbarBg:      '--topbar-bg',
    mainBg:        '--main-bg',
    focusRing:     '--focus-ring',
    focusGlow:     '--focus-glow',
    inputBg:       '--input-bg',
    hoverBg:       '--hover-bg',
    strong:        '--strong',
    em:            '--em',
    codeText:      '--code-text',
    codeInlineBg:  '--code-inline-bg',
    preText:       '--pre-text',
    accentHover:   '--accent-hover',
    accentBg:      '--accent-bg',
    accentBgStrong:'--accent-bg-strong',
    accentText:    '--accent-text',
    error:         '--error',
    success:       '--success',
    warning:       '--warning',
    info:          '--info',
  };

  // ── Current State ─────────────────────────────────────────────────────────
  let _state = {
    mode: 'dark',           // 'light' | 'dark' | 'system'
    skin: 'default',        // 'default' | 'ares' | 'mono' | 'slate' | 'poseidon' | 'sisyphus' | 'charizard'
    theme: 'dark',          // resolved theme (always 'light' or 'dark')
    iconPack: 'pixel',      // 'pixel' | 'modern' | 'minimal'
    customColors: null,     // { light: { bg: '...', ... }, dark: { ... } } or null
    fontSize: 'default',    // 'small' | 'default' | 'large'
    layoutDensity: 'comfortable', // 'compact' | 'comfortable' | 'spacious'
  };

  let _changeCallbacks = [];
  let _customStyleTag = null;

  // ── Base Theme Colors ─────────────────────────────────────────────────────
  // Default light and dark mode colors (matching style.css :root and .dark)
  const BASE_COLORS = {
    light: {
      bg: '#FEFCF7', sidebar: '#FAF7F0', border: '#E0D8C8', border2: 'rgba(0,0,0,0.15)',
      text: '#1A1610', muted: '#5C5344', accent: '#B8860B', blue: '#0288A8', gold: '#8B6508',
      codeBg: '#F5F0E5', surface: '#F3EEE3', topbarBg: 'rgba(250,247,240,.98)', mainBg: 'rgba(254,252,247,0.5)',
      focusRing: 'rgba(184,134,11,.35)', focusGlow: 'rgba(184,134,11,.1)',
      inputBg: 'rgba(0,0,0,.03)', hoverBg: 'rgba(0,0,0,.05)',
      strong: '#0F0D08', em: '#5C5344', codeText: '#8b4513', codeInlineBg: 'rgba(0,0,0,.06)', preText: '#1A1610',
      accentHover: '#996F08', accentBg: 'rgba(184,134,11,0.08)', accentBgStrong: 'rgba(184,134,11,0.15)', accentText: '#8B6508',
      error: '#C62828', success: '#3D8B40', warning: '#E68A00', info: '#0288A8',
    },
    dark: {
      bg: '#0D0D1A', sidebar: '#141425', border: '#2A2A45', border2: 'rgba(255,255,255,0.14)',
      text: '#FFF8DC', muted: '#C0C0C0', accent: '#FFD700', blue: '#4DD0E1', gold: '#FFBF00',
      codeBg: '#1A1A2E', surface: '#1A1A2E', topbarBg: 'rgba(20,20,37,.98)', mainBg: 'rgba(13,13,26,0.5)',
      focusRing: 'rgba(255,215,0,.35)', focusGlow: 'rgba(255,215,0,.08)',
      inputBg: 'rgba(255,255,255,.04)', hoverBg: 'rgba(255,255,255,.06)',
      strong: '#fff', em: '#C0C0C0', codeText: '#f0c27f', codeInlineBg: 'rgba(0,0,0,.35)', preText: '#e2e8f0',
      accentHover: '#FFBF00', accentBg: 'rgba(255,215,0,0.08)', accentBgStrong: 'rgba(255,215,0,0.15)', accentText: '#FFD700',
      error: '#EF5350', success: '#4CAF50', warning: '#FFA726', info: '#4DD0E1',
    }
  };

  // ── Skin Color Overrides ──────────────────────────────────────────────────
  // Matches style.css [data-skin="..."] blocks
  const SKIN_COLORS = {
    ares: {
      light: { accent: '#C0392B', accentHover: '#A93226', accentBg: 'rgba(192,57,43,0.08)', accentBgStrong: 'rgba(192,57,43,0.15)', accentText: '#922B21' },
      dark:  { accent: '#FF4444', accentHover: '#CC3333', accentBg: 'rgba(255,68,68,0.08)', accentBgStrong: 'rgba(255,68,68,0.15)', accentText: '#FF4444' },
    },
    mono: {
      light: { accent: '#666666', accentHover: '#555555', accentBg: 'rgba(102,102,102,0.08)', accentBgStrong: 'rgba(102,102,102,0.15)', accentText: '#555555' },
      dark:  { accent: '#CCCCCC', accentHover: '#999999', accentBg: 'rgba(204,204,204,0.08)', accentBgStrong: 'rgba(204,204,204,0.15)', accentText: '#CCCCCC' },
    },
    slate: {
      light: { accent: '#475569', accentHover: '#334155', accentBg: 'rgba(71,85,105,0.08)', accentBgStrong: 'rgba(71,85,105,0.15)', accentText: '#334155' },
      dark:  { accent: '#94A3B8', accentHover: '#64748B', accentBg: 'rgba(148,163,184,0.08)', accentBgStrong: 'rgba(148,163,184,0.15)', accentText: '#94A3B8' },
    },
    poseidon: {
      light: { accent: '#0369A1', accentHover: '#025080', accentBg: 'rgba(3,105,161,0.08)', accentBgStrong: 'rgba(3,105,161,0.15)', accentText: '#025080' },
      dark:  { accent: '#0EA5E9', accentHover: '#0284C7', accentBg: 'rgba(14,165,233,0.08)', accentBgStrong: 'rgba(14,165,233,0.15)', accentText: '#0EA5E9' },
    },
    sisyphus: {
      light: { accent: '#7C3AED', accentHover: '#6D28D9', accentBg: 'rgba(124,58,237,0.08)', accentBgStrong: 'rgba(124,58,237,0.15)', accentText: '#6D28D9' },
      dark:  { accent: '#A78BFA', accentHover: '#8B5CF6', accentBg: 'rgba(167,139,250,0.08)', accentBgStrong: 'rgba(167,139,250,0.15)', accentText: '#A78BFA' },
    },
    charizard: {
      light: { accent: '#EA580C', accentHover: '#C2410C', accentBg: 'rgba(234,88,12,0.08)', accentBgStrong: 'rgba(234,88,12,0.15)', accentText: '#C2410C' },
      dark:  { accent: '#FB923C', accentHover: '#F97316', accentBg: 'rgba(251,146,60,0.08)', accentBgStrong: 'rgba(251,146,60,0.15)', accentText: '#FB923C' },
    },
  };

  // ── Internal Helpers ──────────────────────────────────────────────────────

  function _applyCustomColors(colors) {
    if (!colors) return;
    const root = document.documentElement;
    for (const [jsKey, cssVar] of Object.entries(CSS_VARS)) {
      if (colors[jsKey] !== undefined) {
        root.style.setProperty(cssVar, colors[jsKey]);
      }
    }
  }

  function _injectCustomStyleTag(colorsLight, colorsDark) {
    // Remove existing custom style tag
    if (_customStyleTag && _customStyleTag.parentNode) {
      _customStyleTag.parentNode.removeChild(_customStyleTag);
      _customStyleTag = null;
    }
    if (!colorsLight && !colorsDark) return;

    let css = '';
    if (colorsLight) {
      css += ':root:not(.dark) { ';
      for (const [jsKey, cssVar] of Object.entries(CSS_VARS)) {
        if (colorsLight[jsKey] !== undefined) {
          css += `${cssVar}: ${colorsLight[jsKey]}; `;
        }
      }
      css += '} ';
    }
    if (colorsDark) {
      css += ':root.dark { ';
      for (const [jsKey, cssVar] of Object.entries(CSS_VARS)) {
        if (colorsDark[jsKey] !== undefined) {
          css += `${cssVar}: ${colorsDark[jsKey]}; `;
        }
      }
      css += '} ';
    }

    if (css) {
      _customStyleTag = document.createElement('style');
      _customStyleTag.id = 'pantheon-custom-theme';
      _customStyleTag.textContent = css;
      document.head.appendChild(_customStyleTag);
    }
  }

  function _resolveTheme(mode) {
    if (mode === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return mode;
  }

  function _fireChange() {
    const config = PantheonTheme.getCurrentConfig();
    _changeCallbacks.forEach(function(fn) {
      try { fn(config); } catch(e) { /* plugin error, continue */ }
    });
  }

  /**
   * Apply the current theme state to the DOM.
   * Called internally after any state change.
   */
  function _apply() {
    const root = document.documentElement;
    const resolved = _resolveTheme(_state.mode);

    // Theme mode (dark class)
    if (_state.mode === 'system') {
      root.classList.toggle('dark', resolved === 'dark');
    } else {
      root.classList.toggle('dark', _state.mode === 'dark');
    }

    // Skin
    root.dataset.skin = _state.skin;

    // Font size
    root.dataset.fontSize = _state.fontSize;

    // Custom colors: if custom mode, inject via style tag
    if (_state.customColors) {
      _injectCustomStyleTag(_state.customColors.light, _state.customColors.dark);
    } else {
      _injectCustomStyleTag(null, null);
    }

    // Persist to localStorage for boot.js compatibility
    try {
      localStorage.setItem('hermes-theme', _state.mode);
      localStorage.setItem('hermes-skin', _state.skin);
      localStorage.setItem('hermes-font-size', _state.fontSize);
    } catch(e) { /* localStorage may be unavailable */ }

    // Icon pack: set data attribute on root
    root.dataset.iconPack = _state.iconPack;

    // Layout density: set data attribute on root
    root.dataset.layoutDensity = _state.layoutDensity;

    _fireChange();
  }

  // ── Public SDK API ────────────────────────────────────────────────────────

  const PantheonTheme = {
    /**
     * Apply custom CSS variable colors.
     * Merges with current base theme. Pass null/empty to clear custom colors.
     *
     * @param {Object|null} colors
     *   { light: { bg: '#fff', text: '#000', ... },
     *     dark:  { bg: '#000', text: '#fff', ... } }
     *   If only one mode is provided, only that mode is overridden.
     */
    setColors: function(colors) {
      if (!colors || (typeof colors !== 'object')) {
        _state.customColors = null;
      } else {
        _state.customColors = {
          light: colors.light || null,
          dark: colors.dark || null,
        };
      }
      _apply();
    },

    /**
     * Set the icon pack. Icons are loaded from static/icons/{packName}/
     *
     * @param {string} packName - 'pixel' | 'modern' | 'minimal'
     */
    setIconPack: function(packName) {
      if (!packName || typeof packName !== 'string') return;
      _state.iconPack = packName;
      _apply();
    },

    /**
     * Set theme mode.
     *
     * @param {string} mode - 'light' | 'dark' | 'system'
     */
    setMode: function(mode) {
      if (!['light', 'dark', 'system'].includes(mode)) return;
      _state.mode = mode;
      _apply();
    },

    /**
     * Set theme skin (accent color).
     *
     * @param {string} skin - 'default' | 'ares' | 'mono' | 'slate' | 'poseidon' | 'sisyphus' | 'charizard'
     */
    setSkin: function(skin) {
      const validSkins = ['default', 'ares', 'mono', 'slate', 'poseidon', 'sisyphus', 'charizard'];
      if (!validSkins.includes(skin)) return;
      _state.skin = skin;
      _apply();
    },

    /**
     * Set font size.
     *
     * @param {string} size - 'small' | 'default' | 'large'
     */
    setFontSize: function(size) {
      if (!['small', 'default', 'large'].includes(size)) return;
      _state.fontSize = size;
      _apply();
    },

    /**
     * Set layout density.
     *
     * @param {string} density - 'compact' | 'comfortable' | 'spacious'
     */
    setLayoutDensity: function(density) {
      if (!['compact', 'comfortable', 'spacious'].includes(density)) return;
      _state.layoutDensity = density;
      _apply();
    },

    /**
     * Get the current full theme configuration.
     *
     * @returns {Object} current theme state
     */
    getCurrentConfig: function() {
      return JSON.parse(JSON.stringify(_state));
    },

    /**
     * Register a callback fired whenever the theme changes.
     * The callback receives the current config object.
     *
     * @param {Function} callback - function(config) { ... }
     */
    onChange: function(callback) {
      if (typeof callback === 'function') {
        _changeCallbacks.push(callback);
      }
    },

    /**
     * Remove a previously registered onChange callback.
     *
     * @param {Function} callback - the function to remove
     */
    offChange: function(callback) {
      const idx = _changeCallbacks.indexOf(callback);
      if (idx !== -1) _changeCallbacks.splice(idx, 1);
    },

    /**
     * Reset all theme settings to factory defaults.
     */
    reset: function() {
      _state = {
        mode: 'dark',
        skin: 'default',
        theme: 'dark',
        iconPack: 'pixel',
        customColors: null,
        fontSize: 'default',
        layoutDensity: 'comfortable',
      };
      if (_customStyleTag && _customStyleTag.parentNode) {
        _customStyleTag.parentNode.removeChild(_customStyleTag);
        _customStyleTag = null;
      }
      // Remove inline style overrides
      const root = document.documentElement;
      for (const cssVar of Object.values(CSS_VARS)) {
        root.style.removeProperty(cssVar);
      }
      delete root.dataset.skin;
      delete root.dataset.fontSize;
      delete root.dataset.iconPack;
      delete root.dataset.layoutDensity;
      root.classList.remove('dark');
      _apply();
    },

    /**
     * Hydrate state from a settings object (from settings.json).
     *
     * @param {Object} settings - appearance settings object
     */
    hydrate: function(settings) {
      if (!settings) return;
      if (settings.theme) _state.mode = settings.theme;
      if (settings.skin) _state.skin = settings.skin;
      if (settings.font_size) _state.fontSize = settings.font_size;
      if (settings.custom_theme) {
        _state.customColors = settings.custom_theme;
      }
      if (settings.icon_pack) {
        _state.iconPack = settings.icon_pack;
      }
      if (settings.layout_density) {
        _state.layoutDensity = settings.layout_density;
      }
      _apply();
    },

    /**
     * Get the URL prefix for the current icon pack.
     *
     * @returns {string} e.g., 'static/icons/pixel/' or 'static/icons/modern/'
     */
    getIconUrl: function(filename) {
      return 'static/icons/' + _state.iconPack + '/' + filename;
    },

    /**
     * Get the base path for the current icon pack.
     *
     * @returns {string} e.g., 'static/icons/pixel/'
     */
    getIconPackPath: function() {
      return 'static/icons/' + _state.iconPack + '/';
    },
  };

  // ── Expose globally ───────────────────────────────────────────────────────
  window.PantheonTheme = PantheonTheme;

  // ── Listen for system color scheme changes ─────────────────────────────────
  try {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
      if (_state.mode === 'system') {
        _apply();
      }
    });
  } catch(e) { /* older browser */ }

  // ── Initialize from DOM state if boot.js hasn't called hydrate ────────────
  // This runs as a fallback so the SDK is always in a consistent state.
  (function _initFromDom() {
    const root = document.documentElement;
    if (root.classList.contains('dark')) _state.mode = 'dark';
    else _state.mode = 'light';
    if (root.dataset.skin) _state.skin = root.dataset.skin;
    if (root.dataset.fontSize) _state.fontSize = root.dataset.fontSize;
    if (root.dataset.iconPack) _state.iconPack = root.dataset.iconPack;
    try {
      const stored = localStorage.getItem('hermes-theme');
      if (stored === 'system') { _state.mode = 'system'; }
    } catch(e) {}
    _state.theme = _resolveTheme(_state.mode);
  })();

})();
