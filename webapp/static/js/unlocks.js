/* Unlocks & Fleet: knowledge, rewards, multi-tools, frigates, companions. */
async function loadUnlocks() {
  if (!S.path) return;
  const d = await api('/api/extras?path=' + encodeURIComponent(S.path));
  const bar = ([a, b]) => `<progress max="${b}" value="${a}"></progress> <span class="muted">${a} / ${b}</span>`;
  $('#uKnow').innerHTML = `<div class="form" style="grid-template-columns:150px 1fr auto;align-items:center;row-gap:8px">
    ${Object.entries(d.knowledge.words).map(([race, v]) => `<label>${esc(race)} words</label><div>${bar(v)}</div>
      <button class="btn" data-words="${esc(race)}" ${v[0] >= v[1] ? 'disabled' : ''}>Learn all</button>`).join('')}
    ${d.knowledge.groups.map(g => `<label>${esc(g.label)}</label><div>${bar([g.known, g.total])}</div>
      <button class="btn" data-learn="${g.group}" ${g.known >= g.total ? 'disabled' : ''}>Learn all</button>`).join('')}</div>
    <div class="row" style="margin-top:10px"><button class="btn primary" data-words="*">Learn every alien word</button>
      <button class="btn primary" id="uEverything">Unlock everything</button></div>`;
  $('#uEverything').onclick = () => guard(async () => {
    if (!confirm('Learn every word, blueprint, recipe, base part and customisation part in this save?')) return;
    let n = 0;
    await post('/api/extras', {path: S.path, action: 'words'});
    for (const g of d.knowledge.groups) n += (await post('/api/extras', {path: S.path, action: g.group})).result || 0;
    toast(`Unlocked ${n} blueprints and recipes, plus every word. Backup made.`); await loadUnlocks();
  });
  const act = (body, msg) => guard(async () => { await post('/api/extras', {path: S.path, ...body}); toast(msg + ' Backup made.'); await loadUnlocks(); });
  $$('#uKnow [data-words]').forEach(b => b.onclick = () => act({action: 'words', races: b.dataset.words === '*' ? null : [b.dataset.words]}, 'Words learned.'));
  $$('#uKnow [data-learn]').forEach(b => b.onclick = () => act({action: b.dataset.learn}, 'Learned.'));
  await loadRewards();
  const cls = (v, id) => `<select id="${id}">${['C', 'B', 'A', 'S'].map(c => `<option ${c === v ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
  $('#uTools').innerHTML = d.multitools.map(m => `<div class="card"><div class="row"><b>${esc(m.name || m.model)}</b>${m.active ? '<span class="badge hot">EQUIPPED</span>' : ''}<span class="muted">${m.slots} slots</span></div>
    <div class="form" style="margin-top:8px"><label>Name</label><input id="mt_n${m.index}" value="${esc(m.name)}" placeholder="(unnamed)">
      <label>Seed</label><input id="mt_s${m.index}" class="mono" value="${esc(m.seed)}"><label>Class</label>${cls(m.class, 'mt_c' + m.index)}</div>
    <div class="row" style="margin-top:8px"><button class="btn primary" data-mt="${m.index}">Save</button><button class="btn" data-mtr="${m.index}">Random seed</button></div></div>`).join('') || '<p class="muted">No multi-tools.</p>';
  $$('[data-mt]').forEach(b => b.onclick = () => { const i = b.dataset.mt;
    act({action: 'multitool', index: +i, name: $('#mt_n' + i).value, seed: $('#mt_s' + i).value, class: $('#mt_c' + i).value}, 'Multi-tool saved.'); });
  $$('[data-mtr]').forEach(b => b.onclick = () => { $('#mt_s' + b.dataset.mtr).value = randomSeed(); });
  $('#uFrig').innerHTML = d.frigates.map(f => `<div class="card"><div class="row"><b>${esc(f.name || f.type + ' frigate')}</b><span class="badge">${esc(f.type)}</span>
      ${f.damaged ? '<span class="badge hot">DAMAGED</span>' : ''}<span class="muted">${f.expeditions} expeditions</span></div>
    <div class="form" style="margin-top:8px"><label>Name</label><input id="fr_n${f.index}" value="${esc(f.name)}" placeholder="(unnamed)"><label>Class</label>${cls(f.class, 'fr_c' + f.index)}
      ${Object.entries(f.stats).map(([k, v]) => `<label>${esc(k)}</label><input type="number" data-stat="${esc(k)}" data-fr="${f.index}" value="${v}" style="width:90px">`).join('')}</div>
    <div class="row" style="margin-top:8px"><button class="btn primary" data-fs="${f.index}">Save</button>${f.damaged ? `<button class="btn" data-fx="${f.index}">Repair</button>` : ''}</div></div>`).join('') || '<p class="muted">No frigates.</p>';
  $$('[data-fs]').forEach(b => b.onclick = () => { const i = b.dataset.fs, stats = {};
    $$(`[data-fr="${i}"]`).forEach(el => stats[el.dataset.stat] = +el.value);
    act({action: 'frigate', index: +i, name: $('#fr_n' + i).value, class: $('#fr_c' + i).value, stats}, 'Frigate saved.'); });
  $$('[data-fx]').forEach(b => b.onclick = () => act({action: 'frigate', index: +b.dataset.fx, repair: true}, 'Frigate repaired.'));
  $('#uPets').innerHTML = d.companions.map(p => `<div class="card"><div class="row"><b>${esc(p.name || p.creature)}</b><span class="muted">${esc(p.biome)}${p.predator ? ' · predator' : ''}</span></div>
    <div class="form" style="margin-top:8px"><label>Name</label><input id="pt_n${p.index}" value="${esc(p.name)}"><label>Size</label>
      <input id="pt_s${p.index}" type="number" step="0.05" min="0.1" max="10" value="${p.scale}" style="width:90px"></div>
    <div class="row" style="margin-top:8px"><button class="btn primary" data-pt="${p.index}">Save</button></div></div>`).join('') || '<p class="muted">No companions.</p>';
  $$('[data-pt]').forEach(b => b.onclick = () => { const i = b.dataset.pt;
    act({action: 'companion', index: +i, name: $('#pt_n' + i).value, scale: +$('#pt_s' + i).value}, 'Companion saved.'); });
}

const REW = {group: 'expedition'};
async function loadRewards() {
  const d = await api(`/api/rewards?path=${encodeURIComponent(S.path)}&group=${REW.group}&q=${encodeURIComponent($('#wQ')?.value || '')}`);
  $('#wGroups').innerHTML = d.groups.map(g => `<button class="btn ${g.group === REW.group ? 'primary' : ''}" data-g="${g.group}">${esc(g.label)}
      <span class="muted">${g.unlocked}/${g.total}</span></button>`).join('')
    + `<span style="flex:1"></span><button class="btn" id="wAll">Unlock all in this group</button><button class="btn" id="wAgain">Make all claimable again</button>`;
  $$('#wGroups [data-g]').forEach(b => b.onclick = () => { REW.group = b.dataset.g; guard(loadRewards); });
  const act = body => guard(async () => { const r = await post('/api/rewards', {path: S.path, group: REW.group, ...body});
    toast(`${r.changed} rewards updated. Backup made.`); await loadRewards(); });
  $('#wAll').onclick = () => act({unlock: true});
  $('#wAgain').onclick = () => act({redeemed: false});
  $('#wCount').textContent = `showing ${d.items.length} of ${d.shown}`;
  $('#wList').innerHTML = d.items.map(i => `<div class="rew ${i.unlocked ? 'on' : ''}"><span title="${esc(i.id)}">${esc(i.name)}</span>
      <button class="btn" data-id="${esc(i.id)}" data-u="${i.unlocked ? 0 : 1}">${i.unlocked ? 'Locked' : 'Unlock'}</button>
      ${i.redeemed ? `<button class="btn" data-id="${esc(i.id)}" data-r="0" title="Let the game give this reward again">Claim again</button>` : ''}</div>`).join('')
    || '<span class="muted">Nothing found.</span>';
  $$('#wList [data-u]').forEach(b => b.onclick = () => act({ids: [b.dataset.id], unlock: b.dataset.u === '1'}));
  $$('#wList [data-r]').forEach(b => b.onclick = () => act({ids: [b.dataset.id], redeemed: false}));
  let t = null; $('#wQ').oninput = () => { clearTimeout(t); t = setTimeout(() => guard(loadRewards), 250); };
}
