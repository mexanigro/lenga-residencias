// Visor 360° de un panorama equirectangular. La vista se maneja en coordenadas de la imagen:
// u (0..1, horizontal, da la vuelta) y v (0..1, vertical, 0.5 = horizonte).
import * as THREE from 'three';

// Puntos de paso en cada panorama: [ambiente destino, u %, v %] y dónde está el ventanal (para el mini plano)
const VIEWS = {
  living: { start: 0.5, window: 0.5, spots: [['balcony', 50, 54], ['kitchen', 77, 52], ['suite', 3, 50], ['bedroom', 12, 51]] },
  kitchen: { start: 0.55, window: 0.6, spots: [['balcony', 60, 46], ['living', 25, 52]] },
  suite: { start: 0.6, window: 0.64, spots: [['balcony', 64, 47], ['bath', 16, 47], ['living', 6, 50]] },
  bedroom: { start: 0.56, window: 0.58, spots: [['balcony', 58, 45], ['living', 10, 49]] },
  bath: { start: 0.5, window: 0.5, spots: [['suite', 91, 48]] },
  balcony: { start: 0.02, window: 0.0, spots: [['living', 50, 56]] },
};

const dir = (u, v, out = new THREE.Vector3()) => {
  const th = Math.PI * v, ph = 2 * Math.PI * u;
  return out.set(Math.sin(th) * Math.cos(ph), Math.cos(th), Math.sin(th) * Math.sin(ph));
};

