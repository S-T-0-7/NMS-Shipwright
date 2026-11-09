/* Lightweight WebGL2 ship viewer: drag to orbit, wheel/pinch to zoom, double-click to reset.
   ShipViewer.mount(el) -> viewer; viewer.load(url) fetches the binary from /api/model (see model3d.pack). */
(function () {
  const VS = `#version 300 es
  in vec3 p; in vec3 n; in vec2 t; uniform mat4 mvp; uniform mat4 model;
  out vec3 vn; out vec3 vp; out vec2 vt;
  void main(){ vn = mat3(model) * n; vt = t; vp = (model * vec4(p,1.)).xyz; gl_Position = mvp * vec4(p,1.); }`;
  const FS = `#version 300 es
  precision highp float; in vec3 vn; in vec3 vp; in vec2 vt;
  uniform vec3 col; uniform vec3 eye; uniform float emit; uniform float spec; uniform float alpha;
  uniform sampler2D map; uniform float mapped; uniform float tint; out vec4 o;
  void main(){
    // The normals come from the game's own vertex data, smoothing and all. A geometry we could
    // not read them from arrives as zero, and then the face the triangle lies in has to do.
    vec3 V = normalize(eye - vp), F = normalize(cross(dFdx(vp), dFdy(vp)));
    if (dot(F, V) < 0.) F = -F;
    vec3 N = length(vn) > .5 ? normalize(vn) : F;
    if (dot(N, V) < 0.) N = -N;   // a one-sided panel seen from behind still faces the light
    vec3 L1 = normalize(vec3(.5,.8,.4)), L2 = normalize(vec3(-.6,.2,-.5));
    float d = max(dot(N,L1),0.)*.85 + max(dot(N,L2),0.)*.3 + .22 + .12*N.y;
    float s = pow(max(dot(N, normalize(L1+V)),0.), 40.) * spec;
    float rim = pow(1. - max(dot(N,V),0.), 3.) * .25;
    // The game's own map, used for its detail rather than its colour. A ship's colour comes
    // from the palette the seed picks and is laid on at paint time through the mask map, so the
    // colour map on its own is nothing like the ship you see -- the Fighter's reads teal. Its
    // light and shade is the real thing though: panel lines, grime, the wear around a vent.
    vec3 base = col;
    if (mapped > .5) {
      vec3 m = texture(map, vt).rgb;
      float lum = dot(m, vec3(.299, .587, .114));
      base = col * mix(1., lum * 1.7 + .25, tint);
    }
    vec3 c = base * d + vec3(s) + rim * vec3(.55,.65,.8);
    o = vec4(mix(c, base, emit), alpha);
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

  /* The game ships its textures block-compressed, which is the form the GPU wants, so the file
     goes to WebGL exactly as it comes out of the pak. Only the formats the spacecraft textures
     use are handled; anything else leaves that part drawn in flat colour. */
  const DDS = {BC1: ['WEBGL_compressed_texture_s3tc', 0x83F1, 8],
               BC2: ['WEBGL_compressed_texture_s3tc', 0x83F2, 16],
               BC3: ['WEBGL_compressed_texture_s3tc', 0x83F3, 16],
               BC4: ['EXT_texture_compression_rgtc', 0x8DBB, 8],
               BC5: ['EXT_texture_compression_rgtc', 0x8DBD, 16],
               BC7: ['EXT_texture_compression_bptc', 0x8E8C, 16]};
  const FOURCC = {0x31545844: 'BC1', 0x33545844: 'BC2', 0x35545844: 'BC3',
                  0x31495441: 'BC4', 0x32495441: 'BC5'};
  const DXGI = {70: 'BC1', 71: 'BC1', 72: 'BC1', 73: 'BC2', 74: 'BC2', 75: 'BC2', 76: 'BC3',
                77: 'BC3', 78: 'BC3', 79: 'BC4', 80: 'BC4', 82: 'BC5', 83: 'BC5',
                97: 'BC7', 98: 'BC7', 99: 'BC7'};

  /* The files themselves are kept for the life of the page. A GL texture belongs to its own
     context and dies with the viewer, but the download does not have to happen again: switching
     between two ships of a type would otherwise pull the same ten megabytes twice. */
  const files = new Map();
  function fileFor(path) {
    if (!files.has(path)) {
      files.set(path, fetch('/api/texture?path=' + encodeURIComponent(path))
        .then(r => (r.ok ? r.arrayBuffer() : null))
        .catch(() => null));
    }
    return files.get(path);
  }

  function readDDS(buf) {
    const v = new DataView(buf);
    if (buf.byteLength < 128 || v.getUint32(0, true) !== 0x20534444) return null;
    const height = v.getUint32(12, true), width = v.getUint32(16, true);
    const mips = Math.max(1, v.getUint32(28, true));
    const four = v.getUint32(84, true);
    let kind, offset;
    if (four === 0x30315844) { kind = DXGI[v.getUint32(128, true)]; offset = 148; }
    else { kind = FOURCC[four]; offset = 128; }
    return kind ? {kind, width, height, mips, offset} : null;
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
    const v = {yaw: -2.4, pitch: .35, dist: 1, auto: true, groups: [], center: [0, 0, 0], radius: 1,
               alive: true, tint: 1};
    const exts = {};
    const haveExt = name => (name in exts ? exts[name] : (exts[name] = gl.getExtension(name)));
    const maps = new Map();   // texture path -> WebGLTexture (or null once it is known to fail)

    /* One texture, uploaded mip by mip straight from the file. */
    function upload(buf) {
      const d = readDDS(buf);
      if (!d || !DDS[d.kind] || !haveExt(DDS[d.kind][0])) return null;
      const [, fmt, blockBytes] = DDS[d.kind];
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      let off = d.offset, w = d.width, h = d.height, level = 0;
      for (; level < d.mips; level++) {
        const size = Math.max(1, Math.ceil(w / 4)) * Math.max(1, Math.ceil(h / 4)) * blockBytes;
        if (off + size > buf.byteLength) break;
        gl.compressedTexImage2D(gl.TEXTURE_2D, level, fmt, w, h, 0,
                                new Uint8Array(buf, off, size));
        off += size; w = Math.max(1, w >> 1); h = Math.max(1, h >> 1);
      }
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER,
                       level > 1 ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_BASE_LEVEL, 0);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAX_LEVEL, Math.max(0, level - 1));
      return tex;
    }

    function mapFor(path) {
      if (!path) return null;
      if (maps.has(path)) return maps.get(path);
      maps.set(path, null);                       // flat colour until it arrives
      fileFor(path).then(buf => { if (buf && v.alive) maps.set(path, upload(buf)); });
      return null;
    }
    const reset = () => { v.yaw = -2.4; v.pitch = .35; v.dist = v.radius * 2.6; };
    // The HUD's Spin button follows the spin, which a drag or a view button also stops.
    const setAuto = on => { v.auto = on; v.onauto?.(on); };

    function frame() {
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
        gl.uniform1i(U('map'), 0);
        const draw = g => {
          gl.uniform3fv(U('col'), g.col); gl.uniform1f(U('emit'), g.emit);
          gl.uniform1f(U('spec'), g.spec); gl.uniform1f(U('alpha'), g.alpha);
          const tex = g.tex ? (maps.get(g.tex) || mapFor(g.tex)) : null;
          gl.uniform1f(U('mapped'), tex ? 1 : 0);
          gl.uniform1f(U('tint'), v.tint);
          if (tex) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); }
          gl.bindVertexArray(g.vao); gl.drawElements(gl.TRIANGLES, g.count, gl.UNSIGNED_INT, 0);
        };
        for (const g of v.groups) if (!g.blend) draw(g);
        gl.enable(gl.BLEND); gl.depthMask(false);
        for (const g of v.groups) if (g.blend === 'alpha') { gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); draw(g); }
        for (const g of v.groups) if (g.blend === 'add') { gl.blendFunc(gl.SRC_ALPHA, gl.ONE); draw(g); }
        gl.depthMask(true); gl.disable(gl.BLEND);
      }
      if (v.auto) v.yaw += .004;
    }
    function draw() {
      if (!v.alive) return;
      frame();
      requestAnimationFrame(draw);
    }

    let drag = null, pinch = null;
    canvas.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; setAuto(false); canvas.setPointerCapture(e.pointerId); canvas.style.cursor = 'grabbing'; });
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
    canvas.addEventListener('dblclick', () => { reset(); setAuto(true); });

    v.view = name => { setAuto(false); [v.yaw, v.pitch] = {front: [0, .05], side: [Math.PI / 2, .05], top: [0, 1.5], back: [Math.PI, .1], three: [-2.4, .35]}[name]; };
    v.spin = on => setAuto(on ?? !v.auto);
    v.setPose = on => { v.posed = on; return v.srcUrl ? v.load(v.srcUrl) : null; };  // flying vs landed
    v.destroy = () => { v.alive = false; gl.getExtension('WEBGL_lose_context')?.loseContext(); };
    /* A still of the ship as it stands. The frame is drawn and read in the same task, because
       the drawing buffer is cleared the moment the browser composites. */
    v.snapshot = (type = 'image/png') => { frame(); return canvas.toDataURL(type); };
    v.setColours = cols => { for (const g of v.groups) if (g.cls === 'paint' && cols.paint) g.col = cols.paint; else if (cols[g.cls]) g.col = cols[g.cls]; };
    v.load = async url => {
      v.srcUrl = url.replace(/&pose=flight\b/, '');  // remember the base so Fly/Land can reload it
      const r = await fetch(v.posed ? v.srcUrl + '&pose=flight' : v.srcUrl);
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
      const buf = await r.arrayBuffer(), hl = new DataView(buf).getUint32(0, true);
      const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl))), base = 4 + hl;
      for (const g of v.groups) { gl.deleteVertexArray(g.vao); g.bufs.forEach(b => gl.deleteBuffer(b)); }
      v.groups = head.groups.map(g => {
        const pos = new Float32Array(buf, base + g.offset, g.vertices * 3);
        const nrm = new Float32Array(buf, base + g.offset + g.vertices * 12, g.vertices * 3);
        const uv = new Float32Array(buf, base + g.offset + g.vertices * 24, g.vertices * 2);
        const idx = new Uint32Array(buf, base + g.offset + g.vertices * 32, g.indices);
        const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
        const bufs = [[pos, 'p', 3], [nrm, 'n', 3], [uv, 't', 2]].map(([data, name, size]) => {
          const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
          const at = gl.getAttribLocation(prog, name);
          if (at >= 0) { gl.enableVertexAttribArray(at); gl.vertexAttribPointer(at, size, gl.FLOAT, false, 0, 0); }
          return b;
        });
        const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW); bufs.push(ib);
        const c = CLASS[g.class] || CLASS.paint;
        if (g.tex) mapFor(g.tex);
        return {cls: g.class, tex: g.tex || '', vao, bufs, count: g.indices,
                col: head.colours[g.class] || c.col || [.75, .75, .78],
                emit: c.emit || 0, spec: c.spec ?? .4, alpha: c.alpha ?? 1, blend: c.blend || null};
      });
      v.posable = !!head.posable;  // the HUD shows Fly/Land only when the ship has a deploy anim
      const pb = v.elId && document.getElementById('pose-' + v.elId);
      if (pb) pb.style.display = v.posable ? '' : 'none';
      const [lo, hi] = head.bounds;
      v.center = [-(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
      v.radius = Math.max(.5, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
      if (!v.loaded) { reset(); v.loaded = true; }  // fit on the first model only; later loads keep
      return head;                                   // the user's angle/zoom (double-click resets)
    };
    requestAnimationFrame(draw);
    return v;
  }
  window.ShipViewer = {mount};
})();
