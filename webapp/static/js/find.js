/* Finding a matching ship in real star systems. */
const glyphLine = g => [...g].map(c => GLYPHS[parseInt(c, 16)]).join(' &middot; ');
async function loadFind() {
  if (!S.path) return;
  S.loc = await api('/api/location?path=' + encodeURIComponent(S.path));
  const c = S.loc.current;
  if (!$('#fAddr').value) { $('#fAddr').value = c.glyphs; $('#fGal').value = c.galaxy; }
  $('#fVisited').innerHTML = S.loc.visited.length ? '<span class="muted">Systems you know:</span> ' + S.loc.visited.map((v, i) =>
    `<button class="btn" data-i="${i}" title="${esc(v.coords)}">${esc(v.galaxy_name)} &middot; ${v.system}</button>`).join('') : '';
  $$('#fVisited button').forEach(b => b.onclick = () => {
    const v = S.loc.visited[+b.dataset.i]; $('#fAddr').value = v.glyphs; $('#fGal').value = v.galaxy; guard(showSystem);
  });
}
function placeHtml(s) {
  return `<b>${esc(s.galaxy_name)}</b>, system ${s.system} (0x${s.system.toString(16).toUpperCase()}) in region (${s.x}, ${s.y}, ${s.z})
    <div>Galactic coordinates <span class="mono">${esc(s.coords)}</span> &middot; portal glyphs <span class="mono">${esc(s.glyphs)}</span></div>
    <small class="muted">${glyphLine(s.glyphs)} (first glyph picks the planet)</small>`;
}
function shipCard(ship, seed, title, note) {
  return `<div class="card res">
    <img class="thumb" data-thumb="${esc(ship)}" data-seed="${esc(seed)}" alt="">
    <div style="margin-top:6px"><b>${esc(title)}</b>${note ? ` <small class="muted">${note}</small>` : ''}</div>
    <div class="row" style="margin-top:6px;justify-content:space-between"><code>${esc(seed)}</code>
      <button class="btn" data-seed="${esc(seed)}" data-ship="${esc(ship)}">Put in my save...</button></div></div>`;
}
/* Cards are built as strings all over the app, so the pictures are filled in afterwards. */
function paintThumbs(root = document) {
  root.querySelectorAll('img[data-thumb]').forEach(img => {
    if (!img.dataset.done) { img.dataset.done = '1'; thumbInto(img, img.dataset.thumb, img.dataset.seed); }
  });
}
function freighterCard(x, home) {
  return `<div class="card res">
    <img class="thumb" data-thumb="${esc(x.alias)}" data-seed="${esc(x.seed)}" alt="">
    <div><b>${esc(x.type[0].toUpperCase() + x.type.slice(1))}</b></div>
    <div class="row" style="margin-top:6px;justify-content:space-between"><code>${esc(x.seed)}</code>
      <button class="btn" data-seed="${esc(x.seed)}" data-ship="${esc(x.alias)}" data-home="${esc(home)}">Apply to your freighter</button></div></div>`;
}
async function applyFreighter(seed, ship, home) {
  if (!confirm(`Give your freighter this ${ship === 'capital_freighter' ? 'capital freighter' : 'freighter'} look (seed ${seed})?\n` +
    `Its home system is set to where it was found, which sets its colours and who is aboard. Your freighter base and cargo stay. A backup is made first.`)) return;
  await guard(async () => {
    await post('/api/freighter', {path: S.path, seed, ship, home});
    toast('Freighter updated. Backup made.');
    if ($('#frCard')) await loadFreighter();
  });
}
/* ---- the freighter, and who is aboard it -------------------------------------------------
   The crew is not in the save, so there is no field to set: the home system is the whole of it.
   The race that holds a system is something the tool already works out for any address, so the
   choice is offered as a race and turned into the nearest system of that race. */
let FR = null;

const RACE_NOTE = {Gek: 'Gek', "Vy'keen": "Vy'keen", Korvax: 'Korvax', none: 'nobody (uninhabited)'};

