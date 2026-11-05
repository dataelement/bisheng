// Fit the 1280px pages to narrow windows (the preview frame, a phone), move between
// pages with the keyboard, and toggle one-slide presenting with P. No storage, no network.
(function () {
  var deck = document.querySelector('.deck');
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var current = 0;
  function fit() {
    var w = document.documentElement.clientWidth;
    deck.style.setProperty('--fit', Math.min(1, (w - 16) / 1280).toFixed(4));
    var s = Math.min(window.innerWidth / 1280, window.innerHeight / 720);
    document.documentElement.style.setProperty('--present-scale', s.toFixed(4));
  }
  function show(i) {
    current = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach(function (el, k) { el.classList.toggle('current', k === current); });
    if (!document.body.classList.contains('present')) slides[current].scrollIntoView({ block: 'center' });
  }
  function nearest() {
    var mid = window.innerHeight / 2, best = 0, dist = Infinity;
    slides.forEach(function (el, k) {
      var r = el.getBoundingClientRect(), d = Math.abs(r.top + r.height / 2 - mid);
      if (d < dist) { dist = d; best = k; }
    });
    return best;
  }
  document.addEventListener('keydown', function (e) {
    var present = document.body.classList.contains('present');
    if (!present) current = nearest();
    if (e.key === 'p' || e.key === 'P') { document.body.classList.toggle('present'); show(current); return; }
    if (e.key === 'Escape' && present) { document.body.classList.remove('present'); show(current); return; }
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' '].indexOf(e.key) >= 0) { e.preventDefault(); show(current + 1); }
    if (['ArrowLeft', 'ArrowUp', 'PageUp'].indexOf(e.key) >= 0) { e.preventDefault(); show(current - 1); }
  });
  window.addEventListener('resize', fit);
  fit();
  if (slides.length) slides[0].classList.add('current');
})();
