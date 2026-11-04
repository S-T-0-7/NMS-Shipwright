/* The corvette builder.

   The build menu in game decides what may go where; a save file does not, so this page lets a
   module stand anywhere, at any angle, bolted to nothing. The model on screen is the file: a
   module's position and its Up and At go straight into the save when you press Save.

   The hull is not in the list. It anchors the base and is carried over untouched. */
const $ = s => document.querySelector(s);
const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const qs = new URLSearchParams(location.search);

const B = {path: qs.get('path') || '', index: +(qs.get('index') || 0), scene: null, palette: [],
           names: {}, modules: [], undo: [], redo: [], snap: 3, dirty: false,
           snaps: new Map(), snapParts: true, snapped: null};

function toast(msg, bad) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'on' + (bad ? ' bad' : '');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.className = ''; }, bad ? 6000 : 2600);
}
async function api(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}
const round = v => Math.round(v * 1000) / 1000;
/* What a coordinate reads as in the panel. The stored value keeps every bit the save gave it --
   a module nobody has touched must go back exactly as it came. */
const shown = v => Math.round(v * 1000) / 1000 || 0;
const snapped = v => (B.snap ? Math.round(v / B.snap) * B.snap : round(v));
// Turning snaps to 15 degrees whenever position does, and runs free when position does.
const ANGLE_STEP = 15 * Math.PI / 180;
const snappedAngle = a => (B.snap ? Math.round(a / ANGLE_STEP) * ANGLE_STEP : a);

/* Turn a vector about one of the world axes -- the save keeps a module's Up and At, so turning
   one is turning both. */
function spin(v, axis, ang) {
  const c = Math.cos(ang), s = Math.sin(ang), u = [0, 0, 0];
  u[axis] = 1;
  const ux = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const d = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  return [round(v[0] * c + ux[0] * s + u[0] * d * (1 - c)),
          round(v[1] * c + ux[1] * s + u[1] * d * (1 - c)),
          round(v[2] * c + ux[2] * s + u[2] * d * (1 - c))];
}

/* ---- snapping to other parts ------------------------------------------------------------

   The game joins modules by laying one part's `X_In_` socket exactly onto another part's
   `X_Out_` socket of the same kind, frame for frame. Both sides come out of the placement
   scenes, so the builder can do the same thing: for every socket on the part being dragged,
   work out where the part would have to stand for that socket to meet a free one on the ship,
   and take whichever answer is nearest to where the pointer actually is. */

const SNAP_REACH = 6;        // how far a snap may pull a part from where the pointer put it
const SOCKET_REACH = 16;     // sockets further than this are not worth working an answer out for
const mat4 = {
  mul(a, b) {
    const o = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  },
  /* These are all rotation plus translation, so the inverse is the transpose and a moved origin. */
  invRigid(m) {
    const t = [m[12], m[13], m[14]], o = [m[0], m[4], m[8], 0, m[1], m[5], m[9], 0, m[2], m[6], m[10], 0, 0, 0, 0, 1];
    for (let r = 0; r < 3; r++) o[12 + r] = -(o[r] * t[0] + o[4 + r] * t[1] + o[8 + r] * t[2]);
    return o;
  },
  of(m) { return {position: [m[12], m[13], m[14]], up: [m[4], m[5], m[6]], at: [m[8], m[9], m[10]]}; },
};

/* Every socket on the ship that is not on `skip`, keyed by kind and direction. */
function shipSockets(skip) {
  const by = new Map();
  B.modules.forEach((m, i) => {
    if (i === skip) return;
    for (const s of B.snaps.get(m.id) || []) {
      const key = s.kind + '|' + s.io;
      if (!by.has(key)) by.set(key, []);
      by.get(key).push(mat4.mul(m.matrix, s.m));
    }
  });
  return by;
}

/* Where `m` would stand if one of its sockets met one on the ship.

   A join is scored by how far it would drag the part away from where the pointer put it, not by
   how near the socket is: a socket can sit close by and still fling the part to the far side of
   the module it belongs to. */