async function loadFreighter() {
  const box = $('#frCard');
  box.innerHTML = '<p class="muted">Reading the save...</p>';
  FR = await api('/api/freighter?path=' + encodeURIComponent(S.path));
  if (!FR.filename) { box.innerHTML = '<p class="muted">This save has no freighter yet.</p>'; return; }
  const kind = FR.filename.includes('CAPITAL') ? 'Capital freighter' : 'Freighter';
  const place = FR.home_place;
  box.innerHTML = `<div class="row" style="justify-content:space-between">
      <div><b>${esc(kind)}</b> <code>${esc(FR.seed)}</code></div></div>
    <p style="margin:8px 0 0">Home system: ${place ? `<code>${esc(place.glyphs)}</code> <span class="muted">${esc(place.coords)} &middot; ${esc(place.galaxy_name)}</span>`
      : '<span class="muted">not set</span>'}</p>
    <p style="margin:4px 0 0">Aboard: <b>${esc(RACE_NOTE[FR.home_race] || FR.home_race || 'unknown')}</b></p>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="frFind">Pick a different race</button>
      <span class="muted" id="frNote"></span></div>
    <div class="row" id="frRaces" style="margin-top:8px"></div>`;
  $('#frFind').onclick = () => guard(findHomes);
  if (!$('#frAddr').value) {
    if (place) { $('#frAddr').value = place.glyphs; $('#frGal').value = place.galaxy; }
    else {
      const loc = S.loc || (S.loc = await api('/api/location?path=' + encodeURIComponent(S.path)));
      $('#frAddr').value = loc.current.glyphs; $('#frGal').value = loc.current.galaxy;
    }
  }
}

async function findHomes() {
  const from = FR.home_place ? FR.home_place.glyphs : null;
  $('#frNote').textContent = 'Looking through the systems next door...';
  const addr = from || (await api('/api/location?path=' + encodeURIComponent(S.path))).current.glyphs;
  const d = await api('/api/freighter/races?addr=' + encodeURIComponent(addr));
  const races = Object.entries(d.races).filter(([r]) => r !== 'none');
  $('#frNote').textContent = `nearest of each race among ${d.searched} systems in the same region`;
  $('#frRaces').innerHTML = races.map(([r, p]) =>
    `<button class="btn" data-home="${esc(p.glyphs)}" title="${esc(p.coords)}">${esc(RACE_NOTE[r] || r)}
       <span class="muted">&middot; ${esc(p.glyphs)}</span></button>`).join('')
    || '<span class="muted">No inhabited system found nearby.</span>';
  $$('#frRaces button').forEach(b => b.onclick = () => guard(() => setHome(b.dataset.home, b.textContent.trim().split(' ')[0])));
}

async function setHome(glyphs, race) {
  if (!confirm(`Move your freighter's home system to ${glyphs}?\n\n` +
    'That system is held by the ' + race + ', and the game draws the aliens aboard your freighter from the home system. ' +
    'The freighter itself -- its shape, its colours, your base and cargo -- is not touched. A backup is made first.\n\n' +
    'Worth knowing: the crew is not stored in the save, so this is the only thing the game has to go on, but the ' +
    'tool cannot show you the result. Load the save and look.')) return;
  FR = await post('/api/freighter/home', {path: S.path, home: glyphs});
  toast('Home system moved. Backup made.');
  await loadFreighter();
}

/* ---- building one from parts --------------------------------------------------------------
   The same part tree and seed search the Designer uses, ending in "make this my freighter"
   rather than "put this in slot N". A freighter's hull is not stored part by part -- the seed
   decides the lot -- so picking parts is really describing what to go hunting for. */
const FB = {job: null, timer: null};

async function loadFreighterBuilder() {
  if ($('#fbShip').options.length) return;        // the tree is built once and then kept
  const types = await api('/api/freighter/types');
  $('#fbShip').innerHTML = types.map(t => `<option value="${esc(t.ship)}">${esc(t.label)}</option>`).join('');
  $('#fbShip').value = (FR && FR.filename && FR.filename.includes('CAPITAL')) ? 'capital_freighter' : 'freighter';
  await fbTree();
}

async function fbTree() {
  const box = $('#fbTree');
  box.innerHTML = '<span class="muted">Reading the parts...</span>';
  const tree = await api('/api/design/tree?ship=' + $('#fbShip').value);
  box.innerHTML = '';
  renderGroups(tree, box, fbPreview);
  fbPreview();
}

