/* Design & Find: the part tree, seed search and saved designs. */
async function openDesignerFor(s) {
  $$('nav button').find(b => b.dataset.page === 'designer').click();
  $('#dShip').value = s.ship; await loadTree();
  const r = await api(`/api/parts?ship=${encodeURIComponent(s.ship)}&seed=${encodeURIComponent(s.seed)}`);
  preselect(r.parts.map(p => p.id));
  S.edit = {slot: s.index, ship: s.ship, name: s.name || '(unnamed)'};
  showEdit(); fillTargets();
}

/* Pinning every part of an existing ship makes the search hopeless (one ship in billions), so
   this lets go of the pins that cost the most, cheapest first, until the wait is bearable. */
function loosen(minutes) {
  const rate = 5e6, budget = minutes * 60 * rate;      // seeds we can afford to test
  const dropped = [];
  for (let guard = 0; guard < 50 && oddsOneIn() > budget; guard++) {
    let worst = null, worstCost = 1;
    for (const sel of $$('#dTree select')) {
      if (sel.value === '') continue;
      const w = sel.dataset.weights ? JSON.parse(sel.dataset.weights) : null;
      if (!w) continue;
      const cost = w.reduce((a, b) => a + b, 0) / (w[+sel.value] || 1);
      if (cost > worstCost) { worst = sel; worstCost = cost; }
    }
    if (!worst) break;
    dropped.push(worst.previousElementSibling?.textContent?.trim() || 'a group');
    worst.value = '';
    worst.dispatchEvent(new Event('change'));
  }
  return dropped;
}
function showEdit() {
  $('#dEdit').innerHTML = S.edit ? `<div class="card edit">Editing <b>slot ${S.edit.slot}</b> (${esc(S.edit.name)}): its parts are filled in below,
    and "Into your save" now points at that ship. Change what you like, then search for a seed.
    <div class="row" style="margin-top:8px"><button class="btn" id="dLoosen">Make it searchable</button>
      <span class="muted">sets the fiddliest details back to "Any" -- every part you pin makes the search slower</span>
      <span style="flex:1"></span><button class="btn" id="dEditStop">Stop editing</button></div></div>` : '';
  if (!S.edit) return;
  $('#dEditStop').onclick = () => { S.edit = null; showEdit(); fillTargets(); };
  $('#dLoosen').onclick = () => {
    const dropped = loosen(2);
    toast(dropped.length ? `Set back to "Any": ${dropped.join(', ')}.` : 'This design is already quick to search.');
  };
}
function preselect(ids) {
  const want = new Set(ids);
  for (let i = 0; i < $$('#dTree select').length; i++) {
    const sel = $$('#dTree select')[i], k = JSON.parse(sel.dataset.ids).findIndex(x => want.has(x));
    if (k >= 0) { sel.value = String(k); sel.dispatchEvent(new Event('change')); }
  }
  preview(); updateOdds();
}
/* One in how many seeds has the picked parts. Options are weighted the way the game weighs them,
   so a rare option counts as rare rather than as "one in however many". */
function oddsOneIn() {
  let n = 1;
  for (const s of $$('#dTree select')) {
    if (s.value === '') continue;
    const w = s.dataset.weights ? JSON.parse(s.dataset.weights) : null;
    if (!w) { n *= JSON.parse(s.dataset.ids).length; continue; }
    const total = w.reduce((a, b) => a + b, 0), mine = w[+s.value];
    n *= mine > 0 ? total / mine : 1e9;
  }
  return n;
}
const humanTime = secs => !isFinite(secs) ? 'a very long time'
  : secs < 90 ? `${Math.max(1, Math.round(secs))} s`
  : secs < 5400 ? `${Math.round(secs / 60)} min`
  : secs < 172800 ? `${(secs / 3600).toFixed(1)} h` : `${Math.round(secs / 86400)} days`;
