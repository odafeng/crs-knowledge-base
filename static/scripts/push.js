// Push notifications for new stories.
// The buttons stay hidden unless the site is configured for push (two <meta> tags) and the browser can do it.
const key = document.querySelector('meta[name="push-key"]')?.content;
const api = document.querySelector('meta[name="push-api"]')?.content;
const toggles = [...document.querySelectorAll('[data-push-toggle]')];
const statusLine = document.querySelector('[data-push-status]');
const siteRoot = new URL(document.documentElement.dataset.root || './', location.href);
const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const onIos = /iPad|iPhone|iPod/.test(navigator.userAgent) && !navigator.standalone;

const TEXT = {
  off: ['開啟推播', '開啟最新消息推播', ''],
  on: ['關閉推播', '關閉最新消息推播', '推播已開啟。有新消息時這台裝置會收到通知。'],
  blocked: ['開啟推播', '開啟最新消息推播', '瀏覽器目前封鎖了本站的通知。請到瀏覽器的網站設定把通知改成允許，再按一次。'],
  failed: ['開啟推播', '開啟最新消息推播', '沒有開啟成功，請稍後再試。'],
};

function show(state) {
  const [label, name, message] = TEXT[state];
  for (const button of toggles) {
    button.hidden = false;
    button.dataset.pushState = state;
    button.setAttribute('aria-pressed', String(state === 'on'));
    const text = button.querySelector('[data-push-label]');
    if (text) text.textContent = label; else button.setAttribute('aria-label', name);
  }
  if (statusLine) statusLine.textContent = message;
}

function keyBytes(base64url) {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(base64url.length / 4) * 4, '=');
  return Uint8Array.from(atob(base64), char => char.charCodeAt(0));
}

// The subscription store answers two calls: push_subscribe and push_unsubscribe.
async function call(name, body) {
  const response = await fetch(`${api}/rpc/${name}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(apiKey ? { apikey: apiKey } : {}) },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
}
const apiKey = document.querySelector('meta[name="push-api-key"]')?.content;

async function turnOn() {
  if (await Notification.requestPermission() !== 'granted') return show('blocked');
  const registration = await navigator.serviceWorker.register(new URL('sw.js', siteRoot));
  await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  const { endpoint, keys } = subscription.toJSON();
  await call('push_subscribe', { endpoint, p256dh: keys.p256dh, auth: keys.auth });
  show('on');
}

async function turnOff() {
  const registration = await navigator.serviceWorker.getRegistration(siteRoot);
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    await call('push_unsubscribe', { endpoint: subscription.endpoint });
    await subscription.unsubscribe();
  }
  show('off');
}

// Preview builds only demonstrate the control: nothing is registered and nothing leaves the page.
function startPreview() {
  const note = '這是預覽：這裡只示範按鈕的樣子，正式網站才會真的訂閱推播。';
  const read = () => { try { return sessionStorage.getItem('push-preview') === 'on'; } catch { return false; } };
  const paint = on => { show(on ? 'on' : 'off'); if (statusLine) statusLine.textContent = on ? `推播已開啟。${note}` : note; };
  paint(read());
  for (const button of toggles) {
    button.addEventListener('click', () => {
      const on = button.dataset.pushState !== 'on';
      try { sessionStorage.setItem('push-preview', on ? 'on' : 'off'); } catch { /* storage blocked */ }
      paint(on);
    });
  }
}

async function start() {
  if (!key || !api || !toggles.length) return;
  if (document.querySelector('meta[name="push-preview"]')) return startPreview();
  if (!supported) {
    if (onIos && statusLine) statusLine.textContent = 'iPhone 與 iPad 要先把本站加入主畫面，再從主畫面打開，才能開啟推播。';
    return;
  }
  const registration = await navigator.serviceWorker.getRegistration(siteRoot);
  const subscription = await registration?.pushManager.getSubscription();
  show(subscription ? 'on' : Notification.permission === 'denied' ? 'blocked' : 'off');
  for (const button of toggles) {
    button.addEventListener('click', async () => {
      const wasOn = button.dataset.pushState === 'on';
      for (const b of toggles) b.disabled = true;
      try { await (wasOn ? turnOff() : turnOn()); } catch { show('failed'); }
      for (const b of toggles) b.disabled = false;
    });
  }
}

start();
