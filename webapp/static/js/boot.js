/* Start-up: load the save, the ships and the designer, then keep an eye on the game. */
(async () => {
  if (!(window.pywebview && pywebview.api && pywebview.api.pick_folder)) throw new Error('Type the folder into the box, then press "Use this folder".');
  const folder = await pywebview.api.pick_folder($('#hDir').value || '');
  if (folder) { $('#hDir').value = folder; await useGameFolder(folder); }
});
$('#hDirSave').onclick = () => guard(() => useGameFolder($('#hDir').value.trim()));
$('#hCheck').onclick = () => guard(async () => { toast('Checking everything, this takes a few seconds...'); await loadHealth(true); toast('Check finished.'); });
$('#hRefresh').onclick = () => guard(refreshGameData);

function setupExport() {
  if (!S.path) return;
  $('#xExport').removeAttribute('href');
  $('#xExport').onclick = e => { e.preventDefault(); guard(async () => {
    const r = await fetch('/api/save/export?path=' + encodeURIComponent(S.path));
    if (!r.ok) throw new Error('Could not read the save.');
    const name = shortPath(S.path).split('/').pop().replace(/\.hg$/, '') + '.json';
    await saveTextFile(name, await r.text());
  }); };
  $('#xImport').onchange = e => guard(async () => {
    const f = e.target.files[0]; e.target.value = ''; if (!f) return;
    if (!confirm(`Replace this save with ${f.name}? A backup of the current save is made first.`)) return;
    await post('/api/save/import', {path: S.path, json: await f.text()}); toast('Save imported. Backup made.'); await loadShips();
  });
}
async function rawOpen(at) {
  const d = await api(`/api/raw?path=${encodeURIComponent(S.path)}&at=${encodeURIComponent(at)}`);
  const parts = at ? at.split('.') : [];
  $('#rPath').innerHTML = ['<a href="#" data-at="">save</a>', ...parts.map((p, i) => `<a href="#" data-at="${esc(parts.slice(0, i + 1).join('.'))}">${esc(p)}</a>`)].join(' / ');
  $$('#rPath a').forEach(a => a.onclick = e => { e.preventDefault(); guard(() => rawOpen(a.dataset.at)); });
  if (d.leaf) {
    $('#rEdit').innerHTML = `<input id="rVal" class="mono" value="${esc(d.value)}" style="min-width:360px"><button class="btn primary" id="rSave">Save value</button>`;
    $('#rSave').onclick = () => guard(async () => { await post('/api/raw', {path: S.path, at, value: $('#rVal').value}); toast('Value saved. Backup made.'); });
    return;
  }
  $('#rEdit').innerHTML = d.more ? `<span class="muted">${d.more} more not shown</span>` : '';
  $('#rList').innerHTML = d.children.map(c => `<div data-k="${esc(c.key)}"><span class="k">${esc(c.key)}</span><span class="v">${esc(c.preview)}</span></div>`).join('');
  $$('#rList div').forEach(el => el.onclick = () => guard(() => rawOpen(at ? at + '.' + el.dataset.k : el.dataset.k)));
}
$('#rawBox').ontoggle = () => { if ($('#rawBox').open && S.path) guard(() => rawOpen('')); };

