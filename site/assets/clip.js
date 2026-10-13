/* The demo recording's controls: a play button over the poster, a "Watch the demo" button, and chapters that seek. Without this script the video keeps its own controls. */
(function () {
  'use strict';
  var v = document.getElementById('clip'), box = document.getElementById('clipBox'), play = document.getElementById('clipPlay'), go = document.getElementById('clipGo');
  if (!v || !box || !play) return;
  var chapters = Array.prototype.slice.call(document.querySelectorAll('#clipChapters button'));
  var label = play.querySelector('.lt');
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  v.removeAttribute('controls');
  play.hidden = false;

  function start(t) {
    if (typeof t === 'number') { try { v.currentTime = t; } catch (e) { /* metadata not loaded yet: it plays from the start */ } }
    v.setAttribute('controls', '');
    box.classList.add('playing');
    var p = v.play();
    if (p && p.catch) p.catch(function () { box.classList.remove('playing'); });
  }
  function mark() {
    var now = v.currentTime, on = -1;
    chapters.forEach(function (b, i) { if (Number(b.getAttribute('data-t')) <= now + 0.25) on = i; });
    chapters.forEach(function (b, i) { b.classList.toggle('on', i === on && (!v.paused || now > 0)); });
  }
  play.addEventListener('click', function () { start(v.ended ? 0 : undefined); });
  if (go) go.addEventListener('click', function () {
    box.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
    start(v.ended || v.currentTime === 0 ? 0 : undefined);
  });
  chapters.forEach(function (b) {
    b.addEventListener('click', function () { start(Number(b.getAttribute('data-t'))); });
  });
  v.addEventListener('timeupdate', mark);
  v.addEventListener('seeked', mark);
  v.addEventListener('ended', function () {
    box.classList.remove('playing');
    v.removeAttribute('controls');
    if (label) label.textContent = 'Watch again';
    chapters.forEach(function (b) { b.classList.remove('on'); });
  });
  v.addEventListener('play', function () { if (label) label.textContent = 'Watch the demo'; });
})();
