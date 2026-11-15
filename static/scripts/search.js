// Client-side search over search.json (built with the site). No server, no third party.
const input = document.getElementById('q');
const out = document.getElementById('search-results');
const siteRoot = new URL(document.documentElement.dataset.root || './', location.href);
let index;

async function search() {
  const terms = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length || terms.join('').length < 2) { out.replaceChildren(); return; }
  index ??= await (await fetch(input.dataset.index)).json();
  const hits = index.filter(entry => terms.every(term => entry.text.includes(term)));
  const summary = document.createElement('p');
  summary.textContent = hits.length ? `找到 ${hits.length} 筆` : '找不到符合的消息或文獻';
  const list = document.createElement('ul');
  for (const hit of hits.slice(0, 8)) {
    const item = document.createElement('li');
    const href = new URL(hit.path.slice(1) + input.dataset.suffix, siteRoot).href;
    const link = Object.assign(document.createElement('a'), { href, textContent: hit.title });
    const meta = Object.assign(document.createElement('span'), { textContent: hit.meta });
    item.append(link, meta);
    list.append(item);
  }
  out.replaceChildren(summary, list);
}

if (input && out) {
  input.addEventListener('input', search);
  input.form.addEventListener('submit', event => event.preventDefault());
  if (location.hash === '#q') input.focus();
}
