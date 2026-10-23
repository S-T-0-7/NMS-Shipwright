/* Shared state, helpers and the pages the app shows. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const S = {path: null, ships: [], empty: [], models: [], slot: null, palettes: {},
           target: 'primary', paint: null, job: null, edit: null, optLabel: {}};
const randomSeed = () => '0x' + [...crypto.getRandomValues(new Uint8Array(8))].map(b => b.toString(16).padStart(2, '0')).join('').toUpperCase();
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const hex = c => '#' + (c || [0, 0, 0]).map(v => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0')).join('');
const modelUrl = (ship, q) => `/api/model?ship=${encodeURIComponent(ship)}&${q}`;
const VIEWERS = {};
/* Line art, all drawn in one 16px box with one stroke weight, so a button carrying an icon
   reads the same wherever it is. Put `ic('name')` in markup built here, or data-icon="name" on
   markup in editor.html -- paintIcons() fills those in once the page is up. */
const ICON = {
  fly: '<path d="M8 2.6v8.2M4.6 6 8 2.6 11.4 6M2.6 13.4h10.8"/>',
  land: '<path d="M8 10.8V2.6M11.4 7.4 8 10.8 4.6 7.4M2.6 13.4h10.8"/>',
  spin: '<path d="M13.4 8a5.4 5.4 0 1 1-1.6-3.8"/><path d="M13.7 2.2v3.4h-3.4"/>',
  search: '<circle cx="7" cy="7" r="4.3"/><path d="m10.2 10.2 3.4 3.4"/>',
  stop: '<rect x="4.2" y="4.2" width="7.6" height="7.6" rx="1.6"/>',
  plus: '<path d="M8 3.2v9.6M3.2 8h9.6"/>',
  trash: '<path d="M3 4.4h10M6.4 4.4V2.9h3.2v1.5M4.8 4.4l.6 8.3a1 1 0 0 0 1 .9h3.2a1 1 0 0 0 1-.9l.6-8.3"/>',
  disk: '<path d="M3 3.9a1 1 0 0 1 1-1h6.2l3 3v6.2a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M5.4 2.9v3.3h4.2V2.9M5.4 13.1V9.4h5.2v3.7"/>',
  folder: '<path d="M2.6 12.4V4.4a.8.8 0 0 1 .8-.8h2.7l1.4 1.6h4.9a.8.8 0 0 1 .8.8v6.4a.8.8 0 0 1-.8.8H3.4a.8.8 0 0 1-.8-.8z"/>',
  down: '<path d="M2.8 10v2.4a1 1 0 0 0 1 1h8.4a1 1 0 0 0 1-1V10"/><path d="M8 2.6v6.8M5.4 6.8 8 9.4l2.6-2.6"/>',
  up: '<path d="M2.8 10v2.4a1 1 0 0 0 1 1h8.4a1 1 0 0 0 1-1V10"/><path d="M8 9.4V2.6M5.4 5.2 8 2.6l2.6 2.6"/>',
  box: '<path d="M2.6 5.2 8 2.4l5.4 2.8v5.6L8 13.6l-5.4-2.8z"/><path d="m2.6 5.2 5.4 2.8 5.4-2.8M8 8v5.6"/>',
  dice: '<rect x="2.6" y="2.6" width="10.8" height="10.8" rx="2.5"/><path d="M5.8 5.8h.01M8 8h.01M10.2 10.2h.01"/>',
  sliders: '<path d="M2.8 5.2h10.4M2.8 10.8h10.4"/><circle cx="6" cy="5.2" r="1.7"/><circle cx="10" cy="10.8" r="1.7"/>',
  grid: '<rect x="2.6" y="2.6" width="4.7" height="4.7" rx="1.1"/><rect x="8.7" y="2.6" width="4.7" height="4.7" rx="1.1"/><rect x="2.6" y="8.7" width="4.7" height="4.7" rx="1.1"/><rect x="8.7" y="8.7" width="4.7" height="4.7" rx="1.1"/>',
  ship: '<path d="M8 2.1c1.6 1.8 2.5 4 2.5 6.3l2.7 2.2v1.5l-3-1.1-.6 2.4H6.4l-.6-2.4-3 1.1v-1.5l2.7-2.2C5.5 6.1 6.4 3.9 8 2.1z"/>',
  key: '<circle cx="5.4" cy="10.6" r="2.7"/><path d="M7.4 8.7 13.3 2.8v2.5M11.2 4.9l1.4 1.4"/>',
  list: '<path d="M6 4.2h7.4M6 8h7.4M6 11.8h7.4M2.8 4.2h.01M2.8 8h.01M2.8 11.8h.01"/>',
  globe: '<circle cx="8" cy="8" r="5.4"/><path d="M2.6 8h10.8M8 2.6c1.5 1.7 2.3 3.5 2.3 5.4S9.5 11.7 8 13.4C6.5 11.7 5.7 9.9 5.7 8s.8-3.7 2.3-5.4z"/>',
  layers: '<path d="M8 2.1 13.6 5 8 7.9 2.4 5z"/><path d="m2.4 8 5.6 2.9L13.6 8M2.4 11l5.6 2.9L13.6 11"/>',
  bolt: '<path d="M8.9 2 3.7 9.1h3.5L7.1 14l5.2-7.1H8.8z"/>',
  wrench: '<path d="M10.5 2.4a3.7 3.7 0 0 0-4.6 4.6l-3.3 3.3a1.2 1.2 0 0 0 0 1.7l1.4 1.4a1.2 1.2 0 0 0 1.7 0L9 10.1a3.7 3.7 0 0 0 4.6-4.6l-2 2-2.1-.5-.5-2.1z"/>',
  expand: '<path d="M6.2 2.6H2.6v3.6M9.8 2.6h3.6v3.6M6.2 13.4H2.6V9.8M9.8 13.4h3.4V9.8"/>',
  check: '<path d="m3.2 8.4 3.2 3.2 6.4-7"/>',
};
const svg = d => `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"
  stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ic = name => ICON[name] ? svg(ICON[name]) : '';
/* editor.html marks its buttons with data-icon="..." rather than carrying a page of raw SVG. */
const paintIcons = (root = document) => root.querySelectorAll('[data-icon]').forEach(el => {
  if (!el.querySelector('svg')) el.insertAdjacentHTML('afterbegin', ic(el.dataset.icon));
});
const VIEWS = [['three', '3/4'], ['front', 'Front'], ['side', 'Side'], ['top', 'Top'], ['back', 'Back']];

function show3d(id, url, fallback) {
  const el = $('#' + id); if (!el) return;
  VIEWERS[id]?.destroy(); el.classList.add('v3d');
  const v = VIEWERS[id] = window.ShipViewer && ShipViewer.mount(el);
  const fail = msg => { v?.destroy(); el.classList.remove('v3d'); el.innerHTML = fallback || `<span class="muted">${esc(msg)}</span>`; };
  if (!v) return fail('3D view needs WebGL2');
  v.elId = id;  // lets the viewer find its own Fly/Land button in the HUD
  hud(el, id);
  v.load(url).catch(e => fail(e.message));
}

/* The viewer's controls, laid over the canvas in its corners rather than stacked underneath:
   the model is the thing worth the room, and the buttons belong to it. */
function hud(el, id) {
  const v = VIEWERS[id], d = document.createElement('div');
  d.className = 'vhud';
  d.innerHTML = `<div class="hudrow end"><div class="glass pad">
      <button class="iconbtn on" title="Keep it turning">${svg(ICON.spin)}</button>
      <button class="iconbtn" id="pose-${id}" style="display:none" title="Show it flying">${svg(ICON.fly)}</button></div></div>
    <div class="hudrow"><div class="glass seg">${VIEWS.map(([k, l]) => `<button data-v="${k}">${l}</button>`).join('')}</div>
      <span class="vhint">Drag to turn &middot; scroll to zoom &middot; double-click to reset</span></div>`;
  el.appendChild(d);
  const [spin, pose] = d.querySelectorAll('.iconbtn'), seg = d.querySelector('.seg');
  spin.onclick = () => v.spin();
  // A drag or an angle button stops the spin too, so the button follows the viewer, not the click.
  v.onauto = on => { spin.classList.toggle('on', on); if (on) seg.querySelectorAll('.on').forEach(b => b.classList.remove('on')); };
  seg.onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    v.view(b.dataset.v);
    seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  };
  pose.onclick = () => {
    if (!v.posable) return;
    const on = !v.posed;
    v.setPose(on);
    pose.classList.toggle('on', on);
    pose.innerHTML = svg(on ? ICON.land : ICON.fly);
    pose.title = on ? 'Show it landed' : 'Show it flying';
  };
}

async function api(url, opts) {
  const r = await fetch(url, opts);
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
  if (!r.ok || (data && data.ok === false)) {
    const err = new Error((data && data.error) || `${r.status} ${r.statusText}`);
    err.status = r.status;
    if (data && data.hint) { err.hint = data.hint; err.gameData = true; }
    throw err;
  }
  return data;
}
const post = (url, body) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
function toast(msg, err) {
  const d = document.createElement('div'); if (err) d.className = 'err'; d.textContent = msg;
  $('#toast').append(d); setTimeout(() => d.remove(), err ? 9000 : 5000);
}
async function guard(fn) {
  try { return await fn(); } catch (e) {
    toast(e.hint ? `${e.message}\n${e.hint}` : e.message, true);
    if (e.gameData || e.status === 409) showBanner(e.message + (e.status === 409 ? ' Nothing was saved.' : ''), true);
  }
}

function showBanner(text, bad, action) {
  const b = $('#banner');
  b.hidden = false; b.className = 'banner' + (bad ? '' : ' info');
  b.innerHTML = esc(text) + (action ? ` <button class="btn" id="bFix">${esc(action)}</button>` : '')
    + ' <button class="btn" id="bHide">Dismiss</button>';
  $('#bHide').onclick = () => { b.hidden = true; };
  if (action) $('#bFix').onclick = () => guard(refreshGameData);
}

async function loadHealth(deep) {
  const h = await api('/api/health' + (deep ? '?deep=1' : ''));
  if ($('#hList')) {
    $('#hBuild').textContent = h.nms_dir ? `game build ${h.build.exe[0]} bytes · ${h.build.paks} archives` : '';
    if ($('#hDir') !== document.activeElement) $('#hDir').value = h.nms_dir || '';
    $('#hList').innerHTML = h.checks.map(c => `<div class="hrow ${c.ok ? '' : 'bad'}"><b>${c.ok ? '✓' : '✕'} ${esc(c.name)}</b>
      <span class="d">${esc(String(c.detail))}</span><span style="flex:1"></span><span class="muted">${esc(c.needed_for)}</span></div>`).join('');
  }
  if (!h.nms_dir) {
    showBanner('No Man\'s Sky was not found on this PC. Open Save > Game data and choose the folder it is installed in '
               + '(the one containing Binaries\\NMS.exe).', true);
  } else if (!h.ok) {
    const broken = h.checks.filter(c => !c.ok).map(c => c.name).join(', ');
    showBanner(`Some game data could not be read (${broken}). Features that need it will not work.`, true, 'Re-read game files');
  } else if (h.updated) {
    showBanner('No Man\'s Sky was updated. The tool re-read the new game files.', false);
  } else {
    $('#banner').hidden = true;
  }
  return h;
}
async function refreshGameData() {
  toast('Reading the game files again, this takes a moment...');
  const h = await api('/api/health/refresh', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  toast(h.ok ? 'Game files re-read. Everything checks out.' : 'Game files re-read, but some checks still fail.', !h.ok);
  await loadHealth(false);
}
const shortPath = p => p.split(/[\\/]/).slice(-2).join('/');

$$('nav button').forEach(b => b.onclick = () => {
  $$('nav button').forEach(x => x.classList.toggle('active', x === b));
  $$('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + b.dataset.page));
  const load = {player: async () => { await loadPlayer(); await loadBackups(); setupExport(); await loadHealth(false); }, quests: loadQuests,
                inventory: loadInventories, unlocks: loadUnlocks, designer: () => post('/api/find/warm', {}).catch(() => {})}[b.dataset.page];
  if (load) guard(load);
});

async function loadStatus() {
  const st = await api('/api/status'), pill = $('#gamePill');
  pill.className = 'pill ' + (st.game_running ? 'on' : 'off');
  pill.textContent = st.game_running ? 'Game running: edits blocked' : 'Game closed: safe to edit';
  if (st.version && $('#navVer')) $('#navVer').textContent = 'v' + st.version;
}
async function loadSaves() {
  const saves = await api('/api/saves');
  const hm = t => `${Math.floor(t / 3600)}h ${String(Math.floor(t / 60) % 60).padStart(2, '0')}m`;
  const slots = {};
  saves.forEach(s => (slots[s.slot] = slots[s.slot] || []).push(s));
  $('#saveSel').innerHTML = Object.keys(slots).sort((a, b) => a - b).map(n => {
    const list = slots[n].sort((a, b) => b.mtime - a.mtime), top = list[0];
    const head = `Slot ${n}${top.name ? ` "${top.name}"` : ''}${top.difficulty ? ` · ${top.difficulty}` : ''}${top.playtime ? ` · ${hm(top.playtime)} played` : ''}`;
    return `<optgroup label="${esc(head)}">` + list.map(s =>
      `<option value="${esc(s.path)}">${s === saves[0] ? '★ ' : ''}${esc(s.kind)}${s.summary ? ' - ' + esc(s.summary) : ''} (${new Date(s.mtime * 1000).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'})})</option>`).join('') + '</optgroup>';
  }).join('');
  S.path = saves.length ? saves[0].path : null;
  $('#saveSel').value = S.path || '';
}
$('#saveSel').onchange = e => { S.path = e.target.value; guard(loadShips);
  const act = $$('.page').find(p => p.classList.contains('active'))?.id;
  const reload = {'page-quests': loadQuests, 'page-inventory': loadInventories, 'page-unlocks': loadUnlocks}[act];
  if (reload) guard(reload); };
$('#refresh').onclick = () => guard(async () => { await loadStatus(); await loadSaves(); await loadShips(); });