function snapTo(m, want, skip) {
  const mine = B.snaps.get(m.id);
  if (!B.snapParts || !mine || !mine.length) return null;
  const ship = shipSockets(skip);
  let best = null;
  for (const s of mine) {
    const targets = ship.get(s.kind + '|' + (s.io === 'in' ? 'out' : 'in'));
    if (!targets) continue;
    const inv = mat4.invRigid(s.m);
    for (const t of targets) {
      if (Math.hypot(t[12] - want[0], t[13] - want[1], t[14] - want[2]) > SOCKET_REACH) continue;
      const stood = mat4.mul(t, inv);
      const d = Math.hypot(stood[12] - want[0], stood[13] - want[1], stood[14] - want[2]);
      if (d > SNAP_REACH || (best && d >= best.d)) continue;
      best = {d, kind: s.kind, m: stood};
    }
  }
  return best ? {...mat4.of(best.m), kind: best.kind} : null;
}

/* Put a module where a drag asks, snapped onto the ship if anything is in reach. */
function dropAt(m, want, index) {
  const hit = snapTo(m, want, index);
  if (hit) {
    m.position = hit.position.map(round);
    m.up = hit.up.map(round);
    m.at = hit.at.map(round);
    B.snapped = hit.kind;
  } else {
    m.position = want.map(snapped);
    B.snapped = null;
  }
  setMatrix(m);
  showSnapHint();
}
function showSnapHint() {
  const el = $('#bHint');
  if (!el) return;
  el.classList.toggle('on', !!B.snapped);
  el.textContent = B.snapped ? 'Snapped: ' + B.snapped : el.dataset.idle;
}

/* ---- the model under the picture ------------------------------------------------------- */

function setMatrix(m) {
  m.matrix = B.scene.place(m.position, m.up, m.at);
  return m;
}
function mark() {
  B.undo.push(JSON.stringify(B.modules.map(m => ({id: m.id, ts: m.ts, position: m.position, up: m.up, at: m.at}))));
  if (B.undo.length > 80) B.undo.shift();
  B.redo.length = 0;
  B.dirty = true;
  refreshChrome();
}
function restore(json) {
  B.modules = JSON.parse(json).map(m => setMatrix(m));
  B.scene.items = B.modules;
  if (B.scene.selected >= B.modules.length) B.scene.selected = -1;
  drawInspector();
  refreshChrome();
}
function undo() {
  if (!B.undo.length) return;
  B.redo.push(JSON.stringify(B.modules.map(m => ({id: m.id, ts: m.ts, position: m.position, up: m.up, at: m.at}))));
  restore(B.undo.pop());
}
function redo() {
  if (!B.redo.length) return;
  B.undo.push(JSON.stringify(B.modules.map(m => ({id: m.id, ts: m.ts, position: m.position, up: m.up, at: m.at}))));
  restore(B.redo.pop());
}
function refreshChrome() {
  $('#bCount').textContent = `${B.modules.length} module${B.modules.length === 1 ? '' : 's'}` +
    (B.dirty ? ' · unsaved' : '');
  $('#bUndo').disabled = !B.undo.length;
  $('#bRedo').disabled = !B.redo.length;
}

/* Geometry is fetched once per part id and drawn again for every copy on the ship. */
const pending = new Map();
async function needPart(id) {
  if (B.scene.parts.has(id)) return true;
  if (!pending.has(id)) {
    pending.set(id, fetch('/api/corvette/part?id=' + encodeURIComponent(id))
      .then(r => (r.ok ? r.arrayBuffer() : Promise.reject(new Error('no model for ' + id))))
      .then(buf => B.scene.addPart(id, buf)));
  }
  if (!B.snaps.has(id)) loadSnaps([id]);
  try {
    await pending.get(id);
    return true;
  } catch (e) {
    pending.delete(id);
    return false;
  }
}

