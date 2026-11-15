// Reader preferences: theme and text size. Both are remembered on this device only.
// Until the reader picks a theme, CSS follows the system setting by itself.
const root = document.documentElement;
const store = {
  get: key => { try { return localStorage.getItem(key); } catch { return null; } },
  set: (key, value) => { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

for (const button of document.querySelectorAll('[data-action="toggle-theme"]')) {
  button.addEventListener('click', () => {
    const current = root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    root.dataset.theme = current === 'dark' ? 'light' : 'dark';
    store.set('theme', root.dataset.theme);
  });
}

function setFontSize(size) {
  if (size === 'md') delete root.dataset.fontSize; else root.dataset.fontSize = size;
  for (const b of document.querySelectorAll('[data-font-size-option]')) {
    b.setAttribute('aria-pressed', String(b.dataset.fontSizeOption === size));
  }
}
for (const button of document.querySelectorAll('[data-font-size-option]')) {
  button.addEventListener('click', () => {
    setFontSize(button.dataset.fontSizeOption);
    store.set('fontSize', button.dataset.fontSizeOption);
  });
}
setFontSize(store.get('fontSize') || 'md');
