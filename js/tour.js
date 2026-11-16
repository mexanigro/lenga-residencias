// Recorrido en primera persona: una foto por ambiente, se mira arrastrando y se camina
// con puntos de paso. Las vistas se comparten entre tipologías (los pisos se repiten).
import { drawPlan } from './plan.js';

const $ = (s) => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

const LABEL = { living: 'Living', kitchen: 'Cocina', suite: 'Suite', bedroom: 'Dormitorio', bath: 'Baño', balcony: 'Balcón' };
// Puntos de paso sobre cada foto (% del ancho y alto de la imagen)
const SPOTS = {
  living: [['balcony', 52, 56], ['kitchen', 84, 46], ['suite', 15, 52], ['bedroom', 15, 64]],
  kitchen: [['living', 16, 58], ['balcony', 36, 46]],
  suite: [['balcony', 50, 50], ['bath', 84, 54], ['living', 16, 60]],
  bedroom: [['balcony', 52, 50], ['living', 16, 62]],
  bath: [['suite', 18, 60]],
  balcony: [['living', 50, 82]],
};
// Qué ambiente del plano corresponde a cada vista
const RULES = [
  ['living', (r) => /^(estar|comedor)/i.test(r[0])],
  ['kitchen', (r) => /^cocina/i.test(r[0])],
  ['suite', (r) => r[0] === 'Suite'],
  ['bedroom', (r) => /^(dormitorio|estudio|biblioteca)/i.test(r[0])],
  ['bath', (r) => r[0] === 'Baño'],
  ['balcony', (r) => r[5] === 'balcony'],
];
const src = (key) => `img/view-${key}.webp`;