function fbPreview() {
  clearTimeout(FB.timer);
  FB.timer = setTimeout(() => {
    const parts = wantedIn('#fbTree'), box = $('#fbPreview');
    $('#fbUse').hidden = true;
    if (!parts.length) {
      VIEWERS.fbPreview?.destroy(); delete VIEWERS.fbPreview;
      box.classList.remove('v3d');
      box.innerHTML = '<span class="muted">Nothing chosen yet. Pick a part and it appears here.</span>';
      return;
    }
    /* Some choices carry no mesh of their own -- a capital freighter's _HULL_A3 draws nothing
       until the rows under it are picked too -- and a blank panel with no word for it reads as
       a broken preview. */
    show3d('fbPreview', modelUrl($('#fbShip').value, 'parts=' + encodeURIComponent(parts.join(','))), null, head => {
      if (head.groups.length) return;
      VIEWERS.fbPreview?.destroy(); delete VIEWERS.fbPreview;
      box.classList.remove('v3d');
      box.innerHTML = '<span class="muted">These parts draw nothing on their own -- this one is a choice the hull hangs off '
        + 'rather than a piece with a shape. Pick a few more rows and it appears.</span>';
    });
  }, 250);
}

/* A seed, straight out of the box or rolled, drawn as the whole freighter it really makes. */
function fbShowSeed(seed) {
  if (!seed) throw new Error('Type a seed first.');
  FB.seed = seed;
  show3d('fbPreview', modelUrl($('#fbShip').value, 'seed=' + encodeURIComponent(seed)));
  $('#fbUse').hidden = false;
  $('#fbStatus').textContent = `Showing seed ${seed}.`;
}

async function fbFind() {
  const want = wantedIn('#fbTree');
  if (!want.length) throw new Error('Pick at least one part first.');
  const r = await post('/api/design/search', {ship: $('#fbShip').value, want, n: 5, seconds: 600});
  FB.job = {id: r.job, ship: $('#fbShip').value};
  $('#fbResults').innerHTML = '';
  $('#fbFind').disabled = true; $('#fbStop').disabled = false;
  fbPoll();
}

async function fbPoll() {
  const job = FB.job, j = await api('/api/jobs/' + job.id);
  $('#fbStatus').textContent = `${j.status}: tested ${Number(j.tested).toLocaleString()} seeds in `
    + `${Number(j.seconds).toFixed(0)}s, found ${j.results.length}${j.error ? ' -- ' + j.error : ''}`;
  const box = $('#fbResults');
  if (box.children.length !== j.results.length) {
    box.innerHTML = j.results.map(res => `<div class="card res">
      <img class="thumb" data-thumb="${esc(job.ship)}" data-seed="${esc(res.seed)}" alt="">
      <div class="row" style="margin-top:6px;justify-content:space-between"><code>${esc(res.seed)}</code>
        <button class="btn" data-fbseed="${esc(res.seed)}">Make this my freighter</button></div></div>`).join('');
    $$('#fbResults [data-fbseed]').forEach(b => b.onclick = () => fbUse(b.dataset.fbseed));
    paintThumbs(box);
  }
  if (j.status === 'running') return void setTimeout(() => guard(fbPoll), 900);
  $('#fbFind').disabled = false; $('#fbStop').disabled = true;
}

async function fbUse(seed) {
  const ship = $('#fbShip').value;
  if (!confirm(`Make seed ${seed} your ${ship === 'capital_freighter' ? 'capital freighter' : 'freighter'}?\n\n` +
    'Its shape, parts and colours all change. Its home system stays as it is, so the same aliens stay aboard, ' +
    'and your freighter base, cargo and everything installed are untouched. A backup is made first.')) return;
  await post('/api/freighter', {path: S.path, seed, ship});
  toast('Freighter rebuilt. Backup made.');
  await loadFreighter();
}

$('#fbShip').onchange = () => guard(fbTree);
$('#fbReset').onclick = () => guard(fbTree);
$('#fbRoll').onclick = () => { $('#fbSeed').value = randomSeed(); guard(async () => fbShowSeed($('#fbSeed').value)); };
$('#fbSee').onclick = () => guard(async () => fbShowSeed($('#fbSeed').value.trim()));
$('#fbSeed').onkeydown = e => { if (e.key === 'Enter') guard(async () => fbShowSeed($('#fbSeed').value.trim())); };
$('#fbUse').onclick = () => guard(() => fbUse(FB.seed));
$('#fbFind').onclick = () => guard(fbFind);
$('#fbStop').onclick = () => FB.job && post(`/api/jobs/${FB.job.id}/cancel`, {});

