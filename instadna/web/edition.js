// Person edition: search, filters, copy, chart tooltips and the data room. No third-party code.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const make = (tag, props = {}, ...kids) => { const el = Object.assign(document.createElement(tag), props); el.append(...kids.filter(k => k != null)); return el; };

// Site search over page text.
(() => {
  const input = $('#search'), out = $('#search-results');
  let pages;
  input?.addEventListener('input', async () => {
    const q = input.value.trim().toLocaleLowerCase();
    out.replaceChildren();
    if (q.length < 2) return;
    try { pages ??= await (await fetch(input.dataset.root + 'search-index.json')).json(); }
    catch { out.textContent = 'Search is unavailable.'; return; }
    const words = q.split(/\s+/);
    const hits = pages.filter(p => words.every(w => (p.title + ' ' + p.text).toLocaleLowerCase().includes(w))).slice(0, 12);
    for (const p of hits) out.append(make('a', {href: input.dataset.root + p.url, textContent: p.title}));
    if (!hits.length) out.textContent = 'No matching pages.';
  });
})();

// Category buttons, text search and selects for card collections.
function wireCollection(cls) {
  const cards = $$('.' + cls);
  if (!cards.length) return;
  const group = $(`.filters[data-target="${cls}"]`);
  const search = $(`[data-search="${cls}"]`), recency = $(`[data-recency="${cls}"]`);
  const family = $(`[data-family="${cls}"]`), kind = $(`[data-kind="${cls}"]`);
  const count = cards[0].closest('article').querySelector('.count');
  let category = 'all';
  const apply = () => {
    const q = (search?.value || '').trim().toLocaleLowerCase();
    let shown = 0;
    for (const c of cards) {
      const ok = (category === 'all' || c.dataset.category === category)
        && (!q || c.textContent.toLocaleLowerCase().includes(q))
        && (!recency || recency.value === 'all' || c.dataset.recency === recency.value)
        && (!family || family.value === 'all' || c.dataset.family === family.value)
        && (!kind || kind.value === 'all' || c.dataset.kind === kind.value);
      c.hidden = !ok; shown += ok;
    }
    if (count) count.textContent = `${shown} of ${cards.length} shown`;
  };
  group?.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    category = b.dataset.filter;
    for (const x of $$('button', group)) x.setAttribute('aria-pressed', String(x === b));
    apply();
  });
  for (const el of [search, recency, family, kind]) el?.addEventListener('input', apply);
}
['item', 'ref-card', 'phrase', 'shot'].forEach(wireCollection);

// Copy a scene brief.
document.addEventListener('click', async e => {
  const b = e.target.closest('.copy'); if (!b) return;
  const status = $('.copy-status');
  try { await navigator.clipboard.writeText(b.previousElementSibling.textContent); if (status) status.textContent = 'Brief copied.'; }
  catch { if (status) status.textContent = 'Copy failed — select the text instead.'; }
  setTimeout(() => { if (status) status.textContent = ''; }, 2200);
});

// Chart tooltips on hover and keyboard focus.
for (const fig of $$('.chart')) {
  const tip = $('.tip', fig);
  const show = (mark) => {
    const box = fig.getBoundingClientRect(), r = mark.getBoundingClientRect();
    tip.textContent = mark.dataset.tip; tip.hidden = false;
    const x = Math.min(Math.max(8, r.left - box.left + r.width / 2 - tip.offsetWidth / 2), box.width - tip.offsetWidth - 8);
    tip.style.left = x + 'px'; tip.style.top = Math.max(4, r.top - box.top - tip.offsetHeight - 8) + 'px';
  };
  for (const m of $$('[data-tip]', fig)) {
    m.addEventListener('pointerenter', () => show(m)); m.addEventListener('focus', () => show(m));
    m.addEventListener('pointerleave', () => { tip.hidden = true; }); m.addEventListener('blur', () => { tip.hidden = true; });
  }
}

