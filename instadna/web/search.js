const input = document.querySelector('#search');
const results = document.querySelector('#search-results');
let pages;
input?.addEventListener('input', async () => {
  const query = input.value.trim().toLocaleLowerCase();
  results.replaceChildren();
  if (query.length < 2) return;
  if (!pages) {
    try { const response = await fetch(`${input.dataset.root}search-index.json`); if (!response.ok) throw new Error('Search unavailable'); pages = await response.json(); }
    catch { results.textContent = 'Search is unavailable. Use the section links below.'; return; }
  }
  if (input.value.trim().toLocaleLowerCase() !== query) return;
  const tokens = query.split(/\s+/);
  const hits = pages.filter(p => tokens.every(t => `${p.title} ${p.text}`.toLocaleLowerCase().includes(t))).slice(0,12);
  for (const page of hits) { const a = document.createElement('a'); a.href = input.dataset.root + page.url; a.textContent = page.title; results.append(a); }
  if (!hits.length) results.textContent = 'No matching pages.';
});
