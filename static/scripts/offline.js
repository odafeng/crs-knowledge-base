// Register independently of push configuration so every reader can use the site offline.
if ('serviceWorker' in navigator) {
  const siteRoot = new URL(document.documentElement.dataset.root || './', location.href);
  navigator.serviceWorker.register(new URL('sw.js', siteRoot)).catch(console.error);
}