/* The finder: one system's freighter fleet, the same ships the Design & Find system view
   lists, put where the freighter itself is edited. */
async function showFreighters() {
  const box = $('#frFound');
  box.innerHTML = '<p class="muted">Generating the system...</p>';
  const s = await api(`/api/system?addr=${encodeURIComponent($('#frAddr').value.trim())}&galaxy=${+$('#frGal').value || 0}`);
  if (!s.region_valid) { box.innerHTML = '<p class="muted">This region is empty: it has no star systems.</p>'; return; }
  const fleet = s.ships.filter(x => x.kind === 'freighter fleet' && (x.alias === 'freighter' || x.alias === 'capital_freighter'));
  $('#frWhere').innerHTML = `<span class="muted">${esc(s.galaxy_name)} &middot; system ${s.system} &middot;
    ${s.inhabited ? 'held by the <b>' + esc(s.race) + '</b>' : 'uninhabited'}</span>`;
  box.innerHTML = fleet.length ? fleet.map(x => freighterCard(x, s.ua)).join('')
    : '<p class="muted">No freighter fleet warps into this system.</p>';
  $$('#frFound button[data-seed]').forEach(b => b.onclick = () => applyFreighter(b.dataset.seed, b.dataset.ship, b.dataset.home));
  paintThumbs(box);
}
$('#frShow').onclick = () => guard(showFreighters);
$('#frAddr').onkeydown = e => { if (e.key === 'Enter') guard(showFreighters); };
$('#frHere').onclick = () => guard(async () => {
  const loc = S.loc || (S.loc = await api('/api/location?path=' + encodeURIComponent(S.path)));
  $('#frAddr').value = loc.current.glyphs; $('#frGal').value = loc.current.galaxy;
  await showFreighters();
});