function updateOdds() {
  const n = oddsOneIn(), secs = n / 5e6;  // 5 M seeds/s until a search measures the real rate
  $('#dOdds').textContent = n > 1 ? `About 1 in ${Math.round(n).toLocaleString()} seeds has these parts: `
    + `roughly ${humanTime(secs)} per result.${secs > 1800 ? ' Set some details back to "Any" to speed it up.' : ''}` : '';
}
$('#fBox').ontoggle = () => { if ($('#fBox').open) guard(loadFind); };
/* native Save / Open dialogs in the app window; download / file picker in a browser */
async function saveTextFile(name, text) {
  if (window.pywebview && pywebview.api && pywebview.api.save_text) {
    const where = await pywebview.api.save_text(name, text);
    if (where) toast('Saved to ' + where);
    return where;
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], {type: 'application/json'})); a.download = name;
  document.body.append(a); a.click(); a.remove();
  return name;
}
async function openTextFile() {
  if (window.pywebview && pywebview.api && pywebview.api.open_text) return await pywebview.api.open_text();
  return new Promise(res => {
    const i = document.createElement('input'); i.type = 'file'; i.accept = '.json,application/json';
    i.onchange = async () => { const f = i.files[0]; res(f ? {name: f.name, text: await f.text()} : null); };
    i.click();
  });
}

function fillTargets() {
  const sel = $('#dTarget'); if (!sel) return;
  const ship = $('#dShip').value, empty = (S.empty || []).length;
  sel.innerHTML = `<option value="new" ${empty ? '' : 'disabled'}>A new ship (first empty slot${empty ? '' : ' -- none free'})</option>`
    + (S.ships || []).map(s => `<option value="${s.index}">Replace slot ${s.index}: ${esc(s.name || '(unnamed)')} (${esc(s.category)})${s.ship && s.ship !== ship ? ' -- changes its type' : ''}</option>`).join('');
  if (S.edit) sel.value = String(S.edit.slot);                  // editing a ship: put it back where it came from
  else if (!empty && S.ships && S.ships.length) sel.value = String(S.slot ?? S.ships[0].index);
}
async function installDesign() {
  const want = wanted(); if (!want.length) throw new Error('Pick some parts or load a design first.');
  if (!S.path) throw new Error('No save selected.');
  const target = $('#dTarget').value, ship = $('#dShip').value;
  const label = target === 'new' ? 'a new ship slot' : $('#dTarget').selectedOptions[0].textContent.replace(/^Replace /, '');
  const saved = (S.designs || []).find(x => x.id === $('#dSaved').value && x.ship === ship);
  const seeds = [...new Set([...$$('#dResults code')].map(c => c.textContent).concat(saved ? saved.seeds : []))];
  if (!confirm(`Put this ${ship} design (${want.length} parts) into ${label}?\n\nA backup of your save is made first. `
      + (seeds.length ? 'A known seed is used if it still matches.' : 'No known seed yet, so it searches for one first.'))) return;
  const name = saved ? saved.name : 'Custom design';
  const r = await post('/api/designs/install', {path: S.path, slot: target, seconds: searchSeconds(),
                                                design: {name, ship, want, found_seeds: seeds}});
  S.installJob = r.job; $('#dInstall').disabled = true; $('#dInstallStop').hidden = false;
  const phases = {checking: 'Checking known seeds...', searching: 'Searching for a matching seed...', writing: 'Writing to your save...'};
  while (true) {
    await new Promise(res => setTimeout(res, 700));
    const j = await api('/api/jobs/' + S.installJob);
    $('#dInstallStatus').textContent = j.status === 'running'
      ? `${phases[j.phase] || 'Working...'}${j.tested ? ` ${Number(j.tested).toLocaleString()} seeds tested` : ''}`
        + (j.phase === 'searching' ? (x => x ? ' -- ' + x : '')(etaText(j, {oneIn: oddsOneIn(), want: 1})) : '') : '';
    if (j.status === 'running') continue;
    $('#dInstall').disabled = false; $('#dInstallStop').hidden = true;
    if (j.status === 'error') throw new Error(j.error);
    if (j.status === 'cancelled') { toast('Stopped. Nothing was changed.'); return; }
    showBanner(`Saved: ${j.result.what} is now this ${ship} design (${j.result.seed}) in ${j.result.file}. Backup made. Load this save in the game to see it.`, false);
    $('#dInstallStatus').textContent = `Last put in: ${j.result.what} (${j.result.seed})`;
    await loadShips(); fillTargets();
    return;
  }
}