export function openTour(cur, onClose) {
  const { u, t } = cur;
  const tour = $('#tour'), stage = $('#tourStage'), pano = $('#pano'), img = $('#panoA');
  const spots = $('#spots'), stopsNav = $('#tourStops'), map = $('#tourMap'), hint = $('#tourHint');
  const ac = new AbortController(), on = { signal: ac.signal };
  const stops = RULES.map(([key, test]) => { const room = t.plan.find(test); return room && { key, room }; }).filter(Boolean);
  stops.forEach((s) => { new Image().src = src(s.key); });

  let W = 0, range = 0, off = 0, vel = 0, current = null, busy = false, raf = 0;

  function layout() {
    const vw = innerWidth, vh = innerHeight;
    W = Math.max(vw * 1.3, vh * 1.5);
    const H = W / 1.5;
    pano.style.width = `${W}px`;
    pano.style.height = `${H}px`;
    pano.style.top = `${(vh - H) / 2}px`;
    range = (W - vw) / 2;
    off = Math.max(-range, Math.min(range, off));
    apply();
  }
  function apply() {
    pano.style.transform = `translateX(${-W / 2 + off}px)`;
    // el cono del mini plano gira según hacia dónde se mira
    const cone = map.querySelector('.cone');
    if (cone) cone.setAttribute('transform', cone.dataset.base + ` rotate(${(-off / (range || 1)) * 38})`);
  }

  /* mini plano con la posición */
  drawPlan(map, t, { areas: false });
  const marker = document.createElementNS(NS, 'g');
  map.appendChild(marker);
  function placeMarker(room) {
    const [, x, y, w, h] = room;
    const cx = x + w / 2, cy = y + h / 2;
    marker.innerHTML = `<path class="cone" data-base="translate(${cx} ${cy})" transform="translate(${cx} ${cy})" d="M0 0 L-2.2 -4.2 A4.7 4.7 0 0 1 2.2 -4.2 Z"/><circle class="me" cx="${cx}" cy="${cy}" r=".55"/>`;
  }

  /* ambientes */
  stopsNav.innerHTML = '';
  const stopBtns = stops.map((s) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = LABEL[s.key];
    b.addEventListener('click', () => go(s.key), on);
    stopsNav.appendChild(b);
    return b;
  });

  function render(key) {
    current = key;
    const s = stops.find((x) => x.key === key);
    $('#tTitle').textContent = LABEL[key];
    $('#tKicker').textContent = `Unidad ${u.id}, ${t.name}`;
    img.src = src(key);
    img.alt = `Vista en primera persona: ${LABEL[key].toLowerCase()} de la unidad ${u.id}`;
    stopBtns.forEach((b, i) => b.setAttribute('aria-current', stops[i].key === key ? 'true' : 'false'));
    spots.innerHTML = '';
    const seen = new Set();
    for (const [to, x, y] of SPOTS[key] || []) {
      if (seen.has(to) || !stops.some((s2) => s2.key === to)) continue;
      seen.add(to);
      const b = document.createElement('button');
      b.className = 'spot';
      b.type = 'button';
      b.style.left = `${x}%`;
      b.style.top = `${y}%`;
      b.innerHTML = `<i aria-hidden="true"></i><span>${LABEL[to]}</span>`;
      b.setAttribute('aria-label', `Ir a ${LABEL[to].toLowerCase()}`);
      b.addEventListener('click', (e) => { e.stopPropagation(); go(to, x, y); }, on);
      b.addEventListener('pointerdown', (e) => e.stopPropagation(), on);
      spots.appendChild(b);
    }
    placeMarker(s.room);
    off = 0;
    apply();
  }

  // caminar hacia el punto: la foto actual se agranda y se desvanece mientras entra la siguiente
  async function go(key, ox = 50, oy = 50) {
    if (busy || key === current) return;
    busy = true;
    const next = new Image();
    next.src = src(key);
    try { await next.decode(); } catch { /* si falla, igual cambia */ }
    if (!reduced) {
      const r = pano.getBoundingClientRect();
      const ghost = img.cloneNode();
      Object.assign(ghost.style, { position: 'fixed', left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px`, transformOrigin: `${ox}% ${oy}%`, zIndex: 1, pointerEvents: 'none', objectFit: 'cover' });
      stage.appendChild(ghost);
      render(key);
      ghost.animate([{ transform: 'scale(1)', opacity: 1 }, { transform: 'scale(1.7)', opacity: 0 }], { duration: 800, easing: 'cubic-bezier(.45,0,.2,1)' }).finished.then(() => ghost.remove());
      const base = pano.style.transform;
      await pano.animate([{ transform: `${base} scale(1.12)`, opacity: 0 }, { transform: `${base} scale(1)`, opacity: 1 }], { duration: 800, easing: 'cubic-bezier(.22,.8,.2,1)' }).finished;
    } else render(key);
    busy = false;
  }

  /* mirar alrededor */
  let drag = null;
  stage.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, off, t: performance.now() };
    vel = 0;
    stage.setPointerCapture(e.pointerId);
    stage.classList.add('is-drag');
    hint.classList.add('is-off');
  }, on);
  stage.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const now = performance.now();
    const next = Math.max(-range, Math.min(range, drag.off + (e.clientX - drag.x)));
    vel = (next - off) / Math.max(1, now - drag.t);
    drag.t = now;
    off = next;
    apply();
  }, on);
  const end = () => {
    if (!drag) return;
    drag = null;
    stage.classList.remove('is-drag');
    if (reduced) return;
    const coast = () => {
      vel *= 0.92;
      off = Math.max(-range, Math.min(range, off + vel * 16));
      apply();
      if (Math.abs(vel) > 0.02) raf = requestAnimationFrame(coast);
    };
    raf = requestAnimationFrame(coast);
  };
  stage.addEventListener('pointerup', end, on);
  stage.addEventListener('pointercancel', end, on);
  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    off = Math.max(-range, Math.min(range, off - (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY)));
    apply();
  }, { ...on, passive: false });
  window.addEventListener('resize', layout, on);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      if (e.target.closest?.('.tour__stops')) return;
      off = Math.max(-range, Math.min(range, off + (e.key === 'ArrowLeft' ? 90 : -90)));
      apply();
    }
  }, { ...on, capture: true });

  function close() {
    cancelAnimationFrame(raf);
    ac.abort();
    tour.hidden = true;
    onClose?.();
  }
  $('#tourClose').addEventListener('click', close, on);

  tour.hidden = false;
  hint.classList.remove('is-off');
  layout();
  render(stops[0].key);
  $('#tourClose').focus();
}
