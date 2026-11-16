import { FLOOR_ZONES } from './zones.js';
import { LQIP } from './assets.js';
import { initBuilding } from './building.js';

const $ = (s) => document.querySelector(s);
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const ease = (t) => t * t * (3 - 2 * t);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const NS = 'http://www.w3.org/2000/svg';

/* ================= carga inicial =================
   Se ve al instante una versión borrosa de la primera toma; la barra avanza con la carga
   real de las imágenes del recorrido y al terminar la toma aérea aparece nítida. */
$('#loaderBg').style.backgroundImage = `url(${LQIP})`;
const CRITICAL = ['img/aerea-1.webp', 'img/aerea-2.webp', 'img/lote.webp', 'img/torre.webp'];
let target = 0, shown = 0, done = 0;
const bar = $('#loaderBar'), pct = $('#loaderPct');
const step = () => { done++; target = done / (CRITICAL.length + 1); };
(function tick() {
  shown += (target - shown) * (reduced ? 1 : 0.07);
  if (target - shown < 0.002) shown = target;
  bar.style.width = `${shown * 100}%`;
  pct.textContent = Math.round(shown * 100);
  if (shown < 1) requestAnimationFrame(tick);
})();
await Promise.all([
  document.fonts.ready.then(step),
  ...CRITICAL.map((src) => new Promise((r) => { const i = new Image(); i.onload = i.onerror = r; i.src = src; }).then(step)),
]);
await Promise.race([
  new Promise((r) => { const w = () => (shown >= 1 ? r() : setTimeout(w, 40)); w(); }),
  new Promise((r) => setTimeout(r, 1500)),
]);
await new Promise((r) => setTimeout(r, reduced ? 0 : 450));
$('#loader').classList.add('is-done');
document.body.classList.remove('is-loading');
const shot1 = $('#shot1');
if (!reduced) {
  shot1.querySelector('.shot__img').animate([{ transform: 'scale(1.14)', filter: 'blur(14px)' }, { transform: 'scale(1)', filter: 'blur(0)' }], { duration: 2200, easing: 'cubic-bezier(.2,.8,.2,1)' });
  $('#cHero').animate([{ opacity: 0, transform: 'translateY(30px)' }, { opacity: 1, transform: 'none' }], { duration: 1600, delay: 500, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' });
}

/* ================= scroll suave ================= */
const lenis = reduced ? null : new window.Lenis({ lerp: 0.075, wheelMultiplier: 0.9 });
if (lenis) { const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); }; requestAnimationFrame(raf); }
const lockScroll = (on) => {
  document.documentElement.classList.toggle('lenis-stopped', on);
  if (lenis) on ? lenis.stop() : lenis.start();
};
const story = $('#top');
const endY = () => story.offsetHeight - innerHeight;
const scrollTo = (y, slow = false) => (lenis ? lenis.scrollTo(y, { duration: slow ? 4.5 : 2, immediate: reduced }) : window.scrollTo(0, y));
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href="#top"], a[href="#edificio"]');
  if (!a || document.body.classList.contains('in-level')) return;
  e.preventDefault();
  if (a.getAttribute('href') === '#top') scrollTo(0);
  else { scrollTo(endY(), true); setTimeout(() => $('#edificio').focus({ preventScroll: true }), lenis ? 4600 : 0); }
});

/* ================= la torre crece piso a piso =================
   Cada piso es el render recortado con el contorno de su losa, apoyado sobre la foto del lote vacío. */
const riseSvg = $('#rise'), defs = $('#riseDefs');
const riseFloors = Object.keys(FLOOR_ZONES).map(Number).sort((a, b) => a - b).map((n) => {
  const cp = document.createElementNS(NS, 'clipPath');
  cp.id = `rf${n}`;
  const poly = document.createElementNS(NS, 'polygon');
  poly.setAttribute('points', FLOOR_ZONES[n].map((p) => p.join(',')).join(' '));
  cp.appendChild(poly);
  defs.appendChild(cp);
  const g = document.createElementNS(NS, 'g');
  g.setAttribute('class', 'rise-floor');
  g.setAttribute('opacity', '0');
  const img = document.createElementNS(NS, 'image');
  img.setAttribute('href', 'img/torre.webp');
  img.setAttribute('width', '1536');
  img.setAttribute('height', '1024');
  img.setAttribute('clip-path', `url(#rf${n})`);
  g.appendChild(img);
  riseSvg.appendChild(g);
  return g;
});

/* ================= el recorrido =================
   p = 0 → 1 a lo largo del scroll. Cada tramo mueve una sola cosa. */