async function loadDesigns(sel) {
  S.designs = await api('/api/designs');
  $('#dSaved').innerHTML = S.designs.length
    ? S.designs.map(d => `<option value="${esc(d.id)}">${esc(d.name)} (${esc(d.ship)})${d.mine ? ' *' : ''}</option>`).join('')
    : '<option value="">No saved designs yet</option>';
  if (sel) $('#dSaved').value = sel;
  designNote();
}
function designNote() {
  const d = (S.designs || []).find(x => x.id === $('#dSaved').value);
  $('#dDelete').hidden = !(d && d.mine);
  $('#dDesignNote').textContent = d ? `${d.want.length} parts${d.seeds.length ? `, ${d.seeds.length} known seeds` : ''}` : '';
}
async function loadDesign() {
  const d = (S.designs || []).find(x => x.id === $('#dSaved').value);
  if (!d) throw new Error('No saved design selected.');
  $('#dShip').value = d.ship;
  await loadTree();
  preselect(d.want);
  const seeds = d.seeds || [];
  $('#dResults').innerHTML = (d.notes ? `<p class="muted" style="grid-column:1/-1;margin:0 0 6px">${esc(d.notes)}</p>` : '')
    + (seeds.length ? seeds.map(seed => shipCard(d.ship, seed, d.name, 'known seed')).join('')
       : '<p class="muted">No known seeds saved with this design -- press "Find seeds".</p>');
  wireApply($('#dResults'), d.ship);
  toast(`${d.name}: ${d.want.length} parts filled in${seeds.length ? `, ${seeds.length} known seeds listed below` : ''}.`);
}
function wireApply(box, ship) {
  box.querySelectorAll('[data-seed]').forEach(b => b.onclick = () => applySeed(b.dataset.seed, b.dataset.ship || ship));
}