async function loadSnaps(ids) {
  const want = ids.filter(i => !B.snaps.has(i));
  if (!want.length) return;
  want.forEach(i => B.snaps.set(i, []));   // claim them, so two drags do not both fetch
  const got = await api('/api/corvette/snaps?ids=' + encodeURIComponent(want.join(',')));
  for (const id of want) B.snaps.set(id, got[id] || []);
}

/* ---- palette --------------------------------------------------------------------------- */

function renderPalette() {
  const text = $('#bSearch').value.trim().toLowerCase();
  const groups = B.palette.map(g => ({
    label: g.label,
    parts: g.parts.filter(p => !text || (p.name + ' ' + p.id).toLowerCase().includes(text)),
  })).filter(g => g.parts.length);
  $('#bGroups').innerHTML = groups.map((g, i) => `<details class="bgroup"${text || i === 0 ? ' open' : ''}>
    <summary><span>${esc(g.label)}</span><span>${g.parts.length}</span></summary>
    ${g.parts.map(p => `<button class="bpart" data-id="${esc(p.id)}">${esc(p.name)}<code>${esc(p.id)}</code></button>`).join('')}
  </details>`).join('') || '<p class="bempty">Nothing matches.</p>';
  document.querySelectorAll('.bpart').forEach(b => { b.onclick = () => addModule(b.dataset.id); });
}

/* A new module lands between the camera and the ship, where it can be seen and taken hold of.
   Dropping it at the origin would bury it inside the hull. */
async function addModule(id) {
  if (!(await needPart(id))) { toast('Nothing in the game files draws ' + id, true); return; }
  const d = B.scene.viewDir(), t = B.scene.target, k = B.scene.dist * .4;
  mark();
  const fresh = {id, position: [0, 0, 0], up: [0, 1, 0], at: [0, 0, 1]};
  dropAt(setMatrix(fresh), [t[0] - d[0] * k, t[1] - d[1] * k, t[2] - d[2] * k], -1);
  B.modules.push(fresh);
  B.scene.items = B.modules;
  B.scene.selected = B.modules.length - 1;
  drawInspector();
  refreshChrome();
  toast('Added ' + (B.names[id] || id));
}

/* ---- inspector ------------------------------------------------------------------------- */

const trio = v => v.map(n => (Math.round(n * 1000) / 1000 || 0)).join(', ');

/* Turn a module about a world axis, from `base` if one is given or from where it stands. */
function turn(m, axis, ang, base) {
  const src = base || {up: m.up, at: m.at};
  m.up = spin(src.up, axis, ang);
  m.at = spin(src.at, axis, ang);
  return setMatrix(m);
}
/* Snap a part back onto the axes, for when a free turn has left it at an awkward angle. */
function squareUp(m) {
  const nearest = v => {
    const i = v.reduce((best, x, j) => (Math.abs(x) > Math.abs(v[best]) ? j : best), 0);
    const o = [0, 0, 0];
    o[i] = v[i] < 0 ? -1 : 1;
    return o;
  };
  const up = nearest(m.up), at = nearest(m.at);
  // Two vectors that square up onto the same axis would flatten the part, so fall back.
  m.up = up;
  m.at = up.findIndex(Boolean) === at.findIndex(Boolean) ? (up[1] ? [0, 0, 1] : [0, 1, 0]) : at;
  return setMatrix(m);
}
/* The sliders' three angles, read off the orientation the save holds.

   Turning is stored as Up and At, not as angles, so the angles are worked back out: the part is
   taken to be rolled about Z, then pitched about X, then yawed about Y, which is the order the
   sliders put them back in. Pitched to straight up or down the yaw and the roll describe the
   same turn and the pair of them can swap between readings -- the rings still work there. */