// Data room: every collected item, filterable, with full text, transcript and machine notes on demand.
(async () => {
  const root = $('#room'); if (!root) return;
  let index;
  try { index = await (await fetch(root.dataset.src)).json(); }
  catch { root.textContent = 'The data room could not be loaded.'; return; }
  const items = index.items;
  const opts = (values, label) => [make('option', {value: 'all', textContent: label}), ...values.map(v => make('option', {value: v, textContent: v}))];
  const q = make('input', {type: 'search', placeholder: 'Search captions, posts, titles, transcripts…', 'aria-label': 'Search items'});
  const platform = make('select', {'aria-label': 'Platform'}, ...opts([...new Set(items.map(i => i.platform_label))], 'All platforms'));
  const kind = make('select', {'aria-label': 'Format'}, ...opts([...new Set(items.map(i => i.kind))].sort(), 'All formats'));
  const year = make('select', {'aria-label': 'Year'}, ...opts([...new Set(items.map(i => (i.published_at || 'undated').slice(0, 4)))].sort().reverse(), 'All years'));
  const count = make('p', {className: 'count', role: 'status'});
  const list = make('div', {className: 'room-list'});
  const more = make('button', {type: 'button', className: 'copy room-more', textContent: 'Show more'});
  const dialog = make('dialog');
  root.replaceChildren(make('div', {className: 'room-tools'}, q, platform, kind, year), count, list, more, dialog);
  let filtered = items, shown = 0;
  const card = i => {
    const b = make('button', {type: 'button', className: 'room-item'});
    if (i.thumb) b.append(make('img', {src: 'data/' + i.thumb, alt: '', loading: 'lazy', width: 240, height: 300}));
    b.append(make('div', {}, make('strong', {textContent: `${i.platform_label} · ${i.kind}`}),
      make('span', {className: 'muted', textContent: (i.published_at || 'date unknown').slice(0, 10) + (i.duration_s ? ` · ${Math.round(i.duration_s)}s` : '')}),
      make('p', {textContent: i.title || i.snippet || ''})));
    b.addEventListener('click', () => open(i));
    return b;
  };
  const page = () => { const next = filtered.slice(shown, shown + 60); list.append(...next.map(card)); shown += next.length; more.hidden = shown >= filtered.length; };
  const apply = () => {
    const words = q.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    filtered = items.filter(i => (platform.value === 'all' || i.platform_label === platform.value)
      && (kind.value === 'all' || i.kind === kind.value)
      && (year.value === 'all' || (i.published_at || 'undated').startsWith(year.value))
      && words.every(w => i.search.includes(w)));
    list.replaceChildren(); shown = 0; page();
    count.textContent = `${filtered.length.toLocaleString()} of ${items.length.toLocaleString()} items`;
  };
  for (const el of [q, platform, kind, year]) el.addEventListener('input', apply);
  more.addEventListener('click', page);
  const section = (title, body) => body ? [make('h3', {textContent: title}), body] : [];
  async function open(i) {
    let d;
    try { d = (await (await fetch('data/' + i.shard)).json())[i.id]; } catch { d = null; }
    const body = make('div', {className: 'dialog-body'});
    const close = make('button', {type: 'button', className: 'copy close', textContent: 'Close'});
    close.addEventListener('click', () => dialog.close());
    body.append(close, make('span', {className: 'eyebrow', textContent: `${i.platform_label} · ${i.kind} · ${i.id}`}),
      make('h2', {textContent: i.title || (i.published_at || '').slice(0, 10)}),
      make('p', {}, make('a', {href: i.url, rel: 'noreferrer', textContent: 'Open the original ↗'}), ` · published ${(i.published_at || 'date unknown').slice(0, 16).replace('T', ' ')}`));
    if (!d) { body.append(make('p', {textContent: 'Details could not be loaded.'})); }
    else {
      if (d.thumbs?.length) body.append(make('div', {className: 'cards'}, ...d.thumbs.map(t => make('img', {src: 'data/' + t, alt: '', loading: 'lazy'}))));
      body.append(...section('Text', d.text ? make('p', {textContent: d.text, className: 'pre'}) : null));
      body.append(...section('Machine summary', d.summary ? make('p', {textContent: d.summary}) : null));
      if (d.facts?.length) body.append(...section('Notes', make('ul', {}, ...d.facts.map(([k, v]) => make('li', {}, make('strong', {textContent: k + ': '}), v)))));
      if (d.transcript?.length) body.append(...section(`Transcript (${d.transcript_source})`, make('div', {}, ...d.transcript.map(s => make('p', {className: 'seg'}, make('b', {textContent: s[0]}), s[1])))));
      body.append(make('p', {className: 'muted', textContent: 'Automatic transcription and machine observations: verify quotes, names and attribution against the original before reuse.'}));
    }
    dialog.replaceChildren(body); dialog.showModal();
  }
  apply();
})();

// Storyboard: the current shot follows the voice; play from any shot; optionally only the 30-second cut.
(() => {
  const board = $('.board');
  if (!board) return;
  const audio = $('.board-audio', board), screen = $('.board-current', board), now = $('.board-now', board);
  const said = $('.board-vo', board), only = $('.board-short', board);
  const cards = new Map($$('.shot', board).map(c => [c.id, c]));
  const segs = new Map($$('.seg', board).map(r => [r.dataset.shot, r]));
  let shots = [], current = null, raf = 0;
  const clock = t => `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, '0')}`;
  const at = t => shots.find(s => t >= s.start && t < s.end) || shots[shots.length - 1];
  const picture = s => (s.styled && s.styled.fp) || s.frame;
  const show = t => {
    const s = at(t);
    if (!s) return;
    if (s !== current) {
      current = s;
      const img = picture(s);
      if (img) { screen.src = img.thumbnail || img.path; screen.alt = `${s.id}: ${s.title}`; }
      for (const [id, c] of cards) c.classList.toggle('playing', id === s.id);
      for (const [id, r] of segs) r.classList.toggle('on', id === s.id);
      const next = shots[shots.indexOf(s) + 1], nextImg = next && picture(next);
      if (nextImg) new Image().src = nextImg.thumbnail || nextImg.path; // no flash on the cut
    }
    now.textContent = `${s.id} · ${clock(s.start)}–${clock(s.end)} · ${s.title}`;
    said.textContent = s.words.filter(w => w.start <= t).map(w => w.w).join(' ');
  };
  const skip = () => {
    if (!only || !only.checked) return;
    const s = at(audio.currentTime);
    if (!s || s.short_cut) return;
    const next = shots.find(x => x.start >= s.end - 1e-3 && x.short_cut);
    if (next) audio.currentTime = next.start; else audio.pause();
  };
  const tick = () => { skip(); show(audio.currentTime); if (!audio.paused) raf = requestAnimationFrame(tick); };
  fetch(board.dataset.src).then(r => r.json()).then(d => { shots = d.shots; show(0); })
    .catch(() => { now.textContent = 'Shot timing is unavailable; the cards below still work.'; });
  audio.addEventListener('play', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(tick); });
  audio.addEventListener('pause', () => cancelAnimationFrame(raf));
  audio.addEventListener('seeked', () => show(audio.currentTime));
  only?.addEventListener('change', () => { skip(); show(audio.currentTime); });
  board.addEventListener('click', e => {
    const b = e.target.closest('[data-seek]');
    if (!b) return;
    audio.currentTime = +b.dataset.seek;
    audio.play().catch(() => {});
    board.querySelector('.board-player').scrollIntoView({block: 'nearest'});
  });
})();
