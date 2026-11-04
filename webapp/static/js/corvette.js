/* The Corvette page: the modules a save has bolted to the ship, and the ship they add up to.

   Where a module sits is a plain transform in the save -- the build menu's grid and snapping
   never reach the file -- so the list shows each one exactly as written, grouped by part so a
   ship with six of the same hab reads as six, not as six rows to scroll past. */
/* The save holds these to the last bit the format allows; two places is enough to read. */
const cvPos = p => p.map(n => (Math.round(n * 100) / 100 || 0)).join(', ');
const cvMark = m => (m.turned ? 'turned' : !m.scenes.length && !m.hull ? 'blank' : '');
const cvWhy = m => m.turned ? 'Facing ' + cvPos(m.at) + ' -- at an angle the build menu has no rotation for'
  : m.hull ? 'The base this corvette is built on. It anchors the modules and has nothing of its own to draw.'
  : m.scenes.length ? m.scenes.join(' + ') : 'Nothing in the game files draws this module';

async function loadCorvette() {
  if (!S.path) return;
  $('#cvList').innerHTML = '<p class="muted" style="padding:8px">Reading the save...</p>';
  $('#cvFoot').hidden = $('#cvTurned').hidden = true;
  $('#cvCount').textContent = '';
  S.corvettes = await api('/api/corvettes?path=' + encodeURIComponent(S.path));
  const pick = $('#cvPick');
  pick.hidden = S.corvettes.length < 2;
  pick.innerHTML = S.corvettes.map(c => `<option value="${c.index}">${esc(c.name || 'Corvette ' + (c.index + 1))}</option>`).join('');
  pick.onchange = () => showCorvette(+pick.value);
  if (!S.corvettes.length) {
    $('#cvList').innerHTML = '<p class="muted" style="padding:8px">No corvette in this save.</p>';
    $('#cvView').innerHTML = '<span class="muted">Build a corvette in game and it will show up here.</span>';
    return;
  }
  showCorvette(S.corvettes[0].index);
}

function showCorvette(index) {
  const c = S.corvettes.find(x => x.index === index);
  if (!c) return;
  const turned = c.modules.filter(m => m.turned).length;
  const blank = c.modules.filter(m => !m.scenes.length && !m.hull).length;
  $('#cvCount').textContent = `${c.modules.length} module${c.modules.length === 1 ? '' : 's'}`;
  $('#cvTurned').hidden = !turned;
  $('#cvTurned').textContent = `${turned} at an angle`;

  const groups = new Map();
  for (const m of c.modules) {
    if (!groups.has(m.id)) groups.set(m.id, []);
    groups.get(m.id).push(m);
  }
  $('#cvList').innerHTML = [...groups.values()].map(g => {
    const m = g[0];
    return `<div class="cvgroup"><div class="cvhead"><b>${esc(m.name)}</b>
        ${m.hull ? '' : `<code>${esc(m.id)}</code>`}${g.length > 1 ? `<span class="count">${g.length}</span>` : ''}</div>
      <div class="cvat">${g.map(x => `<i class="${cvMark(x)}" title="${esc(cvWhy(x))}"
        >${esc(cvPos(x.position))}</i>`).join('')}</div></div>`;
  }).join('');

  const notes = [];
  if (turned) notes.push('An orange position sits at an angle no build-menu rotation would reach.');
  if (blank) notes.push(`${blank} module${blank === 1 ? ' has' : 's have'} no model to draw and ${blank === 1 ? 'is' : 'are'} left out of the view.`);
  $('#cvFoot').hidden = !notes.length;
  $('#cvFoot').innerHTML = notes.map(esc).join('<br>');

  $('#cvBuild').onclick = () => openBuilder(index);
  show3d('cvView', `/api/corvette/model?path=${encodeURIComponent(S.path)}&index=${index}`,
         '<span class="muted">Could not draw this corvette.</span>');
}

/* The builder wants the room, so it gets a window of its own where the app can give it one. */
function openBuilder(index) {
  const url = `/builder?path=${encodeURIComponent(S.path)}&index=${index}`;
  if (window.pywebview && pywebview.api && pywebview.api.open_window) {
    guard(() => pywebview.api.open_window(location.origin + url, 'Corvette Builder'));
    return;
  }
  if (!window.open(url, 'corvette-builder')) location.href = url;
}