const DEG = 180 / Math.PI;
function anglesOf(m) {
  const right = [m.up[1] * m.at[2] - m.up[2] * m.at[1],
                 m.up[2] * m.at[0] - m.up[0] * m.at[2],
                 m.up[0] * m.at[1] - m.up[1] * m.at[0]];
  return [Math.asin(Math.max(-1, Math.min(1, -m.at[1]))) * DEG,
          Math.atan2(m.at[0], m.at[2]) * DEG,
          Math.atan2(right[1], m.up[1]) * DEG].map(d => Math.round(d * 10) / 10);
}
function setAngles(m, deg) {
  const [x, y, z] = deg.map(d => d / DEG);
  const put = v => spin(spin(spin(v, 2, z), 0, x), 1, y);
  m.up = put([0, 1, 0]);
  m.at = put([0, 0, 1]);
  return setMatrix(m);
}

const AXIS_SLIDERS = [['bRotX', 'X'], ['bRotY', 'Y'], ['bRotZ', 'Z']];

function syncFacing(m) {
  const face = $('#bFacing');
  if (!face) return;
  const deg = anglesOf(m);
  AXIS_SLIDERS.forEach(([id], i) => {
    const slider = $('#' + id);
    $('#' + id + 'V').textContent = deg[i] + '°';
    if (document.activeElement !== slider) slider.value = deg[i];
  });
  const square = [...m.up, ...m.at].every(c => Math.abs(c - Math.round(c)) < 0.01);
  face.className = 'bfacing' + (square ? '' : ' free');
  face.textContent = `up ${trio(m.up)} · at ${trio(m.at)}` + (square ? '' : ' — off the axes');
}

function drawInspector() {
  const i = B.scene.selected, m = B.modules[i];
  const box = $('#bInsp');
  if (!m) {
    box.innerHTML = `<p class="bempty">Nothing selected.<br><br>Click a module in the view to pick it
      up, or a part on the left to add one.</p>` + keysHtml();
    return;
  }
  box.innerHTML = `<h3>${esc(B.names[m.id] || m.id)}</h3><code class="muted">${esc(m.id)}</code>
    <div class="xyz">
      <label>X</label><input type="number" id="bx" step="${B.snap || 0.5}" value="${shown(m.position[0])}">
      <label>Y</label><input type="number" id="by" step="${B.snap || 0.5}" value="${shown(m.position[1])}">
      <label>Z</label><input type="number" id="bz" step="${B.snap || 0.5}" value="${shown(m.position[2])}">
    </div>
    <div class="bturn">${AXIS_SLIDERS.map(([id, ax], i) => `
      <label class="a${ax}">${ax}<b id="${id}V"></b></label>
      <input class="bslider a${ax}" type="range" id="${id}" min="-180" max="180" step="1">`).join('')}</div>
    <p class="bfacing" id="bFacing"></p>
    <div class="row">
      <button class="btn" id="bTurn">Turn 90&deg;</button>
      <button class="btn" id="bFlat">Square up</button>
      <button class="btn" id="bDup">Duplicate</button>
    </div>
    <div class="row"><button class="btn" id="bDel">Remove module</button></div>` + keysHtml();

  ['bx', 'by', 'bz'].forEach((id, axis) => {
    $('#' + id).onchange = e => {
      mark();
      m.position[axis] = parseFloat(e.target.value) || 0;
      setMatrix(m);
      refreshChrome();
    };
  });
  /* One slider per ring. Each sets its own angle and leaves the other two where they read, so
     a part can be tipped and then turned without the first turn coming undone. Dragging a
     slider is one undo step, taken when it is grabbed. */
  let held = false;
  AXIS_SLIDERS.forEach(([id], i) => {
    const slider = $('#' + id);
    slider.onpointerdown = () => { mark(); held = true; };
    slider.oninput = e => {
      if (!held) { mark(); held = true; }
      const deg = anglesOf(m);
      deg[i] = +e.target.value;
      setAngles(m, deg);
      syncFacing(m);
    };
    slider.onchange = () => { held = false; refreshChrome(); };
  });
  $('#bTurn').onclick = () => { mark(); turn(m, 1, Math.PI / 2); syncFacing(m); refreshChrome(); };
  $('#bFlat').onclick = () => { mark(); squareUp(m); syncFacing(m); refreshChrome(); };
  syncFacing(m);
  $('#bDup').onclick = () => {
    mark();
    B.modules.push(setMatrix({id: m.id, position: m.position.slice(), up: m.up.slice(), at: m.at.slice()}));  // a copy is new, so it gets a new build time
    B.scene.items = B.modules;
    B.scene.selected = B.modules.length - 1;
    drawInspector();
    refreshChrome();
  };
  $('#bDel').onclick = removeSelected;
}
function keysHtml() {
  return `<div class="bkeys"><kbd>Del</kbd> remove &middot; <kbd>Ctrl</kbd>+<kbd>D</kbd> duplicate<br>
    <kbd>R</kbd> turn 90&deg; &middot; <kbd>Esc</kbd> deselect<br>
    drag a <span style="color:#eb5444">red</span>, <span style="color:#5ac772">green</span> or
    <span style="color:#549aef">blue</span> arrow to slide along X, Y or Z<br>
    drag a ring to turn about that axis &middot; drag the module itself to slide it flat<br>
    hold <kbd>Shift</kbd> to raise and lower<br>
    <kbd>Ctrl</kbd>+<kbd>Z</kbd> undo &middot; <kbd>Ctrl</kbd>+<kbd>Y</kbd> redo</div>`;
}
function removeSelected() {
  const i = B.scene.selected;
  if (i < 0) return;
  mark();
  B.modules.splice(i, 1);
  B.scene.items = B.modules;
  B.scene.selected = -1;
  drawInspector();
  refreshChrome();
}

