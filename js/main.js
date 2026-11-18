import { LQIP } from './assets.js';
import { initBuilding } from './building.js';
import { createFlight } from './flight.js';

const $ = (s) => document.querySelector(s);
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ================= carga inicial =================
   Se ve al instante una versión borrosa del primer cuadro; la barra avanza con la carga real del
   vuelo (uno de cada dieciséis cuadros, suficiente para empezar a bajar) y de la foto final de la torre.
   El resto de los cuadros sigue llegando por detrás mientras se mira la portada. */
$('#loaderBg').style.backgroundImage = `url(${LQIP})`;
const flight = createFlight($('#flight'), $('#marks'), { reduced });
const bar = $('#loaderBar'), pct = $('#loaderPct');
const progress = (r) => { bar.style.width = `${r * 100}%`; pct.textContent = Math.round(r * 100); };
const prog = setInterval(() => progress(flight.ready() * 0.96), 90); // la barra tiene su propia transición
const torreImg = new Image();
torreImg.src = 'img/torre.webp';
// ponytail: tope de 12 s; con una conexión muy lenta se entra igual y los cuadros siguen llegando
await Promise.race([
  Promise.all([document.fonts.ready, flight.critical, Promise.race([torreImg.decode(), new Promise((r) => { torreImg.onload = r; })]).catch(() => {})]),
  new Promise((r) => setTimeout(r, 12000)),
]);
clearInterval(prog);
progress(1);
await new Promise((r) => setTimeout(r, reduced ? 0 : 550));
$('#loader').classList.add('is-done');
document.body.classList.remove('is-loading');
flight.intro();
if (!reduced) {
  $('#cHero').animate([{ opacity: 0, transform: 'translateY(30px)' }, { opacity: 1, transform: 'none' }], { duration: 1600, delay: 500, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' });
  $('#marks').animate([{ opacity: 0 }, { opacity: 1 }], { duration: 1400, delay: 900, easing: 'ease-out', fill: 'backwards' });
}

/* ================= scroll suave ================= */
const lenis = reduced || !window.Lenis ? null : new window.Lenis({ lerp: 0.075, wheelMultiplier: 0.9 });
if (lenis) { const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); }; requestAnimationFrame(raf); }
const lockScroll = (on) => {
  document.documentElement.classList.toggle('lenis-stopped', on);
  if (lenis) on ? lenis.stop() : lenis.start();
};
const story = $('#top');
const endY = () => story.offsetHeight - innerHeight;
const scrollTo = (y, slow = false) => (lenis ? lenis.scrollTo(y, { duration: slow ? 6 : 2, immediate: reduced }) : window.scrollTo(0, y));
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href="#top"], a[href="#edificio"]');
  if (!a || document.body.classList.contains('in-level')) return;
  e.preventDefault();
  if (a.getAttribute('href') === '#top') scrollTo(0);
  // el atajo de teclado salta directo y lleva el foco; el resto vuela despacio hasta el edificio
  else if (a.classList.contains('skip')) { lenis ? lenis.scrollTo(endY(), { immediate: true }) : window.scrollTo(0, endY()); $('#edificio').focus({ preventScroll: true }); }
  else { scrollTo(endY(), true); setTimeout(() => $('#edificio').focus({ preventScroll: true }), lenis ? 6100 : 0); }
});

/* ================= el recorrido =================
   p = 0 → 1 a lo largo del scroll. El vuelo ocupa casi todo; al final la foto de la torre
   (la misma toma, en alta) queda quieta y se vuelve interactiva. */
const building = initBuilding({ lockScroll });
const frameWrap = $('#frameWrap'), frame = $('#frame'), marks = $('#marks');
const ease = (t) => t * t * (3 - 2 * t);
const copy = { hero: $('#cHero'), why: $('#cWhy'), plot: $('#cPlot'), rise: $('#cRise') };
const hint = $('#hint');
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
  const moved = Math.abs(p - lastP) > 0.00005;
  // el vuelo se dibuja siempre (pueden haber llegado cuadros nuevos), el resto solo si cambió el scroll
  flight.draw(seg(p, 0, 0.965));
  if (!moved) return;
  lastP = p;

  marks.style.opacity = 1 - seg(p, 0.02, 0.08);
  frameWrap.style.opacity = seg(p, 0.955, 0.99);
  // la foto final aparece con el mismo encuadre que el vuelo (recortado) y se acomoda hasta verse entera
  if (!document.body.classList.contains('in-level')) {
    const cover = Math.max(1, innerWidth / innerHeight / (2752 / 1536));
    const s = cover + (1 - cover) * ease(seg(p, 0.96, 0.995));
    frame.style.transform = s > 1.0005 ? `scale(${s})` : '';
  }

  copy.hero.style.opacity = 1 - seg(p, 0.03, 0.09);
  copy.hero.style.transform = `translateY(${-seg(p, 0.03, 0.09) * 40}px)`;
  fadeInOut(copy.why, p, 0.13, 0.18, 0.3, 0.35);
  fadeInOut(copy.plot, p, 0.42, 0.47, 0.6, 0.65);
  fadeInOut(copy.rise, p, 0.7, 0.75, 0.88, 0.93);
  hint.style.opacity = 1 - seg(p, 0.01, 0.04);

  // final del scroll: el edificio se vuelve interactivo
  // dentro de un nivel no se toca: si la pantalla gira, el final del recorrido cambia y el edificio se apagaría
  if (!document.body.classList.contains('in-level')) {
    const atEnd = p > 0.985;
    building.setLive(atEnd);
    document.body.classList.toggle('at-end', atEnd);
  }
}
requestAnimationFrame(render);

// enlace directo a un piso o unidad: saltar al edificio y abrirlo
if (location.hash.startsWith('#/piso') || location.hash === '#edificio') {
  window.scrollTo(0, endY());
  lenis?.scrollTo(endY(), { immediate: true });
  setTimeout(() => building.openFromHash(), 60);
}
