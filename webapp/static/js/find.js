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
    <div style="margin-top:6px"><b>${esc(title)}</b>${note ? ` <small class="muted">${note}</small>` : ''}</div>
    <div class="row" style="margin-top:6px;justify-content:space-between"><code>${esc(seed)}</code>
      <button class="btn" data-seed="${esc(seed)}" data-ship="${esc(ship)}">Put in my save...</button></div></div>`;
}
function freighterCard(x, home) {
  return `<div class="card res"><div><b>${esc(x.type[0].toUpperCase() + x.type.slice(1))}</b></div>
    <div class="row" style="margin-top:6px;justify-content:space-between"><code>${esc(x.seed)}</code>
      <button class="btn" data-seed="${esc(x.seed)}" data-ship="${esc(x.alias)}" data-home="${esc(home)}">Apply to your freighter</button></div></div>`;
}
async function applyFreighter(seed, ship, home) {
  if (!confirm(`Give your freighter this ${ship === 'capital_freighter' ? 'capital freighter' : 'freighter'} look (seed ${seed})?\n` +
    `Its home system is set to where it was found, which sets its colours. Your freighter base and cargo stay. A backup is made first.`)) return;
  await guard(async () => { await post('/api/freighter', {path: S.path, seed, ship, home}); toast('Freighter updated. Backup made.'); });
}
async function showSystem() {
  const box = $('#fSystem'); box.innerHTML = '<p class="muted">Generating the system...</p>';
  const s = await api(`/api/system?addr=${encodeURIComponent($('#fAddr').value.trim())}&galaxy=${+$('#fGal').value || 0}`);
  if (!s.region_valid) { box.innerHTML = `<div class="card" style="padding:12px">${placeHtml(s)}<p>This region is empty: it has no star systems.</p></div>`; return; }
  const station = s.ships.filter(x => x.station);
  const fleet = s.ships.filter(x => x.kind === 'freighter fleet' && (x.alias === 'freighter' || x.alias === 'capital_freighter'));
  const others = s.ships.filter(x => !x.station && !fleet.includes(x));
  const bodies = s.planet_list.map(p => `<span class="badge ${p.levels[2] === 3 ? 'hot' : ''}" title="sentinels: ${esc(p.sentinels)}">${p.index}: ${esc(p.biome_name)}${p.levels[2] === 3 ? ' - corrupted sentinels' : ''}</span>`).join(' ');
  box.innerHTML = `<div class="card" style="padding:12px">${placeHtml(s)}
      <p style="margin:8px 0 0">${s.planets} planets, ${s.moons} moons &middot; ${s.dissonant ? '<span class="badge hot">DISSONANT</span>' : 'not dissonant'}</p>
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
}
$('#fShow').onclick = () => guard(showSystem);
$('#fAddr').onkeydown = e => { if (e.key === 'Enter') guard(showSystem); };
$('#fHere').onclick = () => guard(async () => {
  await loadFind(); $('#fAddr').value = S.loc.current.glyphs; $('#fGal').value = S.loc.current.galaxy; await showSystem();
});
$('#dFind').onclick = () => guard(async () => {
  const want = wanted(); if (!want.length) throw new Error('Pick at least one part first.');
  if (!S.loc) await loadFind();
  const ship = $('#dShip').value;
  const r = await post('/api/find/scan', {ship, want, addr: S.loc.current.ua, radius: +$('#dRad').value, n: +$('#dN').value,
    closest: $('#dClose').checked});
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
        <div style="margin-top:6px"><span class="badge ${res.score === res.total ? 'hot' : ''}">${res.score}/${res.total} parts</span>
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