/* ---- pointer handling ------------------------------------------------------------------ */

function wireCanvas() {
  const c = B.scene.canvas;
  let mode = null, start = null, last = null, grab = null, plane = null, moved = false;
  let axis = -1, axisBase = null, axisFrom = 0, turnBase = null;

  const showFields = m => {
    const f = ['bx', 'by', 'bz'].map(id => $('#' + id));
    if (f[0]) f.forEach((el, i) => { el.value = shown(m.position[i]); });
  };

  c.addEventListener('contextmenu', e => e.preventDefault());
  c.addEventListener('pointerdown', e => {
    c.setPointerCapture(e.pointerId);
    start = last = [e.clientX, e.clientY];
    moved = false;
    const hit = e.button === 0 ? B.scene.pick(e.clientX, e.clientY) : null;
    const held = B.modules[B.scene.selected];
    if (hit && hit.axis !== undefined && held) {
      // An arrow was grabbed: this drag runs along that one axis and nothing else. The line is
      // pinned where the part started, so the reading does not chase the part as it moves.
      axisBase = held.position.slice();
      const t = B.scene.alongAxis(e.clientX, e.clientY, axisBase, hit.axis);
      if (t !== null) {
        axis = hit.axis;
        axisFrom = t;
        mode = 'axis';
        B.scene.hoverAxis = axis;
        c.style.cursor = 'grabbing';
        return;
      }
    }
    if (hit && hit.ring !== undefined && held) {
      // A ring was grabbed: this drag turns the part about that axis and moves it not at all.
      const a = B.scene.angleAround(e.clientX, e.clientY, held.position, hit.ring);
      if (a !== null) {
        axis = hit.ring;
        axisFrom = a;
        turnBase = {up: held.up.slice(), at: held.at.slice()};
        mode = 'turn';
        B.scene.hoverRing = axis;
        c.style.cursor = 'grabbing';
        return;
      }
    }
    if (hit && hit.item !== undefined) {
      B.scene.selected = hit.item;
      drawInspector();
      const m = B.modules[hit.item];
      // Slide across the floor by default, up and down the screen with Shift held.
      plane = e.shiftKey ? screenPlane() : [0, 1, 0];
      const at = B.scene.onPlane(e.clientX, e.clientY, m.position, plane);
      if (at) {
        grab = [at[0] - m.position[0], at[1] - m.position[1], at[2] - m.position[2]];
        mode = 'move';
        c.style.cursor = 'grabbing';
        return;
      }
    }
    if (e.button === 0 && !hit) { B.scene.selected = -1; drawInspector(); }
    mode = 'orbit';
    c.style.cursor = 'grabbing';
  });
  c.addEventListener('pointermove', e => {
    if (!mode) {
      const h = B.scene.pick(e.clientX, e.clientY);
      const onAxis = h && h.axis !== undefined ? h.axis : -1;
      const onRing = h && h.ring !== undefined ? h.ring : -1;
      const onItem = h && h.item !== undefined ? h.item : -1;
      if (onAxis !== B.scene.hoverAxis || onRing !== B.scene.hoverRing || onItem !== B.scene.hover) {
        B.scene.hoverAxis = onAxis;
        B.scene.hoverRing = onRing;
        B.scene.hover = onItem;
        c.style.cursor = onAxis >= 0 || onRing >= 0 ? 'crosshair' : onItem >= 0 ? 'grab' : 'default';
      }
      return;
    }
    const dx = e.clientX - last[0], dy = e.clientY - last[1];
    last = [e.clientX, e.clientY];
    if (mode === 'orbit') {
      B.scene.yaw -= dx * .008;
      B.scene.pitch = Math.max(-1.5, Math.min(1.5, B.scene.pitch + dy * .008));
      return;
    }
    // Until the pointer has actually travelled -- measured from where it went down, so a slow
    // drag still counts -- this is a click and not a drag. Moving the part before then would
    // shunt it to the nearest snap just for being picked up.
    if (!moved) {
      if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) <= 2) return;
      mark();                                 // one undo step per drag, taken on the first move
      moved = true;
    }
    const m = B.modules[B.scene.selected];
    if (!m) return;
    if (mode === 'turn') {
      const a = B.scene.angleAround(e.clientX, e.clientY, m.position, axis);
      if (a === null) return;
      const d = snappedAngle(a - axisFrom);
      turn(m, axis, d, turnBase);
      syncFacing(m);
      return;
    }
    if (mode === 'axis') {
      const t = B.scene.alongAxis(e.clientX, e.clientY, axisBase, axis);
      if (t === null) return;
      const want = m.position.slice();
      want[axis] = axisBase[axis] + t - axisFrom;
      dropAt(m, want, B.scene.selected);
    } else {
      const at = B.scene.onPlane(e.clientX, e.clientY, m.position, plane);
      if (!at) return;
      dropAt(m, [at[0] - grab[0], at[1] - grab[1], at[2] - grab[2]], B.scene.selected);
    }
    showFields(m);
  });
  const stop = () => {
    if (mode && mode !== 'orbit' && moved) { B.dirty = true; refreshChrome(); }
    if (mode === 'axis') B.scene.hoverAxis = -1;
    if (mode === 'turn') B.scene.hoverRing = -1;
    mode = null;
    axis = -1;
    c.style.cursor = 'default';
  };
  c.addEventListener('pointerup', stop);
  c.addEventListener('pointercancel', stop);
  c.addEventListener('wheel', e => {
    e.preventDefault();
    B.scene.dist = Math.max(4, Math.min(1200, B.scene.dist * Math.exp(e.deltaY * .001)));
  }, {passive: false});

  addEventListener('keydown', e => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); undo(); }
    else if ((e.ctrlKey || e.metaKey) && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); redo(); }
    else if ((e.ctrlKey || e.metaKey) && k === 'd') { e.preventDefault(); $('#bDup') && $('#bDup').click(); }
    else if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); saveBuild(); }
    else if (k === 'delete' || k === 'backspace') { e.preventDefault(); removeSelected(); }
    else if (k === 'r') { $('#bTurn') && $('#bTurn').click(); }
    else if (k === 'escape') { B.scene.selected = -1; drawInspector(); }
  });
}
/* The plane facing the camera, for dragging a module towards or away from the floor. */
function screenPlane() {
  const d = B.scene.viewDir();
  return [-d[0], 0, -d[2]];
}