async function initDesigner() {
  S.models = await api('/api/models');
  const types = await api('/api/design/types');
  $('#dShip').innerHTML = types.map(t => `<option value="${t.ship}">${esc(t.label)}</option>`).join('');
  $('#dShip').value = 'sentinel';
  S.lookOpts = await api('/api/look/options');
  $('#dShip').onchange = () => guard(loadTree); $('#dReset').onclick = () => guard(loadTree);
  await loadDesigns();
  $('#dSaved').onchange = designNote;
  fillTargets();
  $('#dInstall').onclick = () => guard(installDesign).finally(() => { $('#dInstall').disabled = false; $('#dInstallStop').hidden = true; });
  $('#dInstallStop').onclick = () => guard(async () => { if (S.installJob) await post(`/api/jobs/${S.installJob}/cancel`, {}); });
  $('#dExport').onclick = () => guard(async () => {
    const d = (S.designs || []).find(x => x.id === $('#dSaved').value);
    let file;
    if (d && $('#dShip').value === d.ship && wanted().join() === [...d.want].filter(p => wanted().includes(p)).join()) {
      file = await api(`/api/designs/${encodeURIComponent(d.id)}/file`);
    } else {  // the current, unsaved selection
      const want = wanted(); if (!want.length) throw new Error('Pick some parts or load a design first.');
      const name = prompt('Name for this design file:', 'My design'); if (!name) return;
      const seeds = [...$$('#dResults code')].map(c => c.textContent).slice(0, 12);
      file = {filename: name.toLowerCase().replace(/[^a-z0-9]+/g, '_') + '.nmsdesign.json',
              text: JSON.stringify({name, ship: $('#dShip').value, want, avoid: [], found_seeds: seeds, made_with: 'NMS Shipwright'}, null, 1)};
    }
    await saveTextFile(file.filename, file.text);
  });
  $('#dImport').onclick = () => guard(async () => {
    const f = await openTextFile(); if (!f) return;
    const r = await post('/api/designs/import', {text: f.text});
    S.designs = r.designs; await loadDesigns(r.id); await loadDesign();
    toast(`Opened "${r.name}" and added it to your saved designs.`);
  });
  $('#dLoad').onclick = () => guard(loadDesign);
  $('#dSave').onclick = () => guard(async () => {
    const want = wanted(); if (!want.length) throw new Error('Pick some parts first.');
    const name = prompt('Name for this design:'); if (!name) return;
    const seeds = [...$$('#dResults code')].map(c => c.textContent).slice(0, 12);
    const r = await post('/api/designs', {name, ship: $('#dShip').value, want, seeds});
    S.designs = r.designs; await loadDesigns(r.id); toast(`Saved "${name}".`);
  });
  $('#dDelete').onclick = () => guard(async () => {
    const d = (S.designs || []).find(x => x.id === $('#dSaved').value);
    if (!d || !d.mine || !confirm(`Delete the saved design "${d.name}"?`)) return;
    const r = await api('/api/designs/' + encodeURIComponent(d.id), {method: 'DELETE'});
    S.designs = r.designs; await loadDesigns(); toast('Deleted.');
  });
  await loadTree();
}
async function loadTree() {
  setTimeout(fillTargets, 0);
  const tree = await api('/api/design/tree?ship=' + $('#dShip').value);
  $('#dTree').innerHTML = ''; renderGroups(tree, $('#dTree')); preview(); updateOdds();
  S.look = {primary: [], secondary: [], undercoat: [], mode: []}; S.lookOpen = null; renderLookPicker();
}
const LOOK_ROWS = [['primary', 'Main colour', 'paint'], ['secondary', 'Second colour', 'paint'], ['undercoat', 'Undercoat', 'undercoat']];
const cap = m => m ? m[0] + m.slice(1).toLowerCase() : '';
function renderLookPicker() {
  const box = $('#dLook'), o = S.lookOpts;
  if (o.no_seed_look.includes($('#dShip').value)) {
    box.innerHTML = '<b>Colours</b><p class="muted" style="margin:6px 0 0">Sentinel colours come from their parts and your paint, not the seed. Use Recolour on the My Ships page.</p>';
    return;
  }
  const palOf = k => LOOK_ROWS.find(r => r[0] === k)[2];
  const chips = k => S.look[k].length
    ? S.look[k].map(i => `<span class="sw" title="colour ${i}" style="background:${o[palOf(k)][i]}"></span>`).join('')
    : '<span class="muted">Any</span>';
  box.innerHTML = '<b>Colours &amp; finish</b> <span class="muted">(set by the seed; click colours to allow them, again to remove)</span>' +
    LOOK_ROWS.map(([k, label, pal]) => `<div class="lookrow"><label class="muted">${label}</label><div>
      <div class="lookpick">${chips(k)}<button class="btn" data-open="${k}" style="padding:3px 9px">${S.lookOpen === k ? 'Done' : 'Choose'}</button>
        ${S.look[k].length ? `<button class="btn" data-clear="${k}" style="padding:3px 9px">Any</button>` : ''}</div>
      ${S.lookOpen === k ? `<div class="lookgrid">${o[pal].map((c, i) => `<i data-k="${k}" data-i="${i}" class="${S.look[k].includes(i) ? 'on' : ''}" title="colour ${i}" style="background:${c}"></i>`).join('')}</div>` : ''}
    </div></div>`).join('') +
    `<div class="lookrow"><label class="muted">Hull finish</label><div class="lookpick">${o.modes.map(m =>
      `<label><input type="checkbox" data-mode="${m}" ${S.look.mode.includes(m) ? 'checked' : ''}> ${cap(m)}</label>`).join('')}
      <span class="muted">(none ticked = any)</span></div></div>`;
  box.querySelectorAll('[data-open]').forEach(b => b.onclick = () => { S.lookOpen = S.lookOpen === b.dataset.open ? null : b.dataset.open; renderLookPicker(); });
  box.querySelectorAll('[data-clear]').forEach(b => b.onclick = () => { S.look[b.dataset.clear] = []; renderLookPicker(); });
  box.querySelectorAll('.lookgrid i').forEach(el => el.onclick = () => {
    const list = S.look[el.dataset.k], i = +el.dataset.i, at = list.indexOf(i);
    if (at >= 0) list.splice(at, 1); else list.push(i);
    renderLookPicker();
  });
  box.querySelectorAll('[data-mode]').forEach(cb => cb.onchange = () => {
    S.look.mode = [...box.querySelectorAll('[data-mode]:checked')].map(x => x.dataset.mode);
  });
}
const lookSet = () => S.look && ['primary', 'secondary', 'undercoat', 'mode'].some(k => S.look[k].length);
function lookBadge(look) {
  if (!look || !S.lookOpts) return '';
  const o = S.lookOpts, sw = (pal, i) => `<span class="sw" title="colour ${i}" style="background:${o[pal][i]}"></span>`;
  return `<div class="row" style="gap:4px;margin-top:4px">${sw('paint', look.primary)}${sw('paint', look.secondary)}${sw('undercoat', look.undercoat)}
    <span class="muted" style="font-size:12px">${cap(look.mode)}</span></div>`;
}
function renderGroups(groups, box) {
  for (const g of groups) {
    const row = document.createElement('div'); row.className = 'grp';
    const label = document.createElement('label'); label.textContent = g.type.replace(/^_+|_+$/g, '').replace(/_/g, ' '); label.title = g.type;
    const sel = document.createElement('select');
    sel.innerHTML = '<option value="">Any</option>' + g.options.map((o, i) => `<option value="${i}">${esc(o.name ? `${o.name}  (${o.id})` : o.id)}</option>`).join('');
    sel.dataset.ids = JSON.stringify(g.options.map(o => o.id));
    sel.dataset.weights = JSON.stringify(g.options.map(o => o.weight == null ? 20 : o.weight));
    for (const o of g.options) S.optLabel[o.id] = o.name || o.id;
    const kids = document.createElement('div'); kids.className = 'kids';
    sel.onchange = () => { kids.innerHTML = ''; const o = g.options[sel.value]; if (o && o.children.length) renderGroups(o.children, kids); preview(); updateOdds(); };
    row.append(label, sel); box.append(row, kids);
  }
}
const wanted = () => $$('#dTree select').filter(s => s.value !== '').map(s => JSON.parse(s.dataset.ids)[+s.value]);
let previewTimer;
function preview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const parts = wanted(), box = $('#dPreview');
    if (!parts.length) { VIEWERS.dPreview?.destroy(); delete VIEWERS.dPreview; box.classList.remove('v3d'); box.innerHTML = '<span class="muted">Clean slate. Pick a part and it appears here, piece by piece.</span>'; return; }
    const url = modelUrl($('#dShip').value, 'parts=' + encodeURIComponent(parts.join(',')));
    if (VIEWERS.dPreview) VIEWERS.dPreview.load(url).catch(e => toast(e.message, true));
    else show3d('dPreview', url);
  }, 150);
}
$('#dGo').onclick = () => guard(async () => {
  const want = wanted(); if (!want.length && !lookSet()) throw new Error('Pick at least one part or colour first.');
  const r = await post('/api/design/search', {ship: $('#dShip').value, want, n: +$('#dN').value, seconds: searchSeconds(), look: S.look});
  S.job = {id: r.job, ship: $('#dShip').value, want: +$('#dN').value, oneIn: oddsOneIn()}; $('#dResults').innerHTML = '';
  $('#dGo').disabled = $('#dFind').disabled = true; $('#dStop').disabled = false; pollJob();
});
$('#dStop').onclick = () => S.job && post(`/api/jobs/${S.job.id}/cancel`, {});
$('#dLimit').onchange = () => { $('#dSecs').disabled = !$('#dLimit').checked; };
/* Seconds to allow, or null for "until I press Stop". */
const searchSeconds = () => $('#dLimit').checked ? Math.max(60, (+$('#dSecs').value || 10) * 60) : null;

