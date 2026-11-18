// Recorrido 3D del departamento modelo (tipo L2), en tiempo real.
// El modelo es el mismo de los renders (tools/depto.py) con la luz de Cycles horneada en texturas (tools/hornear.py):
// se ve igual desde cualquier punto, así que se puede caminar libre. Tres maneras de moverse:
//  · mirar arrastrando (o con flechas ← →), caminar con W A S D o las flechas ↑ ↓, como en un juego;
//  · tocar el piso: se camina hasta ahí esquivando paredes y muebles;
//  · tocar un ambiente (rótulo o barra): se camina hasta él pasando por las puertas.
// Coordenadas: Blender (x este, y norte, z arriba) → Three.js (x, z, −y). En el plano del sitio, (x, −y).
import * as THREE from 'three';
import { GLTFLoader } from './vendor/addons/GLTFLoader.js';
import { Reflector } from './vendor/addons/Reflector.js';
import { createRealism } from './realismo.js';
import { DEPTO3D } from './depto3d.js';

const R = 0.2; // radio del cuerpo: la cámara no se acerca más que esto a paredes y muebles (m)
const SPEED = 1.5; // caminando (m/s)
const GLIDE = 1.35; // al ir a un punto (m/s)
const CELL = 0.1; // grilla de caminos (m)
const EYE = DEPTO3D.eye ?? 1.55;
// punto de vista de cada ambiente (Blender x, y) y hacia dónde mira al llegar
const VIEWS = Object.fromEntries(Object.entries(DEPTO3D.views).map(([k, v]) => [k, { label: v.label, start: v.yaw, pos: v.pos }]));
// rótulos de los ambientes vecinos, puestos en la puerta que lleva a cada uno (Blender x, y; de tools/depto.py LINKS)
const DOORS = {
  living: [['kitchen', 9.7, -1.25], ['balcony', 4.5, -0.45], ['suite', 4.8, -4.25]],
  kitchen: [['living', 6.3, -3.2], ['balcony', 9.0, 0.55], ['bedroom', 10.8, -2.7]],
  balcony: [['living', 4.5, -0.45], ['kitchen', 7.6, 1.15]],
  suite: [['living', 4.5, -6.1], ['bath', 5.0, -6.45]],
  bath: [['suite', 4.0, -6.55]],
  bedroom: [['kitchen', 12.25, -4.75]],
};
// dónde se puede pisar (Blender x0, y0, x1, y1): el departamento y el balcón; paredes y muebles se restan después
const BOUNDS = [-0.4, -10.4, 13.4, 2.6];
const WALKABLE = [[0, -10, 13, 0], [-0.2, 0, 13.2, 2.33]]; // el contorno de DEPTO3D.walk en dos rectángulos
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const wrap180 = (d) => ((((d + 180) % 360) + 360) % 360) - 180;
// la mirada sigue al objetivo como una cabeza: suave y sin pasar de ~160°/s
const turnToward = (from, to, dt) => {
  const d = wrap180(to - from), max = 160 * dt;
  return wrap180(from + clamp(d * Math.min(1, dt * 4), -max, max));
};
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
// ambiente según la posición (Blender x, y)
const roomAt = (x, y) => {
  if (y > 0.05) return 'balcony';
  if (y > -5.6) return x < 7.6 ? 'living' : 'kitchen';
  if (x < 5) return 'suite';
  if (x < 9) return 'bath';
  return 'bedroom';
};

