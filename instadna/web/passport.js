const toolbar = document.querySelector('.item-toolbar');
if (toolbar) {
  let category = 'all';
  const search = document.querySelector('#item-search');
  const recurrence = document.querySelector('#item-recurrence');
  const recency = document.querySelector('#item-recency');
  const cards = [...document.querySelectorAll('.passport-item')];
  function filter() {
    const query = search.value.trim().toLocaleLowerCase();
    let count = 0;
    cards.forEach(card => {
      card.hidden = (category !== 'all' && card.dataset.category !== category) || (recurrence.value !== 'all' && card.dataset.recurrence !== recurrence.value) || (recency.value !== 'all' && card.dataset.recency !== recency.value) || !card.textContent.toLocaleLowerCase().includes(query);
      if (!card.hidden) count++;
    });
    document.querySelector('#item-count').textContent = `${count} of ${cards.length} separate items`;
  }
  toolbar.addEventListener('click', event => {
    const button = event.target.closest('button[data-category]');
    if (!button) return;
    category = button.dataset.category;
    toolbar.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    filter();
  });
  search.addEventListener('input', filter);
  recurrence.addEventListener('change', filter);
  recency.addEventListener('change', filter);
  document.querySelector('.passport-items').addEventListener('click', async event => {
    const button = event.target.closest('.copy-brief');
    if (!button) return;
    const text = button.closest('details').querySelector('.item-brief').textContent;
    const status = document.querySelector('#item-copy-status');
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = 'Usage brief copied.';
    } catch {
      status.textContent = 'Select the visible usage brief to copy it.';
    }
  });
  function revealHash() {
    const card = cards.find(c => '#' + c.id === location.hash);
    if (!card) return;
    category = 'all'; search.value = ''; recurrence.value = 'all'; recency.value = 'all';
    toolbar.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.category === 'all')));
    filter(); card.scrollIntoView();
  }
  window.addEventListener('hashchange', revealHash);
  revealHash();
}