const building = initBuilding({ lockScroll });
const shot2 = $('#shot2'), frameWrap = $('#frameWrap'), frame = $('#frame'), torre = $('#torre'), bgTorre = $('#bgTorre');
const img1 = shot1.querySelector('.shot__img'), img2 = shot2.querySelector('.shot__img');
const pins1 = shot1.querySelectorAll('.pin, .place'), pins2 = shot2.querySelectorAll('.pin');
const copy = { hero: $('#cHero'), why: $('#cWhy'), plot: $('#cPlot'), rise: $('#cRise') };
const counter = $('#counter'), riseN = $('#riseN'), hint = $('#hint');
let lastP = -1;

const seg = (p, a, b) => clamp01((p - a) / (b - a));
const fadeInOut = (el, p, a, b, c, d, dy = 24) => {
  const o = Math.min(seg(p, a, b), 1 - seg(p, c, d));
  el.style.opacity = o;
  el.style.visibility = o > 0.01 ? 'visible' : 'hidden';
  el.style.transform = `translateY(${(1 - seg(p, a, b)) * dy - seg(p, c, d) * dy}px)`;
};

function render() {
  requestAnimationFrame(render);
  const p = clamp01(window.scrollY / Math.max(1, endY()));
  if (Math.abs(p - lastP) < 0.0002) return;
  lastP = p;

  // 1. toma aérea alta: el dron se acerca al lote
  const z1 = 1 + 0.75 * ease(seg(p, 0, 0.34));
  img1.style.transform = `scale(${z1})`;
  img1.style.transformOrigin = 'var(--x) var(--y)';
  shot1.style.opacity = 1 - seg(p, 0.27, 0.36);
  pins1.forEach((el) => { el.style.opacity = 1 - seg(p, 0.12, 0.2); el.style.transform = `scale(${1 / z1})`; el.style.transformOrigin = '50% 100%'; });
  // 2. toma intermedia: baja hasta la altura de la costanera
  const z2 = 1.22 - 0.22 * ease(seg(p, 0.27, 0.38)) + 0.5 * ease(seg(p, 0.38, 0.58));
  img2.style.transform = `scale(${z2})`;
  img2.style.transformOrigin = 'var(--x) var(--y)';
  shot2.style.opacity = seg(p, 0.27, 0.36) * (1 - seg(p, 0.5, 0.58));
  pins2.forEach((el) => { el.style.opacity = seg(p, 0.36, 0.4) * (1 - seg(p, 0.46, 0.5)); el.style.transform = `scale(${1 / z2})`; el.style.transformOrigin = '50% 100%'; });
  // 3. a nivel de la costanera, frente al lote vacío
  frameWrap.style.opacity = seg(p, 0.5, 0.58);
  if (!document.body.classList.contains('in-level')) {
    const s = 1.16 - 0.16 * ease(seg(p, 0.5, 0.62));
    frame.style.transform = s > 1.0005 ? `scale(${s})` : '';
    frame.style.filter = p < 0.6 ? `blur(${(1 - seg(p, 0.5, 0.6)) * 8}px)` : '';
  }
  // 4. la torre crece piso a piso
  const b = seg(p, 0.6, 0.86) * riseFloors.length;
  riseFloors.forEach((g, i) => {
    const o = clamp01(b - i);
    g.setAttribute('opacity', o.toFixed(3));
    g.style.transform = o < 1 ? `translateY(${(1 - ease(o)) * -18}px)` : '';
  });
  const tFull = seg(p, 0.86, 0.93);
  torre.style.opacity = tFull;
  bgTorre.style.opacity = tFull;
  riseN.textContent = String(Math.max(1, Math.min(18, Math.ceil(b)))).padStart(2, '0');
  counter.style.opacity = seg(p, 0.6, 0.63) * (1 - seg(p, 0.86, 0.9));

  // textos
  copy.hero.style.opacity = 1 - seg(p, 0.04, 0.1);
  copy.hero.style.transform = `translateY(${-seg(p, 0.04, 0.1) * 40}px)`;
  fadeInOut(copy.why, p, 0.12, 0.16, 0.26, 0.3);
  fadeInOut(copy.plot, p, 0.4, 0.44, 0.52, 0.56);
  fadeInOut(copy.rise, p, 0.62, 0.66, 0.86, 0.9);
  hint.style.opacity = 1 - seg(p, 0.01, 0.04);

  // 5. final del scroll: el edificio se vuelve interactivo
  const atEnd = p > 0.985;
  building.setLive(atEnd);
  document.body.classList.toggle('at-end', atEnd);
}
requestAnimationFrame(render);

// enlace directo a un piso o unidad: saltar al edificio y abrirlo
if (location.hash.startsWith('#/piso')) {
  window.scrollTo(0, endY());
  lenis?.scrollTo(endY(), { immediate: true });
  setTimeout(() => building.openFromHash(), 60);
}
