/* The inventory grid and its slots. */
const INV = {list: [], cur: null, data: null, sel: null};
async function loadInventories() {
  if (!S.path) return;
  INV.list = await api('/api/inventories?path=' + encodeURIComponent(S.path));
  let html = '', group = '';
  for (const i of INV.list) {
    if (i.group !== group) { group = i.group; html += `<h4>${esc(group)}</h4>`; }
    html += `<button data-inv="${esc(i.path)}"><span>${esc(i.name)}</span><span class="muted">${i.used}/${i.slots}</span></button>`;
  }
  $('#iList').innerHTML = html || '<p class="muted">No inventories found.</p>';
  $$('#iList button').forEach(b => b.onclick = () => guard(() => openInventory(b.dataset.inv)));
  if (!INV.list.some(i => i.path === INV.cur)) INV.cur = INV.list[0]?.path;
  if (INV.cur) await openInventory(INV.cur);
}
async function openInventory(path, data) {
  INV.cur = path; INV.sel = null;
  INV.data = data || await api(`/api/inventory?path=${encodeURIComponent(S.path)}&inv=${encodeURIComponent(path)}`);
  $$('#iList button').forEach(b => b.classList.toggle('sel', b.dataset.inv === path));
  const meta = INV.list.find(i => i.path === path) || {};
  $('#iTitle').textContent = meta.name || path;
  const cap = INV.data.max_slots;
  $('#iInfo').textContent = ` · ${INV.data.valid.length} slots · class ${INV.data.class || '?'}`
    + (cap ? ` · the game allows up to ${cap} here` : '');
  $('#iSlots').value = INV.data.valid.length;
  $('#iSlots').max = cap || 120;
  drawGrid(); $('#iSlot').innerHTML = '<span class="muted">Click a slot to change it.</span>';
}
function drawGrid() {
  const d = INV.data, valid = new Set(d.valid.map(v => v.join(','))), at = {};
  d.slots.forEach(s => at[s.x + ',' + s.y] = s);
  const w = d.width || 10, h = d.height || 1;
  $('#iGrid').style.gridTemplateColumns = `repeat(${w}, minmax(0, 1fr))`;
  let html = '';
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const k = x + ',' + y, s = at[k], ok = valid.has(k);
    html += `<div class="cell ${ok ? '' : 'locked'} ${s ? s.type : ''} ${s && s.damaged ? 'dmg' : ''} ${INV.sel === k ? 'sel' : ''}" data-k="${k}" title="${s ? esc(s.name + ' (' + s.id + ')') : ''}">
      ${s ? `<b>${esc(s.name)}</b><small>${s.type === 'Technology' ? (s.max > 1 ? Math.round(100 * s.amount / s.max) + '%' : '') : s.amount + '/' + s.max}</small>` : ''}</div>`;
  }
  $('#iGrid').innerHTML = html;
  $$('#iGrid .cell').forEach(c => c.onclick = () => { INV.sel = c.dataset.k; drawGrid(); slotEditor(at[c.dataset.k]); });
}
async function invEdit(op, extra = {}) {
  const r = await post('/api/inventory', {path: S.path, inv: INV.cur, op, ...extra});
  const keep = INV.sel; await openInventory(INV.cur, r); INV.sel = keep; drawGrid();
  const li = INV.list.find(i => i.path === INV.cur); if (li) { li.used = r.slots.length; li.slots = r.valid.length; }
  return r;
}
function slotEditor(s) {
  const [x, y] = INV.sel.split(',').map(Number);
  const locked = !INV.data.valid.some(v => v[0] === x && v[1] === y);
  $('#iSlot').innerHTML = `
    ${locked ? `<div class="row"><b>This slot is not part of the inventory</b>
      <button class="btn primary" id="sUnlock">Add this slot</button></div>` : ''}
    ${s ? `<div class="row"><b>${esc(s.name)}</b><span class="muted mono">${esc(s.id)}</span><span class="badge">${esc(s.type)}</span>${s.damaged ? '<span class="badge hot">DAMAGED</span>' : ''}</div>
      <div class="row" style="margin-top:8px"><label class="muted">${s.type === 'Technology' ? 'Charge' : 'Amount'}</label>
        <input id="sAmt" type="number" min="0" value="${s.amount}" style="width:110px"><span class="muted">max ${s.max}</span>
        <button class="btn primary" id="sAmtGo">Set</button><button class="btn" id="sMax">Max</button><button class="btn" id="sDel">Empty slot</button></div>`
      : (locked ? '' : `<div class="row"><span class="muted">Empty slot.</span>
        <button class="btn" id="sLock">Remove this slot</button></div>`)}
    <div class="row" style="margin-top:12px" ${locked ? 'hidden' : ''}><label class="muted">${s ? 'Replace with' : 'Add'}</label>
      <input id="sQ" placeholder="Search items, e.g. carbon, hyperdrive..." style="min-width:280px">
      <select id="sType"><option value="">All</option><option>Substance</option><option>Product</option><option>Technology</option></select></div>
    <div class="results" id="sRes" style="margin-top:8px"></div>`;
  if (s) {
    $('#sAmtGo').onclick = () => guard(async () => { await invEdit('amount', {x, y, amount: +$('#sAmt').value}); toast('Amount set. Backup made.'); slotEditor(INV.data.slots.find(q => q.x === x && q.y === y)); });
    $('#sMax').onclick = () => { $('#sAmt').value = s.max; $('#sAmtGo').click(); };
    $('#sDel').onclick = () => guard(async () => { await invEdit('remove', {x, y}); toast('Slot emptied. Backup made.'); slotEditor(null); });
  }
  if ($('#sUnlock')) $('#sUnlock').onclick = () => guard(async () => {
    await invEdit('unlock', {x, y}); toast('Slot added. Backup made.'); slotEditor(null);
  });
  if ($('#sLock')) $('#sLock').onclick = () => guard(async () => {
    await invEdit('lock', {x, y}); toast('Slot removed. Backup made.'); slotEditor(null);
  });
  let t = null;
  const find = () => { clearTimeout(t); t = setTimeout(() => guard(async () => {
    const q = $('#sQ').value.trim(); if (!q) { $('#sRes').innerHTML = ''; return; }
    const rows = await api(`/api/items?q=${encodeURIComponent(q)}&type=${encodeURIComponent($('#sType').value)}`);
    $('#sRes').innerHTML = rows.map(r => `<button class="btn chip" data-id="${esc(r.id)}" title="${esc(r.id)}">${esc(r.name)} <span class="muted">${esc(r.type)}</span></button>`).join(' ') || '<span class="muted">Nothing found.</span>';
    $$('#sRes button').forEach(b => b.onclick = () => guard(async () => {
      await invEdit('set', {x, y, id: b.dataset.id}); toast(`${b.textContent.trim()} added. Backup made.`);
      slotEditor(INV.data.slots.find(q => q.x === x && q.y === y));
    }));
  }), 200); };
  $('#sQ').oninput = find; $('#sType').onchange = find;
}
$('#iSetSlots').onclick = () => guard(async () => {
  const n = +$('#iSlots').value;
  const now = INV.data.valid.length;
  if (n === now) return;
  if (n < now && !confirm(`Take ${now - n} slot(s) away from this inventory? Anything in them must be moved out first.`)) return;
  await invEdit('slots', {count: n});
  toast(`This inventory now has ${INV.data.valid.length} slots. Backup made.`);
});
$$('#page-inventory [data-op]').forEach(b => b.onclick = () => guard(async () => {
  if (!INV.cur) return;
  await invEdit(b.dataset.op); toast(`${b.textContent} done. Backup made.`);
}));
