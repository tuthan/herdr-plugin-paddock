// The reel's soundtrack, synthesised with Web Audio from the same moments as the picture (REEL.T).
// Live: a look-ahead scheduler on an AudioContext. Offline: every event on an OfflineAudioContext for the MP4.
const SCORE = (() => {
  const T = REEL.T;
  const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
  const rng = seed => () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let x = Math.imul(seed ^ seed >>> 15, 1 | seed); x = x + Math.imul(x ^ x >>> 7, 61 | x) ^ x; return ((x ^ x >>> 14) >>> 0) / 4294967296; };

  function noiseBuf(ctx) {
    const r = rng(3), b = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = r() * 2 - 1;
    return b;
  }
  function impulse(ctx, secs, decay) {
    const r = rng(11), n = Math.floor(ctx.sampleRate * secs), b = ctx.createBuffer(2, n, ctx.sampleRate);
    for (let c = 0; c < 2; c++) { const d = b.getChannelData(c); for (let i = 0; i < n; i++) d[i] = (r() * 2 - 1) * Math.pow(1 - i / n, decay); }
    return b;
  }
  const buses = new WeakMap();
  function base(ctx) {
    if (buses.has(ctx)) return buses.get(ctx);
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.knee.value = 10; comp.ratio.value = 3; comp.attack.value = .005; comp.release.value = .25;
    const master = ctx.createGain(); master.gain.value = .85;
    comp.connect(master); master.connect(ctx.destination);
    const rev = ctx.createConvolver(); rev.buffer = impulse(ctx, 3.2, 2.6);
    const rg = ctx.createGain(); rg.gain.value = .5; rev.connect(rg); rg.connect(comp);
    const b = { ctx, comp, rev, master, noise: noiseBuf(ctx) };
    buses.set(ctx, b); return b;
  }

  // ---------- instruments: (bus, when, ...) ----------
  const G = (ctx, w, peak, a, d, curve = 'exp') => {
    const g = ctx.createGain(); g.gain.setValueAtTime(.0001, w);
    g.gain.exponentialRampToValueAtTime(Math.max(peak, .0002), w + a);
    if (curve === 'exp') g.gain.exponentialRampToValueAtTime(.0001, w + a + d); else g.gain.linearRampToValueAtTime(0, w + a + d);
    return g;
  };
  const out = (b, node, rev = 0) => { node.connect(b.dry); if (rev) { const s = b.ctx.createGain(); s.gain.value = rev; node.connect(s); s.connect(b.send); } };
  function pad(b, w, dur, notes, { vol = .012, cut = 1200, att = .8, rel = 1.6, rev = .55 } = {}) {
    const c = b.ctx, g = c.createGain();
    g.gain.setValueAtTime(0, w); g.gain.linearRampToValueAtTime(vol, w + att); g.gain.setValueAtTime(vol, w + Math.max(att, dur)); g.gain.linearRampToValueAtTime(0, w + dur + rel);
    const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = cut; f.Q.value = .5;
    f.connect(g); out(b, g, rev);
    for (const n of notes) for (const dt of [-8, 8]) { const o = c.createOscillator(); o.type = 'sawtooth'; o.frequency.value = mtof(n); o.detune.value = dt; o.connect(f); o.start(w); o.stop(w + dur + rel + .05); }
  }
  function pluck(b, w, n, v = .08, dec = .45, rev = .4, type = 'triangle') {
    const c = b.ctx, o = c.createOscillator(), o2 = c.createOscillator(), g = G(c, w, v, .004, dec), g2 = G(c, w, v * .3, .003, dec * .5);
    o.type = type; o.frequency.value = mtof(n); o2.type = 'sine'; o2.frequency.value = mtof(n) * 2;
    o.connect(g); o2.connect(g2); out(b, g, rev); out(b, g2, rev);
    o.start(w); o2.start(w); o.stop(w + dec + .05); o2.stop(w + dec + .05);
  }
  function kick(b, w, v = .8) {
    const c = b.ctx, o = c.createOscillator(); o.type = 'sine';
    o.frequency.setValueAtTime(150, w); o.frequency.exponentialRampToValueAtTime(45, w + .12);
    const g = G(c, w, v, .003, .4); o.connect(g); out(b, g, 0); o.start(w); o.stop(w + .45);
    const s = c.createBufferSource(); s.buffer = b.noise; const f = c.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = 2500;
    const g2 = G(c, w, v * .12, .001, .012); s.connect(f); f.connect(g2); out(b, g2, 0); s.start(w, .3); s.stop(w + .03);
  }
  function tom(b, w, v = .5) {
    const c = b.ctx, o = c.createOscillator(); o.type = 'sine';
    o.frequency.setValueAtTime(190, w); o.frequency.exponentialRampToValueAtTime(70, w + .25);
    const g = G(c, w, v, .003, .5); o.connect(g); out(b, g, .3); o.start(w); o.stop(w + .55);
  }
  function hat(b, w, v = .06, dec = .045, hp = 7500, off = .1) {
    const c = b.ctx, s = c.createBufferSource(); s.buffer = b.noise;
    const f = c.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = hp;
    const g = G(c, w, v, .001, dec); s.connect(f); f.connect(g); out(b, g, .05); s.start(w, off); s.stop(w + dec + .02);
  }
  function clap(b, w, v = .22) {
    const c = b.ctx, s = c.createBufferSource(); s.buffer = b.noise;
    const f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 1600; f.Q.value = .9;
    const g = G(c, w, v, .002, .18); s.connect(f); f.connect(g); out(b, g, .35); s.start(w, .7); s.stop(w + .22);
  }
  function bass(b, w, n, dur = .3, v = .2) {
    const c = b.ctx, o = c.createOscillator(), o2 = c.createOscillator(); o.type = 'triangle'; o2.type = 'sine';
    o.frequency.value = mtof(n); o2.frequency.value = mtof(n - 12);
    const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = 520;
    const g = c.createGain(); g.gain.setValueAtTime(.0001, w); g.gain.exponentialRampToValueAtTime(v, w + .01); g.gain.setValueAtTime(v, w + dur * .6); g.gain.exponentialRampToValueAtTime(.0001, w + dur);
    o.connect(f); o2.connect(f); f.connect(g); out(b, g, 0); o.start(w); o2.start(w); o.stop(w + dur + .02); o2.stop(w + dur + .02);
  }
  function whoosh(b, w, dur, f0, f1, v = .07) {
    const c = b.ctx, s = c.createBufferSource(); s.buffer = b.noise; s.loop = true;
    const f = c.createBiquadFilter(); f.type = 'bandpass'; f.Q.value = 1.1;
    f.frequency.setValueAtTime(f0, w); f.frequency.exponentialRampToValueAtTime(f1, w + dur);
    const g = c.createGain(); g.gain.setValueAtTime(0, w); g.gain.linearRampToValueAtTime(v, w + dur * .55); g.gain.linearRampToValueAtTime(0, w + dur);
    s.connect(f); f.connect(g); out(b, g, .4); s.start(w, .5); s.stop(w + dur + .02);
  }
  function riser(b, w, dur, v = .14) {
    const c = b.ctx, s = c.createBufferSource(); s.buffer = b.noise; s.loop = true;
    const f = c.createBiquadFilter(); f.type = 'highpass'; f.frequency.setValueAtTime(300, w); f.frequency.exponentialRampToValueAtTime(7000, w + dur);
    const g = c.createGain(); g.gain.setValueAtTime(.0001, w); g.gain.exponentialRampToValueAtTime(v, w + dur); g.gain.linearRampToValueAtTime(0, w + dur + .04);
    s.connect(f); f.connect(g); out(b, g, .3); s.start(w, .2); s.stop(w + dur + .06);
  }
  function boom(b, w, v = .9) {
    const c = b.ctx, o = c.createOscillator(); o.type = 'sine';
    o.frequency.setValueAtTime(72, w); o.frequency.exponentialRampToValueAtTime(34, w + 1.6);
    const g = G(c, w, v, .006, 2.4); o.connect(g); out(b, g, .15); o.start(w); o.stop(w + 2.5);
    const s = c.createBufferSource(); s.buffer = b.noise; const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = 900;
    const g2 = G(c, w, v * .35, .004, .5); s.connect(f); f.connect(g2); out(b, g2, .6); s.start(w, 1.1); s.stop(w + .6);
  }
  function tick(b, w, v = .03, hp = 4200) { hat(b, w, v, .016, hp, (w * 3.7) % 1.5); }
  function keyc(b, w, v = .22) {
    const c = b.ctx, s = c.createBufferSource(); s.buffer = b.noise; const f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 2600; f.Q.value = 1.6;
    const g = G(c, w, v, .001, .03); s.connect(f); f.connect(g); out(b, g, .05); s.start(w, .9); s.stop(w + .05);
    const o = c.createOscillator(); o.frequency.value = 680; const g2 = G(c, w, v * .4, .001, .02); o.connect(g2); out(b, g2, 0); o.start(w); o.stop(w + .04);
  }
  function tap(b, w, v = .14) {
    const c = b.ctx, o = c.createOscillator(); o.type = 'sine'; o.frequency.setValueAtTime(2100, w); o.frequency.exponentialRampToValueAtTime(1200, w + .03);
    const g = G(c, w, v, .001, .045); o.connect(g); out(b, g, .1); o.start(w); o.stop(w + .06);
    tick(b, w, v * .4, 3000);
  }
  function buzz(b, w) {
    const c = b.ctx;
    for (const dt of [0, .14]) {
      const o = c.createOscillator(); o.type = 'square'; o.frequency.value = 155;
      const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = 320;
      const g = c.createGain(); g.gain.setValueAtTime(0, w + dt); g.gain.linearRampToValueAtTime(.16, w + dt + .01); g.gain.setValueAtTime(.16, w + dt + .08); g.gain.linearRampToValueAtTime(0, w + dt + .1);
      o.connect(f); f.connect(g); out(b, g, 0); o.start(w + dt); o.stop(w + dt + .12);
    }
  }
  function blip(b, w, dur, v = .05) {
    const c = b.ctx, o = c.createOscillator(); o.type = 'sine'; o.frequency.setValueAtTime(520, w); o.frequency.exponentialRampToValueAtTime(1900, w + dur);
    const g = c.createGain(); g.gain.setValueAtTime(0, w); g.gain.linearRampToValueAtTime(v, w + .05); g.gain.linearRampToValueAtTime(0, w + dur);
    o.connect(g); out(b, g, .4); o.start(w); o.stop(w + dur + .02);
  }
  function fadeAll(b, w, dur) {
    for (const n of [b.dry, b.send]) { n.gain.setValueAtTime(1, w); n.gain.linearRampToValueAtTime(0, w + dur); }
  }

  // ---------- the score: a sorted list of [time, duration, play(bus, when)] ----------
  const EV = [];
  const at = (t, d, f) => EV.push([t, d, f]);
  const CH = {
    F: [[53, 57, 60, 64], 41], G: [[55, 59, 62, 64], 43], A: [[57, 60, 64, 67], 45], E: [[52, 55, 59, 62], 40],
  };
  // scene 1
  at(0.05, 7.0, (b, w) => pad(b, w, 6.6, [45, 52, 57, 60], { vol: .009, cut: 650, att: 2.2, rel: 1.0 }));
  [69, 72, 74, 76, 79, 81, 84, 86].forEach((n, i) => at(.38 + i * .1, .4, (b, w) => pluck(b, w, n, .045, .3, .5)));
  for (let t = 2.25; t < 6.2; t += .25) at(t, .05, (b, w) => tick(b, w, (Math.round((t - 2.25) / .25) % 4 === 0) ? .05 : .025, 6000));
  at(4.44, .8, (b, w) => { pluck(b, w, 77, .11, .7, .5, 'sine'); pluck(b, w, 76, .09, .7, .5, 'sine'); kick(b, w, .45); });
  at(4.95, .8, (b, w) => { pluck(b, w, 77, .06, .6, .6, 'sine'); pluck(b, w, 76, .05, .6, .6, 'sine'); });
  at(5.55, 1.45, (b, w) => riser(b, w, 1.45, .16));
  // scene 2: the mark
  at(7.0, 2.6, (b, w) => boom(b, w, .85));
  at(7.0, 5.2, (b, w) => pad(b, w, 3.0, [41, 48, 52, 55, 57, 64], { vol: .011, cut: 2600, att: .04, rel: 2.2 }));
  at(7.2, 1.0, (b, w) => whoosh(b, w, .9, 500, 5200, .06));
  [84, 86, 88, 91, 93, 96, 98].forEach((n, i) => at(7.86 + i * .055, .7, (b, w) => pluck(b, w, n, .04, .6, .7, 'sine')));
  at(9.88, .7, (b, w) => whoosh(b, w, .7, 3200, 420, .06));
  // the groove: bars of 2 s from 10.5
  const prog = ['F', 'G', 'A', 'E', 'F', 'G', 'A', 'E', 'F', 'G', 'A', 'E', 'F', 'G', 'A'];
  prog.forEach((ch, i) => {
    const bt = 10.5 + i * 2; if (bt >= 42) return;
    const [notes, root] = CH[ch];
    const cut = bt < 25 ? 1100 : bt < 31 ? 1700 : 2300;
    at(bt, 3.6, (b, w) => pad(b, w, 2.0, notes, { vol: .0085, cut, att: .5, rel: 1.4 }));
    if (bt >= 12.5) [0, .75, 1.0, 1.75].forEach((o, k) => at(bt + o, .32, (b, w) => bass(b, w, root + (k === 2 ? 12 : 0), .3, .16)));
  });
  for (let t = 10.75; t < 41.9; t += .5) at(t, .06, (b, w) => hat(b, w, t > 37.4 ? .07 : .05));
  for (let t = 25.0; t < 37.4; t += .5) at(t, .05, (b, w) => hat(b, w, .025, .03, 9000));
  for (let t = 12.5; t < 42; t += .5) {
    const reading = t > 17.2 && t < 20.3;
    if (!reading) at(t, .45, (b, w) => kick(b, w, t > 37.4 ? .75 : .55));
  }
  for (let t = 14.5 + .5; t < 41; t += 1) { if (t > 17.2 && t < 20.5) continue; at(t, .22, (b, w) => clap(b, w, .16)); }
  for (let t = 37.5; t < 41; t += .25) at(t, .05, (b, w) => hat(b, w, .035, .03, 9500));
  // trust: an arpeggio
  const arp = [69, 72, 76, 79, 76, 72];
  for (let i = 0, t = 31.5; t < 37.3; t += .125, i++) at(t, .25, (b, w) => pluck(b, w, arp[i % arp.length] + (t > 34.5 ? 2 : 0), .028, .18, .35));
  // the wall and the end
  [38.1, 38.35, 38.6].forEach((t, i) => at(t, .6, (b, w) => { tom(b, w, .45); pluck(b, w, [57, 64, 69][i], .06, .5, .5); }));
  at(39.6, 2.4, (b, w) => riser(b, w, 2.4, .2));
  for (let k = 0; k < 16; k++) { const t = 41.0 + k * .0625; at(t, .2, (b, w) => clap(b, w, .05 + k * .012)); }
  at(42.0, 2.6, (b, w) => boom(b, w, .95));
  at(42.0, 5, (b, w) => pad(b, w, 1.8, [36, 43, 52, 59, 62, 64], { vol: .012, cut: 3200, att: .02, rel: 2.4 }));
  [84, 88, 91, 95, 98].forEach((n, i) => at(42.02 + i * .08, 1.6, (b, w) => pluck(b, w, n, .035, 1.4, .8, 'sine')));
  at(42.65, 2.2, (b, w) => pluck(b, w, 81, .05, 2.0, .9, 'sine'));
  at(44.2, .8, (b, w) => fadeAll(b, w, .8));
  // interface sounds
  at(T.notif, .5, (b, w) => buzz(b, w));
  at(T.notif + .05, 1.2, (b, w) => { pluck(b, w, 88, .07, 1.0, .6, 'sine'); pluck(b, w + .11, 95, .06, 1.1, .6, 'sine'); });
  [T.tapNotif, T.tapReview, T.tapYes, T.tapBack, T.tapReady, T.tapSend, T.tapRelease, T.tapSendKey, T.tapConnect].forEach(t => at(t, .1, (b, w) => tap(b, w)));
  at(T.open - .05, .5, (b, w) => whoosh(b, w, .5, 700, 3400, .05));
  at(T.sheet - .05, .55, (b, w) => whoosh(b, w, .55, 2600, 600, .055));
  at(T.read, .3, (b, w) => pluck(b, w, 88, .035, .2, .3, 'sine'));
  at(T.guard, .7, (b, w) => { pluck(b, w, 81, .06, .5, .5, 'sine'); pluck(b, w + .06, 88, .045, .6, .5, 'sine'); });
  [72, 76, 79, 84].forEach((n, i) => at(T.sent - .12 + i * .06, .8, (b, w) => pluck(b, w, n, .06, .7, .5)));
  at(T.sheetDown, .45, (b, w) => whoosh(b, w, .45, 600, 2400, .04));
  at(T.answered + .2, .5, (b, w) => pluck(b, w, 76, .04, .4, .4, 'sine'));
  at(T.push, .4, (b, w) => whoosh(b, w, .4, 1200, 3600, .035));
  { const r = rng(5); for (let t = T.typeA; t < T.typeB; t += .068) at(t, .03, (b, w) => tick(b, w, .02 + r() * .02, 3500 + r() * 2500)); }
  [T.tapDown, T.tapEnter, T.approve].forEach(t => at(t, .06, (b, w) => keyc(b, w)));
  [.15, .45, .7, .95, 1.15, 1.6, 1.9].forEach(o => at(T.tapEnter + o, .03, (b, w) => tick(b, w, .025, 5000)));
  at(T.tapSend + .05, .4, (b, w) => whoosh(b, w, .35, 900, 4200, .04));
  at(T.tapRelease + .1, .5, (b, w) => pluck(b, w, 57, .06, .4, .3));
  { const r = rng(9); for (let k = 0; k < 44; k++) { const t = 32.0 + r() * 1.0; at(t, .03, (b, w) => tick(b, w, .018, 6500)); } }
  for (let t = 32.85; t < 33.45; t += .03) at(t, .02, (b, w) => tick(b, w, .012, 7000));
  at(T.packet, .55, (b, w) => blip(b, w, .5));
  at(T.packetEnd, .5, (b, w) => pluck(b, w, 84, .05, .4, .5, 'sine'));
  at(T.match, .9, (b, w) => { pluck(b, w, 76, .06, .8, .5, 'sine'); pluck(b, w + .08, 83, .05, .8, .5, 'sine'); });
  [76, 79, 83, 88].forEach((n, i) => at(T.added + i * .06, .8, (b, w) => pluck(b, w, n, .05, .7, .5)));
  at(T.connected, 1.0, (b, w) => { pluck(b, w, 72, .05, .8, .5, 'sine'); pluck(b, w + .1, 79, .05, .9, .5, 'sine'); });
  EV.sort((a, b) => a[0] - b[0]);

  function session(ctx, startCtx, from) {
    const b = base(ctx);
    const dry = ctx.createGain(), send = ctx.createGain();
    dry.connect(b.comp); send.connect(b.rev);
    return { ctx, dry, send, noise: b.noise, t0: startCtx - from, idx: 0 };
  }
  function schedule(s, until) {
    while (s.idx < EV.length && EV[s.idx][0] < until) {
      const [t, d, f] = EV[s.idx++];
      if (t + d < s.from) continue;
      try { f(s, s.t0 + t); } catch (e) { }
    }
  }

  // ---------- live ----------
  let ctx = null, live = null, timer = null;
  const ensure = () => { if (!ctx) { const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return null; ctx = new AC({ latencyHint: 'interactive' }); } return ctx; };
  function play(from) {
    stop();
    const c = ensure(); if (!c) return false;
    if (c.state === 'suspended') c.resume();
    const s = session(c, c.currentTime + .05, from); s.from = from;
    live = s;
    const loop = () => { if (live !== s) return; schedule(s, (c.currentTime - s.t0) + .6); };
    loop(); timer = setInterval(loop, 80);
    return true;
  }
  function stop() {
    if (timer) clearInterval(timer); timer = null;
    if (live && ctx) {
      const s = live, n = ctx.currentTime;
      for (const g of [s.dry, s.send]) { g.gain.cancelScheduledValues(n); g.gain.setValueAtTime(g.gain.value, n); g.gain.linearRampToValueAtTime(0, n + .04); }
      setTimeout(() => { try { s.dry.disconnect(); s.send.disconnect(); } catch (e) { } }, 200);
    }
    live = null;
  }
  const now = () => (live && ctx) ? ctx.currentTime - live.t0 : null;

  // ---------- offline (for the MP4) ----------
  async function renderWav(rate = 48000) {
    const c = new OfflineAudioContext(2, Math.ceil(rate * REEL.DUR), rate);
    const s = session(c, 0, 0); s.from = 0;
    schedule(s, 1e9);
    const buf = await c.startRendering();
    const L = buf.getChannelData(0), Rr = buf.getChannelData(1), n = L.length;
    const ab = new ArrayBuffer(44 + n * 4), v = new DataView(ab);
    const ws = (o, str) => { for (let i = 0; i < str.length; i++) v.setUint8(o + i, str.charCodeAt(i)); };
    ws(0, 'RIFF'); v.setUint32(4, 36 + n * 4, true); ws(8, 'WAVE'); ws(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 2, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 4, true); v.setUint16(32, 4, true); v.setUint16(34, 16, true); ws(36, 'data'); v.setUint32(40, n * 4, true);
    let peak = 0;
    for (let i = 0, o = 44; i < n; i++, o += 4) {
      const a = Math.max(-1, Math.min(1, L[i])), bb = Math.max(-1, Math.min(1, Rr[i]));
      peak = Math.max(peak, Math.abs(a), Math.abs(bb));
      v.setInt16(o, a * 32767, true); v.setInt16(o + 2, bb * 32767, true);
    }
    const u8 = new Uint8Array(ab); let bin = '';
    for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return { b64: btoa(bin), peak };
  }
  return { play, stop, now, renderWav, get ctx() { return ctx; } };
})();