/* How long the rest of the search should take, from the odds and the speed it is really running at. */
function etaText(j, job) {
  const tested = Number(j.tested) || 0, secs = Number(j.seconds) || 0;
  if (!job.oneIn || job.oneIn <= 1 || secs < 2 || !tested) return '';
  const rate = tested / secs, left = Math.max(0, (job.want || 1) - j.results.length);
  if (!left) return '';
  // Seeds are independent, so what has been tested already does not bring the next result closer.
  return `${(rate / 1e6).toFixed(1)} M seeds/s, about ${humanTime(job.oneIn / rate)} per result`
    + (left > 1 ? `, ${humanTime(left * job.oneIn / rate)} for all ${left} left` : '');
}
async function pollJob() {
  const job = S.job, j = await api('/api/jobs/' + job.id);
  const eta = j.status === 'running' ? etaText(j, job) : '';
  $('#dStatus').textContent = `${j.status}: tested ${Number(j.tested).toLocaleString()} seeds in ${Number(j.seconds).toFixed(0)}s, `
    + `found ${j.results.length}${eta ? ' -- ' + eta : ''}${j.error ? ' -- ' + j.error : ''}`;
  const box = $('#dResults');
  for (let i = box.children.length; i < j.results.length; i++) {
    const res = j.results[i], d = document.createElement('div'); d.className = 'card res';
    d.innerHTML = `${lookBadge(res.look)}
      <div class="row" style="margin-top:6px;justify-content:space-between"><code>${res.seed}</code><button class="btn">Put in my save...</button></div>`;
    d.querySelector('button').onclick = () => applySeed(res.seed, job.ship); box.append(d);
  }
  if (j.status === 'running') setTimeout(() => guard(pollJob), 800);
  else { $('#dGo').disabled = $('#dFind').disabled = false; $('#dStop').disabled = true; }
}
