const $ = (s) => document.querySelector(s);
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const smooth = (a, b, x) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const NS = 'http://www.w3.org/2000/svg';

/* ================= loader: la silueta de la torre se dibuja piso a piso ================= */
const loaderLines = [];
{
  const svg = $('#loaderTower');
  const line = (attrs) => { const l = document.createElementNS(NS, 'line'); for (const k in attrs) l.setAttribute(k, attrs[k]); svg.appendChild(l); return l; };
  loaderLines.push(line({ x1: 10, x2: 190, y1: 232, y2: 232, class: 'ground' }));
  for (let n = 1; n <= 18; n++) {
    const th = n <= 2 ? 0 : (n - 3) * 4 * Math.PI / 180;
    const w = n <= 2 ? 128 : 66 * (Math.abs(Math.cos(th)) + Math.abs(Math.sin(th)));
    const y = 226 - (n - 1) * 11.2;
    loaderLines.push(line({ x1: 100 - w / 2, x2: 100 + w / 2, y1: y, y2: y }));
  }
  for (const l of loaderLines) { const len = l.getTotalLength(); l.style.strokeDasharray = len; l.style.strokeDashoffset = len; l.dataset.len = len; }
}
let loadTarget = 0, loadShown = 0;
const bump = (v) => { loadTarget = Math.max(loadTarget, v); };
(function tick() {
  loadShown += (loadTarget - loadShown) * (reduced ? 1 : 0.08);
  if (loadTarget - loadShown < 0.002) loadShown = loadTarget;
  $('#loaderPct').textContent = Math.round(loadShown * 100);
  const k = loadShown * loaderLines.length;
  loaderLines.forEach((l, i) => { l.style.strokeDashoffset = l.dataset.len * (1 - clamp01(k - i)); });
  if (loadShown < 1) requestAnimationFrame(tick);
})();

bump(0.08);
const bldImg = $('#bldImg');
const [{ createScene }, { initBuilding }] = await Promise.all([
  import('./scene.js').then((m) => { bump(0.5); return m; }),
  import('./building.js'),
  document.fonts.ready.then(() => bump(0.25)),
  (bldImg.complete ? Promise.resolve() : new Promise((r) => { bldImg.onload = bldImg.onerror = r; })).then(() => bump(0.35)),
]);
const scene = createScene($('#gl'), { reduced });
bump(1);
await Promise.race([
  new Promise((r) => { const w = () => (loadShown >= 1 ? r() : setTimeout(w, 50)); w(); }),
  new Promise((r) => setTimeout(r, 1600)),
]);
$('#loader').classList.add('is-done');
document.body.classList.remove('is-loading');

/* ================= scroll ================= */
const { gsap, ScrollTrigger } = window;
gsap.registerPlugin(ScrollTrigger);
const lenis = reduced ? null : new window.Lenis({ lerp: 0.085 });
if (lenis) {
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);
}
const lockScroll = (on) => {
  document.documentElement.classList.toggle('lenis-stopped', on);
  if (lenis) on ? lenis.stop() : lenis.start();
};
const scrollEnd = () => document.documentElement.scrollHeight - innerHeight;
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href^="#"]');
  if (!a || document.body.classList.contains('overlay-open')) return;
  e.preventDefault();
  const to = a.getAttribute('href') === '#top' ? 0 : scrollEnd();
  if (lenis) lenis.scrollTo(to, { duration: to ? 3.2 : 2.4 });
  else window.scrollTo(0, to);
  if (to) setTimeout(() => $('#edificio').focus({ preventScroll: true }), lenis ? 3300 : 0);
});

const building = initBuilding({ lockScroll });

// entrada: las curvas de nivel se dibujan desde el lote hacia afuera
if (!reduced) {
  const r = { v: 0 };
  gsap.to(r, { v: 1900, duration: 3.6, ease: 'power2.out', onUpdate: () => scene.reveal(r.v) });
  gsap.from('.hero__title', { opacity: 0, y: 40, duration: 1.4, ease: 'power3.out', delay: 0.2 });
  gsap.from('.hero__lede, .scroll-hint > *', { opacity: 0, duration: 1.2, delay: 0.9 }); // hijos: #hint lo maneja el scroll
}

/* descenso → la torre se arma → el render del edificio */
const st = scene.state, bld = $('#bld'), bldFrame = $('#bldFrame'), riseCount = $('#riseCount');
const labelBox = $('#maplabels'), legend = $('#legend');
ScrollTrigger.create({
  trigger: '#top', start: 'top top', end: 'bottom bottom',
  onUpdate: (self) => {
    const p = self.progress;
    st.story = p;
    st.build = smooth(0.4, 0.8, p);
    riseCount.textContent = String(Math.max(1, Math.round(st.build * 18))).padStart(2, '0');
    // la maqueta se funde con el render: desenfoque y escala que se asientan
    const reveal = smooth(0.84, 0.96, p);
    bld.style.opacity = reveal;
    bld.classList.toggle('is-shown', reveal > 0);
    bldFrame.style.transform = `scale(${1.08 - 0.08 * reveal})`;
    bldFrame.style.filter = reveal < 1 ? `blur(${(1 - reveal) * 10}px)` : 'none';
    st.active = reveal < 1;
    // también acá (no solo por cuadro): con la escena pausada el onFrame no corre
    legend.classList.toggle('is-off', p > 0.8);
    labelBox.hidden = p > 0.55;
    const atEnd = p > 0.985;
    building.setLive(atEnd);
    document.body.classList.toggle('at-building', atEnd);
  },
});
gsap.timeline({ scrollTrigger: { trigger: '#top', start: 'top top', end: 'bottom bottom', scrub: true } })
  .to('#hint', { opacity: 0, duration: 0.03 }, 0.01)
  .to('#hero', { opacity: 0, y: -50, duration: 0.08 }, 0.05)
  .fromTo('#why', { opacity: 0, x: 40 }, { opacity: 1, x: 0, duration: 0.06 }, 0.17)
  .to('#why', { opacity: 0, x: -20, duration: 0.05 }, 0.33)
  .to('#rise', { opacity: 1, duration: 0.05 }, 0.4)
  .fromTo('#sweep', { x: '-30vw' }, { x: '110vw', ease: 'none', duration: 0.4 }, 0.41)
  .to('#rise', { opacity: 0, duration: 0.05 }, 0.8)
  .set({}, {}, 1);

/* etiquetas del mapa + leyenda */
const labelEls = scene.labels.map((l) => {
  const el = document.createElement('span');
  el.className = `ml ml--${l.cls}`;
  el.textContent = l.text;
  labelBox.appendChild(el);
  return el;
});
const altEl = $('#alt'), scaleBar = $('#scaleBar');
scene.onFrame = () => {
  const s = st.story;
  scene.labels.forEach((l, i) => {
    const el = labelEls[i];
    const fade = l.cls === 'site' ? 1 - smooth(0.42, 0.5, s) : 1 - smooth(0.24, 0.36, s);
    const p = scene.toScreen(l.pos);
    el.style.opacity = p.on ? fade : 0;
    if (fade > 0) el.style.transform = `translate3d(${p.x}px, ${p.y}px, 0) translate(-50%, ${l.cls === 'site' ? '-100%' : '-50%'})`;
  });
  const m = scene.metrics();
  altEl.textContent = m.alt.toLocaleString('es-AR');
  scaleBar.style.width = `${Math.max(8, Math.min(160, m.px100))}px`;
};

ScrollTrigger.refresh();
