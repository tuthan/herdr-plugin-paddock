// Paddock's screens as markup builders, shared by the reel and the page. Content follows the Android and iOS galleries.
const PD = (() => {
  const C = (cx, cy, r) => `<circle cx="${cx}" cy="${cy}" r="${r}"/>`;
  const P = d => `<path d="${d}"/>`;
  // The agent marks (agent-marks.html): 24-unit grid, 1.8 stroke, round caps.
  const GL = {
    claude: P('M18.3 7.1A8 8 0 1 0 18.3 16.9') + C(13.2, 12, 1),
    codex: P('M8 8l-4 4 4 4') + P('M16 8l4 4-4 4') + P('M13.5 6l-3 12'),
    opencode: P('M19.8 10V7.5L12 3 4.2 7.5v9L12 21l7.8-4.5V14') + P('M8.5 12h8'),
    gemini: C(9, 12, 5.5) + C(15, 12, 5.5),
    copilot: C(12, 12, 9) + P('M15.5 8.5l-2 5-5 2 2-5z'),
    cursor: P('M5 4l14 6-6 2-2 6.5z'),
    pi: P('M5 7h14') + P('M9 7v11') + P('M15 7v9.5c0 1 .6 1.5 1.5 1.5'),
    amp: P('M6 10v4') + P('M10 6v12') + P('M14 9v6') + P('M18 7v10'),
  };
  const glyph = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${GL[k]}</svg>`;
  const sv = (d, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
  const I = {
    gear: sv('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
    chev: sv('<path d="M9 6l6 6-6 6"/>', 'class="chev"'),
    back: sv('<path d="M15 5l-7 7 7 7"/>', 'style="width:24px;height:24px"'),
    arrowL: sv('<path d="M19 12H5M11 6l-6 6 6 6"/>'),
    monitor: sv('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>', 'style="width:22px;height:22px"'),
    term: sv('<path d="M4 17l6-5-6-5M12 19h8"/>', 'style="width:18px;height:18px"'),
    layers: sv('<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>'),
    grid: sv('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
    pulse: sv('<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
    check: sv('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'style="width:16px;height:16px"'),
    check2: sv('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'style="width:20px;height:20px"'),
    up: sv('<path d="M12 19V5M6 11l6-6 6 6"/>', 'style="width:18px;height:18px"'),
    kbd: sv('<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>', 'style="width:16px;height:16px"'),
    lock: sv('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>', 'style="width:22px;height:22px;color:#e2e6fb"'),
    torch: sv('<path d="M8 2h8l-1 6H9z"/><path d="M9 8h6v12a2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2z"/><path d="M12 13v3"/>'),
    cam: sv('<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>'),
  };
  const SIG = '<svg viewBox="0 0 18 12"><rect x="0" y="8" width="3" height="4" rx="1"/><rect x="5" y="5.5" width="3" height="6.5" rx="1"/><rect x="10" y="3" width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/></svg>';
  const WIFI = '<svg viewBox="0 0 16 12"><path d="M8 2.2c2.3 0 4.4.9 6 2.4l1.2-1.3A10.3 10.3 0 0 0 8 .4C5.2.4 2.7 1.5.8 3.3L2 4.6a8.6 8.6 0 0 1 6-2.4zm0 3.6c1.3 0 2.5.5 3.4 1.3l1.2-1.3A6.6 6.6 0 0 0 8 4c-1.8 0-3.4.7-4.6 1.8l1.2 1.3c.9-.8 2.1-1.3 3.4-1.3zM8 9.4l2.2-2.3A3 3 0 0 0 8 6.3c-.9 0-1.6.3-2.2.8z"/></svg>';
  const BAT = '<svg viewBox="0 0 27 12"><rect x=".5" y=".5" width="23" height="11" rx="3.2" fill="none" stroke="#e2e6fb" stroke-opacity=".45"/><rect x="2" y="2" width="17" height="8" rx="2"/><path d="M25 4v4c.8-.3 1.3-1 1.3-2s-.5-1.7-1.3-2z" fill-opacity=".45"/></svg>';
  const sb = p => `<div class="sb"><span>14:03</span><span class="st">${p === 'ios' ? SIG : ''}${WIFI}${BAT}</span></div>`;
  const TABS = [['Herd', I.layers], ['Spaces', I.grid], ['Activity', I.pulse]];
  const tabs = (p, on = 0) => p === 'ios'
    ? `<nav class="tabbar">${TABS.map((t, i) => `<a class="${i === on ? 'on' : ''}">${t[1]}${t[0]}</a>`).join('')}</nav>`
    : `<nav class="navb">${TABS.map((t, i) => `<a class="${i === on ? 'on' : ''}"><i>${t[1]}</i>${t[0]}</a>`).join('')}</nav>`;
  const endOf = p => p === 'ios' ? '<i class="home-ind"></i>' : '<i class="gest"></i>';

  const HOME = {
    needs: [
      { k: 'claude', t: 'Back up the docs vault', s: 'docs-vault › tab 1 · main · <span class="mono">40 s</span> waiting', q: 'Allow this command?', cmd: 'git push origin main' },
      { k: 'codex', t: 'Approve official MCP SDK proposal', s: 'blindpass › tab 8 · Allow command?', dk: 'row2', tail: 'chev' },
    ],
    done: [{ k: 'opencode', t: 'Vault phases 2–6 review against plan', s: 'docs-vault › tab 6 · finished <span class="mono">12 min</span> ago', tail: 'chev' }],
    working: [
      { k: 'gemini', t: 'Summarise phase 06 evidence', s: 'docs-vault › tab 2 · Forging… · <span class="mono">4m 49s</span>', tail: 'blue' },
      { k: 'amp', t: 'Backtest position sizing', s: 'trading-signal › tab 2 · Ran tests · <span class="mono">1m 12s</span>', tail: 'blue' },
    ],
    ready: [
      { k: 'codex', t: 'Assess Rust migration against plan', s: 'blindpass › tab 3 · idle since <span class="mono">14:01</span>', dk: 'ready1', tail: 'grey' },
      { k: 'pi', t: 'Fixture capture', s: 'herdr-fixtures › tab 4 · idle since <span class="mono">13:52</span>', tail: 'grey' },
    ],
  };
  const tailOf = t => t === 'chev' ? I.chev : t === 'blue' ? '<span class="dot blue"></span>' : t === 'grey' ? '<span class="dot"></span>' : '';
  const row = (r, cls = '') => `<div class="row ${cls}"${r.dk ? ` data-k="${r.dk}"` : ''}><span class="mg">${glyph(r.k)}</span><div class="bd"><p class="t">${r.t}</p><p class="s">${r.s}</p></div>${tailOf(r.tail)}</div>`;
  // iOS draws a section as one inset grouped list; Android as separate cards.
  const group = (p, rows, cls = '', pre = '') => p === 'ios'
    ? `<div class="grp ${cls}">${pre}${rows.map(r => row(r)).join('')}</div>`
    : `<div class="grp">${pre}${rows.map(r => row(r, cls)).join('')}</div>`;

  function home(p, o = {}) {
    const ios = p === 'ios', c = HOME.needs[0], after = !!o.after;
    const head = ios
      ? `<div class="lt"><h1 class="h1">Paddock</h1><span class="ib">${I.gear}</span></div>`
      : `<header class="bar"><h1 class="h1">Paddock</h1><span class="ib">${I.gear}</span></header>`;
    const card = `<div class="card red" data-k="card1"><div style="display:flex;gap:12px;align-items:flex-start"><span class="mg">${glyph(c.k)}</span><div class="bd"><p class="t">${c.t}</p><p class="s">${c.s}</p></div></div><p class="q">${c.q}</p><pre class="slab">${c.cmd}</pre><div class="btn p sm" data-k="review"><span>Review</span></div></div>`;
    const nw = { k: 'claude', t: c.t, s: 'docs-vault › tab 1 · answered from this phone · <span class="mono">1 s</span>', tail: 'blue' };
    const nwWrap = `<div data-k="nwwrap" style="overflow:hidden;${after || o.anim ? '' : 'display:none;'}${o.anim ? 'height:0;' : ''}">${row(nw, ios ? '' : '')}</div>`;
    const sum = after
      ? '<span class="c-r b6">1 needs you</span> · 1 done · 3 working · 2 ready'
      : '<span class="c-r b6">2 need you</span> · 1 done · 2 working · 2 ready';
    return `<div class="view" data-k="home">${sb(p)}${head}
<p class="sum" data-k="sum">${sum}</p>
<div class="chips"><span class="chip on"><span class="dot green"></span>desktop</span><span class="chip"><span class="dot green"></span>buildbox</span><span class="chip dash" data-k="live">live · 3 s</span></div>
<div class="scroll"><div class="sc" data-k="sc">
<p class="k red"><span class="dot red"></span><span data-k="kneeds">Needs you · ${after ? 1 : 2}</span></p>
${after ? '' : card}
${group(p, [HOME.needs[1]], 'red')}
<p class="k green"><span class="dot green"></span>Done · 1</p>
${group(p, HOME.done, 'green')}
<p class="k"><span class="dot blue"></span><span data-k="kwork">Working · ${after ? 3 : 2}</span></p>
${group(p, HOME.working, '', nwWrap)}
<p class="k"><span class="dot"></span>Ready · 2</p>
${group(p, HOME.ready)}
</div></div>${p === 'ios' ? '<i class="edge"></i>' : ''}${tabs(p, 0)}${endOf(p)}${o.sheet ? sheet(p, o) : ''}</div>`;
  }

  const SLAB_SHORT = '<span class="c-d">Bash</span>\n<span class="c-w">git push origin main</span>\n\n<span class="c-d">Push the vault backup commit to origin</span>';
  const SLAB_LONG = '<span class="c-d">Bash</span>\n<span class="c-w">rsync -a \\\n  --exclude \'.obsidian/workspace*\' \\\n  --delete \\\n  ~/Projects/docs-vault/ \\\n  /mnt/backup/docs-vault/\ngit -C ~/Projects/docs-vault add -A\ngit -C ~/Projects/docs-vault \\\n  commit -m "vault backup 2026-10-06"\ngit -C ~/Projects/docs-vault push origin main</span>\n\n<span class="c-d">Mirror the vault to the backup disk,\nthen commit and push the backup.</span>';
  function sheet(p, o = {}) {
    const ready = !!o.ready, sent = !!o.sent;
    return `<div class="scrim" data-k="scrim"></div><section class="sheet" data-k="sheet" aria-label="Claude asks">
<div class="grab"></div>
<div data-k="ask" style="display:flex;flex-direction:column;gap:12px;${sent ? 'visibility:hidden;' : ''}">
<div style="display:flex;gap:12px;align-items:flex-start"><span class="mg">${glyph('claude')}</span><div class="bd"><p class="t wrap">Back up the docs vault</p><p class="s wrap">claude · docs-vault › tab 1 · desktop · blocked <span class="mono">40 s</span></p></div></div>
<p class="k red" style="margin:0"><span class="dot red"></span>Claude asks</p>
<pre class="slab" data-k="slab"${o.long ? ' tabindex="0" style="max-height:172px;overflow-y:auto"' : ''}>${o.long ? SLAB_LONG : SLAB_SHORT}</pre>
<p class="q">Do you want to proceed?</p>
<div style="display:flex;flex-direction:column;gap:8px">
<button type="button" class="btn p${ready ? '' : ' off'}" data-k="yes"${ready || o.live ? '' : ' disabled'}><span class="fill" data-k="yesfill"></span><span data-k="yesT">Yes</span></button>
<button type="button" class="btn sec" data-k="no">No</button>
</div>
<div class="guard"><span data-k="g1" class="${ready ? 'ok' : ''}"><i></i>read in full</span><span data-k="g2" class="${ready ? 'ok' : ''}"><i></i>1.5 s guard</span><span class="ok"><i></i>window 20 s</span></div>
<div class="foot"><a>${I.term} See the terminal</a><span class="mono">hook request<br>7f3a9c1e</span></div>
</div>
<div data-k="sent" style="position:absolute;left:${p === 'ios' ? 18 : 16}px;right:${p === 'ios' ? 18 : 16}px;top:30px;display:flex;flex-direction:column;gap:16px;${sent ? '' : 'opacity:0;visibility:hidden;'}">
<div style="display:flex;gap:12px;align-items:center"><span class="mg" style="background:rgba(158,206,106,.16);color:#9ece6a">${I.check2}</span><div class="bd"><p class="t">Yes delivered</p><p class="s">to hook request <span class="mono">7f3a9c1e</span> · claude</p></div></div>
<div class="ev"><span class="tm">14:03:12</span><span class="dot green"></span><span class="tx">Answer delivered to the hook request it was bound to</span></div>
<div class="ev"><span class="tm">14:03:13</span><span class="dot blue"></span><span class="tx">Claude reports <span class="c-b b6">working</span><br><span class="mono">pane.agent_status_changed</span></span></div>
<div class="ev"><span class="tm">now</span><span class="dot" style="background:transparent;border:1.5px dashed #565f89"></span><span class="tx c-d">Paddock shows what it observed. What Claude does next is in the terminal.</span></div>
<div class="btn sec" data-k="back"><span>Back to the herd</span></div>
<div class="btn ghost"><span>Follow what Claude does next</span></div>
</div>
</section>`;
  }

  const lock = p => `<div class="view" data-k="lockv"><div class="lock"></div>${sb(p)}
<div style="position:relative;display:flex;flex-direction:column;align-items:center;padding-top:6px">${I.lock}<p class="lk-date">Tuesday 6 October</p><p class="lk-time">14:03</p></div>
<div class="nt" data-k="notif"><span class="ap">nt</span><div><div class="hd"><span>ntfy</span><span>now</span></div><b>Paddock: attention on desktop</b><p>Review in Paddock.</p>${p === 'ios' ? '' : '<div class="acts"><span>Open</span><span>Review</span></div>'}</div></div>
<div class="lk-btm"><i>${I.torch}</i><i>${I.cam}</i></div>${endOf(p)}</div>`;

  const compose = p => `<div class="view" data-k="compose">${sb(p)}
${p === 'ios' ? `<div class="navt"><span class="bk">${I.back}Herd</span><div class="ttl"><b>Assess Rust migration…</b><span>codex · blindpass › tab 3</span></div><span class="rt">${I.monitor}</span></div>` : `<div class="abar"><span class="ib">${I.arrowL}</span><div class="ttl"><b>Assess Rust migration against plan</b><span>codex · blindpass › tab 3 · main</span></div><span class="ib">${I.monitor}</span></div>`}
<div style="padding:6px 16px 0;display:flex;flex-direction:column;gap:14px">
<div class="chips" style="padding:0"><span class="chip" data-k="cchip"><span class="dot" data-k="cdot"></span><span data-k="cchipT">Ready by herdr's status · since 14:01</span></span></div>
<div class="field area"><span><span data-k="ctext"></span><i class="caret" data-k="caret"></i></span></div>
<div style="display:flex;flex-wrap:wrap;gap:8px">${['Continue', 'Run the tests', 'Where are you?', 'Commit what is done', 'Stop and summarize'].map(s => `<span class="chip">${s}</span>`).join('')}</div>
<div style="display:flex;gap:8px"><div class="btn danger sm" style="width:auto;flex:0 0 auto;padding:0 14px"><span>Esc · Interrupt</span></div><div class="btn p sm" data-k="send" style="flex:1"><span style="display:flex;gap:6px;align-items:center">${I.up} Send prompt</span></div></div>
<p class="s wrap" style="font-size:13px;line-height:1.5">Sent as one submission, Enter included. Paddock reads herdr's status again right before it sends.</p>
</div>
<div class="toast" data-k="ctoast" style="opacity:0"><span class="dot blue"></span><span>Sent · codex is working</span></div>${endOf(p)}</div>`;

  const key = (t, cls = '', dk = '') => `<span class="key ${cls}"${dk ? ` data-k="${dk}"` : ''}>${t}</span>`;
  const term = p => `<div class="view" data-k="termv">${sb(p)}
<div class="abar"><span class="ib">${I.arrowL}</span><div class="ttl"><b>Approve official MCP SDK…</b><span>codex · blindpass › tab 8 · desktop</span></div><span class="ib">${I.monitor}</span></div>
<div class="seg"><span>Output</span><span class="on">Terminal</span></div>
<div class="chips" style="padding:10px 12px"><span class="chip amber" data-k="pill"><span class="dot amber" data-k="pilldot"></span><span data-k="pillT">In control · 60×38</span></span><span class="chip">${I.kbd} Keyboard</span><span class="chip" data-k="release">Release</span></div>
<pre class="term ctl" data-k="term"></pre>
<div data-k="keys" style="display:flex;flex-direction:column;gap:6px;padding:8px 0 40px">
<div class="keys">${key('Esc', 'red')}${key('Enter', '', 'kEnter')}${key('↑')}${key('↓', '', 'kDown')}${key('←')}${key('→')}${key('Tab')}${key('^C')}</div>
<div class="keys">${key('Ctrl', '', 'kCtrl')}${key('Alt')}${key('Shift')}<span class="key div"></span>${key('Home')}${key('End')}${key('PgUp')}${key('PgDn')}</div>
</div>
<div class="toast" data-k="ttoast" style="opacity:0;bottom:150px"><span class="dot"></span><span>Control released · observing</span></div>${endOf(p)}</div>`;

  const pair = (p, o = {}) => `<div class="view" data-k="pairv">${sb(p)}
<div class="abar"><span class="ib">${I.arrowL}</span><div class="ttl"><b>Add a machine</b><span>from a pairing link</span></div></div>
<div style="padding:2px 16px 0;display:flex;flex-direction:column;gap:10px">
<div class="chips" style="padding:0"><span class="chip green">${I.check} Filled from the pairing link</span></div>
<div class="field"><span class="lb2">Host</span><span class="mono">192.168.42.23</span></div>
<div style="display:flex;gap:8px"><div class="field" style="flex:1"><span class="lb2">User</span><span class="mono">dev</span></div><div class="field" style="width:124px"><span class="lb2" style="width:36px">Port</span><span class="mono">22</span></div></div>
<div class="field"><span class="lb2">Session</span><span class="mono">default</span></div>
<p class="s wrap" style="font-size:12.5px;line-height:1.45">Host key pinned from the link. A server that shows any other key is refused.</p>
<p class="lb" style="margin-top:4px">This phone's key</p>
<div class="card" style="gap:6px;padding:12px 14px"><p class="s wrap" style="color:#c0caf5">ECDSA P-256 · StrongBox · cannot be exported</p><p class="fp">SHA256:<mark data-k="pfp8">Xk3fQ9aT</mark>7hL2mPvB8nRcYw4dJ6sE1uGzK0oNqF5tHiA</p></div>
<div class="btn ghost" data-k="sendkey"${o.done ? ' style="color:#9ece6a;border-color:rgba(158,206,106,.5)"' : ''}><span data-k="sendkeyT">${o.done ? 'Approved on the desktop' : 'Send the key to this desktop'}</span></div>
<div class="btn p${o.done ? '' : ' off'}" data-k="connect"><span data-k="connectT">${o.done ? 'Connected · desktop' : 'Connect'}</span></div>
<div class="chips" style="padding:0;min-height:32px"><span class="chip green" data-k="hk" style="opacity:${o.done ? 1 : 0}">${I.check} Host key matches the link</span></div>
</div>${endOf(p)}</div>`;

  const device = (p, inner) => p === 'ios'
    ? `<div class="dev iphone"><div class="scr ui ios">${inner}<span class="touch" data-k="touch"></span></div><span class="island"></span></div>`
    : `<div class="dev pixel"><div class="scr ui and">${inner}<span class="touch" data-k="touch"></span></div><span class="cam"></span></div>`;
  const keys = root => { const m = {}; root.querySelectorAll('[data-k]').forEach(e => { m[e.dataset.k] = e; }); return m; };
  // offset of el inside root, ignoring transforms (layout coordinates)
  const offsetIn = (el, root) => {
    let x = 0, y = 0, e = el;
    while (e && e !== root) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
    return { x, y, w: el.offsetWidth, h: el.offsetHeight };
  };
  return { glyph, GL, I, home, sheet, lock, compose, term, pair, device, keys, offsetIn, HOME };
})();
