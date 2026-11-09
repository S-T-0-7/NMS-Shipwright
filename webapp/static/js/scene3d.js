/* The builder's renderer: many parts, each with its own place in the world.

   The ship viewer draws one model baked into a few buffers, which is right for looking at a
   finished ship and useless for building one -- here every module has to move on its own, be
   clicked on, and light up when it is picked. So each module keeps its own transform and a
   part's geometry is uploaded once however many copies of it the ship carries.

   Picking is done by drawing the scene a second time, off screen, with each module painted a
   flat colour made from its index, then reading the one pixel under the pointer. It costs a
   frame but it is exact, which matters when parts overlap as freely as these can. */
(function () {
  const VS = `#version 300 es
  in vec3 p; in vec3 n; uniform mat4 vp; uniform mat4 model; out vec3 vn; out vec3 wp;
  void main(){ vec4 w = model * vec4(p,1.); vn = mat3(model) * n; wp = w.xyz; gl_Position = vp * w; }`;
  const FS = `#version 300 es
  precision highp float; in vec3 vn; in vec3 wp;
  uniform vec3 col; uniform vec3 eye; uniform float emit; uniform float spec; uniform float alpha;
  uniform vec3 tint; uniform float tintMix; out vec4 o;
  void main(){
    // The game's own normals, where the geometry carried them; the face of the triangle otherwise.
    vec3 V = normalize(eye - wp), F = normalize(cross(dFdx(wp), dFdy(wp)));
    if (dot(F, V) < 0.) F = -F;
    vec3 N = length(vn) > .5 ? normalize(vn) : F;
    if (dot(N, V) < 0.) N = -N;
    vec3 L1 = normalize(vec3(.5,.8,.4)), L2 = normalize(vec3(-.6,.2,-.5));
    float d = max(dot(N,L1),0.)*.85 + max(dot(N,L2),0.)*.3 + .22 + .12*N.y;
    float s = pow(max(dot(N, normalize(L1+V)),0.), 40.) * spec;
    float rim = pow(1. - max(dot(N,V),0.), 3.) * .25;
    vec3 base = mix(col, tint, tintMix);
    o = vec4(mix(base * d + vec3(s) + rim * vec3(.55,.65,.8), base, emit), alpha);
  }`;
  const PICK_VS = `#version 300 es
  in vec3 p; uniform mat4 vp; uniform mat4 model;
  void main(){ gl_Position = vp * model * vec4(p,1.); }`;
  const PICK_FS = `#version 300 es
  precision highp float; uniform vec3 tag; out vec4 o; void main(){ o = vec4(tag, 1.); }`;
  const LINE_VS = `#version 300 es
  in vec3 p; uniform mat4 vp; void main(){ gl_Position = vp * vec4(p,1.); }`;
  const LINE_FS = `#version 300 es
  precision highp float; uniform vec4 col; out vec4 o; void main(){ o = col; }`;
  const GIZMO_VS = `#version 300 es
  in vec3 p; in vec3 n; uniform mat4 vp; uniform mat4 model; out vec3 vn;
  void main(){ vn = mat3(model) * n; gl_Position = vp * model * vec4(p,1.); }`;
  const GIZMO_FS = `#version 300 es
  precision highp float; in vec3 vn; uniform vec3 col; out vec4 o;
  void main(){
    vec3 N = normalize(vn);
    float d = max(dot(N, normalize(vec3(.4,.8,.5))), 0.) * .4 + .72;
    o = vec4(col * d, 1.);
  }`;
  // Red runs along X, green up Y, blue along Z -- the axes the inspector names.
  const AXIS_COL = [[.92, .33, .27], [.35, .78, .45], [.33, .6, .95]];
  // Picking tags this high are handles rather than modules: arrows to slide by, rings to turn by.
  const HANDLE_TAG = 0xF00000;
  const RING_TAG = 0xE00000;

  const CLASS = {paint: {col: [.75, .75, .78], spec: .35}, secondary: {col: [.62, .6, .56], spec: .35},
                 metal: {col: [.52, .54, .58], spec: .8}, dark: {col: [.12, .12, .14], spec: .3},
                 glass: {col: [.1, .16, .24], spec: 1.2, alpha: .45, blend: 'alpha'},
                 light: {col: [.45, .85, 1], emit: .85, spec: 0, alpha: .8, blend: 'add'},
                 glow: {col: [.5, .85, 1], emit: .9, spec: 0, alpha: .7, blend: 'add'}};

  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const scaled = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

  function mul(a, b) {  // column-major; a applied after b
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  }
  function persp(fov, asp, n, f) {
    const t = 1 / Math.tan(fov / 2), o = new Float32Array(16);
    o[0] = t / asp; o[5] = t; o[10] = (f + n) / (n - f); o[11] = -1; o[14] = 2 * f * n / (n - f);
    return o;
  }
  function lookAt(e, c, u) {
    const z = norm(sub(e, c)), x = norm(cross(u, z)), y = cross(z, x), o = new Float32Array(16);
    o.set([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, e), -dot(y, e), -dot(z, e), 1]);
    return o;
  }
  /* A module's frame, built from the Up and At the save stores for it -- the same three columns
     the game writes, so what is drawn here is what the file will say. */
  function placement(pos, up, at) {
    const x = cross(up, at);
    return new Float32Array([x[0], x[1], x[2], 0, up[0], up[1], up[2], 0, at[0], at[1], at[2], 0,
                             pos[0], pos[1], pos[2], 1]);
  }
  /* The arrows and rings are built here rather than read from the game, so they are the one
     thing left that needs its normals worked out. */
  function normals(pos, idx) {
    const n = new Float32Array(pos.length);
    for (let t = 0; t < idx.length; t += 3) {
      const a = idx[t] * 3, b = idx[t + 1] * 3, c = idx[t + 2] * 3;
      const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
      const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      for (const k of [a, b, c]) { n[k] += nx; n[k + 1] += ny; n[k + 2] += nz; }
    }
    return n;
  }
  /* A unit arrow pointing up Y: shaft, then a cone for the head. The fat one is never seen --
     it is what the picking pass draws, so a handle is easier to hit than it looks. */
  function arrowMesh(shaftR, headR) {
    const seg = 14, pos = [], idx = [];
    const ring = (y, r) => {
      const base = pos.length / 3;
      for (let i = 0; i < seg; i++) {
        const a = i / seg * Math.PI * 2;
        pos.push(Math.cos(a) * r, y, Math.sin(a) * r);
      }
      return base;
    };
    const r0 = ring(0, shaftR), r1 = ring(.74, shaftR), r2 = ring(.74, headR);
    const tip = pos.length / 3;
    pos.push(0, 1, 0);
    const tube = (a, b) => {
      for (let i = 0; i < seg; i++) {
        const j = (i + 1) % seg;
        idx.push(a + i, b + i, b + j, a + i, b + j, a + j);
      }
    };
    tube(r0, r1); tube(r1, r2);
    for (let i = 0; i < seg; i++) idx.push(r2 + i, tip, r2 + (i + 1) % seg);
    return {pos: new Float32Array(pos), idx: new Uint32Array(idx)};
  }
  /* A ring lying flat around Y, to be stood up on an axis the same way an arrow is. Turning a
     part is a drag around one of these. */
  function ringMesh(thickness) {
    const major = 48, minor = 8, pos = [], idx = [];
    for (let i = 0; i < major; i++) {
      const a = i / major * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
      for (let j = 0; j < minor; j++) {
        const b = j / minor * Math.PI * 2;
        const r = 1 + Math.cos(b) * thickness;
        pos.push(ca * r, Math.sin(b) * thickness, sa * r);
      }
    }
    for (let i = 0; i < major; i++) for (let j = 0; j < minor; j++) {
      const a = i * minor + j, b = i * minor + (j + 1) % minor;
      const c = ((i + 1) % major) * minor + j, d = ((i + 1) % major) * minor + (j + 1) % minor;
      idx.push(a, c, d, a, d, b);
    }
    return {pos: new Float32Array(pos), idx: new Uint32Array(idx)};
  }
  /* An arrow stood up along one axis at `origin`, `k` long. */
  function axisMatrix(axis, origin, k) {
    const up = [0, 0, 0];
    up[axis] = 1;
    const x = norm(cross(axis === 1 ? [1, 0, 0] : [0, 1, 0], up)), z = cross(up, x);
    return new Float32Array([x[0] * k, x[1] * k, x[2] * k, 0, up[0] * k, up[1] * k, up[2] * k, 0,
                             z[0] * k, z[1] * k, z[2] * k, 0, origin[0], origin[1], origin[2], 1]);
  }

  function invert(m) {
    const a = Array.from(m), v = new Array(16);
    v[0] = a[5]*a[10]*a[15]-a[5]*a[11]*a[14]-a[9]*a[6]*a[15]+a[9]*a[7]*a[14]+a[13]*a[6]*a[11]-a[13]*a[7]*a[10];
    v[4] = -a[4]*a[10]*a[15]+a[4]*a[11]*a[14]+a[8]*a[6]*a[15]-a[8]*a[7]*a[14]-a[12]*a[6]*a[11]+a[12]*a[7]*a[10];
    v[8] = a[4]*a[9]*a[15]-a[4]*a[11]*a[13]-a[8]*a[5]*a[15]+a[8]*a[7]*a[13]+a[12]*a[5]*a[11]-a[12]*a[7]*a[9];
    v[12] = -a[4]*a[9]*a[14]+a[4]*a[10]*a[13]+a[8]*a[5]*a[14]-a[8]*a[6]*a[13]-a[12]*a[5]*a[10]+a[12]*a[6]*a[9];
    v[1] = -a[1]*a[10]*a[15]+a[1]*a[11]*a[14]+a[9]*a[2]*a[15]-a[9]*a[3]*a[14]-a[13]*a[2]*a[11]+a[13]*a[3]*a[10];
    v[5] = a[0]*a[10]*a[15]-a[0]*a[11]*a[14]-a[8]*a[2]*a[15]+a[8]*a[3]*a[14]+a[12]*a[2]*a[11]-a[12]*a[3]*a[10];
    v[9] = -a[0]*a[9]*a[15]+a[0]*a[11]*a[13]+a[8]*a[1]*a[15]-a[8]*a[3]*a[13]-a[12]*a[1]*a[11]+a[12]*a[3]*a[9];
    v[13] = a[0]*a[9]*a[14]-a[0]*a[10]*a[13]-a[8]*a[1]*a[14]+a[8]*a[2]*a[13]+a[12]*a[1]*a[10]-a[12]*a[2]*a[9];
    v[2] = a[1]*a[6]*a[15]-a[1]*a[7]*a[14]-a[5]*a[2]*a[15]+a[5]*a[3]*a[14]+a[13]*a[2]*a[7]-a[13]*a[3]*a[6];
    v[6] = -a[0]*a[6]*a[15]+a[0]*a[7]*a[14]+a[4]*a[2]*a[15]-a[4]*a[3]*a[14]-a[12]*a[2]*a[7]+a[12]*a[3]*a[6];
    v[10] = a[0]*a[5]*a[15]-a[0]*a[7]*a[13]-a[4]*a[1]*a[15]+a[4]*a[3]*a[13]+a[12]*a[1]*a[7]-a[12]*a[3]*a[5];
    v[14] = -a[0]*a[5]*a[14]+a[0]*a[6]*a[13]+a[4]*a[1]*a[14]-a[4]*a[2]*a[13]-a[12]*a[1]*a[6]+a[12]*a[2]*a[5];
    v[3] = -a[1]*a[6]*a[11]+a[1]*a[7]*a[10]+a[5]*a[2]*a[11]-a[5]*a[3]*a[10]-a[9]*a[2]*a[7]+a[9]*a[3]*a[6];
    v[7] = a[0]*a[6]*a[11]-a[0]*a[7]*a[10]-a[4]*a[2]*a[11]+a[4]*a[3]*a[10]+a[8]*a[2]*a[7]-a[8]*a[3]*a[6];
    v[11] = -a[0]*a[5]*a[11]+a[0]*a[7]*a[9]+a[4]*a[1]*a[11]-a[4]*a[3]*a[9]-a[8]*a[1]*a[7]+a[8]*a[3]*a[5];
    v[15] = a[0]*a[5]*a[10]-a[0]*a[6]*a[9]-a[4]*a[1]*a[10]+a[4]*a[2]*a[9]+a[8]*a[1]*a[6]-a[8]*a[2]*a[5];
    let det = a[0] * v[0] + a[1] * v[4] + a[2] * v[8] + a[3] * v[12];
    if (!det) return null;
    det = 1 / det;
    return v.map(x => x * det);
  }

  function mount(el) {
    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'width:100%;height:100%;display:block;touch-action:none';
    el.innerHTML = '';
    el.appendChild(canvas);
    const gl = canvas.getContext('webgl2', {antialias: true});
    if (!gl) { el.innerHTML = '<p class="muted">This needs WebGL2.</p>'; return null; }

    const build = (vs, fs) => {
      const sh = (t, src) => { const x = gl.createShader(t); gl.shaderSource(x, src); gl.compileShader(x); return x; };
      const p = gl.createProgram();
      gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      return p;
    };
    const solid = build(VS, FS), picker = build(PICK_VS, PICK_FS), liner = build(LINE_VS, LINE_FS);
    const gizmo = build(GIZMO_VS, GIZMO_FS);

    const S = {parts: new Map(), items: [], selected: -1, hover: -1, hoverAxis: -1, hoverRing: -1,
               alive: true, yaw: -2.4, pitch: .4, dist: 60, target: [0, 4, 0],
               showGrid: true, arrows: true, rings: true};

    function upload(mesh) {
      const vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      for (const [loc, data] of [[0, mesh.pos], [1, normals(mesh.pos, mesh.idx)]]) {
        const b = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, b);
        gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
      }
      const ib = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.idx, gl.STATIC_DRAW);
      gl.bindVertexArray(null);
      return {vao, count: mesh.idx.length};
    }
    const arrow = upload(arrowMesh(.022, .075)), arrowFat = upload(arrowMesh(.075, .13));
    const ring = upload(ringMesh(.016)), ringFat = upload(ringMesh(.055));

    /* Geometry for one part id, uploaded once however many copies of it the ship carries. */
    S.addPart = (id, buf) => {
      if (S.parts.has(id)) return S.parts.get(id);
      const hl = new DataView(buf).getUint32(0, true);
      const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl))), base = 4 + hl;
      const groups = head.groups.map(g => {
        const pos = new Float32Array(buf, base + g.offset, g.vertices * 3);
        const nrm = new Float32Array(buf, base + g.offset + g.vertices * 12, g.vertices * 3);
        const idx = new Uint32Array(buf, base + g.offset + g.vertices * 24, g.indices);
        const vao = gl.createVertexArray();
        gl.bindVertexArray(vao);
        for (const [loc, data] of [[0, pos], [1, nrm]]) {
          const b = gl.createBuffer();
          gl.bindBuffer(gl.ARRAY_BUFFER, b);
          gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
          gl.enableVertexAttribArray(loc);
          gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
        }
        const ib = gl.createBuffer();
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
        gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
        gl.bindVertexArray(null);
        const c = CLASS[g.class] || CLASS.paint;
        return {vao, count: g.indices, col: c.col || [.75, .75, .78], emit: c.emit || 0,
                spec: c.spec === undefined ? .4 : c.spec, alpha: c.alpha === undefined ? 1 : c.alpha,
                blend: c.blend || null};
      });
      const part = {groups, bounds: head.bounds};
      S.parts.set(id, part);
      return part;
    };

    /* Game X runs to the ship's left, so the world is mirrored for display and every
       screen-to-world answer comes back in game axes already. The camera watches the mirrored
       world, so what it is pointed at is mirrored too -- `S.target` is set by callers in game
       axes, like everything else they hand over, and turned round here. */
    const FLIP = new Float32Array([-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    const aimedAt = () => [-S.target[0], S.target[1], S.target[2]];
    const eye = () => {
      const t = aimedAt();
      return [t[0] + S.dist * Math.cos(S.pitch) * Math.sin(S.yaw),
              t[1] + S.dist * Math.sin(S.pitch),
              t[2] + S.dist * Math.cos(S.pitch) * Math.cos(S.yaw)];
    };
    const camera = (w, h) => {
      const e = eye();
      return {e, vp: mul(mul(persp(.7, w / Math.max(h, 1), .5, 4000), lookAt(e, aimedAt(), [0, 1, 0])), FLIP)};
    };

    let gridBuf = null, gridCount = 0;
    (function makeGrid() {
      const step = 6, n = 16, half = step * n, pts = [];
      for (let i = -n; i <= n; i++) {
        pts.push(-half, 0, i * step, half, 0, i * step, i * step, 0, -half, i * step, 0, half);
      }
      gridBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, gridBuf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pts), gl.STATIC_DRAW);
      gridCount = pts.length / 3;
    })();

    function drawItems(prog, cam, pickMode) {
      gl.useProgram(prog);
      const U = n => gl.getUniformLocation(prog, n);
      gl.uniformMatrix4fv(U('vp'), false, cam.vp);
      if (!pickMode) gl.uniform3fv(U('eye'), cam.e);
      const pass = want => {
        for (let i = 0; i < S.items.length; i++) {
          const it = S.items[i], part = S.parts.get(it.id);
          if (!part || it.hidden) continue;
          gl.uniformMatrix4fv(U('model'), false, it.matrix);
          if (pickMode) {
            const n = i + 1;
            gl.uniform3fv(U('tag'), [(n & 255) / 255, ((n >> 8) & 255) / 255, ((n >> 16) & 255) / 255]);
          } else {
            const lit = i === S.selected ? .6 : i === S.hover ? .25 : 0;
            gl.uniform3fv(U('tint'), i === S.selected ? [1, .5, .3] : [.5, .85, 1]);
            gl.uniform1f(U('tintMix'), lit);
          }
          for (const g of part.groups) {
            if (pickMode ? g.blend : g.blend !== want) continue;
            if (!pickMode) {
              gl.uniform3fv(U('col'), g.col);
              gl.uniform1f(U('emit'), g.emit);
              gl.uniform1f(U('spec'), g.spec);
              gl.uniform1f(U('alpha'), g.alpha);
            }
            gl.bindVertexArray(g.vao);
            gl.drawElements(gl.TRIANGLES, g.count, gl.UNSIGNED_INT, 0);
          }
        }
      };
      if (pickMode) { pass(null); return; }
      gl.disable(gl.BLEND); gl.depthMask(true);
      pass(null);
      gl.enable(gl.BLEND); gl.depthMask(false);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); pass('alpha');
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE); pass('add');
      gl.depthMask(true); gl.disable(gl.BLEND);
    }

    /* The arrows the selected module is dragged by. They are drawn over everything and kept a
       constant size on screen, so a handle is as easy to grab on a part across the ship as on
       one under the camera. */
    const handleAt = () => {
      const it = S.items[S.selected];
      return S.arrows && it && !it.hidden ? it.position : null;
    };
    const handleSize = () => S.dist * .17;
    function drawHandles(cam, pickMode) {
      const origin = handleAt();
      if (!origin) return;
      const prog = pickMode ? picker : gizmo;
      gl.useProgram(prog);
      const U = n => gl.getUniformLocation(prog, n);
      gl.uniformMatrix4fv(U('vp'), false, cam.vp);
      // Clearing depth rather than turning the test off keeps the handles straight with each
      // other where they cross, while still drawing them over the ship.
      gl.clear(gl.DEPTH_BUFFER_BIT);
      const k = handleSize();
      const draw = (mesh, axis, size, tag, lit) => {
        gl.uniformMatrix4fv(U('model'), false, axisMatrix(axis, origin, size));
        if (pickMode) {
          gl.uniform3fv(U('tag'), [(tag & 255) / 255, ((tag >> 8) & 255) / 255, ((tag >> 16) & 255) / 255]);
        } else {
          gl.uniform3fv(U('col'), lit ? [1, .92, .45] : AXIS_COL[axis]);
        }
        gl.bindVertexArray(mesh.vao);
        gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_INT, 0);
      };
      // The rings sit just outside the arrow tips, so neither gets in the other's way.
      for (let axis = 0; axis < 3; axis++) {
        if (S.rings) draw(pickMode ? ringFat : ring, axis, k * 1.22, RING_TAG + axis, axis === S.hoverRing);
        if (S.arrows) draw(pickMode ? arrowFat : arrow, axis, k, HANDLE_TAG + axis, axis === S.hoverAxis);
      }
    }

    function frame() {
      if (!S.alive) return;
      const w = canvas.clientWidth * devicePixelRatio | 0, h = canvas.clientHeight * devicePixelRatio | 0;
      if (w && h && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(.047, .055, .07, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      const cam = camera(canvas.width, canvas.height);
      if (S.showGrid) {
        gl.useProgram(liner);
        gl.uniformMatrix4fv(gl.getUniformLocation(liner, 'vp'), false, cam.vp);
        gl.uniform4fv(gl.getUniformLocation(liner, 'col'), [.28, .33, .43, .55]);
        gl.bindVertexArray(null);
        gl.bindBuffer(gl.ARRAY_BUFFER, gridBuf);
        gl.enableVertexAttribArray(0);
        gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.drawArrays(gl.LINES, 0, gridCount);
        gl.disable(gl.BLEND);
      }
      drawItems(solid, cam, false);
      drawHandles(cam, false);
      requestAnimationFrame(frame);
    }

    /* What is under this point: the scene again in flat index colours, one pixel read. Modules
       are tagged by their index; the three drag handles sit well above any of them. */
    let fbo = null, fboTex = null, fboDepth = null, fboW = 0, fboH = 0;
    S.pick = (cx, cy) => {
      const r = canvas.getBoundingClientRect(), w = canvas.width, h = canvas.height;
      const x = Math.round((cx - r.left) / r.width * w), y = Math.round((1 - (cy - r.top) / r.height) * h);
      if (!w || !h || x < 0 || y < 0 || x >= w || y >= h) return null;
      if (!fbo || fboW !== w || fboH !== h) {
        if (fbo) { gl.deleteFramebuffer(fbo); gl.deleteTexture(fboTex); gl.deleteRenderbuffer(fboDepth); }
        fbo = gl.createFramebuffer();
        fboTex = gl.createTexture();
        fboDepth = gl.createRenderbuffer();
        gl.bindTexture(gl.TEXTURE_2D, fboTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.bindRenderbuffer(gl.RENDERBUFFER, fboDepth);
        gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
        gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, fboTex, 0);
        gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, fboDepth);
        fboW = w; fboH = h;
      }
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.depthMask(true);
      const cam = camera(w, h);
      drawItems(picker, cam, true);
      drawHandles(cam, true);   // drawn last and over everything, as on screen
      const px = new Uint8Array(4);
      gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      const n = px[0] | (px[1] << 8) | (px[2] << 16);
      if (!n) return null;
      if (n >= HANDLE_TAG) return {axis: n - HANDLE_TAG};
      if (n >= RING_TAG) return {ring: n - RING_TAG};
      return {item: n - 1};
    };

    function unproject(inv, x, y, z) {
      const v = [x, y, z, 1], o = [0, 0, 0, 0];
      for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) o[r] += inv[c * 4 + r] * v[c];
      return [o[0] / o[3], o[1] / o[3], o[2] / o[3]];
    }
    /* Where a screen point lands on a plane through `origin` facing `normal`, in game axes. */
    S.onPlane = (cx, cy, origin, normal) => {
      const r = canvas.getBoundingClientRect();
      const nx = (cx - r.left) / r.width * 2 - 1, ny = 1 - (cy - r.top) / r.height * 2;
      const inv = invert(camera(canvas.width, canvas.height).vp);
      if (!inv) return null;
      const near = unproject(inv, nx, ny, -1), far = unproject(inv, nx, ny, 1);
      const dir = sub(far, near), denom = dot(normal, dir);
      if (Math.abs(denom) < 1e-6) return null;
      return add(near, scaled(dir, dot(normal, sub(origin, near)) / denom));
    };
    /* How far along `axis` from `origin` the pointer is: the point on that line closest to the
       ray through the screen. This is what an arrow drag follows, so the part slides along one
       axis and no other however the camera happens to be turned. */
    S.alongAxis = (cx, cy, origin, axis) => {
      const r = canvas.getBoundingClientRect();
      const nx = (cx - r.left) / r.width * 2 - 1, ny = 1 - (cy - r.top) / r.height * 2;
      const inv = invert(camera(canvas.width, canvas.height).vp);
      if (!inv) return null;
      const near = unproject(inv, nx, ny, -1), dir = sub(unproject(inv, nx, ny, 1), near);
      const u = [0, 0, 0];
      u[axis] = 1;
      const w = sub(near, origin);
      const a = dot(dir, dir), b = dot(dir, u), d = dot(dir, w), e = dot(u, w);
      const denom = a - b * b;                 // u is a unit vector, so dot(u, u) is 1
      if (Math.abs(denom) < 1e-9) return null; // looking straight down the axis: no answer
      return (a * e - b * d) / denom;
    };

    /* Where the pointer sits around `axis`, as an angle in the plane the ring lies in. A turn
       drag is the difference between two of these, so it follows the ring rather than the
       distance dragged. */
    S.angleAround = (cx, cy, origin, axis) => {
      const u = [0, 0, 0];
      u[axis] = 1;
      const at = S.onPlane(cx, cy, origin, u);
      if (!at) return null;
      const e1 = axis === 1 ? [1, 0, 0] : [0, 1, 0], e2 = cross(u, e1);
      const w = sub(at, origin);
      return Math.atan2(dot(w, e2), dot(w, e1));
    };

    /* The way the camera looks, in game axes, so a drag can run across the view. */
    S.viewDir = () => {
      const e = eye(), t = aimedAt();
      return norm([-(t[0] - e[0]), t[1] - e[1], t[2] - e[2]]);
    };

    S.place = placement;
    S.frameOn = bounds => {
      const [lo, hi] = bounds;
      S.target = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
      S.dist = Math.max(20, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) * 1.15);
    };
    S.canvas = canvas;
    S.destroy = () => { S.alive = false; gl.getExtension('WEBGL_lose_context') && gl.getExtension('WEBGL_lose_context').loseContext(); };
    requestAnimationFrame(frame);
    return S;
  }
  window.Scene3D = {mount};
})();
