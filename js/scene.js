import * as THREE from 'three';
import { FLOORS, FLOOR_H, PODIUM_H } from './data.js';

const DEG = Math.PI / 180;
const BG = new THREE.Color('#0F2B33');
const WHITE = new THREE.Color('#ffffff');
const SLAB = new THREE.Color('#E4EBE9');
const SLAB_T = 0.5;

/* ---------- terreno (ruido determinístico, mismo resultado en cada carga) ---------- */
function hash(x, y) {
  let h = (x * 374761393 + y * 668265263) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}
function noise(x, y) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x, y) {
  let s = 0, a = 0.5, f = 1;
  for (let i = 0; i < 5; i++) { s += a * noise(x * f, y * f); f *= 2.03; a *= 0.5; }
  return s / 0.97;
}
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const clamp01 = (x) => Math.min(1, Math.max(0, x));

// El lago queda al norte (-z). La torre está en el origen, sobre la costa sur.
const LAKE = { x: 10, z: -170, rx: 230, rz: 150 };
export function terrainHeight(x, z) {
  const qx = (x - LAKE.x) / LAKE.rx, qz = (z - LAKE.z) / LAKE.rz;
  const n = fbm(x * 0.0045 + 3.1, z * 0.0045 + 7.7);
  const d = Math.hypot(qx, qz) + (n - 0.5) * 0.35;
  let h = (d - 1) * 30;
  const ridge = 1 - Math.abs(fbm(x * 0.008 + 11, z * 0.008 - 4) * 2 - 1);
  h += smooth(1.15, 2.4, d) * (130 * fbm(x * 0.006 - 5, z * 0.006 + 2) + 100 * ridge * ridge);
  const r = Math.hypot(x, z);
  return h + (2 - h) * (1 - smooth(26, 60, r)); // lote plano de la torre
}

/* ---------- geometría ---------- */
function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}
// Extruye una forma de planta (x, y=sur) hacia arriba: y de la planta → z del mundo.
function extrudeUp(shape, depth) {
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 5 });
  g.rotateX(Math.PI / 2);
  g.translate(0, depth, 0);
  return g;
}