async function loadQuests() {
  if (!S.path) return;
  $('#qList').innerHTML = '<p class="muted">Reading quests...</p>';
  S.quests = await api('/api/quests?path=' + encodeURIComponent(S.path));
  renderQuests();
}
function questState(r) {
  if (r.status === 'done') return '<span class="badge ok">Finished</span>';
  if (r.status === 'not_started') return '<span class="muted">Not started</span>';
  if (r.final == null) return `<span class="muted">In progress (stage ${r.progress})</span>`;
  return `<progress max="${r.final}" value="${r.progress}"></progress><span class="muted">stage ${r.progress} of ${r.final}</span>`;
}
function renderQuests() {
  const text = $('#qFilter').value.trim().toLowerCase(), show = $('#qShow').value, helpers = $('#qHelpers').checked;
  const groups = new Map();
  for (const r of S.quests || []) {
    if (!helpers && !r.named) continue;
    if (!groups.has(r.group)) groups.set(r.group, []);
    groups.get(r.group).push(r);
  }
  const has = (g, st) => g.some(r => r.status === st || (st === 'in_progress' && r.status === 'unknown'));
  const list = [...groups.values()].filter(g => (show === 'all' || has(g, show)) &&
      (!text || g.some(r => (r.title + ' ' + r.id).toLowerCase().includes(text))))
    .sort((a, b) => (b.some(r => r.current) - a.some(r => r.current)) || (has(b, 'in_progress') - has(a, 'in_progress')) ||
      a[0].title.localeCompare(b[0].title));
  $('#qCount').textContent = `${list.length} quest${list.length === 1 ? '' : 's'}`;
  S.qGroups = list;
  $('#qList').innerHTML = list.length ? list.map((g, gi) => {
    const open = g.filter(r => r.status !== 'done'), done = g.length - open.length;
    const badges = (g.some(r => r.current) ? '<span class="badge hot">Tracked</span>' : '') +
      (g.some(r => r.critical) ? '<span class="badge">Main story</span>' : '') +
      (g.every(r => r.recurring) ? '<span class="badge">Repeatable</span>' : '') +
      (g.length > 1 ? `<span class="badge">${done} of ${g.length} steps finished</span>` : '');
    const head = open.length > 1 ? `<button class="btn primary" data-g="${gi}">Skip whole storyline (${open.length} steps)</button>` : '';
    return `<div class="card qgroup"><div class="qhead"><b>${esc(g[0].title)}</b>${badges}${head}</div>` +
      g.map((r, ri) => `<div class="qrow ${r.status === 'done' ? 'done' : ''}"><code title="Quest id">${esc(r.id)}${r.seed ? ' #' + esc(r.seed) : ''}</code>
        <div class="qstate">${questState(r)}</div>
        <div>${r.status === 'done' ? '' : `<button class="btn" data-g="${gi}" data-r="${ri}">Skip</button>`}</div></div>`).join('') + '</div>';
  }).join('') : '<p class="muted">No quests match.</p>';
  $$('#qList button').forEach(b => b.onclick = () => {
    const g = S.qGroups[+b.dataset.g];
    const rows = b.dataset.r != null ? [g[+b.dataset.r]] : g.filter(r => r.status !== 'done');
    guard(() => skipQuests(rows, b.dataset.r != null ? `"${g[0].title}" (${rows[0].id})` : `the rest of "${g[0].title}"`));
  });
}
async function skipQuests(rows, label) {
  const n = rows.length;
  if (!confirm(`Skip ${label}?

${n} quest step${n === 1 ? '' : 's'} will be marked finished in your save. ` +
      "You won't get the rewards or unlocks from the skipped steps. A backup is made first.")) return;
  const r = await post('/api/quests/skip', {path: S.path, keys: rows.map(x => x.key)});
  toast(r.changed.length ? `Skipped ${r.changed.length} quest step${r.changed.length === 1 ? '' : 's'}. Backup made.` : 'Those steps were already finished.');
  await loadQuests();
}
$('#qFilter').oninput = renderQuests;
$('#qShow').onchange = renderQuests;
$('#qHelpers').onchange = renderQuests;

async function loadBackups() {
  if (!S.path) return;
  const list = await api('/api/backups?path=' + encodeURIComponent(S.path));
  $('#bRows').innerHTML = list.length ? list.map((b, i) => `<tr><td><code>${esc(b.file.split(/[\\/]/).pop())}</code></td><td>${esc(b.made)}</td>
    <td>${(b.size / 1024).toFixed(0)} KB</td><td><button class="btn" data-i="${i}">Restore</button></td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">No backups for this save yet.</td></tr>';
  $$('#bRows button').forEach(btn => btn.onclick = () => guard(async () => {
    if (!confirm('Restore this backup over the current save? The current file is backed up first.')) return;
    await post('/api/backups/restore', {path: S.path, file: list[+btn.dataset.i].file});
    toast('Backup restored.'); await loadShips(); await loadBackups();
  }));
}

(async () => {
  await guard(async () => {
    await loadStatus(); S.palettes = await api('/api/palettes');
    await loadSaves(); await loadShips(); await initDesigner();
  });
  loadHealth(false).catch(() => {});  // warns in the banner if a game update broke something
  setInterval(() => loadStatus().catch(() => {}), 5000);
})();