async function showSystem() {
  const box = $('#fSystem'); box.innerHTML = '<p class="muted">Generating the system...</p>';
  const s = await api(`/api/system?addr=${encodeURIComponent($('#fAddr').value.trim())}&galaxy=${+$('#fGal').value || 0}`);
  if (!s.region_valid) { box.innerHTML = `<div class="card" style="padding:12px">${placeHtml(s)}<p>This region is empty: it has no star systems.</p></div>`; return; }
  const station = s.ships.filter(x => x.station);
  const fleet = s.ships.filter(x => x.kind === 'freighter fleet' && (x.alias === 'freighter' || x.alias === 'capital_freighter'));
  const others = s.ships.filter(x => !x.station && !fleet.includes(x));
  const bodies = s.planet_list.map(p => `<span class="badge ${p.levels[2] === 3 ? 'hot' : ''}" title="sentinels: ${esc(p.sentinels)}">${p.index}: ${esc(p.biome_name)}${p.levels[2] === 3 ? ' - corrupted sentinels' : ''}</span>`).join(' ');
  box.innerHTML = `<div class="card" style="padding:12px">${placeHtml(s)}
      <p style="margin:8px 0 0">${s.planets} planets, ${s.moons} moons &middot; ${s.dissonant ? '<span class="badge hot">DISSONANT</span>' : 'not dissonant'}
        &middot; ${s.inhabited ? 'held by the <b>' + esc(s.race) + '</b>' : 'uninhabited'}</p>
      <div style="margin-top:6px">${bodies}</div></div>
    <h3>Sentinel interceptor at crash sites</h3>
    <p class="muted" style="margin-top:0">${s.dissonant ? 'This system is dissonant, so its crash sites have this interceptor (every crash site in the system has this design; the class can differ).'
      : 'This system is not dissonant, so it has no interceptor crash sites. This is the design it would have.'}</p>
    <div class="results">${shipCard('sentinel', s.interceptor, 'Interceptor', s.dissonant ? '' : '(not available here)')}</div>
    <h3>Space station ships (${station.length})</h3>
    <p class="muted" style="margin-top:0">${s.inhabited === false ? 'This system is uninhabited, so traders rarely visit.'
      : "The ships that land at this system's space station. Wait there and each one arrives in time."}</p>
    <div class="results">${station.map(x => shipCard(x.alias, x.seed, x.type[0].toUpperCase() + x.type.slice(1), '')).join('')}</div>
    <h3>Freighter fleet</h3>
    <p class="muted" style="margin-top:0">The capital freighter and freighters that warp into this system with its fleet. Buy one from its captain,
      or give your own freighter its look.</p>
    <div class="results">${fleet.map(x => freighterCard(x, s.ua)).join('')}</div>
    <h3>Other visitors</h3>
    <div>${others.map(x => `<span class="badge" title="${esc(x.seed)}">${esc(x.type)} &middot; ${esc(x.kind)}</span>`).join(' ')}</div>`;
  $$('#fSystem button[data-seed]').forEach(b => b.onclick = () => b.dataset.home ? applyFreighter(b.dataset.seed, b.dataset.ship, b.dataset.home)
    : applySeed(b.dataset.seed, b.dataset.ship));
  paintThumbs(box);
}
$('#fShow').onclick = () => guard(showSystem);
$('#fAddr').onkeydown = e => { if (e.key === 'Enter') guard(showSystem); };
$('#fHere').onclick = () => guard(async () => {
  await loadFind(); $('#fAddr').value = S.loc.current.glyphs; $('#fGal').value = S.loc.current.galaxy; await showSystem();
});
$('#dFind').onclick = () => guard(async () => {
  const want = wanted();
  if (!want.length && !lookSet()) throw new Error('Pick at least one part or colour first.');
  if (!S.loc) await loadFind();
  const ship = $('#dShip').value;
  const r = await post('/api/find/scan', {ship, want, addr: S.loc.current.ua, radius: +$('#dRad').value, n: +$('#dN').value,
    closest: $('#dClose').checked, look: S.look});
  S.job = {id: r.job, ship, shown: ''}; $('#dResults').innerHTML = '';
  $('#dGo').disabled = $('#dFind').disabled = true; $('#dStop').disabled = false; pollFind();
});
async function pollFind() {
  const job = S.job, j = await api('/api/jobs/' + job.id);
  $('#dStatus').textContent = `${j.status}: scanned ${Number(j.tested).toLocaleString()} systems (${j.regions}/${j.total_regions} regions) in ${Number(j.seconds).toFixed(0)}s, found ${j.results.length}${j.error ? ' -- ' + j.error : ''}`;
  const box = $('#dResults'), key = j.results.map(r => r.seed).join();
  if (key !== job.shown) {  // the ranking can change after every region, so redraw the list
    job.shown = key; box.innerHTML = '';
    for (const res of j.results) {
      const d = document.createElement('div'); d.className = 'card res';
      const miss = res.missing.map(id => S.optLabel[id] || id);
      d.innerHTML = `
        <div style="margin-top:6px"><span class="badge ${res.score === res.total ? 'hot' : ''}">${res.total ? `${res.score}/${res.total} parts` : 'colour match'}</span>
          ${miss.length ? `<small class="muted" title="${esc(miss.join(', '))}">missing ${esc(miss.slice(0, 3).join(', '))}${miss.length > 3 ? '...' : ''}</small>` : ''}</div>
        <div style="margin-top:6px">${placeHtml(res)}</div>
        <div style="margin-top:4px">${res.where === 'crash site' ? 'Crash-site interceptor &middot; <span class="badge hot">DISSONANT</span>'
          : res.where === 'freighter fleet' ? 'Warps in with the freighter fleet' : 'Visits the space station'}
          <small class="muted">&middot; ${res.regions_away ? res.regions_away + ' region(s) away' : 'in your region'}</small></div>
        <div class="row" style="margin-top:6px;justify-content:space-between"><code>${res.seed}</code>
          <button class="btn">${res.where === 'freighter fleet' ? 'Apply to your freighter' : 'Put in my save...'}</button></div>`;
      d.querySelector('button').onclick = () => res.where === 'freighter fleet' ? applyFreighter(res.seed, job.ship, res.ua) : applySeed(res.seed, job.ship);
      box.append(d);
    }
  }
  if (j.status === 'running') setTimeout(() => guard(pollFind), 1000);
  else { $('#dGo').disabled = $('#dFind').disabled = false; $('#dStop').disabled = true; }
}