function windowTexture() {
  const c = document.createElement('canvas'); c.width = 1024; c.height = 64;
  const x = c.getContext('2d');
  x.fillStyle = '#000'; x.fillRect(0, 0, 1024, 64);
  const cw = 32;
  for (let i = 0; i < 32; i++) {
    const r = Math.random();
    if (r < 0.34) {
      x.globalAlpha = 0.45 + Math.random() * 0.55;
      x.fillStyle = r < 0.14 ? '#FFC77D' : '#B87A3C';
      x.fillRect(i * cw + 2, 4, cw - 4, 60);
      x.globalAlpha = 1;
    }
    x.fillStyle = '#1F3539'; x.fillRect(i * cw, 0, 2, 64);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

const TERRAIN_VERT = /* glsl */`
varying float vH; varying vec3 vW; varying float vD;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vW = w.xyz; vH = position.y;
  vec4 mv = viewMatrix * w; vD = -mv.z;
  gl_Position = projectionMatrix * mv;
}`;
const TERRAIN_FRAG = /* glsl */`
uniform vec3 uBg; uniform vec3 uLand; uniform vec3 uLine; uniform vec3 uWater; uniform vec3 uSun;
uniform float uReveal; uniform float uNear; uniform float uFar;
varying float vH; varying vec3 vW; varying float vD;
float iso(float v, float w) {
  float f = abs(fract(v - 0.5) - 0.5) / max(fwidth(v), 1e-5);
  return 1.0 - smoothstep(0.0, w, f);
}
void main() {
  vec3 n = normalize(cross(dFdx(vW), dFdy(vW)));
  if (n.y < 0.0) n = -n;
  float sh = clamp(dot(n, normalize(uSun)), 0.0, 1.0);
  float rev = 1.0 - smoothstep(uReveal - 180.0, uReveal, length(vW.xz));
  vec3 col;
  if (vH < 0.0) {
    float dep = -vH;
    col = mix(uWater * 1.25, uWater, smoothstep(0.0, 22.0, dep));
    float b = iso(dep / 4.0, 1.0) * (1.0 - smoothstep(4.0, 26.0, dep)) * 0.28;
    col = mix(col, uLine, b * rev);
  } else {
    col = uLand * (0.55 + 0.65 * sh);
    float mi = iso(vH / 5.0, 1.0);
    float ma = iso(vH / 25.0, 1.6);
    col = mix(col, uLine, (mi * 0.3 + ma * 0.62) * rev);
  }
  float shore = 1.0 - smoothstep(0.0, 1.8, abs(vH) / max(fwidth(vH), 1e-5));
  col = mix(col, uLine * 1.2, shore * 0.9 * rev);
  gl_FragColor = vec4(mix(col, uBg, smoothstep(uNear, uFar, vD)), 1.0);
  #include <colorspace_fragment>
}`;

// Recorrido de cámara durante el descenso (s = progreso del scroll)
const KEYS = [
  { s: 0.00, p: [30, 620, -330], t: [0, 0, -150] },
  { s: 0.30, p: [-280, 250, -400], t: [0, 10, -40] },
  { s: 0.58, p: [-150, 88, -205], t: [0, 26, 0] },
  { s: 0.82, p: [-70, 40, -185], t: [0, 30, 0] },
  { s: 1.00, p: [0, 9, -132], t: [0, 32.5, 0] }, // mismo encuadre que el render
];
const ease = (t) => t * t * (3 - 2 * t);
function sample(keys, s, outP, outT) {
  let i = 0;
  while (i < keys.length - 2 && s > keys[i + 1].s) i++;
  const a = keys[i], b = keys[i + 1];
  const t = ease(clamp01((s - a.s) / (b.s - a.s)));
  outP.set(...a.p).lerp(new THREE.Vector3(...b.p), t);
  outT.set(...a.t).lerp(new THREE.Vector3(...b.t), t);
}

// Encuadre del render fotorrealista: el descenso termina acá para fundirse con la imagen
export const SHOT = { p: [-38, 20, -140], t: [0, 31, 0] };

export function createScene(canvas, { reduced = false, shot = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: shot });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
  renderer.setClearColor(shot ? '#E9EDEC' : BG);

  const scene = new THREE.Scene();
  scene.fog = shot ? null : new THREE.Fog(BG, 320, 1050);
  const env = [];
  const camera = new THREE.PerspectiveCamera(35, 1, 1, 3000);

  scene.add(new THREE.HemisphereLight(0xC4DCE2, 0x0F2B33, 1.5));
  const sun = new THREE.DirectionalLight(0xFFDDB0, 2.4);
  sun.position.set(-140, 170, -220);
  scene.add(sun);

  /* terreno */
  const tg = new THREE.PlaneGeometry(1700, 1700, 300, 300);
  tg.rotateX(-Math.PI / 2);
  const pos = tg.attributes.position;
  for (let i = 0; i < pos.count; i++) pos.setY(i, terrainHeight(pos.getX(i), pos.getZ(i)));
  const terrainMat = new THREE.ShaderMaterial({
    vertexShader: TERRAIN_VERT, fragmentShader: TERRAIN_FRAG,
    uniforms: {
      uBg: { value: BG }, uLand: { value: new THREE.Color('#1B3D46') }, uLine: { value: new THREE.Color('#7FB0AA') },
      uWater: { value: new THREE.Color('#0B2229') }, uSun: { value: new THREE.Vector3(-0.5, 0.7, -0.6) },
      uReveal: { value: reduced ? 4000 : 0 }, uNear: { value: 380 }, uFar: { value: 1100 },
    },
  });
  env.push(scene.add(new THREE.Mesh(tg, terrainMat)).children.at(-1));

  /* bosque: punteado cartográfico */
  {
    const pts = [];
    for (let i = 0; i < 16000 && pts.length < 7000 * 3; i++) {
      const x = (Math.random() - 0.5) * 1300, z = (Math.random() - 0.5) * 1300;
      const h = terrainHeight(x, z);
      if (h < 3 || h > 140 || Math.hypot(x, z) < 40) continue;
      if (fbm(x * 0.012, z * 0.012) < 0.47) continue;
      pts.push(x, h + 0.8, z);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    env.push(scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x3E6D69, size: 2, sizeAttenuation: true }))).children.at(-1));
  }

  /* pueblo: volúmenes bajos sobre la costa oeste */
  const town = { x: 0, z: 0, n: 0 };
  {
    const box = new THREE.BoxGeometry(1, 1, 1); box.translate(0, 0.5, 0);
    const mesh = new THREE.InstancedMesh(box, new THREE.MeshStandardMaterial({ color: 0x9DB4B0, roughness: 0.9 }), 220);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    let k = 0;
    for (let i = 0; i < 6000 && k < 220; i++) {
      const x = -110 - Math.random() * 220, z = -70 + Math.random() * 160;
      const h = terrainHeight(x, z);
      if (h < 1.2 || h > 22) continue;
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.random() * 0.6);
      s.set(3 + Math.random() * 3, 2.5 + Math.random() * 3.5, 3 + Math.random() * 3);
      p.set(x, h - 0.5, z);
      mesh.setMatrixAt(k++, m.compose(p, q, s));
      town.x += x; town.z += z; town.n++;
    }
    mesh.count = k;
    scene.add(mesh);
    env.push(mesh);
    town.x /= town.n || 1; town.z /= town.n || 1;
  }

  /* muelle */
  {
    const pier = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.6, 46), new THREE.MeshStandardMaterial({ color: 0xC9D6D2 }));
    pier.position.set(-34, 0.4, -46);
    scene.add(pier);
    env.push(pier);
  }

  /* torre */
  const tower = new THREE.Group();
  scene.add(tower);
  const geo = {
    slab: extrudeUp(roundedRect(26, 26, 3.2), SLAB_T),
    glass: extrudeUp(roundedRect(23.2, 23.2, 1.8), FLOOR_H - SLAB_T),
    pSlab: extrudeUp(roundedRect(40, 36, 2.5), SLAB_T),
    pGlass: extrudeUp(roundedRect(37.6, 33.6, 1.5), PODIUM_H - SLAB_T),
  };
  geo.slabEdges = new THREE.EdgesGeometry(geo.slab, 25);
  geo.pEdges = new THREE.EdgesGeometry(geo.pSlab, 25);
  const winTex = windowTexture();

  const floors = FLOORS.map((f, i) => {
    const club = f.zone === 'club';
    const group = new THREE.Group();
    group.position.y = club ? (f.n - 1) * PODIUM_H : 2 * PODIUM_H + (f.n - 3) * FLOOR_H;
    group.rotation.y = -f.rot * DEG; // horario visto desde arriba
    const tex = winTex.clone();
    const gh = club ? PODIUM_H - SLAB_T : FLOOR_H - SLAB_T;
    tex.repeat.set(1 / 30, 1 / gh); tex.offset.set(Math.random(), 1 - 1 / gh);
    const slabMat = new THREE.MeshStandardMaterial({ color: SLAB.clone(), roughness: 0.8, transparent: true });
    const glassMat = new THREE.MeshStandardMaterial({ color: 0x1D4550, roughness: 0.22, metalness: 0.35, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.9, transparent: true });
    const edgeMat = new THREE.LineBasicMaterial({ color: WHITE.clone(), transparent: true, opacity: 0.35 });
    const slab = new THREE.Mesh(club ? geo.pSlab : geo.slab, slabMat);
    const glass = new THREE.Mesh(club ? geo.pGlass : geo.glass, glassMat);
    glass.position.y = SLAB_T;
    const edges = new THREE.LineSegments(club ? geo.pEdges : geo.slabEdges, edgeMat);
    group.add(slab, glass, edges);
    if (f.n === 18) {
      const roof = new THREE.Mesh(geo.slab, slabMat);
      roof.position.y = FLOOR_H;
      const roofEdges = new THREE.LineSegments(geo.slabEdges, edgeMat);
      roofEdges.position.y = FLOOR_H;
      group.add(roof, roofEdges);
    }
    if (f.n === 1) {
      const door = new THREE.Mesh(new THREE.PlaneGeometry(9, 2.9), new THREE.MeshBasicMaterial({ color: 0xFFD49A }));
      door.position.set(0, SLAB_T + 1.45, -16.85);
      door.rotation.y = Math.PI;
      const canopy = new THREE.Mesh(new THREE.BoxGeometry(14, 0.3, 4), slabMat);
      canopy.position.set(0, SLAB_T + 3.05, -18.6);
      group.add(door, canopy);
    }
    tower.add(group);
    return {
      f, i, group, slab, glass, edges, slabMat, glassMat, edgeMat,
      baseY: group.position.y, baseRot: group.rotation.y,
    };
  });
  // Maqueta limpia para usar de referencia: sin terreno, vidrio liso, línea oscura
  if (shot) {
    env.forEach((o) => { o.visible = false; });
    const ground = new THREE.Mesh(new THREE.CircleGeometry(260, 64), new THREE.MeshStandardMaterial({ color: 0xD8DEDC, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    const water = new THREE.Mesh(new THREE.PlaneGeometry(600, 300), new THREE.MeshStandardMaterial({ color: 0x9FB6B8, roughness: 0.3 }));
    water.rotation.x = -Math.PI / 2; water.position.set(0, 0.05, -175);
    scene.add(ground, water);
    for (const fl of floors) {
      fl.glassMat.emissiveIntensity = 0.12;
      fl.glassMat.color.set('#7F99A0');
      fl.edgeMat.color.set('#3A4547'); fl.edgeMat.opacity = 0.8;
    }
  }

  /* estado controlado desde main.js */
  const state = { story: 0, build: 0, active: true };
  const cam = { p: new THREE.Vector3(...KEYS[0].p), t: new THREE.Vector3(...KEYS[0].t) };
  const want = { p: new THREE.Vector3(), t: new THREE.Vector3() };
  let W = 1, H = 1;
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
  }
  resize();
  window.addEventListener('resize', resize);

  const damp = (a, b, k, dt) => a + (b - a) * (1 - Math.exp(-k * dt));
  let last = performance.now();
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!state.active) return;

    if (shot) { state.build = 1; want.p.set(...SHOT.p); want.t.set(...SHOT.t); }
    else sample(KEYS, state.story, want.p, want.t);
    // en pantallas verticales, retroceder para que entre la torre
    if (!shot && W / H < 0.8) want.p.sub(want.t).multiplyScalar(1 + 0.5 * smooth(0.5, 1, state.story)).add(want.t);
    const k = reduced || shot ? 60 : 9;
    for (const ax of ['x', 'y', 'z']) {
      cam.p[ax] = damp(cam.p[ax], want.p[ax], k, dt);
      cam.t[ax] = damp(cam.t[ax], want.t[ax], k, dt);
    }
    camera.position.copy(cam.p);
    camera.lookAt(cam.t);

    // la torre se arma piso a piso: cada losa cae girando hasta su lugar
    const N = floors.length;
    for (const fl of floors) {
      const a = ease(clamp01((state.build - (fl.i / N) * 0.78) / 0.22));
      fl.group.visible = a > 0.005;
      if (!fl.group.visible) continue;
      fl.group.position.y = fl.baseY + (1 - a) * 34;
      fl.group.rotation.y = fl.baseRot + (1 - a) * 0.8;
      fl.slabMat.opacity = a;
      fl.glassMat.opacity = a * 0.96;
      fl.edgeMat.opacity = a * (shot ? 0.8 : 0.35);
    }
    renderer.render(scene, camera);
    api.onFrame?.();
  }
  requestAnimationFrame(frame);

  const v = new THREE.Vector3();
  function toScreen(p) {
    v.set(p[0], p[1], p[2]).project(camera);
    return { x: (v.x * 0.5 + 0.5) * W, y: (-v.y * 0.5 + 0.5) * H, on: v.z < 1 && v.z > -1 };
  }
  function metrics() {
    const d = cam.p.distanceTo(cam.t);
    const worldH = 2 * d * Math.tan((camera.fov * DEG) / 2);
    return { alt: Math.max(0, Math.round(cam.p.y)), px100: (100 / worldH) * H };
  }

  // la cumbre más alta detrás de la torre, para la etiqueta
  let peak = [0, 0, 300], best = -1;
  for (let x = -260; x <= 260; x += 10) for (let z = 140; z <= 460; z += 10) {
    const h = terrainHeight(x, z);
    if (h > best) { best = h; peak = [x, h + 6, z]; }
  }
  const labels = [
    { text: 'Lago Ilén', cls: 'water', pos: [-40, 0, -110] },
    { text: 'Puerto Ilén', cls: 'town', pos: [town.x, 10, town.z] },
    { text: 'Cerro Ilén', cls: 'peak', pos: peak },
    { text: 'Lenga', cls: 'site', pos: [0, 2, 0] },
  ];

  const api = {
    state, toScreen, metrics, labels,
    reveal(val) { terrainMat.uniforms.uReveal.value = val; },
    onFrame: null,
  };
  return api;
}
