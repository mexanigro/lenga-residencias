// Recorrido 360° del departamento modelo (renderizado en Blender, ver tools/depto.py).
// Cada ambiente es un panorama equirectangular. Para pasar de uno a otro se gira la vista hacia la puerta,
// se iguala el encuadre al del video del trayecto (mismo punto, misma dirección, mismo campo visual)
// y se reproduce el video; al terminar, el panorama de llegada queda exactamente donde terminó el video.
import * as THREE from 'three';
import { DEPTO } from './depto.js';

const VIEWS = DEPTO.views, MOVES = DEPTO.moves;
const wrap = (x) => ((x % 1) + 1) % 1;
const yawToU = (yaw) => wrap(0.5 + yaw / 360);
const uToYaw = (u) => ((((u - 0.5) * 360) % 360) + 540) % 360 - 180;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const dir = (u, v, out = new THREE.Vector3()) => {
  const th = Math.PI * v, ph = 2 * Math.PI * u;
  return out.set(Math.sin(th) * Math.cos(ph), Math.cos(th), Math.sin(th) * Math.sin(ph));
};

export function createPano(host, spotsLayer, { reduced = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.appendChild(renderer.domElement);
  // panorama de 6144 px donde la placa lo soporta; 4096 px en celulares y equipos chicos
  const big = renderer.capabilities.maxTextureSize >= 8192 && !matchMedia('(max-width: 900px)').matches;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(70, 1, 0.1, 100);
  const geo = new THREE.SphereGeometry(10, 128, 64);
  geo.scale(-1, 1, 1);
  const mk = () => {
    const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
    scene.add(m);
    return m;
  };
  let front = mk(), back = mk();

  const video = document.createElement('video');
  video.className = 'pano-move';
  video.muted = true;
  video.playsInline = true;
  video.preload = 'auto';
  video.setAttribute('aria-hidden', 'true');
  host.appendChild(video);

  // la imagen se decodifica fuera del hilo principal y se sube a la placa apenas llega (no al entrar al
  // ambiente), así el paso del video al panorama no se traba. Sin mipmaps: a esta escala no hacen falta.
  const loader = new THREE.ImageBitmapLoader();
  loader.setOptions({ imageOrientation: 'flipY' });
  const cache = new Map();
  const tex = (key) => {
    if (!cache.has(key)) {
      cache.set(key, loader.loadAsync(`img/pano/${key}${big ? '' : '-m'}.webp`).then((bmp) => {
        const t = new THREE.Texture(bmp);
        t.flipY = false;
        t.colorSpace = THREE.SRGBColorSpace;
        t.generateMipmaps = false;
        t.minFilter = THREE.LinearFilter;
        t.needsUpdate = true;
        renderer.initTexture(t);
        return t;
      }));
    }
    return cache.get(key);
  };
  const warmed = new Set();
  const warmMove = (name) => {
    if (warmed.has(name) || !MOVES[name]) return;
    warmed.add(name);
    fetch(`img/pano/move/${name}.mp4`).catch(() => {});
  };

  let u = 0.5, v = 0.5, fov = 70, fovTarget = 70, current = null, opts = {}, running = false, idle = 0, fade = null;
  let busy = false, tween = null, W = 1, H = 1;
  const look = new THREE.Vector3(), tmp = new THREE.Vector3();
  const baseFov = () => (W < H ? 88 : 70);
  // campo vertical que muestra lo mismo que el video del trayecto en esta pantalla (el video cubre todo)
  const moveFov = () => {
    const h = Math.tan((DEPTO.fov * Math.PI) / 360);
    const a = W / H;
    return (2 * Math.atan(a >= 16 / 9 ? h / a : (h * 9) / 16) * 180) / Math.PI;
  };

  function resize() {
    W = host.clientWidth;
    H = host.clientHeight;
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
    if (!busy) fovTarget = baseFov();
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(host);

  /* puntos de paso: botones DOM proyectados sobre la esfera */
  let spotEls = [];
  function buildSpots(key) {
    spotsLayer.innerHTML = '';
    spotEls = (VIEWS[key]?.spots || []).map(([to, x, y]) => {
      const b = document.createElement('button');
      b.className = 'pspot';
      b.type = 'button';
      b.innerHTML = `<i aria-hidden="true"></i><span>${VIEWS[to].label}</span>`;
      b.setAttribute('aria-label', `Ir a ${VIEWS[to].label.toLowerCase()}`);
      b.addEventListener('click', (e) => { e.stopPropagation(); opts.onGo?.(to); });
      b.addEventListener('pointerdown', (e) => e.stopPropagation());
      b.addEventListener('pointerenter', () => warmMove(`${current}-${to}`));
      spotsLayer.appendChild(b);
      return { el: b, p: dir(x / 100, y / 100).multiplyScalar(9) };
    });
  }

  /* mirar alrededor */
  let drag = null, vx = 0, vy = 0, dragged = false;
  const hint = document.getElementById('panoHint');
  host.addEventListener('pointerdown', (e) => {
    if (busy) return;
    drag = { x: e.clientX, y: e.clientY, t: performance.now() };
    vx = vy = 0;
    idle = -1;
    dragged = true;
    host.setPointerCapture(e.pointerId);
    host.classList.add('is-drag');
    hint?.classList.add('is-off');
  });
  host.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const k = (fov / 70) / Math.max(W, 1) * 0.32;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    u -= dx * k;
    v = Math.min(0.8, Math.max(0.2, v - dy * k * 1.6));
    const dt = Math.max(1, performance.now() - drag.t);
    vx = (-dx * k) / dt * 16;
    vy = (-dy * k * 1.6) / dt * 16;
    drag = { x: e.clientX, y: e.clientY, t: performance.now() };
  });
  const end = () => { if (!drag) return; drag = null; host.classList.remove('is-drag'); idle = 0; };
  host.addEventListener('pointerup', end);
  host.addEventListener('pointercancel', end);
  host.addEventListener('wheel', (e) => { e.preventDefault(); zoom(Math.sign(e.deltaY) * 6); }, { passive: false });
  document.addEventListener('keydown', (e) => {
    if (!running || busy || e.target.closest('input, textarea, .pano-bar')) return;
    const m = { ArrowLeft: [-0.02, 0], ArrowRight: [0.02, 0], ArrowUp: [0, -0.03], ArrowDown: [0, 0.03] }[e.key];
    if (!m) return;
    e.preventDefault();
    idle = -1;
    u += m[0];
    v = Math.min(0.8, Math.max(0.2, v + m[1]));
  });

  function zoom(d) { if (!busy) { fovTarget = Math.min(95, Math.max(35, fovTarget + d)); idle = -1; } }

  // anima la vista hacia (u, v, fov) por el camino corto
  function turnTo(tu, tv, tf, ms) {
    return new Promise((res) => {
      let du = wrap(tu - u);
      if (du > 0.5) du -= 1;
      tween = { u0: u, du, v0: v, dv: tv - v, f0: fov, df: tf - fov, t0: performance.now(), ms: reduced ? 1 : ms, res };
    });
  }

  let last = performance.now();
  function frame(now) {
    if (!running) return;
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (tween) {
      const t = Math.min(1, (now - tween.t0) / tween.ms), e = ease(t);
      u = tween.u0 + tween.du * e;
      v = tween.v0 + tween.dv * e;
      fov = fovTarget = tween.f0 + tween.df * e;
      if (t >= 1) { const r = tween.res; tween = null; r(); }
    } else if (!drag && !busy) {
      u += vx;
      v = Math.min(0.8, Math.max(0.2, v + vy));
      vx *= 0.92;
      vy *= 0.92;
      // giro muy lento mientras nadie toca
      if (idle >= 0) { idle += dt; if (idle > 4 && !reduced) u += dt * 0.005; }
      fov += (fovTarget - fov) * Math.min(1, dt * 8);
    }
    if (fade) {
      const t = Math.min(1, (now - fade.t0) / fade.ms), e = t * t * (3 - 2 * t);
      front.material.opacity = e;
      back.material.opacity = 1 - e;
      if (t >= 1) { back.material.opacity = 0; fade = null; }
    }
    draw();
  }
  function draw() {
    camera.fov = fov;
    camera.updateProjectionMatrix();
    camera.lookAt(dir(u, v, look));
    renderer.render(scene, camera);
    for (const s of spotEls) {
      tmp.copy(s.p).project(camera);
      const vis = !busy && tmp.z < 1 && Math.abs(tmp.x) < 1.1 && Math.abs(tmp.y) < 1.1;
      s.el.style.opacity = vis ? 1 : 0;
      s.el.style.pointerEvents = vis ? 'auto' : 'none';
      if (vis) s.el.style.transform = `translate(${(tmp.x * 0.5 + 0.5) * W}px, ${(-tmp.y * 0.5 + 0.5) * H}px) translate(-50%, -50%)`;
    }
    opts.onLook?.(uToYaw(u));
  }

  async function setRoom(key, t, { ms = 0, yaw = null } = {}) {
    [front, back] = [back, front];
    front.material.map = t;
    front.material.needsUpdate = true;
    front.material.opacity = ms ? 0 : 1;
    back.material.opacity = ms ? back.material.opacity : 0;
    fade = ms ? { t0: performance.now(), ms } : null;
    current = key;
    u = yawToU(yaw ?? VIEWS[key].start);
    v = 0.5;
    vx = vy = 0;
    idle = 0;
    buildSpots(key);
    // los vecinos se precargan un rato después, para que su subida a la placa no coincida con el empalme
    clearTimeout(preloadTimer);
    preloadTimer = setTimeout(() => { for (const [to] of VIEWS[key].spots) { tex(to); warmMove(`${key}-${to}`); } }, 1600);
  }
  let preloadTimer = 0;

  // camina de un ambiente al otro con el video del trayecto
  async function walk(to, { settle = true } = {}) {
    const name = `${current}-${to}`, m = MOVES[name];
    const target = tex(to);
    if (!m || reduced) { await setRoom(to, await target, { ms: reduced ? 1 : 700 }); return; }
    busy = true;
    host.classList.add('is-moving');
    video.src = `img/pano/move/${name}.mp4`;
    const ready = new Promise((r) => { video.oncanplaythrough = r; video.onerror = r; setTimeout(r, 2500); });
    video.load();
    // 1. girar hacia la puerta con el encuadre del video
    await turnTo(yawToU(m.from), 0.5, moveFov(), 650);
    await ready;
    // 2. el video toma el lugar del panorama (son el mismo cuadro) y camina
    video.currentTime = 0;
    video.classList.add('is-on');
    await video.play().catch(() => {});
    await new Promise((r) => { video.onended = r; setTimeout(r, (m.n / m.fps) * 1000 + 1500); });
    // 3. el panorama de llegada queda mirando hacia donde terminó el video
    await setRoom(to, await target, { yaw: m.to });
    fov = fovTarget = moveFov();
    draw(); // el panorama de llegada ya está dibujado debajo del último cuadro del video
    video.classList.remove('is-on');
    host.classList.remove('is-moving');
    busy = false;
    // entre tramos seguidos no se vuelve a abrir el encuadre: el próximo giro sale de acá
    // al llegar, la mirada se abre y gira hacia el encuadre principal del ambiente (como al entrar a un cuarto)
    if (settle) await turnTo(yawToU(VIEWS[to].start), 0.5, baseFov(), 1400);
  }

  return {
    async show(key, o) {
      opts = o;
      if (busy) return;
      if (!running) { running = true; last = performance.now(); resize(); requestAnimationFrame(frame); }
      if (current === null || !VIEWS[current]) {
        await setRoom(key, await tex(key), { ms: reduced ? 1 : 600 });
        fov = fovTarget = baseFov();
      } else if (key !== current) {
        // camino más corto por los ambientes conectados (living → suite → baño, por ejemplo)
        const prev = { [current]: null }, queue = [current];
        while (queue.length && !(key in prev)) {
          const at = queue.shift();
          for (const [to] of VIEWS[at].spots) if (!(to in prev)) { prev[to] = at; queue.push(to); }
        }
        const route = [];
        for (let k = key; k && k !== current; k = prev[k]) route.unshift(k);
        if (route.length && key in prev) for (const [i, step] of route.entries()) await walk(step, { settle: i === route.length - 1 });
        else await setRoom(key, await tex(key), { ms: reduced ? 1 : 700 });
      }
      if (!dragged) hint?.classList.remove('is-off');
    },
    pause() { running = false; video.pause(); },
    reset() { current = null; },
    zoom,
  };
}
