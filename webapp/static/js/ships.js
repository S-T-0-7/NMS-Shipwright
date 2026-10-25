/* My Ships: the ship list, seeds, stats, paint. */
async function loadShips() {
  if (!S.path) { $('#shipList').innerHTML = '<p class="muted">No save files found.</p>'; return; }
  const res = await api('/api/ships?path=' + encodeURIComponent(S.path));
  S.ships = res.ships; S.empty = res.empty;
  $('#newShip').disabled = !S.ships.length; $('#newShip').title = S.empty.length ? `Empty slots: ${S.empty.join(', ')}` : 'No empty slots -- you can replace a ship instead';
  $('#shipList').innerHTML = S.ships.map(s => `
    <div class="card ship ${s.index === S.slot ? 'sel' : ''}" data-slot="${s.index}">
      <div class="thumb">${esc(s.category)}</div>
      <div class="meta"><b>${esc(s.name || '(unnamed)')}</b><div>${esc(s.category)} &middot; slot ${s.index}</div>
        <small class="mono">${esc(s.seed)}</small><div>${s.primary ? '<span class="badge hot">CURRENT</span>' : ''}${s.is_procedural ? '' : '<span class="badge">FIXED MODEL</span>'}${s.paint ? '<span class="badge">PAINTED</span>' : ''}</div></div>
    </div>`).join('') || '<p class="muted">No ships in this save.</p>';
  $$('.ship').forEach(el => el.onclick = () => selectShip(+el.dataset.slot));
  if (S.ships.some(s => s.index === S.slot)) selectShip(S.slot);
  else $('#shipDetail').innerHTML = '<p class="muted">Select a ship.</p>';
}

