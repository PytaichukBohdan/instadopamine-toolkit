const phraseCards = [...document.querySelectorAll('.phrase-card')];
const phraseSearch = document.querySelector('#phrase-search');
const phraseFamily = document.querySelector('#phrase-family');
const phraseRecency = document.querySelector('#phrase-recency');
if (phraseSearch) {
  function filterPhrases() {
    const query = phraseSearch.value.trim().toLocaleLowerCase();
    let count = 0;
    phraseCards.forEach(card => {
      card.hidden = (phraseFamily.value !== 'all' && card.dataset.family !== phraseFamily.value)
        || (phraseRecency.value !== 'all' && card.dataset.recency !== phraseRecency.value)
        || !card.textContent.toLocaleLowerCase().includes(query);
      if (card.hidden) card.querySelector('audio').pause(); else count++;
    });
    document.querySelector('#phrase-count').textContent = `${count} of ${phraseCards.length} original audio excerpts`;
  }
  phraseSearch.addEventListener('input', filterPhrases);
  phraseFamily.addEventListener('change', filterPhrases);
  phraseRecency.addEventListener('change', filterPhrases);
  function revealPhrase() {
    const card = phraseCards.find(c => '#' + c.id === location.hash);
    if (!card) return;
    phraseSearch.value = ''; phraseFamily.value = 'all'; phraseRecency.value = 'all';
    filterPhrases(); card.scrollIntoView();
  }
  window.addEventListener('hashchange', revealPhrase);
  revealPhrase();
}
