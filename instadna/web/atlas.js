const controls = document.querySelector('.atlas-controls');
if (controls) {
  controls.addEventListener('click', event => {
    const button = event.target.closest('button[data-filter]');
    if (!button) return;
    let count = 0;
    document.querySelectorAll('.reference-card').forEach(card => {
      card.hidden = button.dataset.filter !== 'all' && card.dataset.category !== button.dataset.filter;
      if (!card.hidden) count++;
    });
    controls.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    document.querySelector('#atlas-count').textContent = `${count} references · ${button.textContent}`;
  });
  if (/^#R[0-9]+$/.test(location.hash)) document.querySelector(location.hash)?.scrollIntoView();
}
