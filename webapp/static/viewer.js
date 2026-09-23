/* Lightweight WebGL2 ship viewer: drag to orbit, wheel/pinch to zoom, double-click to reset.
   ShipViewer.mount(el) -> viewer; viewer.load(url) fetches the binary from /api/model (see model3d.pack). */
(function () {
  const VS = `#version 300 es
  in vec3 p; in vec3 n; uniform mat4 mvp; uniform mat4 model; out vec3 vn; out vec3 vp;
  void main(){ vn = mat3(model) * n; vp = (model * vec4(p,1.)).xyz; gl_Position = mvp * vec4(p,1.); }`;
  const FS = `#version 300 es
  precision highp float; in vec3 vn; in vec3 vp; uniform vec3 col; uniform vec3 eye; uniform float emit; uniform float spec; uniform float alpha; out vec4 o;
  void main(){
    // The position stream welds vertices across sharp edges, so averaged normals smear hard panels
    // dark. Use the face normal unless the smooth one is close to it (curved surfaces stay smooth).
    vec3 V = normalize(eye - vp), F = normalize(cross(dFdx(vp), dFdy(vp)));
    if (dot(F, V) < 0.) F = -F;
    vec3 N = normalize(vn); if (dot(N, F) < 0.) N = -N;
    N = dot(N, F) > .82 ? N : F;
    vec3 L1 = normalize(vec3(.5,.8,.4)), L2 = normalize(vec3(-.6,.2,-.5));
    float d = max(dot(N,L1),0.)*.85 + max(dot(N,L2),0.)*.3 + .22 + .12*N.y;
    float s = pow(max(dot(N, normalize(L1+V)),0.), 40.) * spec;
    float rim = pow(1. - max(dot(N,V),0.), 3.) * .25;
    vec3 c = col * d + vec3(s) + rim * vec3(.55,.65,.8);
    o = vec4(mix(c, col, emit), alpha);
  }`;
  const CLASS = {paint: {spec: .35}, secondary: {col: [.62, .6, .56], spec: .35}, metal: {col: [.52, .54, .58], spec: .8},
                 dark: {col: [.12, .12, .14], spec: .3},
                 glass: {col: [.1, .16, .24], spec: 1.2, alpha: .45, blend: 'alpha'},
                 light: {col: [.45, .85, 1], emit: .85, spec: 0, alpha: .8, blend: 'add'},
                 glow: {col: [.5, .85, 1], emit: .9, spec: 0, alpha: .7, blend: 'add'}};

  function mat4() { return new Float32Array(16); }
  function mul(a, b) { const o = mat4(); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s; } return o; }
  function persp(fov, asp, n, f) { const t = 1 / Math.tan(fov / 2), o = mat4(); o[0] = t / asp; o[5] = t; o[10] = (f + n) / (n - f); o[11] = -1; o[14] = 2 * f * n / (n - f); return o; }
  function lookAt(e, c, u) {
    const z = norm(sub(e, c)), x = norm(cross(u, z)), y = cross(z, x), o = mat4();
    o.set([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, e), -dot(y, e), -dot(z, e), 1]); return o;
  }
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

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

  function mount(el) {
    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'width:100%;height:100%;display:block;touch-action:none;cursor:grab';
    el.innerHTML = ''; el.appendChild(canvas);
    const gl = canvas.getContext('webgl2', {antialias: true});
    if (!gl) { el.innerHTML = '<span class="muted">3D view needs WebGL2</span>'; return null; }
    const sh = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); return x; };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
    const U = n => gl.getUniformLocation(prog, n);
    const v = {yaw: -2.4, pitch: .35, dist: 1, auto: true, groups: [], center: [0, 0, 0], radius: 1, alive: true};
    const reset = () => { v.yaw = -2.4; v.pitch = .35; v.dist = v.radius * 2.6; };

    function draw() {
      if (!v.alive) return;
      const w = canvas.clientWidth * devicePixelRatio | 0, h = canvas.clientHeight * devicePixelRatio | 0;
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      if (v.groups.length) {
        const c = v.center, e = [c[0] + v.dist * Math.cos(v.pitch) * Math.sin(v.yaw), c[1] + v.dist * Math.sin(v.pitch), c[2] + v.dist * Math.cos(v.pitch) * Math.cos(v.yaw)];
        const model = mat4(); model[0] = -1; model[5] = 1; model[10] = 1; model[15] = 1;  // game X is to the ship's left
        const mvp = mul(persp(.7, w / Math.max(h, 1), v.radius * .02, v.radius * 20), mul(lookAt(e, c, [0, 1, 0]), model));
        gl.useProgram(prog);
        gl.uniformMatrix4fv(U('mvp'), false, mvp); gl.uniformMatrix4fv(U('model'), false, model); gl.uniform3fv(U('eye'), e);
        // solid hull first, then glows and glass on top so they never punch holes in it
        gl.disable(gl.BLEND); gl.depthMask(true);
        const draw = g => {
          gl.uniform3fv(U('col'), g.col); gl.uniform1f(U('emit'), g.emit);
          gl.uniform1f(U('spec'), g.spec); gl.uniform1f(U('alpha'), g.alpha);
          gl.bindVertexArray(g.vao); gl.drawElements(gl.TRIANGLES, g.count, gl.UNSIGNED_INT, 0);
        };
        for (const g of v.groups) if (!g.blend) draw(g);
        gl.enable(gl.BLEND); gl.depthMask(false);
        for (const g of v.groups) if (g.blend === 'alpha') { gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); draw(g); }
        for (const g of v.groups) if (g.blend === 'add') { gl.blendFunc(gl.SRC_ALPHA, gl.ONE); draw(g); }
        gl.depthMask(true); gl.disable(gl.BLEND);
      }
      if (v.auto) v.yaw += .004;
      requestAnimationFrame(draw);
    }

    let drag = null, pinch = null;
    canvas.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; v.auto = false; canvas.setPointerCapture(e.pointerId); canvas.style.cursor = 'grabbing'; });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      v.yaw -= (e.clientX - drag[0]) * .008; v.pitch = Math.max(-1.5, Math.min(1.5, v.pitch + (e.clientY - drag[1]) * .008));
      drag = [e.clientX, e.clientY];
    });
    canvas.addEventListener('pointerup', () => { drag = null; canvas.style.cursor = 'grab'; });
    canvas.addEventListener('wheel', e => { e.preventDefault(); v.dist = Math.max(v.radius * .6, Math.min(v.radius * 8, v.dist * Math.exp(e.deltaY * .001))); }, {passive: false});
    canvas.addEventListener('touchmove', e => {
      if (e.touches.length !== 2) { pinch = null; return; }
      const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      if (pinch) v.dist = Math.max(v.radius * .6, Math.min(v.radius * 8, v.dist * pinch / d)); pinch = d;
    });
    canvas.addEventListener('dblclick', () => { reset(); v.auto = true; });

    v.view = name => { v.auto = false; [v.yaw, v.pitch] = {front: [0, .05], side: [Math.PI / 2, .05], top: [0, 1.5], back: [Math.PI, .1], three: [-2.4, .35]}[name]; };
    v.spin = on => { v.auto = on ?? !v.auto; };
    v.destroy = () => { v.alive = false; gl.getExtension('WEBGL_lose_context')?.loseContext(); };
    v.setColours = cols => { for (const g of v.groups) if (g.cls === 'paint' && cols.paint) g.col = cols.paint; else if (cols[g.cls]) g.col = cols[g.cls]; };
    v.load = async url => {
      const r = await fetch(url); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
      const buf = await r.arrayBuffer(), hl = new DataView(buf).getUint32(0, true);
      const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl))), base = 4 + hl;
      for (const g of v.groups) { gl.deleteVertexArray(g.vao); g.bufs.forEach(b => gl.deleteBuffer(b)); }
      v.groups = head.groups.map(g => {
        const pos = new Float32Array(buf, base + g.offset, g.vertices * 3), idx = new Uint32Array(buf, base + g.offset + g.vertices * 12, g.indices);
        const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
        const bufs = [pos, normals(pos, idx)].map((data, loc) => {
          const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
          const at = gl.getAttribLocation(prog, loc ? 'n' : 'p'); gl.enableVertexAttribArray(at); gl.vertexAttribPointer(at, 3, gl.FLOAT, false, 0, 0); return b;
        });
        const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW); bufs.push(ib);
        const c = CLASS[g.class] || CLASS.paint;
        return {cls: g.class, vao, bufs, count: g.indices, col: head.colours[g.class] || c.col || [.75, .75, .78],
                emit: c.emit || 0, spec: c.spec ?? .4, alpha: c.alpha ?? 1, blend: c.blend || null};
      });
      const [lo, hi] = head.bounds;
      v.center = [-(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
      v.radius = Math.max(.5, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
      reset();
      return head;
    };
    requestAnimationFrame(draw);
    return v;
  }
  window.ShipViewer = {mount};
})();