/* ---- loading and saving ---------------------------------------------------------------- */

async function saveBuild() {
  if (!B.modules.length) { toast('Nothing to save.', true); return; }
  const btn = $('#bSave');
  btn.disabled = true;
  try {
    const r = await api('/api/corvette/save', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: B.path, index: B.index,
                            modules: B.modules.map(m => ({id: m.id, ts: m.ts, position: m.position,
                                                         up: m.up, at: m.at}))}),
    });
    B.dirty = false;
    refreshChrome();
    toast(`Saved ${r.modules} modules into ${r.written.length} file${r.written.length === 1 ? '' : 's'}. Backups made.`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function gameWatch() {
  try {
    const st = await api('/api/status');
    const pill = $('#bGame');
    pill.className = 'pill ' + (st.game_running ? 'on' : 'off');
    pill.textContent = st.game_running ? 'Game running: saving blocked' : 'Game closed: safe to save';
  } catch (e) { /* the status pill is a courtesy; the save itself checks again */ }
}

async function start() {
  B.scene = Scene3D.mount($('#bView'));
  if (!B.scene) return;
  wireCanvas();
  $('#bSearch').oninput = renderPalette;
  $('#bGrid').onchange = e => { B.scene.showGrid = e.target.checked; };
  $('#bArrows').onchange = e => { B.scene.arrows = e.target.checked; };
  $('#bRings').onchange = e => { B.scene.rings = e.target.checked; };
  $('#bSnapParts').onchange = e => { B.snapParts = e.target.checked; };
  $('#bHint').dataset.idle = $('#bHint').textContent;
  $('#bSnap').onchange = e => { B.snap = parseFloat(e.target.value) || 0; drawInspector(); };
  $('#bUndo').onclick = undo;
  $('#bRedo').onclick = redo;
  $('#bSave').onclick = saveBuild;
  addEventListener('beforeunload', e => { if (B.dirty) { e.preventDefault(); e.returnValue = ''; } });

  B.palette = await api('/api/corvette/palette');
  for (const g of B.palette) for (const p of g.parts) B.names[p.id] = p.name;
  renderPalette();

  const list = await api('/api/corvettes?path=' + encodeURIComponent(B.path));
  const corv = list.find(c => c.index === B.index) || list[0];
  if (!corv) { toast('This save has no corvette.', true); drawInspector(); return; }
  B.index = corv.index;
  document.title = (corv.name ? corv.name + ' — ' : '') + 'Corvette Builder';

  const wanted = corv.modules.filter(m => !m.hull);
  const kinds = [...new Set(wanted.map(m => m.id))];
  await Promise.all([loadSnaps(kinds), ...kinds.map(needPart)]);
  // Modules nothing draws -- interior walls and the like -- are carried along unseen rather than
  // dropped, so saving a build never quietly throws away part of the ship.
  B.modules = wanted.map(m => setMatrix({id: m.id, ts: m.ts, position: m.position.slice(),
                                         up: m.up.slice(), at: m.at.slice(),
                                         hidden: !B.scene.parts.has(m.id)}));
  B.scene.items = B.modules;
  const unseen = B.modules.filter(m => m.hidden).length;
  if (unseen) toast(`${unseen} interior module${unseen === 1 ? '' : 's'} cannot be drawn. ` +
                    `${unseen === 1 ? 'It stays' : 'They stay'} on the ship and will be saved as ${unseen === 1 ? 'it is' : 'they are'}.`);

  const lo = [0, 0, 0], hi = [0, 0, 0];
  for (const m of B.modules) for (let i = 0; i < 3; i++) {
    lo[i] = Math.min(lo[i], m.position[i] - 6);
    hi[i] = Math.max(hi[i], m.position[i] + 6);
  }
  B.scene.frameOn([lo, hi]);
  drawInspector();
  refreshChrome();
  gameWatch();
  setInterval(gameWatch, 5000);
}
start().catch(e => toast(e.message, true));
