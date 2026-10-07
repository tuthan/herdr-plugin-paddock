// The reel: every frame is a pure function of t (seconds, 0..45). No CSS animation, no clock, no unseeded randomness,
// so the page plays it live and the renderer captures the same frames.
const REEL = (() => {
  const W = 1920, H = 1080, DUR = 45;
  const E = {
    lin: x => x,
    o2: x => 1 - (1 - x) * (1 - x), o3: x => 1 - Math.pow(1 - x, 3), o4: x => 1 - Math.pow(1 - x, 4), o5: x => 1 - Math.pow(1 - x, 5),
    i2: x => x * x, i3: x => x * x * x, i4: x => x * x * x * x,
    io2: x => x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2,
    io3: x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2,
    io4: x => x < .5 ? 8 * x * x * x * x : 1 - Math.pow(-2 * x + 2, 4) / 2,
    back: x => { const c1 = 1.5, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
    sp: x => x >= 1 ? 1 : 1 - Math.exp(-6.5 * x) * Math.cos(8.5 * x),
  };
  const cl = (v, a = 0, b = 1) => v < a ? a : v > b ? b : v;
  const pr = (t, a, b) => cl((t - a) / (b - a));
  const mix = (a, b, x) => a + (b - a) * x;
  const tw = (t, a, b, v0, v1, e = E.o3) => mix(v0, v1, e(pr(t, a, b)));
  const kf = (t, keys) => {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const [t1, v1, e] = keys[i];
      if (t <= t1) { const [t0, v0] = keys[i - 1]; return mix(v0, v1, (e || E.io3)(pr(t, t0, t1))); }
    }
    return keys[keys.length - 1][1];
  };
  const env = (t, a, b, fi = .4, fo = .35, ei = E.o3, eo = E.i2) => Math.min(ei(pr(t, a, a + fi)), 1 - eo(pr(t, b - fo, b)));

  const set = (el, prop, v) => { const c = el._c || (el._c = {}); if (c[prop] !== v) { c[prop] = v; el.style[prop] = v; } };
  const TK = ['x', 'y', 'z', 's', 'r', 'rx', 'ry', 'persp'];
  function S(el, o) {
    if (TK.some(k => o[k] !== undefined)) {
      let tr = '';
      if (o.persp) tr += `perspective(${o.persp}px) `;
      if (o.x || o.y || o.z) tr += `translate3d(${(o.x || 0).toFixed(2)}px,${(o.y || 0).toFixed(2)}px,${(o.z || 0).toFixed(1)}px) `;
      if (o.rx) tr += `rotateX(${o.rx.toFixed(3)}deg) `;
      if (o.ry) tr += `rotateY(${o.ry.toFixed(3)}deg) `;
      if (o.r) tr += `rotate(${o.r.toFixed(3)}deg) `;
      if (o.s !== undefined && Math.abs(o.s - 1) > 1e-4) tr += `scale(${o.s.toFixed(4)})`;
      set(el, 'transform', tr.trim() || 'none');
    }
    if (o.o !== undefined) set(el, 'opacity', o.o <= .002 ? '0' : o.o >= .998 ? '1' : o.o.toFixed(3));
    if (o.blur !== undefined) set(el, 'filter', o.blur > .05 ? `blur(${o.blur.toFixed(2)}px)` : 'none');
  }
  const txt = (el, v) => { if (el._t !== v) { el._t = v; el.textContent = v; } };
  const htm = (el, v) => { if (el._h !== v) { el._h = v; el.innerHTML = v; } };
  const SHOWN = new Set();
  const show = (el, on) => { SHOWN.add(el); set(el, 'display', on ? '' : 'none'); };
  const cls = (el, c, on) => { const k = '_cl' + c; if (el[k] !== on) { el[k] = on; el.classList.toggle(c, on); } };
  const rng = seed => () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let x = Math.imul(seed ^ seed >>> 15, 1 | seed); x = x + Math.imul(x ^ x >>> 7, 61 | x) ^ x; return ((x ^ x >>> 14) >>> 0) / 4294967296; };
  const h = (tag, cl, html, style) => { const e = document.createElement(tag); if (cl) e.className = cl; if (html !== undefined) e.innerHTML = html; if (style) e.style.cssText = style; return e; };

  // Moments shared by the picture and the soundtrack.
  const T = {
    notif: 11.0, tapNotif: 12.05, open: 12.2, tapReview: 17.0, sheet: 17.25, read: 18.6, guard: 18.9, tapYes: 20.3, sent: 20.6,
    tapBack: 22.5, sheetDown: 22.7, answered: 23.25, tapReady: 25.05, push: 25.2, typeA: 25.8, typeB: 28.1, tapSend: 28.45,
    tapDown: 26.5, tapEnter: 27.3, tapRelease: 30.2, tapSendKey: 33.3, packet: 33.6, packetEnd: 34.1, match: 34.4,
    approve: 35.1, added: 35.35, tapConnect: 35.9, connected: 36.3, wall: 37.4, end: 42.0,
  };
  const CHAPTERS = [
    [0, 'The herd'], [7, 'Paddock'], [10.5, 'Buzz'], [12.6, 'Glance'], [17, 'Decide'], [25, 'Dive'], [31.5, 'Trust'], [37.4, 'In short'],
  ];

  let R = null; // refs, built once per stage
  const thumbs = (window.PADDOCK_THUMBS || []);
  const QR = (window.PADDOCK_QR || '');

  function build(stage) {
    stage.innerHTML = '';
    const r = { stage };
    // ---------- background ----------
    const bg = h('div', 'bgl'); stage.append(bg);
    r.grid = h('div', 'grid'); bg.append(r.grid);
    r.blobs = {};
    for (const [k, c] of [['blue', '122,162,247'], ['red', '247,118,142'], ['green', '158,206,106'], ['violet', '187,154,247']]) {
      const b = h('div', 'blob', '', `background:radial-gradient(closest-side,rgba(${c},.20),rgba(${c},.07) 45%,rgba(${c},0) 100%)`);
      bg.append(b); r.blobs[k] = b;
    }

    // ---------- scene 1: the herd ----------
    r.s1 = h('div', 'scene'); stage.append(r.s1);
    r.herd = h('div', 'herdl'); r.s1.append(r.herd);
    const TILES = [
      ['codex', 'blindpass › tab 3', 'Ran git status', 146], ['opencode', 'paddock › tab 1', 'Refactor ledger', 63], ['gemini', 'docs-vault › tab 2', 'Forging…', 289], ['copilot', 'paddock › tab 5', 'Add icon tile', 18],
      ['cursor', 'omasafe › tab 2', 'Editing scan.rs', 97], ['claude', 'docs-vault › tab 1', 'Allow this command?', 0], ['pi', 'herdr-fixtures › tab 4', 'Fixture capture', 211], ['amp', 'trading-signal › tab 2', 'Ran tests', 72],
    ];
    r.tiles = TILES.map((d, i) => {
      const x = 1000 + (i % 4) * 204, y = 338 + Math.floor(i / 4) * 224;
      const el = h('div', 'tile', `<span class="mgt">${PD.glyph(d[0])}</span><span class="tdot"></span><span class="tn">${d[0]}</span><span class="tp">${d[1]}</span><span class="ts"></span>`, `left:${x}px;top:${y}px`);
      r.herd.append(el);
      return { el, d, x, y, dot: el.querySelector('.tdot'), ts: el.querySelector('.ts'), phase: (i * 0.37) % 3 };
    });
    const ct = r.tiles[5];
    r.rdx = ct.x + 184 - 20 - 6.5; r.rdy = ct.y + 24 + 6.5;
    show(ct.dot, false);
    r.rdot = h('div', 'pdot', '', `left:${r.rdx - 6.5}px;top:${r.rdy - 6.5}px;width:13px;height:13px;background:#7aa2f7`); r.herd.append(r.rdot);
    r.ring = h('div', 'ring', '', `left:${r.rdx - 6.5}px;top:${r.rdy - 6.5}px`); r.herd.append(r.ring);
    r.bcap = h('div', 'bcap', '', `left:${ct.x}px;top:${ct.y + 222}px`); r.herd.append(r.bcap);
    const words = (s, extra = '') => s.split(' ').map(w => `<span class="mask"><span${extra}>${w}</span></span>`).join(' ');
    r.g1 = h('div', 'abs', `<div class="line1">${words('You started')}</div><div class="line1">${words('eight agents')}</div><div class="line1">${words('before dinner.')}</div>`, 'left:150px;top:286px');
    r.g1sub = h('div', 'abs kk', 'claude · codex · opencode · gemini · copilot · cursor · pi · amp', 'left:154px;top:690px;font-size:17px;letter-spacing:.06em;text-transform:none');
    r.g2 = h('div', 'abs', `<div class="line1">${words('Seven are')}</div><div class="line1">${words('working.')}</div>`, 'left:150px;top:350px');
    r.g3 = h('div', 'abs', `<div class="line1">${words('One')} <span class="mask"><span class="red">needs</span></span></div><div class="line1"><span class="mask"><span class="red">you.</span></span></div>`, 'left:150px;top:350px');
    r.s1.append(r.g1, r.g1sub, r.g2, r.g3);
    r.g1w = [...r.g1.querySelectorAll('.mask>span')]; r.g2w = [...r.g2.querySelectorAll('.mask>span')]; r.g3w = [...r.g3.querySelectorAll('.mask>span')];

    // ---------- the mark (scene 2, then the corner bug, then the end card) ----------
    r.lock = h('div', 'lockup'); stage.append(r.lock);
    r.icon = h('div', 'icon', `<svg viewBox="0 0 108 108"><defs><linearGradient id="rg" x1="0" y1="0" x2="0" y2="108" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#292e42"/><stop offset="1" stop-color="#16161e"/></linearGradient><radialGradient id="rgl" cx="54" cy="43.2" r="54" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#7aa2f7" stop-opacity=".18"/><stop offset="1" stop-color="#7aa2f7" stop-opacity="0"/></radialGradient><linearGradient id="rpost" x1="0" y1="29" x2="0" y2="78" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#a4bdff"/><stop offset="1" stop-color="#5f82db"/></linearGradient></defs><g class="ibg"><rect width="108" height="108" fill="url(#rg)"/><rect width="108" height="108" fill="url(#rgl)"/></g><path class="post" pathLength="100" d="M40.5 29V78M40.5 36H54.5a12.5 12.5 0 0 1 0 25H40.5" fill="none" stroke="url(#rpost)" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="100 100"/></svg>`);
    r.ibg = r.icon.querySelector('.ibg'); r.post = r.icon.querySelector('.post');
    r.wm = h('div', 'wm', 'Paddock'.split('').map(c => `<span class="mask"><span>${c}</span></span>`).join(''));
    r.wmL = [...r.wm.querySelectorAll('.mask>span')];
    r.phalo = h('div', 'phalo'); r.pdot = h('div', 'pdot'); r.pring = h('div', 'ring', '', 'width:26px;height:26px;border-width:3px');
    r.lock.append(r.icon, r.wm, r.phalo, r.pdot, r.pring);
    r.tag1 = h('div', 'tag1', 'Answer your agents. <span class="soft">From anywhere.</span>', 'top:716px');
    r.tag2 = h('div', 'tag2 kk', '<span class="dot red"></span>A phone companion for herdr', 'top:812px;display:flex');
    stage.append(r.tag1, r.tag2);

    // ---------- phones (scenes 3 to 6) ----------
    r.ph = h('div', 'scene'); stage.append(r.ph);
    r.texts = [
      ['On your lock screen', 'Buzz.', 'An agent stops to ask, and your phone tells you. The alert never includes your code.', 10.55, 12.5, 'red'],
      ['Who needs you, first', 'Glance.', 'Every agent on one screen, sorted by who needs you.', 12.6, 16.95, 'blue'],
      ['Claude Code permissions', 'Decide.', 'Your Yes goes to the exact request Claude Code is holding, and unlocks only once you have read all of it.', 17.05, 24.9, 'red'],
      ["When twenty seconds isn't enough", 'Dive.', 'Send a follow-up prompt, or take the real terminal. Release it when you are done.', 25.0, 31.35, 'blue'],
      ['SSH · no server in between', 'Trust.', 'Pair in one popup. Compare eight characters. Your phone talks to your machine and nothing else.', 31.5, 37.3, 'green'],
    ].map(([k, w, s, a, b, c]) => {
      const kk = h('div', 'abs kk', `<span class="dot ${c}"></span>${k}`, 'left:154px;top:300px');
      const wd = h('div', 'abs bigw', `<span class="mask"><span>${w}</span></span>`, 'left:144px;top:342px');
      const sub = h('div', 'abs sub', s, 'left:152px;top:580px');
      r.ph.append(kk, wd, sub);
      return { kk, wd, wi: wd.querySelector('.mask>span'), sub, a, b };
    });
    // the visit clock
    r.vc = h('div', 'vclock', `<div class="hd"><span>From alert to answer</span><b>00.0 s</b></div><div class="rl"><i class="base"></i><i class="fl"></i></div>`);
    r.vcT = r.vc.querySelector('b'); r.vcF = r.vc.querySelector('.fl'); const rl = r.vc.querySelector('.rl');
    for (let s = 0; s <= 20; s++) rl.append(h('i', 'tk', '', `left:${s * 32}px;${s % 5 ? '' : 'height:14px;top:1px;background:#565f89'}`));
    r.vcM = [[0, 'Buzz'], [2, 'Glance'], [6, 'Decide'], [14, 'Answered'], [20, 'Pocket']].map(([s, l]) => { const m = h('span', 'mk', l, `left:${s * 32}px${s === 0 ? ';transform:none' : s === 20 ? ';transform:translateX(-100%)' : ''}`); rl.append(m); return [s, m]; });
    r.vcP = h('i', 'ph'); rl.append(r.vcP);
    r.ph.append(r.vc);

    r.shA = h('div', 'shadow'); r.shB = h('div', 'shadow'); r.ph.append(r.shA, r.shB);
    r.A = h('div', 'phw', PD.device('and', PD.home('and', { anim: true, sheet: true }) + PD.lock('and') + PD.compose('and')));
    r.B = h('div', 'phw', PD.device('and', PD.term('and') + PD.pair('and')));
    r.ph.append(r.A, r.B);
    r.a = PD.keys(r.A); r.b = PD.keys(r.B);
    r.aScr = r.A.querySelector('.scr'); r.bScr = r.B.querySelector('.scr');
    r.lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); r.lines.setAttribute('class', 'lines'); r.ph.append(r.lines);
    r.cos = [];

    // ---------- scene 6: the pairing popup ----------
    r.s6 = h('div', 'scene'); stage.append(r.s6);
    const LINK = 'paddock://pair?v=1&host=192.168.42.23&port=22&user=dev&fp=SHA256:4mJ0p7Xb2hQ8sVt1nR6eYkLzW3cD9fGuA5oiTqHxNlE&session=default&pair=41237&sid=Q2v8LmT0pX4rN7bJ1kY9sA';
    r.LINK = LINK;
    r.win = h('div', 'win', `<div class="tb"><i></i><i></i><i></i><span>herdr · Paddock: pair a phone</span></div><div class="wb"><span class="ln c-w" style="color:#e2e6fb">Pair a phone with dev@192.168.42.23 · session default</span><div class="qrrow"><canvas width="265" height="265"></canvas><div class="side"><span class="sd"><b>Scan with Paddock</b>, or open the link on the phone.</span><span class="sd">listening on <b>192.168.42.23:41237</b><br>this network only, one key</span><span class="sd">camera ready, used after Enter</span><span class="sd">paste: the key line, then Enter</span></div></div><span class="ln lk" style="color:#8b95c0"></span><span class="ln"> </span><span class="ln w1"></span><span class="ln w2"></span><span class="ln w3"></span><span class="ln w4"></span><span class="ln w5"></span><span class="ln w6"></span><span class="ln w7"></span></div>`, 'left:700px;top:150px');
    r.s6.append(r.win);
    r.qr = r.win.querySelector('canvas'); r.qx = r.qr.getContext('2d');
    r.sides = [...r.win.querySelectorAll('.sd')]; r.lk = r.win.querySelector('.lk');
    r.wl = [1, 2, 3, 4, 5, 6, 7].map(i => r.win.querySelector('.w' + i));
    r.wire = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); r.wire.setAttribute('class', 'wire');
    r.wire.innerHTML = '<path class="wp" fill="none" stroke="#7aa2f7" stroke-width="2" stroke-dasharray="3 9" stroke-linecap="round" opacity=".7"/><circle class="pk" r="9" fill="#a4bdff"/><circle class="pk2" r="22" fill="none" stroke="#7aa2f7" stroke-width="2"/><text class="wt" font-family="JetBrains Mono, monospace" font-size="14" fill="#8b95c0" text-anchor="middle"><tspan x="0" dy="0">public key only</tspan><tspan x="0" dy="19">this network</tspan></text><path class="mp" fill="none" stroke="#e0af68" stroke-width="2" stroke-dasharray="6 6"/><g class="mb"><rect x="-44" y="-18" width="88" height="36" rx="18" fill="#16161e" stroke="#e0af68" stroke-width="1.5"/><text y="6" font-family="JetBrains Mono, monospace" font-size="15" fill="#e0af68" text-anchor="middle">match</text></g>';
    r.s6.append(r.wire);
    r.wp = r.wire.querySelector('.wp'); r.pk = r.wire.querySelector('.pk'); r.pk2 = r.wire.querySelector('.pk2'); r.wt = r.wire.querySelector('.wt'); r.mp = r.wire.querySelector('.mp'); r.mb = r.wire.querySelector('.mb');
    const tick = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
    r.f3 = h('div', 'facts3', ["Your phone's key never leaves the phone", 'Your machine is checked by its fingerprint', 'No relay. No account. No analytics.'].map(s => `<div>${tick}<span>${s}</span></div>`).join(''));
    r.f3r = [...r.f3.children]; r.s6.append(r.f3);
    // QR module order: each dark module gets a seeded arrival time
    const qn = Math.round(Math.sqrt(QR.length)); r.qn = qn; const rnd = rng(7); r.qmods = [];
    for (let y = 0; y < qn; y++) for (let x = 0; x < qn; x++) if (QR[y * qn + x] === '1') {
      const d = Math.hypot(x - qn / 2, y - qn / 2) / (qn * .7);
      r.qmods.push([x, y, d * .55 + rnd() * .45]);
    }

    // ---------- scene 7: the wall ----------
    r.s7 = h('div', 'scene'); stage.append(r.s7);
    r.wall = h('div', 'wall'); r.s7.append(r.wall);
    r.wcols = [];
    for (let c = 0; c < 11; c++) {
      const col = h('div', 'wcol', '', `left:${(c - 5.5) * 236}px;top:-1100px`);
      for (let k = 0; k < 5; k++) { const src = thumbs.length ? thumbs[(c * 5 + k * 3 + c) % thumbs.length] : ''; if (src) col.append(h('img', '', undefined, '')); if (src) { col.lastChild.src = src; col.lastChild.alt = ''; } }
      r.wall.append(col); r.wcols.push({ col, dir: c % 2 ? 1 : -1, base: (c % 3) * 90 });
    }
    r.wscrim = h('div', 'wscrim'); r.s7.append(r.wscrim);
    r.stats = h('div', 'stats', [['20', 'seconds to answer'], ['1', 'popup to pair'], ['0', 'servers in between']].map(([n, l]) => `<div class="stat1"><b>${n}</b><span>${l}</span></div>`).join(''));
    r.statEls = [...r.stats.children]; r.statN = r.statEls.map(e => e.querySelector('b'));
    r.s7.append(r.stats);

    // ---------- scene 8: the end card ----------
    r.s8 = h('div', 'scene'); stage.append(r.s8);
    r.e1 = h('div', 'endl tag1', 'Answer your agents from anywhere.', 'top:612px;font-size:78px;font-weight:800;font-variation-settings:\'wdth\' 76');
    r.e2 = h('div', 'endl cred', '<span style="color:#8b95c0">Get the plugin</span>  <b>herdr plugin install tuthan/herdr-plugin-paddock</b>', 'top:746px');
    r.e3 = h('div', 'endl disc', 'Paddock is independent and is not affiliated with, endorsed by or sponsored by herdr or its authors.', 'top:1010px');
    r.s8.append(r.e1, r.e2, r.e3);

    // ---------- finish ----------
    r.grain = h('canvas', 'grain'); r.grain.width = 1920 / 2; r.grain.height = 1080 / 2; r.grain.style.cssText = 'width:1920px;height:1080px'; stage.append(r.grain);
    r.gx = r.grain.getContext('2d'); r.grainImgs = [];
    const gr = rng(99);
    for (let i = 0; i < 6; i++) { const im = r.gx.createImageData(960, 540); for (let p = 0; p < im.data.length; p += 4) { const v = gr() * 255; im.data[p] = im.data[p + 1] = im.data[p + 2] = v; im.data[p + 3] = 255; } r.grainImgs.push(im); }
    stage.append(h('div', 'vig'));
    r.fade = h('div', 'fade'); stage.append(r.fade);
    R = r;
    layout();
    return r;
  }

  // Positions that depend on font metrics and layout; recomputed after fonts load.
  function layout() {
    const r = R; if (!r) return;
    // measure with everything laid out
    SHOWN.forEach(el => { el.style.display = ''; if (el._c) el._c.display = undefined; });
    for (const el of [r.a.card1, r.a.nwwrap]) { for (const p of ['height', 'padding', 'marginBottom']) { el.style[p] = ''; if (el._c) el._c[p] = undefined; } }
    r.a.nwwrap.style.height = '0px';
    const wmW = r.wm.offsetWidth || 700;
    const L = 280 + 64 + wmW;
    r.iconL = Math.round((W - L) / 2); r.iconT = 352;
    S(r.icon, {}); r.icon.style.left = r.iconL + 'px'; r.icon.style.top = r.iconT + 'px';
    r.wm.style.left = (r.iconL + 344) + 'px'; r.wm.style.top = (r.iconT + 34) + 'px';
    r.lock.style.transformOrigin = `${r.iconL}px ${r.iconT}px`;
    const k = 280 / 108;
    r.dotX = r.iconL + 53 * k; r.dotY = r.iconT + 48.5 * k; r.dotR = 5 * k;
    r.icon.style.transformOrigin = `${53 * k}px ${48.5 * k}px`;
    r.LW = L;
    // geometry inside the phones (layout coordinates, transforms ignored)
    const a = r.a, sA = r.aScr, b = r.b, sB = r.bScr;
    r.geo = {
      notif: PD.offsetIn(a.notif, sA), review: PD.offsetIn(a.review, sA), card1: PD.offsetIn(a.card1, sA), live: PD.offsetIn(a.live, sA),
      kwork: PD.offsetIn(a.kwork, sA), slab: PD.offsetIn(a.slab, sA), yes: PD.offsetIn(a.yes, sA), back: PD.offsetIn(a.back, sA),
      sheet: PD.offsetIn(a.sheet, sA), sent: PD.offsetIn(a.sent, sA), ready1: PD.offsetIn(a.ready1, sA), send: PD.offsetIn(a.send, sA),
      kDown: PD.offsetIn(b.kDown, sB), kEnter: PD.offsetIn(b.kEnter, sB), release: PD.offsetIn(b.release, sB),
      sendkey: PD.offsetIn(b.sendkey, sB), connect: PD.offsetIn(b.connect, sB), pfp8: PD.offsetIn(b.pfp8, sB),
    };
    r.scrollAmt = Math.max(0, Math.round(r.geo.ready1.y + r.geo.ready1.h + 120 - 852));
    r.card1H = a.card1.offsetHeight; r.nwH = a.nwwrap.firstElementChild ? a.nwwrap.firstElementChild.offsetHeight : 64;
    r.winMark = null; r._q = -1;
  }

  // phone placement: centre (cx, cy), scale s, flat. Returns a mapper from screen-local to stage coordinates.
  const mapA = (cx, cy, s) => (x, y) => [cx + (x + 10 - 206.5) * s, cy + (y + 10 - 436) * s];
  const mapB = (cx, cy, s) => (x, y) => [cx + (x + 10 - 206.5) * s, cy + (y + 10 - 436) * s];

  function touch(el, t, at, g) {
    // a finger: appears, presses, lifts
    const a = at - .22, b = at + .28;
    if (t < a || t > b) { set(el, 'opacity', '0'); return; }
    el.style.left = (g.x + g.w / 2) + 'px'; el.style.top = (g.y + g.h / 2) + 'px';
    const p1 = pr(t, a, at), p2 = pr(t, at, b);
    S(el, { o: p2 > 0 ? 1 - E.i2(p2) : E.o2(p1), s: p2 > 0 ? mix(.82, 1.25, E.o3(p2)) : mix(1.3, .82, E.o3(p1)) });
  }
  const press = (el, t, at) => S(el, { s: 1 - .035 * Math.max(0, 1 - Math.abs(t - at) / .14) });

  // a callout: kicker + text at (x, y) with an elbow line to the anchor (ax, ay)
  function callout(i, t, a, b, ax, ay, ly, kick, text) {
    const r = R;
    let c = r.cos[i];
    if (!c) {
      const el = h('div', 'co', `<div class="kk">${kick}</div><p>${text}</p>`);
      r.ph.append(el);
      const ns = 'http://www.w3.org/2000/svg';
      const path = document.createElementNS(ns, 'path'); path.setAttribute('fill', 'none'); path.setAttribute('stroke', '#7aa2f7'); path.setAttribute('stroke-width', '2'); path.setAttribute('stroke-opacity', '.75');
      const dot = document.createElementNS(ns, 'circle'); dot.setAttribute('r', '6'); dot.setAttribute('fill', '#7aa2f7');
      const rg = document.createElementNS(ns, 'circle'); rg.setAttribute('r', '12'); rg.setAttribute('fill', 'none'); rg.setAttribute('stroke', '#7aa2f7'); rg.setAttribute('stroke-opacity', '.45'); rg.setAttribute('stroke-width', '2');
      r.lines.append(path, dot, rg);
      c = r.cos[i] = { el, path, dot, rg };
    }
    const on = t > a - .05 && t < b + .05;
    show(c.el, on); set(c.path, 'display', on ? '' : 'none'); set(c.dot, 'display', on ? '' : 'none'); set(c.rg, 'display', on ? '' : 'none');
    if (!on) return;
    const lx = 1520, d = `M${ax.toFixed(1)} ${ay.toFixed(1)} L${(lx - 40).toFixed(1)} ${ly.toFixed(1)} L${(lx - 12).toFixed(1)} ${ly.toFixed(1)}`;
    if (c.path._d !== d) { c.path._d = d; c.path.setAttribute('d', d); c.len = c.path.getTotalLength(); c.path.setAttribute('stroke-dasharray', c.len + ' ' + c.len); }
    const pin = E.io3(pr(t, a, a + .45)), pout = E.i2(pr(t, b - .3, b));
    c.path.setAttribute('stroke-dashoffset', (c.len * (1 - pin) + c.len * pout * -1).toFixed(1));
    c.dot.setAttribute('cx', ax); c.dot.setAttribute('cy', ay); c.rg.setAttribute('cx', ax); c.rg.setAttribute('cy', ay);
    S(c.dot, { o: env(t, a, b, .2, .3) }); S(c.rg, { o: env(t, a, b, .2, .3) * .9 });
    c.el.style.left = lx + 'px'; c.el.style.top = (ly - 14) + 'px';
    S(c.el, { o: env(t, a + .25, b, .4, .3), x: tw(t, a + .25, a + .75, 18, 0) - 10 * E.i2(pr(t, b - .3, b)) });
  }

  function termText(t) {
    const sel = t > T.tapDown + .05 ? 1 : 0;
    const H = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const L = [];
    L.push('<span class="c-d">codex · blindpass › tab 8 · main</span>');
    L.push('<span class="c-f">' + '─'.repeat(58) + '</span>');
    L.push('<span class="c-w">• Add the official MCP SDK and put the server</span>');
    L.push('<span class="c-w">  feature behind a flag.</span>');
    L.push('  <span class="c-d">└ Cargo.toml</span>  <span class="c-g">+1</span> <span class="c-r">-0</span>');
    L.push('');
    if (t < T.tapEnter + .12) {
      L.push('<span class="c-y">Allow command?</span>');
      L.push('');
      L.push('  <span class="c-c">$ cargo add rmcp@0.5.0 --features server</span>');
      L.push('');
      const opts = ['Yes, run it', "Yes, and don't ask again for cargo add", 'No, and tell Codex what to do differently'];
      opts.forEach((o, i) => L.push(i === sel ? `<span class="sel">› ${i + 1}. ${H(o)}</span>` : `<span class="c-d">  ${i + 1}. ${H(o)}</span>`));
      L.push('');
      L.push('<span class="c-f">Press enter to confirm or esc to cancel</span>');
    } else {
      const s = [
        [T.tapEnter + .15, '<span class="c-g">✓</span> <span class="c-d">Approved: always run</span> <span class="c-c">cargo add</span>'],
        [T.tapEnter + .2, ''],
        [T.tapEnter + .45, '<span class="c-w">• Ran</span> <span class="c-c">cargo add rmcp@0.5.0 --features server</span>'],
        [T.tapEnter + .7, '<span class="c-d">  └    Updating crates.io index</span>'],
        [T.tapEnter + .95, '<span class="c-d">         Adding</span> <span class="c-w">rmcp v0.5.0</span> <span class="c-d">to dependencies</span>'],
        [T.tapEnter + 1.15, '<span class="c-d">               Features:</span> <span class="c-g">+ server</span>'],
        [T.tapEnter + 1.35, ''],
        [T.tapEnter + 1.6, '<span class="c-w">• Wiring</span> <span class="c-c">rmcp::ServerHandler</span> <span class="c-w">into src/mcp.rs</span>'],
        [T.tapEnter + 1.9, '<span class="c-d">  └ src/mcp.rs</span>  <span class="c-g">+48</span> <span class="c-r">-3</span>'],
        [T.tapEnter + 2.1, ''],
      ];
      s.forEach(([at, l]) => { if (t >= at) L.push(l); });
      if (t >= T.tapEnter + 2.2) {
        const n = Math.floor(t - (T.tapEnter + 2.2)) + 3;
        const sp = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[Math.floor(t * 12) % 10];
        L.push(`<span class="c-b">${sp} Working</span> <span class="c-d">(${n}s · esc to interrupt)</span>`);
      }
    }
    return L.join('\n');
  }

  // ======================================================================================
  function render(t) {
    const r = R; if (!r) return;
    t = cl(t, 0, DUR);

    // ---------- background ----------
    S(r.grid, { x: -((t * 9) % 48), y: -((t * 5) % 48), o: tw(t, 0, 1.2, 0, 1) * (t > 44 ? 1 - pr(t, 44, 45) : 1) });
    const B = r.blobs;
    S(B.blue, { x: kf(t, [[0, 1400], [7, 1500], [12, 1300], [25, 1500], [32, 1200], [38, 960], [45, 960]]), y: kf(t, [[0, 300], [10, 200], [20, 760], [30, 300], [38, 540], [45, 600]]), o: kf(t, [[0, 0], [1.5, .55], [6, .3], [8.5, .35], [11, .9], [31, .9], [33, .45], [38, .8], [42, .7], [44.5, .7], [45, 0]]) });
    S(B.red, { x: kf(t, [[0, 1360], [7, 960], [10, 700], [17, 1240], [23, 1240]]), y: kf(t, [[0, 600], [7, 540], [17, 760]]), o: kf(t, [[4.2, 0], [5, .95], [7.2, .9], [9.5, .35], [10.5, 0], [17, 0], [17.6, .55], [20.6, .55], [21.6, 0], [42.6, 0], [43.2, .45], [45, 0]]) });
    S(B.green, { x: kf(t, [[20, 1300], [32, 1500], [37, 1100]]), y: kf(t, [[20, 700], [32, 500], [37, 400]]), o: kf(t, [[20.5, 0], [21.2, .5], [23, .35], [24, 0], [33.5, 0], [35.5, .7], [37.5, 0]]) });
    S(B.violet, { x: kf(t, [[37, 500], [42, 1400]]), y: kf(t, [[37, 300], [42, 800]]), o: kf(t, [[37.2, 0], [38.2, .8], [41.5, .7], [42.3, 0]]) });

    // ---------- scene 1: the herd ----------
    const s1on = t < 7.0; show(r.s1, s1on);
    if (s1on) {
      // words in, out
      r.g1w.forEach((w, i) => S(w, { y: tw(t, .15 + i * .07, .75 + i * .07, 150, 0, E.o4) + (t > 1.95 ? tw(t, 1.95 + i * .02, 2.3 + i * .02, 0, -150, E.i3) : 0) }));
      S(r.g1sub, { o: env(t, .9, 2.25, .5, .3), y: tw(t, .9, 1.4, 12, 0) });
      r.g2w.forEach((w, i) => S(w, { y: tw(t, 2.25 + i * .08, 2.85 + i * .08, 150, 0, E.o4) + (t > 4.05 ? tw(t, 4.05 + i * .02, 4.4 + i * .02, 0, -150, E.i3) : 0) }));
      r.g3w.forEach((w, i) => S(w, { y: tw(t, 4.4 + i * .1, 5.0 + i * .1, 150, 0, E.o4) }));
      S(r.g3, { x: tw(t, 6.1, 6.7, 0, -80, E.i3), o: 1 - pr(t, 6.15, 6.6), blur: tw(t, 6.1, 6.7, 0, 10, E.i2) });
      // the herd: tiles pop in, breathe, one turns red
      const red = t >= 4.42;
      r.tiles.forEach((T1, i) => {
        const a = .35 + i * .1;
        const quiet = i === 5 ? 1 : tw(t, 4.6, 5.1, 1, .38);
        const out = i === 5 ? 1 - pr(t, 6.25, 6.75) : 1 - pr(t, 6.1, 6.55);
        S(T1.el, { o: E.o2(pr(t, a, a + .35)) * quiet * out, s: mix(.86, 1, E.back(pr(t, a, a + .55))), y: tw(t, a, a + .55, 26, 0) });
        if (i === 5) {
          cls(T1.el, 'red', red);
          txt(T1.ts, red ? 'Allow this command?' : 'Ran ls docs/ · ' + Math.floor(52 + t) + 's');
        } else {
          const sec = T1.d[3] + Math.floor(t);
          txt(T1.ts, `${T1.d[2]} ${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, '0')}s`);
          S(T1.dot, { o: .45 + .55 * (.5 + .5 * Math.cos(2 * Math.PI * (t - T1.phase) / 3)) });
        }
      });
      // the dot that becomes the mark
      set(r.rdot, 'background', red ? '#f7768e' : '#7aa2f7');
      S(r.rdot, { o: E.o2(pr(t, .85, 1.2)) * (red ? 1 : .45 + .55 * (.5 + .5 * Math.cos(2 * Math.PI * (t - 1.2) / 3))) });
      const rp = pr(t, 4.45, 5.6);
      S(r.ring, { s: mix(1, 7, E.o3(rp)), o: rp > 0 && rp < 1 ? .8 * (1 - rp) : 0 });
      const bw = 40 + Math.floor(Math.max(0, t - 4.42));
      htm(r.bcap, `claude <span>· docs-vault › tab 1 ·</span> blocked ${bw} s`);
      S(r.bcap, { o: env(t, 4.8, 6.35, .4, .3), y: tw(t, 4.8, 5.3, 10, 0) });
      // push in: the red dot lands at the centre at 7.0
      const pk = E.i3(pr(t, 6.3, 7.0)), k = mix(1, 36 / 6.5, pk);
      S(r.herd, { x: mix(0, 960 - r.rdx * (36 / 6.5), pk), y: mix(0, 540 - r.rdy * (36 / 6.5), pk), s: k });
    }

    // ---------- the mark ----------
    const lockOn = t >= 7.0; show(r.lock, lockOn);
    if (lockOn) {
      // the dot: from the centre (r=36) into the mark
      const dp = E.o3(pr(t, 7.0, 7.75));
      const dx = mix(960, r.dotX, dp), dy = mix(540, r.dotY, dp), dr = mix(36, r.dotR, dp);
      Object.assign(r.pdot.style, { left: (dx - dr) + 'px', top: (dy - dr) + 'px', width: dr * 2 + 'px', height: dr * 2 + 'px' });
      const hr = r.dotR * 1.9;
      Object.assign(r.phalo.style, { left: (r.dotX - hr) + 'px', top: (r.dotY - hr) + 'px', width: hr * 2 + 'px', height: hr * 2 + 'px' });
      S(r.phalo, { o: E.o2(pr(t, 7.4, 7.9)), s: tw(t, 7.4, 8.0, .4, 1) });
      r.post.setAttribute('stroke-dashoffset', (100 * (1 - E.io3(pr(t, 7.25, 8.05)))).toFixed(2));
      S(r.icon, { s: tw(t, 7.5, 8.3, .9, 1, E.o4) });
      S(r.ibg, { o: E.o2(pr(t, 7.55, 8.2)) });
      r.wmL.forEach((l, i) => S(l, { y: tw(t, 7.85 + i * .055, 8.45 + i * .055, 240, 0, E.o4) }));
      // end card: one pulse
      const pp = pr(t, 42.65, 43.6);
      Object.assign(r.pring.style, { left: (r.dotX - 13) + 'px', top: (r.dotY - 13) + 'px' });
      S(r.pring, { s: mix(1, 4.5, E.o3(pp)), o: pp > 0 && pp < 1 ? .9 * (1 - pp) : 0 });
      // where the lockup lives: centre, corner bug, end card
      const bugK = 46 / 280, endK = .74;
      const bugX = 56 - r.iconL, bugY = 42 - r.iconT;
      const endX = (W - r.LW * endK) / 2 - r.iconL, endY = 300 - r.iconT;
      const p1 = E.io4(pr(t, 9.9, 10.6)), p2 = E.io4(pr(t, 41.5, 42.45));
      const lx = mix(mix(0, bugX, p1), endX, p2), ly = mix(mix(0, bugY, p1), endY, p2), lk = mix(mix(1, bugK, p1), endK, p2);
      S(r.lock, { x: lx, y: ly, s: lk, o: t > 44.2 ? 1 - E.i2(pr(t, 44.2, 45)) : 1 });
    }
    const tagOn = t > 8.4 && t < 10.6; show(r.tag1, tagOn); show(r.tag2, tagOn);
    if (tagOn) {
      S(r.tag1, { o: env(t, 8.55, 10.3, .5, .35), y: tw(t, 8.55, 9.15, 26, 0) - tw(t, 9.95, 10.3, 0, 16) });
      S(r.tag2, { o: env(t, 8.85, 10.25, .5, .3), y: tw(t, 8.85, 9.4, 18, 0) });
    }

    // ---------- phones ----------
    const phOn = t > 9.9 && t < 37.9; show(r.ph, phOn);
    if (phOn) renderPhones(t);

    // ---------- scene 6 ----------
    const s6on = t > 31.3 && t < 37.9; show(r.s6, s6on);
    if (s6on) renderTrust(t);

    // ---------- scene 7 ----------
    const s7on = t > 37.3 && t < 42.4; show(r.s7, s7on);
    if (s7on) {
      const s = tw(t, 37.3, 41.6, 1.45, 1.02, E.o3) * tw(t, 41.3, 42.3, 1, .82, E.i3);
      S(r.wall, { persp: 2000, rx: 26, r: -14, s, o: env(t, 37.3, 42.3, .6, .8), x: tw(t, 37.3, 42.3, 80, -60, E.lin), y: 0, blur: tw(t, 41.5, 42.3, 0, 8, E.i2) });
      r.wcols.forEach(c => S(c.col, { y: c.base + c.dir * (t - 37.3) * 70 }));
      S(r.wscrim, { o: env(t, 37.7, 42.2, .6, .6) });
      const counts = [[20, 38.1], [1, 38.35], [0, 38.6]];
      r.statEls.forEach((e, i) => {
        const [n, a] = counts[i];
        S(e, { o: env(t, a, 41.2, .45, .45), y: tw(t, a, a + .6, 44, 0, E.o4) - tw(t, 40.8, 41.3, 0, 26, E.i2) });
        txt(r.statN[i], String(Math.round(n * E.o3(pr(t, a, a + 1.1)))));
      });
    }

    // ---------- scene 8 ----------
    const s8on = t > 42.2; show(r.s8, s8on);
    if (s8on) {
      const fo = t > 44.2 ? 1 - E.i2(pr(t, 44.2, 45)) : 1;
      S(r.e1, { o: E.o3(pr(t, 42.45, 43.0)) * fo, y: tw(t, 42.45, 43.1, 24, 0, E.o4) });
      S(r.e2, { o: E.o3(pr(t, 42.85, 43.35)) * fo, y: tw(t, 42.85, 43.4, 16, 0, E.o4) });
      S(r.e3, { o: E.o3(pr(t, 43.2, 43.7)) * fo * .9 });
    }

    // ---------- grain ----------
    const gi = window.__staticGrain ? 0 : Math.floor(t * 24) % r.grainImgs.length;
    if (r._g !== gi) { r._g = gi; r.gx.putImageData(r.grainImgs[gi], 0, 0); }
    S(r.fade, { o: t < .25 ? 1 - pr(t, 0, .25) : 0 });
  }

  function renderPhones(t) {
    const r = R, a = r.a, b = r.b, g = r.geo;
    // left-column words
    r.texts.forEach(x => {
      const on = t > x.a - .05 && t < x.b + .45;
      show(x.kk, on); show(x.wd, on); show(x.sub, on);
      if (!on) return;
      S(x.wi, { y: tw(t, x.a, x.a + .65, 250, 0, E.o4) + tw(t, x.b, x.b + .38, 0, -250, E.i3) });
      S(x.kk, { o: env(t, x.a + .1, x.b + .3, .4, .3), y: tw(t, x.a + .1, x.a + .5, 10, 0) });
      S(x.sub, { o: env(t, x.a + .2, x.b + .3, .45, .3), y: tw(t, x.a + .2, x.a + .7, 22, 0, E.o4) - tw(t, x.b, x.b + .3, 0, 14) });
    });
    // visit clock
    const vOn = t > 10.3 && t < 25.6; show(r.vc, vOn);
    if (vOn) {
      const v = kf(t, [[10.9, 0, E.lin], [12.6, 2, E.lin], [17.3, 6, E.lin], [20.6, 14, E.lin], [24.6, 20, E.lin]]);
      S(r.vc, { o: env(t, 10.4, 25.5, .5, .5), y: tw(t, 10.4, 10.9, 16, 0) });
      txt(r.vcT, (v < 10 ? '0' : '') + v.toFixed(1) + ' s');
      set(r.vcF, 'width', (v * 32).toFixed(1) + 'px'); set(r.vcP, 'left', (v * 32).toFixed(1) + 'px');
      r.vcM.forEach(([s, m]) => cls(m, 'on', v >= s - .01));
    }

    // ---------- iPhone ----------
    let ax = 1240, ay = 540, as = 1, ary = 0, arx = 0, ar = 0, ao = 1;
    const ent = E.o4(pr(t, 10.0, 11.1)), settle = E.io3(pr(t, 11.1, 13.6));
    ay += mix(980, 0, ent); ary = mix(-26, -9, ent) * (1 - settle); arx = mix(20, 5, ent) * (1 - settle); ar = mix(7, 0, ent); as = mix(.9, 1, ent);
    if (t > 11.0 && t < 11.45) ax += Math.sin((t - 11.0) * 2 * Math.PI * 18) * 7 * (1 - pr(t, 11.0, 11.45));
    ay += Math.sin(t * .9) * 3;
    const pk = E.io3(pr(t, 24.1, 24.7)) * (1 - E.io3(pr(t, 24.75, 25.3)));
    ay += pk * 34; ary += pk * 7; as -= pk * .03;
    const d5 = E.io4(pr(t, 24.85, 25.7)); ax = mix(ax, 1075, d5); as = mix(as, .98, d5);
    const ex = E.i3(pr(t, 31.15, 31.9)); ax = mix(ax, 900, ex); ay += ex * 1150; ar -= ex * 9;
    S(r.A, { x: ax - 206.5, y: ay - 436, s: as, persp: 2400, ry: ary, rx: arx, r: ar, o: ao });
    show(r.A, t < 31.95);
    r.shA.style.left = (ax - 260) + 'px'; r.shA.style.top = (ay + 400 * as) + 'px'; S(r.shA, { o: ent * (1 - ex) * .8, s: as });
    const MA = mapA(ax, ay, as);

    // lock screen and notification
    const lockOn = t < 12.75; show(a.lockv, lockOn);
    if (lockOn) {
      S(a.lockv, { s: tw(t, T.open, 12.7, 1, 1.08, E.o3), o: 1 - E.o2(pr(t, T.open, 12.65)), blur: tw(t, T.open, 12.7, 0, 8) });
      S(a.notif, { y: tw(t, T.notif, T.notif + .7, -330, 0, E.sp), o: E.o2(pr(t, T.notif, T.notif + .25)), s: 1 - .03 * Math.max(0, 1 - Math.abs(t - T.tapNotif) / .14) });
    }
    // home
    const homeOn = t > T.open && t < 25.75; show(a.home, homeOn);
    if (homeOn) {
      const op = pr(t, T.open, T.open + .55);
      set(a.home, 'transformOrigin', `${g.notif.x + g.notif.w / 2}px ${g.notif.y + g.notif.h / 2}px`);
      const push = E.o4(pr(t, T.push, T.push + .5));
      S(a.home, { s: mix(.22, 1, E.o4(op)), o: E.o2(pr(t, T.open, T.open + .3)) * (1 - push * .45), x: -110 * push });
      // rows arrive in attention order
      [...a.sc.children].forEach((c, i) => { const s0 = 12.5 + i * .055; S(c, { o: E.o2(pr(t, s0, s0 + .35)), y: tw(t, s0, s0 + .5, 18, 0, E.o4) }); });
      txt(a.live, `live · ${1 + Math.floor(t * 1.3) % 3} s`);
      // answered: the card leaves, a working row arrives
      const cp = E.io3(pr(t, T.answered, T.answered + .5));
      set(a.card1, 'height', cp > 0 ? (r.card1H * (1 - cp)).toFixed(1) + 'px' : '');
      set(a.card1, 'marginBottom', (-8 * cp).toFixed(1) + 'px'); set(a.card1, 'padding', cp > 0 ? `${14 * (1 - cp)}px 14px` : '');
      if (cp > 0) S(a.card1, { o: 1 - cp });
      set(a.nwwrap, 'height', (r.nwH * E.io3(pr(t, T.answered + .3, T.answered + .8))).toFixed(1) + 'px');
      const after = t > T.answered + .15;
      htm(a.sum, after ? '<span class="c-r b6">1 needs you</span> · 1 done · 3 working · 2 ready' : '<span class="c-r b6">2 need you</span> · 1 done · 2 working · 2 ready');
      S(a.sum, { o: 1 - .8 * Math.max(0, 1 - Math.abs(t - (T.answered + .15)) / .15) });
      txt(a.kneeds, after ? 'Needs you · 1' : 'Needs you · 2'); txt(a.kwork, t > T.answered + .3 ? 'Working · 3' : 'Working · 2');
      // scroll to Ready before diving
      const scy = -r.scrollAmt * E.io3(pr(t, 24.75, 25.1));
      S(a.sc, { y: scy });
      press(a.review, t, T.tapReview);
      press(a.ready1, t, T.tapReady);
      // the decision sheet
      const sOpen = E.sp(pr(t, T.sheet, T.sheet + .75)), sClose = E.i3(pr(t, T.sheetDown, T.sheetDown + .42));
      const sh = g.sheet.h + 30;
      const sheetOn = t > T.sheet && t < T.sheetDown + .45; show(a.sheet, sheetOn); show(a.scrim, sheetOn);
      if (sheetOn) {
        S(a.sheet, { y: Math.max(-10, sh * (1 - sOpen)) + sh * sClose });
        S(a.scrim, { o: E.o2(pr(t, T.sheet, T.sheet + .3)) * (1 - E.o2(pr(t, T.sheetDown, T.sheetDown + .3))) });
        const fill = pr(t, T.sheet + .15, T.guard);
        set(a.yesfill, 'width', (fill < 1 ? fill * 100 : 0).toFixed(1) + '%');
        cls(a.g1, 'ok', t > T.read); cls(a.g2, 'ok', t > T.guard);
        const yon = E.o2(pr(t, T.guard, T.guard + .2));
        S(a.yes, { o: mix(.42, 1, yon), s: 1 - .035 * Math.max(0, 1 - Math.abs(t - T.tapYes) / .14) + .03 * Math.sin(Math.PI * pr(t, T.guard, T.guard + .45)) });
        cls(a.yes, 'off', false);
        // reading: a light passes down the slab
        const sp = pr(t, T.sheet + .5, T.read);
        set(a.slab, 'background', sp > 0 && sp < 1 ? `linear-gradient(180deg, #0f0f14 ${(sp * 100 - 18).toFixed(1)}%, rgba(122,162,247,.16) ${(sp * 100).toFixed(1)}%, #0f0f14 ${(sp * 100 + 2).toFixed(1)}%)` : '#0f0f14');
        const sw = pr(t, T.sent, T.sent + .25);
        S(a.ask, { o: 1 - sw }); set(a.ask, 'visibility', sw >= 1 ? 'hidden' : 'visible');
        S(a.sent, { o: sw, y: (1 - E.o3(sw)) * 10 }); set(a.sent, 'visibility', sw > 0 ? 'visible' : 'hidden');
        press(a.back, t, T.tapBack);
      }
    }
    // composer
    const cOn = t > T.push - .05; show(a.compose, cOn);
    if (cOn) {
      S(a.compose, { x: 393 * (1 - E.o4(pr(t, T.push, T.push + .5))) });
      const msg = 'Skip the MINA option. Spike sshj with a Keystore-backed P-256 key and report what the host accepts.';
      const n = Math.floor(msg.length * pr(t, T.typeA, T.typeB));
      txt(a.ctext, t > T.tapSend + .25 ? '' : msg.slice(0, n));
      const typing = t > T.typeA && t < T.typeB;
      S(a.caret, { o: typing ? 1 : (Math.floor(t * 2) % 2 ? .1 : 1) });
      press(a.send, t, T.tapSend);
      S(a.ctoast, { o: env(t, T.tapSend + .3, 31.0, .3, .35), y: tw(t, T.tapSend + .3, T.tapSend + .7, 16, 0, E.o4) });
      const working = t > T.tapSend + .4;
      txt(a.cchipT, working ? `Working · ${Math.floor(t - (T.tapSend + .4))} s` : "Ready by herdr's status · since 14:01");
      set(a.cdot, 'background', working ? '#7aa2f7' : '#565f89');
    }
    // touches on the iPhone
    const ta = t < 12.4 ? [T.tapNotif, g.notif] : t < 19 ? [T.tapReview, g.review] : t < 21.5 ? [T.tapYes, g.yes] : t < 24 ? [T.tapBack, g.back] : t < 26 ? [T.tapReady, { ...g.ready1, y: g.ready1.y - r.scrollAmt }] : [T.tapSend, g.send];
    touch(a.touch, t, ta[0], ta[1]);

    // callouts (stage coordinates from the flat iPhone at x 1240)
    const M0 = mapA(1240, 540, 1);
    const at = (gg, fx, fy) => M0(gg.x + gg.w * fx, gg.y + gg.h * fy);
    let p;
    p = at(g.card1, .97, .14); callout(0, t, 13.75, 16.75, p[0], p[1], 250, 'Waiting on you', 'Red needs you, green is done. Working agents stay quiet.');
    p = at(g.live, .9, .5); callout(1, t, 14.45, 16.75, p[0], p[1], 470, 'Always current', 'Live data says how fresh it is. Old data says it is old.');
    p = at(g.kwork, .5, .5); p[0] = M0(352, 0)[0]; callout(2, t, 15.15, 16.8, p[0], p[1] + 40, 690, 'Same order as herdr', 'Needs you, done, working, ready.');
    p = at(g.slab, .97, .5); callout(3, t, 18.0, 20.2, p[0], p[1], 360, 'Read in full', 'The whole command, never a summary on a button.');
    p = at(g.yes, .97, .5); callout(4, t, 18.95, 20.25, p[0], p[1], 600, 'No pocket taps', 'Yes waits 1.5 s after the request appears.');
    p = at({ x: g.sent.x, y: g.sent.y + 70, w: g.sent.w, h: 30 }, .97, .5); callout(5, t, 20.95, 22.4, p[0], p[1], 470, 'One request, one answer', 'Your Yes reaches this request, or nothing.');

    // ---------- Android ----------
    const bOn = t > 24.9; show(r.B, bOn); show(r.shB, bOn);
    if (bOn) {
      const be = E.o4(pr(t, 25.0, 25.95));
      let bx = mix(2300, 1580, be), by = 540 + Math.sin(t * .8 + 1) * 3, bs = .98, bry = mix(32, 0, be);
      const b6 = E.io4(pr(t, 31.2, 32.1)); bx = mix(bx, 1680, b6); bs = mix(bs, .88, b6);
      const bex = E.i3(pr(t, 37.15, 37.8));
      S(r.B, { x: bx - 206.5, y: by - 436 + bex * 60, s: bs * (1 - bex * .12), persp: 2400, ry: bry, o: 1 - bex });
      r.shB.style.left = (bx - 260) + 'px'; r.shB.style.top = (by + 400 * bs) + 'px'; S(r.shB, { o: be * .8 * (1 - bex), s: bs });
      r.mapB = mapB(bx, by, bs);
      // terminal
      const tOn = t < 31.9; show(b.termv, tOn);
      if (tOn) {
        const sw = E.o3(pr(t, 31.3, 31.75));
        S(b.termv, { x: -60 * sw, o: 1 - sw });
        htm(b.term, termText(t));
        const released = t > T.tapRelease + .1;
        cls(b.term, 'ctl', !released);
        txt(b.pillT, released ? 'Observing · read-only' : 'In control · 60×38');
        cls(b.pill, 'amber', !released); set(b.pilldot, 'background', released ? '#565f89' : '#e0af68');
        S(b.keys, { o: released ? .45 : 1 });
        cls(b.kDown, 'arm', Math.abs(t - T.tapDown) < .12); cls(b.kEnter, 'arm', Math.abs(t - T.tapEnter) < .12);
        press(b.release, t, T.tapRelease);
        S(b.ttoast, { o: env(t, T.tapRelease + .15, 31.4, .3, .3), y: tw(t, T.tapRelease + .15, T.tapRelease + .55, 16, 0, E.o4) });
      }
      const pOn = t > 31.3; show(b.pairv, pOn);
      if (pOn) {
        const sw = E.o3(pr(t, 31.4, 31.9));
        S(b.pairv, { x: 60 * (1 - sw), o: sw });
        const sent = t > T.packetEnd, appr = t > T.added + .1;
        txt(b.sendkeyT, appr ? 'Approved on the desktop' : sent ? 'Sent · approve it on the desktop' : t > T.tapSendKey + .1 ? 'Sending…' : 'Send the key to this desktop');
        set(b.sendkey, 'color', appr ? '#9ece6a' : ''); set(b.sendkey, 'borderColor', appr ? 'rgba(158,206,106,.5)' : '');
        press(b.sendkey, t, T.tapSendKey);
        cls(b.connect, 'off', !appr); press(b.connect, t, T.tapConnect);
        txt(b.connectT, t > T.connected + .3 ? 'Connected · desktop' : 'Connect');
        S(b.hk, { o: E.o2(pr(t, T.connected, T.connected + .3)), y: tw(t, T.connected, T.connected + .4, 8, 0) });
        const glow = env(t, T.match, 35.8, .3, .4);
        set(b.pfp8, 'boxShadow', glow > .01 ? `0 0 0 ${(4 * glow).toFixed(1)}px rgba(224,175,104,${(.3 * glow).toFixed(2)})` : 'none');
      }
      const tb = t < 28 ? [T.tapDown, g.kDown] : t < 29 ? [T.tapEnter, g.kEnter] : t < 32 ? [T.tapRelease, g.release] : t < 34.5 ? [T.tapSendKey, g.sendkey] : [T.tapConnect, g.connect];
      touch(b.touch, t, tb[0], tb[1]);
    }
  }

  function renderTrust(t) {
    const r = R, g = r.geo;
    S(r.win, { o: E.o3(pr(t, 31.5, 32.0)) * (1 - E.i3(pr(t, 37.1, 37.75))), y: tw(t, 31.5, 32.2, 50, 0, E.o4) + tw(t, 37.1, 37.75, 0, 40, E.i3), s: tw(t, 31.5, 32.2, .96, 1, E.o4) });
    // QR assembles
    const qp = (t - 32.0) / 1.0, qk = qp >= 1.2 ? 2 : Math.floor(qp * 30);
    if (r._q !== qk) {
      r._q = qk;
      const x = r.qx, n = r.qn, m = 265 / (n + 4);
      x.fillStyle = '#f2f4fb'; x.fillRect(0, 0, 265, 265);
      x.fillStyle = '#16161e';
      for (const [mx, my, d] of r.qmods) {
        const p2 = cl((qp - d) / .25); if (p2 <= 0) continue;
        const s = m * (p2 >= 1 ? 1 : E.back(p2));
        x.fillRect((mx + 2) * m + (m - s) / 2, (my + 2) * m + (m - s) / 2, s + .4, s + .4);
      }
    }
    r.sides.forEach((s, i) => S(s, { o: E.o2(pr(t, 32.5 + i * .15, 32.8 + i * .15)) }));
    const ln = Math.floor(r.LINK.length * pr(t, 32.85, 33.45));
    txt(r.lk, ln > 0 ? r.LINK.slice(0, ln) : '');
    const L = [
      [33.5, '<span style="color:#8b95c0">Waiting up to 120 s for one key: listener, camera or paste.</span>'],
      [T.packetEnd + .05, 'Phone key fingerprint:'],
      [T.packetEnd + .15, '  SHA256:<mark>Xk3fQ9aT</mark>7hL2mPvB8nRcYw4dJ6sE1uGzK0oNqF5tHiA'],
      [T.packetEnd + .25, '  first 8 characters:  [<span class="m8" style="color:#e0af68">Xk3fQ9aT</span>]'],
      [T.packetEnd + .4, '<span style="color:#8b95c0">Approve only if the phone shows the same fingerprint.</span>'],
      [T.packetEnd + .5, '[R]eject (default) / [a]pprove, then Enter: ' + (t > T.approve ? '<span style="color:#e2e6fb">a</span>' : (Math.floor(t * 2) % 2 ? '<i class="cur"></i>' : ''))],
      [T.added, '<span class="ok">✓ Added to ~/.ssh/authorized_keys. Press Connect on the phone.</span>'],
    ];
    L.forEach(([at, s], i) => htm(r.wl[i], t >= at ? s : ''));
    // the wire from the phone's Send button to the listener, and the fingerprint match
    if (r.mapB) {
      const winL = 700, winR = 1300;
      const side = r.sides[1] ? PD.offsetIn(r.sides[1], r.win) : { y: 150, h: 40 };
      const [px, py] = r.mapB(-2, g.sendkey.y + g.sendkey.h / 2);
      const wx = winR + 4, wy = 150 + side.y + 10;
      const d = `M${px.toFixed(1)} ${py.toFixed(1)} C ${(px - 110).toFixed(1)} ${py.toFixed(1)}, ${(wx + 110).toFixed(1)} ${wy.toFixed(1)}, ${wx.toFixed(1)} ${wy.toFixed(1)}`;
      if (r.wp._d !== d) { r.wp._d = d; r.wp.setAttribute('d', d); r.wpl = r.wp.getTotalLength(); }
      const won = env(t, T.tapSendKey, 34.7, .3, .4);
      S(r.wp, { o: won * .75 });
      const kp = pr(t, T.packet, T.packetEnd), pt = r.wp.getPointAtLength(r.wpl * E.io3(kp));
      r.pk.setAttribute('cx', pt.x); r.pk.setAttribute('cy', pt.y); r.pk2.setAttribute('cx', pt.x); r.pk2.setAttribute('cy', pt.y);
      S(r.pk, { o: kp > 0 && kp < 1 ? 1 : 0 }); S(r.pk2, { o: kp > 0 && kp < 1 ? .5 : 0 });
      const mid = r.wp.getPointAtLength(r.wpl * .5);
      r.wt.setAttribute('transform', `translate(${mid.x.toFixed(1)} ${(Math.min(py, wy) - 46).toFixed(1)})`);
      S(r.wt, { o: won });
      const m8 = r.win.querySelector('.m8');
      if (m8) {
        const o = PD.offsetIn(m8, r.win);
        const mx = winL + o.x + o.w + 14, my = 150 + o.y + o.h / 2;
        const [fx, fy] = r.mapB(g.pfp8.x - 4, g.pfp8.y + g.pfp8.h / 2);
        const md = `M${mx.toFixed(1)} ${my.toFixed(1)} L ${(winR + 8).toFixed(1)} ${my.toFixed(1)} C ${(winR + 110).toFixed(1)} ${my.toFixed(1)}, ${(fx - 120).toFixed(1)} ${fy.toFixed(1)}, ${fx.toFixed(1)} ${fy.toFixed(1)}`;
        if (r.mp._d !== md) { r.mp._d = md; r.mp.setAttribute('d', md); r.mpl = r.mp.getTotalLength(); }
        const mo = env(t, T.match, 35.9, .5, .4);
        S(r.mp, { o: mo }); r.mp.setAttribute('stroke-dashoffset', (-t * 30).toFixed(1));
        const mm = r.mp.getPointAtLength(r.mpl - 1 - (r.mpl - (winR + 8 - mx)) * .5);
        r.mb.setAttribute('transform', `translate(${mm.x.toFixed(1)} ${mm.y.toFixed(1)}) scale(${(.6 + .4 * E.back(pr(t, T.match + .2, T.match + .6))).toFixed(3)})`);
        S(r.mb, { o: env(t, T.match + .2, 35.9, .3, .4) });
      } else { S(r.mp, { o: 0 }); S(r.mb, { o: 0 }); }
    }
    r.f3r.forEach((f, i) => S(f, { o: env(t, 35.3 + i * .22, 37.35, .4, .35), x: tw(t, 35.3 + i * .22, 35.8 + i * .22, -16, 0, E.o4) }));
  }

  return { build, render, layout, DUR, T, CHAPTERS, get refs() { return R; } };
})();