export function createPano(host, spotsLayer, { reduced = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  const small = matchMedia('(max-width: 900px)').matches;
  renderer.setPixelRatio(Math.min(devicePixelRatio, small ? 1.5 : 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping; // las texturas ya vienen con el revelado de los renders
  host.appendChild(renderer.domElement);
  // texturas de 2048 en celulares y equipos con poca memoria (las de 4096 ocupan ~500 MB de video)
  const lite = small || renderer.capabilities.maxTextureSize < 4096 || (navigator.deviceMemory || 8) < 8;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b151b);
  const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 2000);
  camera.rotation.order = 'YXZ';

  /* ---------------- carga del modelo ---------------- */
  let ready = null, realism = null, glassMat = null, mirrorSheet = null;
  const solids = [], glassMeshes = []; // lo que se puede tocar con un clic (todo menos vidrio y paisaje)
  function load() {
    if (ready) return ready;
    // son ~11 MB (8 en celulares): el cartel de ayuda muestra el avance mientras bajan
    const hint = document.getElementById('panoHint'), helpText = hint?.textContent;
    let glbPart = 0, texDone = 0;
    const texTotal = DEPTO3D.chunks.length + 1;
    const report = () => {
      if (hint) hint.textContent = `Cargando el departamento… ${Math.round(100 * (0.6 * glbPart + (0.4 * texDone) / texTotal))} %`;
    };
    report();
    const texLoader = new THREE.TextureLoader();
    const tex = (url) => texLoader.loadAsync(url).then((t) => {
      t.colorSpace = THREE.SRGBColorSpace;
      t.flipY = false; // UV de glTF
      t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      texDone++;
      report();
      return t;
    });
    const { glass: G, backdrop: B } = DEPTO3D;
    ready = Promise.all([
      new GLTFLoader().loadAsync(DEPTO3D.glb, (e) => { if (e.total) { glbPart = Math.min(1, e.loaded / e.total); report(); } }),
      Promise.all(DEPTO3D.chunks.map((c) => tex(lite ? c.texM : c.tex))),
      tex(B.vista.tex),
    ]).then(([gltf, maps, vista]) => {
      // un material por zona: la luz ya está en la textura, se muestra tal cual
      const mats = Object.fromEntries(DEPTO3D.chunks.map((c, i) => [c.name, new THREE.MeshBasicMaterial({ map: maps[i] })]));
      // vidrio: casi invisible de frente y con más reflejo (un gris neutro) cuanto más rasante se lo mira, como el real
      mats[G.material] = new THREE.MeshBasicMaterial({ color: 0x9fa6aa, transparent: true, opacity: G.opacity, depthWrite: false });
      mats[G.material].onBeforeCompile = (sh) => {
        sh.vertexShader = 'varying vec3 vGW;\n' + sh.vertexShader.replace('#include <project_vertex>',
          '#include <project_vertex>\n  vGW = (modelMatrix * vec4(transformed, 1.0)).xyz;');
        sh.fragmentShader = 'varying vec3 vGW;\n' + sh.fragmentShader.replace('#include <alphamap_fragment>', `#include <alphamap_fragment>
  {
    vec3 n = normalize(cross(dFdx(vGW), dFdy(vGW)));
    float c = abs(dot(n, normalize(cameraPosition - vGW)));
    diffuseColor.a *= 0.2 + 2.5 * (0.04 + 0.96 * pow(1.0 - c, 5.0));
  }`);
      };
      mats[B.vista.material] = new THREE.MeshBasicMaterial({ map: vista, side: THREE.DoubleSide });
      mats[B.agua.material] = new THREE.MeshBasicMaterial({ color: B.agua.color });
      glassMat = mats[G.material];
      gltf.scene.traverse((o) => {
        if (!o.isMesh) return;
        const name = o.material?.name;
        o.material = mats[name] ?? new THREE.MeshBasicMaterial({ color: 0x888888 });
        if (name === G.material) { o.renderOrder = 2; glassMeshes.push(o); }
        else if (DEPTO3D.chunks.some((c) => c.name === name)) solids.push(o);
        o.matrixAutoUpdate = false;
        o.updateMatrix();
      });
      scene.add(gltf.scene);
      gltf.scene.updateMatrixWorld(true);
      // reflejos y panoramas de Cycles sobre el horneado (js/realismo.js)
      realism = createRealism(renderer, scene, camera, {
        lite,
        captures: Object.entries(DEPTO3D.views).map(([key, v]) => ({ key, pos: v.pos, eye: EYE, url: `img/depto3d/pano-${key}${lite ? '-m' : ''}.webp` })),
        hide: () => [...glassMeshes, ring],
      });
      for (const c of DEPTO3D.chunks) realism.patch(mats[c.name]);
      // el espejo del baño no se puede hornear (depende de dónde se pare uno): refleja en tiempo real, sin panoramas
      // (vistos desde atrás del espejo quedarían corridos). Parado frente a él se ve el reflejo del render de Cycles:
      // una lámina con el panorama encima, que se apaga al alejarse.
      const esp = gltf.scene.getObjectByName('bano-espejo');
      if (esp) {
        const bb = new THREE.Box3().setFromObject(esp), size = bb.getSize(new THREE.Vector3()), c = bb.getCenter(new THREE.Vector3());
        const k = renderer.getPixelRatio() * 0.6;
        const mirror = new Reflector(new THREE.PlaneGeometry(size.x, size.y), {
          textureWidth: Math.round(innerWidth * k), textureHeight: Math.round(innerHeight * k), color: 0x7a7a7a,
        });
        mirror.position.set(c.x, c.y, bb.min.z - 0.002);
        mirror.rotation.y = Math.PI; // mira hacia el baño (−z en Three.js es el norte de Blender)
        const reflect = mirror.onBeforeRender;
        mirror.onBeforeRender = (...a) => { realism.suspend(); reflect(...a); realism.resume(); };
        scene.add(mirror);
        esp.visible = false;
        mirrorSheet = new THREE.Mesh(new THREE.PlaneGeometry(size.x, size.y), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0, depthWrite: false }));
        mirrorSheet.position.set(c.x, c.y, bb.min.z - 0.004);
        mirrorSheet.rotation.y = Math.PI;
        realism.patch(mirrorSheet.material);
        scene.add(mirrorSheet);
        glassMeshes.push(mirror, mirrorSheet); // se ocultan igual que el vidrio en las pasadas auxiliares
      }
      // subir texturas y shaders ahora, no en el primer cuadro (si no, el primer giro da un tirón)
      for (const t of [...maps, vista]) renderer.initTexture(t);
      renderer.compile(scene, camera);
      if (hint) hint.textContent = helpText;
    });
    return ready;
  }

  /* ---------------- colisiones y grilla de caminos ---------------- */
  // un punto está libre si queda dentro del depto y a más de R de toda caja (paredes y muebles)
  const open = (x, y) => {
    if (!WALKABLE.some(([x0, y0, x1, y1]) => x >= x0 && x <= x1 && y >= y0 && y <= y1)) return false;
    for (const [x0, y0, x1, y1] of DEPTO3D.boxes) {
      const dx = Math.max(x0 - x, 0, x - x1), dy = Math.max(y0 - y, 0, y - y1);
      if (dx * dx + dy * dy < R * R) return false;
    }
    return true;
  };
  // la grilla marca libre cada celda cuyo centro lo está (para buscar caminos)
  const [gx0, gy0, gx1, gy1] = BOUNDS;
  const GW = Math.ceil((gx1 - gx0) / CELL), GH = Math.ceil((gy1 - gy0) / CELL);
  const center = (i, j) => [gx0 + (i + 0.5) * CELL, gy0 + (j + 0.5) * CELL];
  const free = new Uint8Array(GW * GH);
  for (let j = 0; j < GH; j++) for (let i = 0; i < GW; i++) free[j * GW + i] = open(...center(i, j)) ? 1 : 0;
  const cellOf = (x, y) => [Math.floor((x - gx0) / CELL), Math.floor((y - gy0) / CELL)];
  const isFree = open;
  // la celda libre más cercana (para un toque sobre un mueble o una pared)
  function nearestFree(x, y, max = 1.2) {
    if (isFree(x, y)) return [x, y];
    const [ci, cj] = cellOf(x, y);
    const r = Math.ceil(max / CELL);
    let best = null, bd = Infinity;
    for (let j = cj - r; j <= cj + r; j++) for (let i = ci - r; i <= ci + r; i++) {
      if (i < 0 || j < 0 || i >= GW || j >= GH || !free[j * GW + i]) continue;
      const d = (i - ci) ** 2 + (j - cj) ** 2;
      if (d < bd) { bd = d; best = center(i, j); }
    }
    return best;
  }
  const sightFree = (a, b) => {
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.ceil(d / (CELL * 0.5));
    for (let k = 1; k < n; k++) if (!isFree(a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n)) return false;
    return true;
  };
  // A* en la grilla (8 vecinos) y después se tensa el camino uniendo los puntos que se ven entre sí
  function findPath(a, b) {
    const [si, sj] = cellOf(...a), [ti, tj] = cellOf(...b);
    if (si === ti && sj === tj) return [a, b];
    const N = GW * GH, g = new Float32Array(N).fill(Infinity), came = new Int32Array(N).fill(-1), closed = new Uint8Array(N);
    const target = tj * GW + ti;
    const h = (k) => Math.hypot((k % GW) - ti, Math.floor(k / GW) - tj);
    // cola de prioridad (montículo binario) de [f, celda]
    const heap = [];
    const push = (f, k) => {
      let n = heap.push([f, k]) - 1;
      while (n > 0) { const p = (n - 1) >> 1; if (heap[p][0] <= f) break; [heap[p], heap[n]] = [heap[n], heap[p]]; n = p; }
    };
    const pop = () => {
      const top = heap[0], last = heap.pop();
      if (heap.length) {
        heap[0] = last;
        for (let n = 0; ;) {
          const l = 2 * n + 1, r = l + 1;
          let m = n;
          if (l < heap.length && heap[l][0] < heap[m][0]) m = l;
          if (r < heap.length && heap[r][0] < heap[m][0]) m = r;
          if (m === n) break;
          [heap[m], heap[n]] = [heap[n], heap[m]];
          n = m;
        }
      }
      return top[1];
    };
    g[sj * GW + si] = 0;
    push(0, sj * GW + si);
    const ok = (k) => free[k] || k === target; // la meta puede ser un punto libre cuya celda no lo es del todo
    while (heap.length) {
      const k = pop();
      if (k === target) break;
      if (closed[k]) continue;
      closed[k] = 1;
      const i = k % GW, j = Math.floor(k / GW);
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        if (!di && !dj) continue;
        const ni = i + di, nj = j + dj;
        if (ni < 0 || nj < 0 || ni >= GW || nj >= GH) continue;
        const nk = nj * GW + ni;
        if (!ok(nk) || closed[nk]) continue;
        if (di && dj && (!ok(j * GW + ni) || !ok(nj * GW + i))) continue; // no cortar esquinas
        const ng = g[k] + (di && dj ? Math.SQRT2 : 1);
        if (ng < g[nk]) { g[nk] = ng; came[nk] = k; push(ng + h(nk), nk); }
      }
    }
    if (came[target] < 0) return null;
    const cells = [];
    for (let k = target; k >= 0; k = came[k]) cells.push(center(k % GW, Math.floor(k / GW)));
    cells.reverse();
    cells[0] = a;
    cells[cells.length - 1] = b;
    const out = [cells[0]];
    let i = 0;
    while (i < cells.length - 1) {
      let j = cells.length - 1;
      while (j > i + 1 && !sightFree(cells[i], cells[j])) j--;
      out.push(cells[j]);
      i = j;
    }
    return out;
  }

  /* ---------------- estado de la cámara ---------------- */
  let px = VIEWS.living.pos[0], py = VIEWS.living.pos[1]; // posición (Blender x, y)
  let yaw = VIEWS.living.start, pitch = -4, fov = 70, fovTarget = 70; // grados; yaw desde el norte, horario
  let vx = 0, vy = 0, wyaw = 0; // velocidades al caminar y al girar
  let glide = null, settle = null, placed = false, running = false, opts = {}, current = null, W = 1, H = 1, gen = 0;
  const keys = new Set();
  const baseFov = () => (W < H ? 88 : 72);

  function applyCamera() {
    camera.position.set(px, EYE, -py);
    camera.rotation.set(THREE.MathUtils.degToRad(pitch), -THREE.MathUtils.degToRad(yaw), 0);
    camera.fov = fov;
    camera.updateProjectionMatrix();
  }

  function resize() {
    W = host.clientWidth;
    H = host.clientHeight;
    renderer.setSize(W, H, false);
    camera.aspect = W / Math.max(1, H);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(host);

  /* ---------------- rótulos de los ambientes ---------------- */
  let spotEls = [], spotsFor = null;
  const tmp = new THREE.Vector3();
  function buildSpots(room) {
    if (spotsFor === room) return;
    spotsFor = room;
    spotsLayer.innerHTML = '';
    spotEls = (DOORS[room] || []).map(([to, x, y]) => {
      const b = document.createElement('button');
      b.className = 'pspot';
      b.type = 'button';
      b.innerHTML = `<i aria-hidden="true"></i><span>${VIEWS[to].label}</span>`;
      b.setAttribute('aria-label', `Ir a ${VIEWS[to].label.toLowerCase()}`);
      b.addEventListener('click', (e) => { e.stopPropagation(); opts.onGo?.(to); });
      b.addEventListener('pointerdown', (e) => e.stopPropagation());
      spotsLayer.appendChild(b);
      return { el: b, p: new THREE.Vector3(x, 0.95, -y) };
    });
  }
  function placeSpots() {
    const moving = glide || Math.hypot(vx, vy) > 0.2;
    for (const s of spotEls) {
      tmp.copy(s.p).project(camera);
      const hw = (s.w ||= s.el.offsetWidth || 120) / 2;
      const x = clamp((tmp.x * 0.5 + 0.5) * W, hw + 6, W - hw - 6), y = (-tmp.y * 0.5 + 0.5) * H;
      const dist = Math.hypot(s.p.x - px, -s.p.z - py);
      const vis = !moving && tmp.z < 1 && Math.abs(tmp.x) < 1 && Math.abs(tmp.y) < 1 && dist > 0.8;
      s.el.style.opacity = vis ? 1 : 0;
      s.el.style.pointerEvents = vis ? 'auto' : 'none';
      if (vis) s.el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
    }
  }

  /* ---------------- marca en el piso al apuntar ---------------- */
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.17, 0.22, 48).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false }),
  );
  ring.position.y = 0.012;
  ring.renderOrder = 3;
  scene.add(ring);
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const floorHit = (cx, cy) => {
    const r = host.getBoundingClientRect();
    ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.ray.intersectPlane(floorPlane, tmp);
    if (!hit || hit.distance > 14) return null;
    return [hit.x, -hit.z];
  };
  // un clic: adónde caminar. Se mide contra el modelo: si se toca el piso se va ahí; si se toca una pared o un
  // mueble, hasta quedar enfrente (y no al ambiente que está detrás)
  const clickTarget = (cx, cy) => {
    floorHit(cx, cy); // deja el rayo armado
    const hit = ray.intersectObjects(solids, false)[0];
    if (!hit || hit.distance > 14) return null;
    let x = hit.point.x, y = -hit.point.z;
    if (hit.point.y > 0.08) {
      const dx = x - px, dy = y - py, d = Math.hypot(dx, dy) || 1;
      x -= (dx / d) * 0.35;
      y -= (dy / d) * 0.35;
    }
    return [x, y];
  };

  /* ---------------- moverse ---------------- */
  function walkTo(target, { endYaw = null, speed = GLIDE } = {}) {
    const goal = nearestFree(target[0], target[1]);
    if (!goal) return Promise.resolve(false);
    const path = findPath([px, py], goal);
    if (!path) return Promise.resolve(false);
    // largo acumulado para recorrer el camino a velocidad pareja
    const cum = [0];
    for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]));
    const len = cum[cum.length - 1];
    if (len < 0.05 && endYaw == null) return Promise.resolve(true);
    // paso de persona: arranca y frena en ~0,4 s y en el medio va parejo (más rápido en los trayectos largos)
    const v = clamp(speed + 0.1 * len, speed, 2.2), ta = Math.min(0.4, len / v), T = reduced ? 0.001 : len / v + ta;
    return new Promise((res) => {
      glide?.res(false);
      settle?.res(false);
      settle = null;
      glide = { path, cum, len, t0: performance.now(), v, ta, T, endYaw, res };
      vx = vy = wyaw = 0;
    });
  }
  // distancia recorrida a los t segundos (perfil trapezoidal de velocidad)
  const travelled = (g, t) => {
    if (reduced || t >= g.T) return g.len;
    if (t < g.ta) return (g.v * t * t) / (2 * g.ta);
    if (t < g.T - g.ta) return g.v * (t - g.ta / 2);
    return g.len - (g.v * (g.T - t) ** 2) / (2 * g.ta);
  };
  const at = (g, s) => {
    const { path, cum } = g;
    if (s <= 0) return path[0];
    for (let i = 1; i < cum.length; i++) if (cum[i] >= s) {
      const f = (s - cum[i - 1]) / Math.max(1e-6, cum[i] - cum[i - 1]);
      return [path[i - 1][0] + (path[i][0] - path[i - 1][0]) * f, path[i - 1][1] + (path[i][1] - path[i - 1][1]) * f];
    }
    return path[path.length - 1];
  };

  /* ---------------- entrada ---------------- */
  let drag = null, pinch = null, idleLook = 0;
  const ptrs = new Map();
  const spread = () => { const [a, b] = [...ptrs.values()]; return Math.hypot(a[0] - b[0], a[1] - b[1]); };
  const hint = document.getElementById('panoHint');
  host.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    host.setPointerCapture(e.pointerId);
    hint?.classList.add('is-off');
    if (ptrs.size === 2) { pinch = spread(); drag = null; return; }
    drag = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: performance.now(), moved: false };
    host.classList.add('is-drag');
  });
  host.addEventListener('pointermove', (e) => {
    if (!ptrs.has(e.pointerId)) {
      // apuntar al piso con el mouse: aparece la marca de adónde se va a caminar
      if (e.pointerType === 'mouse' && running) hover = [e.clientX, e.clientY];
      return;
    }
    ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (pinch && ptrs.size >= 2) {
      const d = spread();
      fovTarget = clamp(fovTarget * (pinch / d), 35, 95);
      pinch = d;
      return;
    }
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) > 6) drag.moved = true;
    if (!drag.moved) return;
    const k = (fov / Math.max(H, 1)) * 1.05; // grados por píxel: lo que se arrastra queda bajo el dedo
    yaw = wrap180(yaw - dx * k);
    pitch = clamp(pitch + dy * k, -60, 55);
    drag.x = e.clientX;
    drag.y = e.clientY;
    hover = null;
    if (glide) { glide.res(false); glide = null; }
  });
  const end = (e) => {
    if (!ptrs.delete(e.pointerId)) return;
    if (ptrs.size < 2) pinch = null;
    if (ptrs.size === 1) { const [p] = ptrs.values(); drag = { x: p[0], y: p[1], x0: p[0], y0: p[1], t0: 0, moved: true }; return; }
    host.classList.remove('is-drag');
    // un toque (sin arrastrar) sobre el piso: caminar hasta ahí
    if (drag && !drag.moved && e.type === 'pointerup' && performance.now() - drag.t0 < 500) {
      const hit = clickTarget(e.clientX, e.clientY);
      if (hit) walkTo(hit).then((ok) => ok && opts.onMoved?.());
    }
    drag = null;
  };
  host.addEventListener('pointerup', end);
  host.addEventListener('pointercancel', end);
  host.addEventListener('lostpointercapture', end);
  host.addEventListener('pointerleave', () => { hover = null; });
  host.addEventListener('wheel', (e) => {
    e.preventDefault();
    const d = e.deltaY * (e.deltaMode === 1 ? 33 : 1);
    zoom(clamp(d * 0.06, -6, 6));
  }, { passive: false });
  let hover = null;

  const MOVE_KEYS = {
    KeyW: 'f', ArrowUp: 'f', KeyS: 'b', ArrowDown: 'b', KeyA: 'l', KeyD: 'r', ArrowLeft: 'tl', ArrowRight: 'tr',
  };
  document.addEventListener('keydown', (e) => {
    if (!running || e.metaKey || e.ctrlKey || e.altKey || e.target.closest?.('input, textarea, select, .pano-bar')) return;
    const m = MOVE_KEYS[e.code];
    if (!m) return;
    e.preventDefault();
    keys.add(m);
    if (e.shiftKey) keys.add('fast'); else keys.delete('fast');
    hint?.classList.add('is-off');
    if (glide) { glide.res(false); glide = null; }
  });
  document.addEventListener('keyup', (e) => { const m = MOVE_KEYS[e.code]; if (m) keys.delete(m); if (e.key === 'Shift') keys.delete('fast'); });
  addEventListener('blur', () => keys.clear());

  function zoom(d) { fovTarget = clamp(fovTarget + d, 35, 95); }

  /* ---------------- cuadro a cuadro ---------------- */
  let last = performance.now(), lastRoom = null, lookTimer = 0;
  function frame(now) {
    if (!running) return;
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;

    if (glide) {
      const el = (now - glide.t0) / 1000, s = travelled(glide, el);
      [px, py] = at(glide, s);
      // la mirada va hacia adelante en el camino y, en el último metro y medio, gira hacia el encuadre del ambiente
      const ahead = at(glide, Math.min(glide.len, s + 1.2));
      const dx = ahead[0] - px, dy = ahead[1] - py;
      let want = Math.hypot(dx, dy) > 0.15 ? (Math.atan2(dx, dy) * 180) / Math.PI : yaw;
      if (glide.endYaw != null) {
        const w = ease(clamp(1 - (glide.len - s) / 1.5, 0, 1));
        want = wrap180(want + wrap180(glide.endYaw - want) * w);
      }
      yaw = turnToward(yaw, want, dt);
      pitch += (-4 - pitch) * Math.min(1, dt * 3);
      if (el >= glide.T) {
        const g = glide;
        glide = null;
        // lo que falte del giro sigue al mismo ritmo, sin frenar (en trayectos cortos no alcanza el último metro y medio)
        if (g.endYaw != null && !reduced) settle = { yaw: g.endYaw, res: g.res };
        else { if (g.endYaw != null) yaw = g.endYaw; g.res(true); }
      }
    } else {
      if (settle) {
        const d = wrap180(settle.yaw - yaw);
        if (keys.size || drag?.moved || Math.abs(d) < 0.3) {
          if (!keys.size && !drag?.moved) yaw = settle.yaw;
          const r = settle.res;
          settle = null;
          r(true);
        } else yaw = turnToward(yaw, settle.yaw, dt);
      }
      // caminar: aceleración suave hacia la velocidad pedida, frena solo al soltar
      const sp = SPEED * (keys.has('fast') ? 1.7 : 1);
      const f = (keys.has('f') ? 1 : 0) - (keys.has('b') ? 1 : 0), st = (keys.has('r') ? 1 : 0) - (keys.has('l') ? 1 : 0);
      const ry = (yaw * Math.PI) / 180;
      let tx = (Math.sin(ry) * f + Math.cos(ry) * st) * sp, ty = (Math.cos(ry) * f - Math.sin(ry) * st) * sp;
      const n = Math.hypot(tx, ty);
      if (n > sp) { tx *= sp / n; ty *= sp / n; }
      const k = Math.min(1, dt * (n ? 7 : 9));
      vx += (tx - vx) * k;
      vy += (ty - vy) * k;
      const turnIn = (keys.has('tr') ? 1 : 0) - (keys.has('tl') ? 1 : 0);
      wyaw += (turnIn * 95 - wyaw) * Math.min(1, dt * 8);
      yaw = wrap180(yaw + wyaw * dt);
      // se mueve por ejes separados: contra una pared se desliza en vez de frenar en seco
      const nx = px + vx * dt, ny = py + vy * dt;
      if (isFree(nx, py)) px = nx; else vx = 0;
      if (isFree(px, ny)) py = ny; else vy = 0;
    }
    fov += (fovTarget - fov) * Math.min(1, dt * 8);

    // marca en el piso
    let ringOn = 0;
    if (hover && !drag && !glide) {
      const h = floorHit(...hover);
      if (h && nearestFree(h[0], h[1], 0.4)) { ring.position.x = h[0]; ring.position.z = -h[1]; ringOn = 0.55; }
    }
    ring.material.opacity += (ringOn - ring.material.opacity) * Math.min(1, dt * 12);

    applyCamera();
    if (realism) {
      realism.update(dt);
      glassMat.opacity = DEPTO3D.glass.opacity * (1 - 0.6 * realism.panoWeight); // el panorama ya trae el vidrio (no se apaga del todo: detrás de una columna sigue el horneado)
      if (mirrorSheet) mirrorSheet.material.opacity = realism.panoWeight;
    }
    renderer.render(scene, camera);
    if (current === null && !placed) return; // todavía cargando: el título y el mapa siguen en el ambiente pedido
    const room = roomAt(px, py);
    if (room !== lastRoom) {
      lastRoom = room;
      current = room;
      buildSpots(room);
      opts.onRoom?.(room);
    }
    placeSpots();
    lookTimer += dt;
    if (lookTimer > 0.05) { lookTimer = 0; opts.onLook?.(yaw, room, [px, -py]); }
  }

  return {
    // Ir a un ambiente: la primera vez aparece en su punto de vista; después se camina hasta él.
    async show(key, o) {
      opts = o;
      const g = ++gen;
      if (!running) {
        running = true;
        last = performance.now();
        resize();
        requestAnimationFrame(frame);
      }
      await load();
      if (g !== gen) return;
      const v = VIEWS[key];
      if (current === null) {
        [px, py] = nearestFree(...v.pos) ?? v.pos;
        yaw = v.start;
        pitch = -4;
        fov = fovTarget = baseFov();
        lastRoom = null;
        placed = true;
        host.classList.add('is-ready');
        return;
      }
      if (roomAt(px, py) === key && Math.hypot(px - v.pos[0], py - v.pos[1]) < 0.3) return;
      realism?.prefetch(key);
      await walkTo(v.pos, { endYaw: v.start });
    },
    pause() {
      running = false;
      gen++;
      glide?.res(false);
      settle?.res(false);
      glide = settle = null;
      keys.clear();
    },
    reset() {
      current = null;
      placed = false;
      lastRoom = null;
      spotsFor = null;
      host.classList.remove('is-ready');
    },
    zoom,
  };
}