function selectShip(slot) {
  S.slot = slot;
  $$('.ship').forEach(el => el.classList.toggle('sel', +el.dataset.slot === slot));
  const s = S.ships.find(x => x.index === slot); if (!s) return;
  const p = s.paint || {};
  S.paint = {primary: p.primary || [0, 0, 0], accent: p.accent || p.primary || [0, 0, 0], palette: p.palette || 'FREIGHTER',
             primary_index: p.primary_index, accent_index: p.accent_index, channels: p.channels || null};
  $('#shipDetail').innerHTML = `
    <h2 style="margin:0">${esc(s.name || '(unnamed)')} <span class="muted" style="font-weight:400">&middot; ${esc(s.category)} &middot; slot ${s.index}</span></h2>
    <div class="hero" id="sView" style="margin-top:10px">${s.ship ? '<span class="muted">Loading 3D model...</span>'
      : `<span class="muted">${s.is_procedural ? 'No 3D model for this ship type yet' : 'Fixed model: the seed does not change its look'}</span>`}</div>
    ${(s.wrong_tech || []).length ? `<div class="banner" style="margin:12px 0 0">This ship is carrying
      ${s.ship === 'sentinel' ? 'ordinary starship parts instead of the sentinel ones (Sentinel Cannon, Luminance Engine and so on)'
        : 'sentinel parts instead of ordinary starship ones'}, because it was copied from another ship.
      <button class="btn" id="sRefit">${ic('wrench')}Fit its own parts</button></div>` : ''}
    <h3>Seed</h3>
    <div class="row"><input id="sSeed" class="mono" value="${esc(s.seed)}" style="width:230px">
      <button class="btn primary" id="sApply">${ic('check')}Apply seed</button>
      <button class="btn" id="sReroll">${ic('dice')}Reroll</button>
      ${s.ship ? `<button class="btn ghost" id="sEdit">${ic('sliders')}Change its parts</button>` : ''}</div>
    ${s.ship ? '<p class="muted" style="margin:6px 0 0">"Change its parts" opens this ship in the Designer with its own parts filled in.</p>' : ''}
    <h3>Stats</h3>
    <div class="card" style="padding:14px" id="sStats"><span class="muted">Loading...</span></div>
    <h3>Recolour</h3>
    <p class="muted" style="margin:0 0 8px">Step 1: click a part of the ship below. Step 2: click a colour. The preview above updates as you pick.
      Step 3: press Save these colours. ${s.paint ? '<b>This ship is painted by you.</b>' : 'This ship still uses its own colours.'}</p>
    <div class="row" id="pChips"></div>
    <p class="warn" id="pFixed" hidden></p>
    <div class="row" style="margin-top:8px">
      <span class="muted" id="pPicking"></span><span style="flex:1"></span>
      <button class="btn primary" id="pApply">${ic('check')}Save these colours</button>
      <button class="btn danger" id="pClear">${ic('trash')}Remove my paint</button></div>
    <div class="row" style="margin-top:10px"><label class="muted">Or any colour</label>
      <input type="color" id="pAny" title="Any colour: it snaps to the nearest paint the game has" style="width:38px;height:30px;padding:0;border:0;background:none">
      <span class="muted" id="pNote"></span></div>
    <div id="pSw"></div>
    <details class="more"><summary>More: rename, change ship type, remove</summary>
    <h3>Name</h3>
    <div class="row"><input id="sName" value="${esc(s.name)}" placeholder="(unnamed)" style="width:260px"><button class="btn" id="sRename">Rename</button></div>
    <h3>Ship type</h3>
    <div class="row"><select id="sModel">${S.models.map(m => `<option value="${m.ship}" ${m.ship === s.ship ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}${s.ship ? '' : `<option value="" selected>${esc(s.category)} (fixed model)</option>`}</select>
      <button class="btn" id="sModelApply">Change type</button></div>
    <h3>Remove</h3>
    <div class="row"><button class="btn danger" id="sRemove">${ic('trash')}Remove this ship</button>
      <span class="muted">Empties the slot. A backup is made first -- undo it from Save &gt; Backups.</span></div>
    </details>
    ${s.is_procedural && s.ship ? '<h3>Colours &amp; finish from the seed</h3><div id="sLook"><span class="muted">Working out the look...</span></div>' : ''}
    <h3>Where to find it in the game</h3><div id="sOrigin">${originHtml(s)}</div>
    <details class="more"><summary>Parts list</summary><div class="parts mono" id="sParts">${s.is_procedural ? 'Loading...' : '<span>Fixed model</span>'}</div></details>`;
  $('#sApply').onclick = () => guard(async () => {
    const r = await post('/api/ship/seed', {path: S.path, slot, seed: $('#sSeed').value.trim()});
    toast(`Seed set to ${r.seed}. Backup made.`); if (r.warning) toast(r.warning, true); await loadShips();
  });
  $('#sReroll').onclick = () => guard(async () => { const r = await post('/api/ship/reroll', {path: S.path, slot}); toast(`Rerolled to ${r.seed}`); await loadShips(); });
  $('#sRename').onclick = () => guard(async () => { await post('/api/ship/name', {path: S.path, slot, name: $('#sName').value}); toast('Renamed. Backup made.'); await loadShips(); });
  if ($('#sRefit')) $('#sRefit').onclick = () => guard(async () => {
    const r = await post('/api/ship/refit', {path: S.path, slot});
    showBanner(`Slot ${slot} now has its own parts: ${r.swaps.map(x => `${x.from} -> ${x.to}`).join(', ')}. Backup made.`, false);
    await loadShips();
  });
  $('#sModelApply').onclick = () => guard(async () => {
    const ship = $('#sModel').value; if (!ship) throw new Error('Pick a ship type first.');
    const m = S.models.find(x => x.ship === ship);
    if (!confirm(`Change slot ${slot} into a ${m.label}? Its look will be generated from its seed.`)) return;
    await post('/api/ship/model', {path: S.path, slot, ship, seed: s.is_procedural ? s.seed : randomSeed()});
    toast(`Slot ${slot} is now a ${m.label}. Backup made.`); await loadShips();
  });
  $('#sRemove').onclick = () => guard(async () => {
    if (!confirm(`Remove the ${s.category} in slot ${slot}?\n\nThe slot becomes empty. A backup is made first -- undo it from Save > Backups.`)) return;
    const r = await post('/api/ship/remove', {path: S.path, slot});
    toast(`Removed the ship in slot ${r.slot}. Backup made.`);
    S.slot = null; $('#shipDetail').innerHTML = '<p class="muted">Select a ship.</p>'; await loadShips();
  });
  if (s.ship) show3d('sView', modelUrl(s.ship, 'seed=' + encodeURIComponent(s.seed)));
  if ($('#sEdit')) $('#sEdit').onclick = () => guard(() => openDesignerFor(s));
  if ($('#sLook')) guard(async () => {
    const l = await api(`/api/look?ship=${encodeURIComponent(s.ship)}&seed=${encodeURIComponent(s.seed)}`);
    if (S.slot !== slot || !$('#sLook')) return;
    $('#sLook').innerHTML = !l.seed_driven ? '<span class="muted">Sentinel colours come from their parts and the Recolour section above, not the seed.</span>'
      : `<div class="row">${Object.entries(l.colours).map(([k, c]) => `<span class="chip"><span class="sw" style="background:${hex(c.rgb)}"></span> ${esc(k)} <span class="muted">#${c.index}</span></span>`).join(' ')}</div>
         <p style="margin:8px 0 4px">Hull finish: <b>${esc(cap(l.keys.mode) || 'plain')}</b>${s.paint ? '<span class="muted"> (your Recolour overrides these colours in game)</span>' : ''}</p>
         <div class="decals">${l.textures.filter(t => t.option).map(t => `<div><span class="sw" style="background:${t.rgb ? hex(t.rgb) : 'transparent'}"></span>
           ${esc(t.list.toLowerCase().replace(/_/g, ' '))} ${esc(t.layer.toLowerCase())}: <b>${esc(t.option)}</b></div>`).join('')}</div>`;
  });
  setupPaint(slot, s.ship, s.seed);
  guard(() => loadStats(slot));
  if (s.is_procedural) guard(async () => {
    const r = await api(`/api/parts?ship=${encodeURIComponent(s.ship || s.filename)}&seed=${encodeURIComponent(s.seed)}`);
    $('#sParts').innerHTML = r.parts.map(p => `<div>${'&nbsp;&nbsp;&nbsp;'.repeat(p.depth)}${esc(p.name || p.id)} <span>${p.name ? esc(p.id) + ' &middot; ' : ''}1 of ${p.choices}</span></div>`).join('');
  });
}

const GLYPHS = ['Sunset', 'Bird', 'Face', 'Diplo', 'Eclipse', 'Balloon', 'Boat', 'Bug', 'Dragonfly', 'Galaxy', 'Voxel', 'Fish', 'Tent', 'Rocket', 'Tree', 'Atlas'];
function originHtml(s) {
  if (!s.ship) return '<p class="muted" style="margin:0">Fixed model: not generated from a star system.</p>';
  if (!s.origin || !s.origin.length) return `<p class="muted" style="margin:0">No star system generates this exact seed. Seeds from rerolls or the Designer
    only exist in your save; ships the game made (bought, crashed, interceptors) trace back to the system they came from.</p>`;
  /* Every row here has been generated and checked, so `where` says what is waiting at the
     address. A row without one could not be generated at all -- say so rather than send
     someone across the galaxy on it. */
  const row = (o, main) => `<div style="margin:${main ? 0 : '8px 0 0'}">
      <b>${esc(o.galaxy_name)}</b>, system ${o.system} (0x${o.system.toString(16).toUpperCase()}) in region (${o.x}, ${o.y}, ${o.z})
      ${o.visited ? '<span class="badge hot">YOU VISITED IT</span>' : ''}
      <div>${o.where ? `Waiting at the <b>${esc(o.where)}</b>${o.what ? ` as a ${esc(o.what)}` : ''}.`
        : '<span class="muted">Could not generate this system to check what is there.</span>'}</div>
      <div>Galactic coordinates <span class="mono">${esc(o.coords)}</span> &middot; portal glyphs <span class="mono">${esc(o.glyphs)}</span></div>
      <small class="muted">${[...o.glyphs].map(c => GLYPHS[parseInt(c, 16)]).join(' &middot; ')} (first glyph picks the planet)</small></div>`;
  const [best, ...rest] = s.origin;
  return row(best, true) + (rest.length && !best.visited ? `<p class="muted" style="margin:10px 0 0">Other possible systems:</p>` + rest.map(o => row(o)).join('') : '');
}

/* Only these paint sets apply to ships; the rest are for bikes, mechs, pets and so on. A save
   holds one set per ship, so these are not three palettes to choose between so much as one list
   of colours with a note of which sets each belongs to -- see allPaints and paintSetFor. */
const PAINT_SETS = {SHIP: 'Ship paints', SHIP_METALLIC: 'Metallic ship paints', FREIGHTER: 'Freighter paints (has true black)'};
const METALLIC = 'SHIP_METALLIC';

/* A plain-English name for a colour, so a swatch grid reads as words and not as 64 squares. */
function colourName(c) {
  const [r, g, b] = c, max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (d < .06) return l < .09 ? 'Black' : l < .3 ? 'Charcoal' : l < .55 ? 'Grey' : l < .85 ? 'Light grey' : 'White';
  let h = 0;
  if (max === r) h = 60 * (((g - b) / d) % 6); else if (max === g) h = 60 * ((b - r) / d + 2); else h = 60 * ((r - g) / d + 4);
  if (h < 0) h += 360;
  const hue = h < 15 ? 'red' : h < 45 ? 'orange' : h < 70 ? 'yellow' : h < 100 ? 'lime' : h < 160 ? 'green'
    : h < 195 ? 'teal' : h < 250 ? 'blue' : h < 290 ? 'purple' : h < 330 ? 'pink' : 'red';
  const sat = d / (1 - Math.abs(2 * l - 1) || 1);
  const shade = l < .22 ? 'Dark ' : l > .78 ? 'Pale ' : sat < .35 ? 'Dusty ' : l > .58 ? 'Bright ' : '';
  return shade + hue.charAt(0).toUpperCase() + hue.slice(1);
}
/* A paint set is stored as 64 slots but holds only ~20 real colours, the rest being repeats.
   Show each colour once, and number any names that still collide ("Dusty blue 2"). */
function namedColours(cols) {
  const seen = {}, out = [], had = new Set();
  cols.forEach((c, i) => {
    const key = c.map(v => Math.round(v * 255)).join(',');
    if (had.has(key)) return;
    had.add(key);
    const base = colourName(c), n = seen[base] = (seen[base] || 0) + 1;
    out.push({rgb: c, i, name: n > 1 ? `${base} ${n}` : base});
  });
  return out;
}
const nearestColour = (cols, c) => cols.reduce((best, x) =>
  (x.rgb || x).reduce((s, v, k) => s + (v - c[k]) ** 2, 0) < (best.rgb || best).reduce((s, v, k) => s + (v - c[k]) ** 2, 0) ? x : best, cols[0]);

/* Every colour a ship can take, once each, with the sets it belongs to and its slot in each.
   Asking someone to pick a set first and a colour second meant guessing which set a colour was
   in: 16 of the 20 metallics are in no other set, true black is only in the freighter paints,
   and the other 24 mostly overlap. So the sets stop being a question and become an answer --
   pick the colour, and whichever set can supply it is the one we store. */
function allPaints(palettes) {
  const out = [], seen = {}, at = {};
  for (const set of Object.keys(PAINT_SETS)) {
    (palettes[set] || []).forEach((rgb, i) => {
      const key = rgb.map(v => Math.round(v * 255)).join(',');
      if (at[key] === undefined) {
        const base = colourName(rgb), n = seen[base] = (seen[base] || 0) + 1;
        at[key] = out.length;
        out.push({rgb, name: n > 1 ? `${base} ${n}` : base, sets: {}});
      }
      if (out[at[key]].sets[set] === undefined) out[at[key]].sets[set] = i;
    });
  }
  return out;
}

/* One set has to cover every slot being painted, since a save keeps one per ship. Prefer the
   set that holds all the chosen colours outright; failing that, the one that holds the most. */
function paintSetFor(picked) {
  const want = picked.filter(Boolean);
  let best = 'FREIGHTER', score = -1;
  for (const set of Object.keys(PAINT_SETS)) {
    const n = want.filter(p => p.sets[set] !== undefined).length;
    if (n > score) { score = n; best = set; }
  }
  return {set: best, whole: score === want.length};
}

/* The game gives a ship five paint slots and each ship draws a different handful of them --
   see textures.paint_channels. Ask which, and offer exactly those. */
async function setupPaint(slot, ship, seed) {
  let channels = [{alt: 'Primary', name: 'Body'}], fixed = [];
  if (ship && seed) {
    try {
      const r = await api(`/api/ship/channels?ship=${encodeURIComponent(ship)}&seed=${encodeURIComponent(seed)}`);
      channels = r.channels; fixed = r.fixed || [];
    } catch (e) { /* fall back to the body alone rather than offering slots we cannot vouch for */ }
  }
  /* A quarter of interceptor seeds draw an opaque layer of their own right over the paint.
     Say so here, where someone is about to spend five minutes picking black. */
  const note = $('#pFixed');
  note.hidden = !fixed.length;
  if (fixed.length) note.textContent = `${fixed.map(f => f.name).join(' and ')}: this seed covers `
    + `the paint with a layer of its own, coloured by the seed and not settable, so the ship will `
    + `keep the colour it has. Tick "Only seeds I can paint" in the Designer and search for another `
    + `seed that builds the same ship -- three seeds in four are fine.`;
  const stored = (S.paint && S.paint.channels) || {};
  S.channels = {};
  for (const c of channels) {
    const had = stored[c.alt];
    S.channels[c.alt] = had ? {rgb: had.rgb, index: had.index}
                            : {rgb: S.paint.primary || [0, 0, 0], index: S.paint.primary_index ?? -1};
  }
  S.target = channels[0].alt;
  const paints = allPaints(S.palettes);
  /* What is stored is a colour, not a slot number: the set is worked out at the end from
     whatever was picked, so nobody has to know which set holds the colour they want. */
  for (const alt of Object.keys(S.channels)) S.channels[alt].pick = nearestColour(paints, S.channels[alt].rgb);
  /* Primary is the base coat and Alternative1 the trim, on an interceptor as on anything else.
     This had them the other way round for interceptors, which showed in the 3D preview. */
  const body = () => S.channels.Primary || S.channels[channels[0].alt];
  const trim = () => S.channels.Alternative1 || body();
  const livePreview = () => VIEWERS.sView && VIEWERS.sView.setColours({paint: body().rgb, secondary: trim().rgb});
  const label = alt => (channels.find(c => c.alt === alt) || {}).name || alt;
  const pickOf = alt => S.channels[alt].pick || nearestColour(paints, S.channels[alt].rgb);
  const chips = () => {
    $('#pChips').innerHTML = channels.map(c =>
      `<button class="btn chip ${S.target === c.alt ? 'primary' : ''}" data-alt="${esc(c.alt)}"
         title="paints ${esc((c.layers || []).join(', '))}"><i style="background:${hex(S.channels[c.alt].rgb)}"></i>
         <span>${esc(c.name)}: ${esc(pickOf(c.alt).name)}</span></button>`).join('');
    $$('#pChips button').forEach(b => b.onclick = () => { S.target = b.dataset.alt; chips(); });
    $('#pPicking').textContent = `Click a colour to set the ${label(S.target).toLowerCase()}`;
    livePreview();
  };
  const choose = p => { S.channels[S.target] = {rgb: p.rgb, index: -1, pick: p}; chips(); };
  const swatches = () => {
    /* Two bands rather than a dropdown: the metallics look different enough to be worth
       keeping apart, and everything is on screen at once either way. */
    const band = (title, list) => !list.length ? '' : `<p class="muted tnote" style="margin:10px 0 4px">${title}</p>`
      + `<div class="swatches">${list.map(p => `<i title="${esc(p.name)}" data-k="${paints.indexOf(p)}">`
      + `<b style="background:${hex(p.rgb)}"></b>${esc(p.name)}</i>`).join('')}</div>`;
    const metal = paints.filter(p => Object.keys(p.sets).length === 1 && p.sets[METALLIC] !== undefined);
    const plain = paints.filter(p => !metal.includes(p));
    $('#pSw').innerHTML = band(`Paints (${plain.length})`, plain) + band(`Metallic paints (${metal.length})`, metal);
    $$('#pSw i').forEach(el => el.onclick = () => choose(paints[+el.dataset.k]));
    $('#pNote').textContent = `${paints.length} paints in all. The game uses only these, so any other colour snaps to the nearest.`;
  };
  $('#pAny').oninput = e => {
    const v = e.target.value, want = [1, 3, 5].map(i => parseInt(v.substr(i, 2), 16) / 255);
    const near = nearestColour(paints, want);  // show what the game will really use
    choose(near);
    $('#pNote').textContent = `Nearest paint: ${near.name}.`;
  };
  $('#pApply').onclick = () => guard(async () => {
    const picks = channels.map(c => pickOf(c.alt));
    const {set, whole} = paintSetFor(picks);
    /* A colour the chosen set does not hold is snapped into it, so what is stored is a real
       slot of that set rather than a colour from another one the game may not honour. */
    const inSet = (S.palettes[set] || []).map((rgb, i) => ({rgb, i}));
    const out = {};
    for (const c of channels) {
      const p = pickOf(c.alt);
      const slot = p.sets[set];
      if (slot !== undefined) out[c.alt] = {rgb: p.rgb, index: slot};
      else { const n = nearestColour(inSet, p.rgb); out[c.alt] = {rgb: n.rgb, index: n.i}; }
    }
    const b = out.Primary || out[channels[0].alt];
    const t = out.Alternative1 || b;
    await post('/api/ship/paint', {path: S.path, slot, palette: set, channels: out,
                                   primary: b.rgb, primary_index: b.index,
                                   accent: t.rgb, accent_index: t.index});
    const said = channels.map(c => `${c.name.toLowerCase()} ${nearestColour(paints, out[c.alt].rgb).name}`).join(', ');
    showBanner(`Painted slot ${slot}: ${said}. Backup made. Load this save in the game to see it.`
      + (whole ? '' : ' One of these is not in the same set as the others, so the closest match in that set was used.'), false);
    await loadShips();
  });
  $('#pClear').onclick = () => guard(async () => { await post('/api/ship/paint/clear', {path: S.path, slot}); toast('Paint removed, back to its own colours. Backup made.'); await loadShips(); });
  swatches(); chips();
}

/* Ship stats: the bonuses the game rolls when it makes a ship, kept inside the game's own ranges. */
async function loadStats(slot) {
  const d = await api(`/api/ship/stats?path=${encodeURIComponent(S.path)}&slot=${slot}`);
  if (S.slot !== slot || !$('#sStats')) return;
  if (!d.stats.length) {
    $('#sStats').innerHTML = '<span class="muted">The game does not give this ship type tunable stats.</span>';
    return;
  }
  $('#sStats').innerHTML = `<p class="muted" style="margin:0 0 10px">These are the bonuses the game rolls when it
      makes a ship. The ranges are what a class ${esc(d.class)} ship of this type can have, straight from the game's tables.</p>
    ${d.stats.map(s => `<div class="row" style="margin-top:6px"><label class="muted" style="min-width:150px">${esc(s.name)}</label>
      <input type="number" step="0.1" min="${s.min}" max="${s.max}" value="${s.value}" data-stat="${esc(s.id)}" style="width:96px">
      <span class="muted">${s.min} to ${s.max}${s.value > s.max || s.value < s.min ? ' — outside that range' : ''}</span></div>`).join('')}
    <div class="row" style="margin-top:12px"><label class="muted" style="min-width:150px">Class</label>
      <select id="sClass">${['C', 'B', 'A', 'S'].map(c => `<option ${c === d.class ? 'selected' : ''}>${c}</option>`).join('')}</select>
      <button class="btn primary" id="sStatsSave">${ic('check')}Save stats</button>
      <button class="btn" id="sStatsBest">${ic('bolt')}Best possible</button></div>`;
  $('#sStatsSave').onclick = () => guard(async () => {
    const values = {};
    $$('#sStats [data-stat]').forEach(i => values[i.dataset.stat] = +i.value);
    await post('/api/ship/stats', {path: S.path, slot, values, class: $('#sClass').value});
    showBanner(`Stats saved for slot ${slot}. Backup made. Load this save in the game to see them.`, false);
    await loadStats(slot); await loadShips();
  });
  $('#sStatsBest').onclick = () => guard(async () => {
    const cls = $('#sClass').value;
    if (!confirm(`Give slot ${slot} the best stats a class ${cls} ship of this type can have?`)) return;
    await post('/api/ship/stats', {path: S.path, slot, class: cls, best: true});
    showBanner(`Slot ${slot} now has the best stats the game allows for a class ${cls} ship of its type. Backup made.`, false);
    await loadStats(slot); await loadShips();
  });
}

function chooseSlot(ship) {
  const lines = S.ships.map(s => `${s.index}: ${s.name || '(unnamed)'} (${s.category})${ship && s.ship !== ship ? '  <- different ship type, look will not match' : ''}`);
  const v = prompt('Apply this seed to which ship slot?\n\n' + lines.join('\n'), S.slot ?? '');
  if (v === null || v.trim() === '') return null;
  const n = parseInt(v, 10);
  return S.ships.some(s => s.index === n) ? n : (toast('No ship in slot ' + v, true), null);
}
async function applySeed(seed, ship) {
  // Where it goes: the Designer's "Into your save" choice when on that page, otherwise ask.
  let slot = null;
  const inDesigner = $('#dTarget') && $('#dTarget').offsetParent && $('#dShip').value === ship;
  if (inDesigner) slot = $('#dTarget').value;
  else if (S.edit && S.edit.ship === ship && confirm(`Put ${seed} on slot ${S.edit.slot} (${S.edit.name})?`)) slot = String(S.edit.slot);
  else {
    const free = (S.empty || []).length;
    const lines = S.ships.map(s => `${s.index}: ${s.name || '(unnamed)'} (${s.category})${s.ship !== ship ? '  <- becomes a ' + ship : ''}`);
    const v = prompt(`Put this ${ship} (${seed}) into your save.\n\nType "new" for a new ship slot${free ? '' : ' (none free)'}, or the slot number to replace:\n\n`
                     + lines.join('\n'), free ? 'new' : String(S.slot ?? ''));
    if (v === null || !v.trim()) return;
    slot = v.trim().toLowerCase();
    if (slot !== 'new' && !S.ships.some(s => String(s.index) === slot)) return toast('No ship in slot ' + v, true);
  }
  const label = slot === 'new' ? 'a new ship slot' : `slot ${slot}`;
  if (inDesigner && !confirm(`Put ${ship} ${seed} into ${label}? A backup of your save is made first.`)) return;
  await guard(async () => {
    const r = await post('/api/ship/put', {path: S.path, slot, ship, seed});
    showBanner(`Saved: ${r.what} is now a ${ship} (${r.seed}) in ${r.file}. Backup made. Load this save in the game to see it.`, false);
    await loadShips(); if (typeof fillTargets === 'function') fillTargets();
  });
}

function newShipPanel() {
  S.slot = null; $$('.ship').forEach(el => el.classList.remove('sel'));
  const total = S.ships.length + S.empty.length;
  const byIndex = i => S.ships.find(s => s.index === i);
  const slotsHtml = Array.from({length: total}, (_, i) => {
    const s = byIndex(i);
    return `<option value="${i}">${i}: ${s ? `${esc(s.category)} — ${esc(s.name || 'unnamed')}` : '(empty)'}</option>`;
  }).join('');
  const firstEmpty = S.empty.length ? S.empty[0] : 0;
  $('#shipDetail').innerHTML = `<h2 style="margin:0 0 12px;display:flex;justify-content:space-between;align-items:center">New ship <button class="btn" id="nClose" title="Cancel -- make no changes" style="padding:2px 11px">✕</button></h2>
    <div class="form2">
      <label class="muted">Slot</label><select id="nSlot">${slotsHtml}</select>
      <label class="muted">Type</label><select id="nModel">${S.models.map(m => `<option value="${m.ship}" ${m.ship === 'sentinel' ? 'selected' : ''}>${esc(m.label)}${m.special ? ' ★' : ''}</option>`).join('')}</select>
      <label class="muted" id="nSeedLabel">Seed</label><div class="row" id="nSeedRow"><input id="nSeed" class="mono" style="width:230px"><button class="btn" id="nRand">Random</button></div>
      <label class="muted">Name</label><input id="nName" placeholder="(unnamed)">
      <label class="muted" id="nFromLabel">Copy inventory &amp; tech from</label><select id="nFrom"><option value="">Standard (fresh empty inventory)</option>${S.ships.map(s => `<option value="${s.index}">${s.index}: ${esc(s.name || '(unnamed)')} (${esc(s.category)})</option>`).join('')}</select>
    </div>
    <p class="muted" id="nSpecialNote" style="margin:8px 0 0;display:none">★ Special ship — spawns exactly as it is (its own model, stats and tech). Seed and inventory options don't apply.</p>
    <p class="muted" id="nSlotNote" style="margin:8px 0 0"></p>
    <div class="hero" id="nPrev" style="margin-top:12px"></div>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="nCreate">${ic('plus')}Create ship</button><button class="btn ghost" id="nCancel">Cancel</button></div>
    <p class="muted">Tip: design it in the Designer first and paste the seed here. Replacing a slot keeps that ship's inventory &amp; tech; filling an empty slot copies the inventory you pick, or a standard empty one. Recolour afterwards from the ship page.</p>`;
  $('#nSlot').value = String(firstEmpty);
  const special = () => S.models.find(x => x.ship === $('#nModel').value)?.special;
  const prev = () => {
    const m = $('#nModel').value, seed = special() ? '0x6' : $('#nSeed').value.trim();
    if (seed) show3d('nPrev', modelUrl(m, 'seed=' + encodeURIComponent(seed)), '<span class="muted">No preview for this ship type</span>');
    else $('#nPrev').innerHTML = '<span class="muted">Enter a seed to preview</span>';
  };
  const sync = () => {
    const i = +$('#nSlot').value, s = byIndex(i), sp = special();
    for (const el of [$('#nSeedLabel'), $('#nSeedRow')]) el.style.display = sp ? 'none' : '';
    for (const el of [$('#nFromLabel'), $('#nFrom')]) el.style.display = (sp || s) ? 'none' : '';
    $('#nSpecialNote').style.display = sp ? '' : 'none';
    $('#nSlotNote').textContent = s ? `Replaces the ${s.category} in slot ${i} — its inventory & tech are kept.` : '';
    $('#nCreate').textContent = s ? 'Replace ship' : 'Create ship';
    prev();
  };
  $('#nRand').onclick = () => { $('#nSeed').value = randomSeed(); prev(); };
  $('#nModel').onchange = sync; $('#nSeed').oninput = prev; $('#nSlot').onchange = sync;
  $('#nClose').onclick = $('#nCancel').onclick = closeNewShip;
  $('#nSeed').value = randomSeed(); sync();
  $('#nCreate').onclick = () => guard(async () => {
    const slot = +$('#nSlot').value, s = byIndex(slot);
    if (s && !confirm(`Replace the ${s.category} in slot ${slot}?\n\nIts model, seed and colour become the new ship; its inventory & tech are kept. A backup is made first.`)) return;
    const from = $('#nFrom').value;
    const r = await post('/api/ship/create', {path: S.path, slot, ship: $('#nModel').value,
      seed: $('#nSeed').value.trim(), name: $('#nName').value, clone_from: from === '' ? null : +from});
    toast(`${r.action === 'replaced' ? 'Replaced ship in' : 'Created ship in'} slot ${r.slot}. Backup made.`); S.slot = r.slot; await loadShips();
  });
}
function closeNewShip() {
  if (S.ships.some(s => s.index === S.slot)) selectShip(S.slot);
  else $('#shipDetail').innerHTML = '<p class="muted">Select a ship.</p>';
}
$('#newShip').onclick = newShipPanel;