export function createPano(host, spotsLayer, { reduced = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(78, 1, 0.1, 100);
  const geo = new THREE.SphereGeometry(10, 96, 64);
  geo.scale(-1, 1, 1);
  const mk = () => { const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })); scene.add(m); return m; };
  let front = mk(), back = mk();
  const loader = new THREE.TextureLoader();
  const cache = new Map();
  const tex = (key) => {
    if (!cache.has(key)) {
      cache.set(key, loader.loadAsync(`img/pano-${key}.webp`).then((t) => {
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = renderer.capabilities.getMaxAnisotropy();
        return t;
      }));
    }
    return cache.get(key);
  };

  let u = 0.5, v = 0.5, fov = 78, fovTarget = 78, current = null, opts = {}, running = false, idle = 0, fade = null;
  let W = 1, H = 1;
  const look = new THREE.Vector3(), tmp = new THREE.Vector3();

  function resize() {
    W = host.clientWidth; H = host.clientHeight;
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
    // en pantallas verticales, un poco más de campo para que no se sienta encerrado
    fovTarget = Math.max(fovTarget, W < H ? 88 : 0);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(host);

  /* puntos de paso */
  let spotEls = [];
  function buildSpots(key) {
    spotsLayer.innerHTML = '';
    spotEls = (VIEWS[key]?.spots || []).filter(([to]) => opts.available.includes(to)).map(([to, x, y]) => {
      const b = document.createElement('button');
      b.className = 'pspot';
      b.type = 'button';
      b.innerHTML = `<i aria-hidden="true"></i><span>${opts.label(to)}</span>`;
      b.setAttribute('aria-label', `Ir a ${opts.label(to).toLowerCase()}`);
      b.addEventListener('click', (e) => { e.stopPropagation(); opts.onGo(to); });
      b.addEventListener('pointerdown', (e) => e.stopPropagation());
      spotsLayer.appendChild(b);
      return { el: b, p: dir(x / 100, y / 100).multiplyScalar(9) };
    });
  }

  /* mirar alrededor */
  let drag = null, vx = 0, vy = 0, dragged = false;
  const el = renderer.domElement;
  host.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, y: e.clientY, t: performance.now() };
    vx = vy = 0; idle = -1; dragged = true;
    host.setPointerCapture(e.pointerId);
    host.classList.add('is-drag');
    hint?.classList.add('is-off');
  });
  host.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const k = (fov / 78) / Math.max(W, 1) * 0.36;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    u -= dx * k; v = Math.min(0.78, Math.max(0.22, v - dy * k * 1.6));
    const dt = Math.max(1, performance.now() - drag.t);
    vx = -dx * k / dt * 16; vy = -dy * k * 1.6 / dt * 16;
    drag = { x: e.clientX, y: e.clientY, t: performance.now() };
  });
  const end = () => { if (!drag) return; drag = null; host.classList.remove('is-drag'); idle = 0; };
  host.addEventListener('pointerup', end);
  host.addEventListener('pointercancel', end);
  host.addEventListener('wheel', (e) => { e.preventDefault(); zoom(Math.sign(e.deltaY) * 6); }, { passive: false });
  const keys = (e) => {
    if (!running || e.target.closest('input, textarea')) return;
    const m = { ArrowLeft: [-0.02, 0], ArrowRight: [0.02, 0], ArrowUp: [0, -0.03], ArrowDown: [0, 0.03] }[e.key];
    if (!m || e.target.closest('.pano-bar')) return;
    e.preventDefault(); idle = -1;
    u += m[0]; v = Math.min(0.78, Math.max(0.22, v + m[1]));
  };
  document.addEventListener('keydown', keys);
  const hint = document.getElementById('panoHint');

  function zoom(d) { fovTarget = Math.min(95, Math.max(38, fovTarget + d)); idle = -1; }

  let last = performance.now();
  function frame(now) {
    if (!running) return;
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!drag) {
      u += vx; v = Math.min(0.78, Math.max(0.22, v + vy));
      vx *= 0.92; vy *= 0.92;
      // giro muy lento mientras nadie toca
      if (idle >= 0) { idle += dt; if (idle > 3 && !reduced) u += dt * 0.006; }
    }
    fov += (fovTarget - fov) * Math.min(1, dt * 8);
    camera.fov = fov;
    camera.updateProjectionMatrix();
    camera.lookAt(dir(u, v, look));
    if (fade) {
      const t = Math.min(1, (now - fade.t0) / fade.ms), e = t * t * (3 - 2 * t);
      front.material.opacity = e;
      back.material.opacity = 1 - e;
      camera.fov = fov - (1 - e) * 14; // sensación de avanzar hacia el próximo ambiente
      camera.updateProjectionMatrix();
      if (t >= 1) { back.material.opacity = 0; fade = null; }
    }
    renderer.render(scene, camera);
    for (const s of spotEls) {
      tmp.copy(s.p).project(camera);
      const vis = tmp.z < 1 && Math.abs(tmp.x) < 1.2 && Math.abs(tmp.y) < 1.2;
      s.el.style.opacity = vis ? 1 : 0;
      s.el.style.pointerEvents = vis ? 'auto' : 'none';
      if (vis) s.el.style.transform = `translate(${(tmp.x * 0.5 + 0.5) * W}px, ${(-tmp.y * 0.5 + 0.5) * H}px) translate(-50%, -50%)`;
    }
    const w = VIEWS[current]?.window ?? 0.5;
    opts.onLook?.((((u - w) % 1) + 1.5) % 1 * 360 - 180);
  }

  return {
    async show(key, o) {
      opts = o;
      const first = current === null;
      const t = await tex(key);
      if (key !== current) {
        [front, back] = [back, front];
        front.material.map = t;
        front.material.needsUpdate = true;
        front.material.opacity = 0;
        fade = { t0: performance.now(), ms: reduced ? 1 : first ? 600 : 900 };
        current = key;
        u = VIEWS[key]?.start ?? 0.5; v = 0.5; vx = vy = 0; idle = 0;
        buildSpots(key);
      }
      if (!running) { running = true; last = performance.now(); resize(); requestAnimationFrame(frame); }
      if (!dragged) hint?.classList.remove('is-off');
      // precarga los ambientes vecinos
      (VIEWS[key]?.spots || []).forEach(([to]) => { if (o.available.includes(to)) tex(to); });
    },
    pause() { running = false; },
    zoom,
  };
}
