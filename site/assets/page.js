(() => {
  const $ = id => document.getElementById(id);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const RENDER = location.hash === '#render';
  const stage = $('stage');
  REEL.build(stage);
  const fontsReady = (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(() => { REEL.layout(); REEL.render(state.t); });

  // ---------- render mode: the stage alone at 1920 x 1080, for frame capture ----------
  const state = { t: 9.3, playing: false, auto: !reduce, user: false, sound: false, last: 0, visible: false };
  if (RENDER) {
    document.documentElement.classList.add('render');
    document.body.prepend(stage);
    window.__ready = fontsReady.then(() => new Promise(r => setTimeout(r, 300))).then(() => true);
    window.__staticGrain = true;
    window.__seek = t => { REEL.render(t); return true; };
    window.__audio = () => SCORE.renderWav(48000);
    return;
  }

  // ---------- the player ----------
  const box = $('reelBox'), seek = $('seek'), prog = $('prog'), tc = $('tc');
  const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  function scaleStage() {
    const fs = document.fullscreenElement === box;
    const w = box.clientWidth, h = box.clientHeight;
    const k = fs ? Math.min(w / 1920, h / 1080) : w / 1920;
    stage.style.transform = `scale(${k})`;
    stage.style.left = fs ? ((w - 1920 * k) / 2) + 'px' : '0px';
    stage.style.top = fs ? ((h - 1080 * k) / 2) + 'px' : '0px';
  }
  new ResizeObserver(scaleStage).observe(box); scaleStage();
  document.addEventListener('fullscreenchange', scaleStage);

  const chap = $('chapters');
  REEL.CHAPTERS.forEach(([t, n], i) => {
    const li = document.createElement('li');
    li.innerHTML = `<button type="button"><span class="tcode">${fmt(t)}</span><span class="nm">${n}</span></button>`;
    li.firstChild.addEventListener('click', () => { go(t + .001); play(true); });
    chap.append(li);
    if (i) { const b = document.createElement('b'); b.style.left = (t / REEL.DUR * 100) + '%'; $('track').append(b); }
  });
  const chapBtns = [...chap.querySelectorAll('button')];

  function ui() {
    const t = state.t;
    seek.value = t.toFixed(2); prog.style.width = (t / REEL.DUR * 100) + '%';
    tc.textContent = `${fmt(t)} / ${fmt(REEL.DUR)}`;
    let c = 0; REEL.CHAPTERS.forEach(([ct], i) => { if (t >= ct - .001) c = i; });
    chapBtns.forEach((b, i) => { const on = i === c; if (b._on !== on) { b._on = on; b.classList.toggle('on', on); b.setAttribute('aria-current', on ? 'true' : 'false'); } });
    $('playT').textContent = state.playing ? 'Pause' : 'Play';
    $('playIc').setAttribute('d', state.playing ? 'M7 5h4v14H7zM13 5h4v14h-4z' : 'M8 5.5v13l11-6.5z');
  }
  function draw() { REEL.render(state.t); ui(); }
  function go(t) { state.t = Math.max(0, Math.min(REEL.DUR, t)); if (state.playing && state.sound) SCORE.play(state.t); draw(); }
  function play(user) {
    if (user) state.user = true;
    if (state.t >= REEL.DUR - .05) state.t = 0;
    state.playing = true; state.last = performance.now();
    if (state.sound) SCORE.play(state.t);
    ui();
  }
  function pause(user) { if (user) { state.user = true; state.auto = false; } state.playing = false; SCORE.stop(); ui(); }
  function toggle() { state.playing ? pause(true) : play(true); }
  function frame(now) {
    if (state.playing) {
      const at = state.sound ? SCORE.now() : null;
      state.t = at != null ? at : state.t + Math.min(.1, (now - state.last) / 1000);
      if (state.t >= REEL.DUR) { state.t = 0; if (state.sound) SCORE.play(0); }
      draw();
    }
    state.last = now;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  $('play').addEventListener('click', toggle);
  box.addEventListener('click', toggle);
  box.addEventListener('keydown', e => {
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); go(state.t + 5); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(state.t - 5); }
    else if (e.key === 'm') { e.preventDefault(); $('snd').click(); }
  });
  seek.addEventListener('input', () => { state.user = true; go(parseFloat(seek.value)); });
  $('snd').addEventListener('click', () => {
    state.sound = !state.sound;
    $('snd').setAttribute('aria-pressed', String(state.sound));
    $('sndT').textContent = state.sound ? 'Sound on' : 'Sound off';
    $('sndW').setAttribute('opacity', state.sound ? '1' : '.3');
    if (state.sound) { if (!state.playing) play(true); else SCORE.play(state.t); } else SCORE.stop();
  });
  const fsb = $('fs');
  if (!box.requestFullscreen) fsb.hidden = true;
  fsb.addEventListener('click', () => {
    try {
      if (document.fullscreenElement) document.exitFullscreen();
      else { const p = box.requestFullscreen(); if (p && p.catch) p.catch(() => { fsb.hidden = true; }); }
    } catch (e) { fsb.hidden = true; }
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden && state.playing) { pause(false); state.resume = true; } else if (!document.hidden && state.resume) { state.resume = false; play(false); } });
  // autoplay muted while the reel is on screen, from the poster frame
  draw();
  if (!reduce) {
    new IntersectionObserver(es => es.forEach(e => {
      state.visible = e.isIntersecting;
      if (e.isIntersecting && state.auto && !state.playing) {
        setTimeout(() => { if (state.visible && state.auto && !state.playing) { if (!state.user) state.t = 0; play(false); } }, state.user ? 0 : 900);
      } else if (!e.isIntersecting && state.playing && !state.sound) { pause(false); }
    }), { threshold: .4 }).observe(box);
  }

  // ---------- phones on the page ----------
  const BUILD = {
    lock: () => PD.device('and', PD.lock('and')),
    home: () => PD.device('and', PD.home('and')),
    sheet: () => PD.device('and', PD.home('and', { sheet: true, ready: true })),
    sent: () => PD.device('and', PD.home('and', { sheet: true, sent: true })),
    pair: () => PD.device('and', PD.pair('and', { done: true })),
  };
  const fits = [];
  document.querySelectorAll('[data-ph]').forEach(el => { el.innerHTML = BUILD[el.dataset.ph](); fits.push(el); });
  function fit(el) {
    const dev = el.querySelector('.dev'); if (!dev) return;
    const s = el.clientWidth / 417;
    dev.style.transform = `scale(${s})`;
    dev.style.left = ((417 - dev.offsetWidth) * s / 2) + 'px';
    if (!el.classList.contains('layer')) el.style.height = (876 * s) + 'px';
  }
  // the guarded-answer demo
  const demo = $('demoPh');
  demo.innerHTML = PD.device('and', PD.home('and', { sheet: true, long: true, live: true }));
  fits.push(demo);
  const ro = new ResizeObserver(() => fits.forEach(fit)); fits.forEach(el => { fit(el); ro.observe(el); });

  const d = PD.keys(demo), say = $('demoSay'), gl = $('guards');
  const gItem = k => gl.querySelector(`[data-g="${k}"]`);
  const D = { t0: 0, read: false, guard: false, done: false, raf: 0 };
  function dState() {
    const ready = D.read && D.guard && !D.done;
    d.yes.disabled = !ready; d.no.disabled = !ready;
    d.yes.classList.toggle('off', !ready); d.no.classList.toggle('off', !ready);
    d.g1.classList.toggle('ok', D.read); d.g2.classList.toggle('ok', D.guard);
    gItem('read').classList.toggle('ok', D.read); gItem('guard').classList.toggle('ok', D.guard);
    if (D.done) return;
    say.innerHTML = !D.read ? 'Scroll the request to the end. <b>Yes stays off</b> until you have read all of it.'
      : !D.guard ? 'Read in full. Waiting out the 1.5 s guard.'
      : '<b>Ready.</b> Yes and No are bound to hook request 7f3a9c1e.';
  }
  function dReset() {
    cancelAnimationFrame(D.raf);
    Object.assign(D, { t0: performance.now(), read: false, guard: false, done: false });
    d.slab.scrollTop = 0;
    d.ask.style.visibility = 'visible'; d.ask.style.opacity = '1';
    d.sent.style.visibility = 'hidden'; d.sent.style.opacity = '0';
    d.yesfill.style.width = '0%';
    const step = () => {
      const p = Math.min(1, (performance.now() - D.t0) / 1500);
      d.yesfill.style.width = (p < 1 ? p * 100 : 0) + '%';
      if (p >= 1 && !D.guard) { D.guard = true; dState(); }
      if (p < 1) D.raf = requestAnimationFrame(step);
    };
    if (reduce) { setTimeout(() => { D.guard = true; dState(); }, 1500); } else D.raf = requestAnimationFrame(step);
    checkRead(); dState();
  }
  function checkRead() {
    const s = d.slab;
    if (!D.read && s.scrollTop + s.clientHeight >= s.scrollHeight - 4) { D.read = true; dState(); }
  }
  d.slab.addEventListener('scroll', checkRead, { passive: true });
  function answer(word) {
    if (!D.read || !D.guard || D.done) return;
    D.done = true; dState();
    d.sent.querySelector('.t').textContent = word + ' delivered';
    d.ask.style.transition = d.sent.style.transition = 'opacity .2s';
    d.ask.style.opacity = '0'; d.ask.style.visibility = 'hidden';
    d.sent.style.visibility = 'visible'; d.sent.style.opacity = '1';
    say.innerHTML = word === 'Yes'
      ? '<b>Delivered</b> to hook request 7f3a9c1e. Claude reports working; Paddock claims nothing beyond that.'
      : '<b>No delivered</b> to hook request 7f3a9c1e. Claude will ask what to do instead.';
  }
  d.yes.addEventListener('click', () => answer('Yes'));
  d.no.addEventListener('click', () => answer('No'));
  d.back.addEventListener('click', dReset);
  $('demoReset').addEventListener('click', dReset);
  dReset();

  // the pairing popup's QR, from the example link's modules
  const qc = $('pairQr');
  if (qc && window.PADDOCK_QR) {
    const bits = window.PADDOCK_QR, n = Math.round(Math.sqrt(bits.length)), m = qc.width / (n + 4), x = qc.getContext('2d');
    x.fillStyle = '#f2f4fb'; x.fillRect(0, 0, qc.width, qc.height); x.fillStyle = '#16161e';
    for (let i = 0; i < bits.length; i++) if (bits[i] === '1') x.fillRect((i % n + 2) * m, (Math.floor(i / n) + 2) * m, m + .3, m + .3);
  }
  // copy buttons
  document.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => {
    const el = $(b.dataset.copy), text = el.textContent;
    const done = ok => { b.textContent = ok ? 'Copied' : 'Select and copy'; setTimeout(() => { b.textContent = 'Copy'; }, 1800); };
    const select = () => { const r = document.createRange(); r.selectNodeContents(el); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); };
    try { navigator.clipboard.writeText(text).then(() => done(true), () => { select(); done(false); }); } catch (e) { select(); done(false); }
  }));

  // ---------- a live herd ----------
  const grid = $('herdGrid'), sum = $('herdSum');
  const KINDS = ['claude', 'codex', 'opencode', 'gemini', 'copilot', 'cursor', 'pi', 'amp'];
  const PROJ = ['docs-vault', 'blindpass', 'paddock', 'omasafe', 'trading-signal', 'herdr-fixtures', 'yadtm', 'portfolio'];
  let seed = 4;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const herd = Array.from({ length: 24 }, (_, i) => {
    const el = document.createElement('div'); el.className = 'cow';
    const k = KINDS[(i * 3 + Math.floor(i / 8)) % 8];
    el.innerHTML = `<div class="top2"><span class="mgt">${PD.glyph(k)}</span><span class="dot blue"></span></div><span class="nm">${PROJ[(i * 5) % 8]} › ${1 + (i * 7) % 9}</span>`;
    grid.append(el);
    return { el, dot: el.querySelector('.dot'), st: 'work', until: 0 };
  });
  [[3, 'red'], [14, 'red'], [9, 'green'], [5, 'ready'], [11, 'ready'], [19, 'ready'], [22, 'ready']].forEach(([i, s]) => { herd[i].st = s; herd[i].until = 2 + rnd() * 6; });
  function paint() {
    const n = { red: 0, green: 0, work: 0, ready: 0 };
    herd.forEach(c => {
      n[c.st]++;
      c.el.className = 'cow' + (c.st === 'red' ? ' red' : c.st === 'green' ? ' green' : c.st === 'ready' ? ' ready' : '');
      c.dot.className = 'dot ' + (c.st === 'red' ? 'red' : c.st === 'green' ? 'green' : c.st === 'ready' ? '' : 'blue');
    });
    sum.innerHTML = `<span class="r">${n.red} need${n.red === 1 ? 's' : ''} you</span> · ${n.green} done · ${n.work} working · ${n.ready} ready`;
  }
  let ht = 0;
  function stepHerd() {
    ht += 1;
    herd.forEach(c => {
      if (c.until && ht >= c.until) {
        c.until = 0;
        c.st = c.st === 'red' ? 'work' : c.st === 'green' ? 'ready' : c.st === 'ready' ? 'work' : c.st;
        if (c.st === 'ready') c.until = ht + 4 + Math.floor(rnd() * 5);
      }
    });
    const reds = herd.filter(c => c.st === 'red').length;
    const work = herd.filter(c => c.st === 'work');
    if (work.length && rnd() < (reds < 2 ? .55 : .15)) { const c = work[Math.floor(rnd() * work.length)]; c.st = 'red'; c.until = ht + 3 + Math.floor(rnd() * 3); }
    if (work.length && rnd() < .3) { const c = work[Math.floor(rnd() * work.length)]; c.st = 'green'; c.until = ht + 3; }
    paint();
  }
  paint();
  if (!reduce) {
    let timer = 0;
    new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting && !timer) timer = setInterval(stepHerd, 1300);
      else if (!e.isIntersecting && timer) { clearInterval(timer); timer = 0; }
    })).observe(grid);
  }
})();
