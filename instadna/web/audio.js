// Native controls remain usable without JavaScript. Keep A/B playback exclusive.
const players = [...document.querySelectorAll('audio')];
for (const player of players) {
  player.addEventListener('play', () => {
    for (const other of players) if (other !== player) other.pause();
  });
}
// Keep historical phrase links useful when their comparison group is collapsed.
function revealLinkedAudio() {
  const target = document.getElementById(location.hash.slice(1));
  const collection = target?.closest('details');
  if (collection) {
    collection.open = true;
    target.scrollIntoView({ block: 'start' });
  }
}
window.addEventListener('hashchange', revealLinkedAudio);
revealLinkedAudio();

for (const comparison of document.querySelectorAll('[data-audio-ab]')) {
  const audio = comparison.querySelector('audio');
  const buttons = [...comparison.querySelectorAll('button[data-audio-src]')];
  const status = comparison.querySelector('.ab-status');
  let switchId = 0;
  let pending = false;
  let heldPosition = 0;
  let heldResume = false;
  for (const button of buttons) {
    button.addEventListener('click', () => {
      if (button.getAttribute('aria-pressed') === 'true') return;
      const position = pending ? heldPosition : audio.currentTime;
      const resume = pending ? heldResume : !audio.paused;
      pending = true;
      heldPosition = position;
      heldResume = resume;
      const currentSwitch = ++switchId;
      audio.pause();
      for (const other of buttons) other.setAttribute('aria-pressed', String(other === button));
      status.textContent = button.dataset.audioLabel;
      comparison.querySelector('.ab-mp3').href = button.dataset.audioSrc;
      const wav = comparison.querySelector('.ab-wav');
      wav.hidden = !button.dataset.audioWav;
      if (button.dataset.audioWav) wav.href = button.dataset.audioWav;
      audio.addEventListener('loadedmetadata', () => {
        if (currentSwitch !== switchId) return;
        pending = false;
        audio.currentTime = Math.min(position, Math.max(0, audio.duration - .02));
        if (resume) audio.play().catch(() => {
          status.textContent = `${button.dataset.audioLabel} — натисніть відтворення`;
        });
      }, { once: true });
      audio.src = button.dataset.audioSrc;
      audio.load();
    });
  }
}
