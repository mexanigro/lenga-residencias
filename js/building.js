// Navegación por niveles: edificio → piso → unidad → 360°.
// El estado vive en la URL (#/piso/12/12A/living), así el botón "atrás" del navegador funciona.
import { FLOORS, TYPES, ZONES, bearingInfo } from './data.js';
import { FLOOR_ZONES, RENDER } from './zones.js';
import { PLATES } from './assets.js';
import { drawPlan } from './plan.js';
import { DEPTO } from './depto.js';

const $ = (s) => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const touchFirst = matchMedia('(hover: none)').matches;
const m2 = (n) => `${n.toLocaleString('es-AR')} m²`;
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const pts = (a) => a.map((p) => p.join(',')).join(' ');
const svgEl = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent?.appendChild(e); return e; };
const wait = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));

// Ambientes que se pueden recorrer en cada tipología: [vista 360, nombre, x %, y %] sobre el render 3D
const SPOTS = {
  B1: [['living', 'Living', 36, 36], ['kitchen', 'Cocina', 68, 28], ['balcony', 'Balcón', 50, 10], ['suite', 'Dormitorio principal', 30, 72], ['bedroom', 'Dormitorio', 70, 72], ['bath', 'Baño', 52, 63]],
  B2: [['living', 'Living', 33, 35], ['kitchen', 'Cocina', 68, 27], ['balcony', 'Balcón', 50, 10], ['suite', 'Suite', 32, 70], ['bedroom', 'Dormitorio', 70, 72], ['bath', 'Baño', 48, 72]],
  L2: [['living', 'Living', 35, 38], ['kitchen', 'Cocina y comedor', 70, 38], ['balcony', 'Balcón', 50, 10], ['suite', 'Suite principal', 27, 72], ['bedroom', 'Segunda suite', 73, 72], ['bath', 'Baño', 48, 67]],
  L3: [['living', 'Living', 32, 36], ['kitchen', 'Cocina', 62, 25], ['balcony', 'Balcón', 45, 9], ['suite', 'Suite', 25, 72], ['bedroom', 'Dormitorio', 60, 76], ['bath', 'Baño', 42, 62]],
  C3: [['living', 'Living', 30, 38], ['kitchen', 'Cocina', 75, 30], ['balcony', 'Galería', 50, 10], ['suite', 'Suite', 22, 72], ['bedroom', 'Dormitorio', 68, 75], ['bath', 'Baño', 37, 65]],
  PH: [['living', 'Living', 28, 40], ['kitchen', 'Cocina', 75, 40], ['balcony', 'Terraza', 50, 15], ['suite', 'Suite', 20, 72], ['bedroom', 'Dormitorio', 68, 75], ['bath', 'Baño', 40, 72]],
};
function planZoom(svg) {
  const pointers = new Map();
  let pinch = null;
  const vb = () => svg.viewBox.baseVal;
  const base = () => svg.dataset.base.split(' ').map(Number);
  const set = (x, y, w, h) => {
    const [bx, by, bw, bh] = base();
    w = Math.min(bw, Math.max(bw / 5, w));
    h = w * (bh / bw);
    x = Math.min(bx + bw - w, Math.max(bx, x));
    y = Math.min(by + bh - h, Math.max(by, y));
    svg.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
    svg.classList.toggle('is-zoomed', w < bw * 0.98);
  };
  // de pantalla a coordenadas del plano (el svg se ajusta "meet", centrado)
  const toPlan = (cx, cy) => {
    const r = svg.getBoundingClientRect(), v = vb();
    const k = Math.min(r.width / v.width, r.height / v.height);
    return [v.x + (cx - r.left - (r.width - v.width * k) / 2) / k, v.y + (cy - r.top - (r.height - v.height * k) / 2) / k, k];
  };
  const zoomAt = (cx, cy, f) => {
    const [px, py] = toPlan(cx, cy), v = vb();
    set(px - (px - v.x) * f, py - (py - v.y) * f, v.width * f, v.height * f);
  };
  svg.addEventListener('wheel', (e) => {
    // si la ficha no entra en pantalla la rueda la desplaza; para acercar ahí: Ctrl + rueda o pellizco del trackpad
    const lvl = svg.closest('.level');
    if (lvl && lvl.scrollHeight > lvl.clientHeight + 1 && !e.ctrlKey) return;
    e.preventDefault();
    // proporcional al giro: un clic de rueda ≈ 18 %, un trackpad avanza suave
    const d = e.deltaY * (e.deltaMode === 1 ? 33 : 1);
    zoomAt(e.clientX, e.clientY, Math.exp(Math.max(-1, Math.min(1, d / 100)) * 0.2));
  }, { passive: false });
  svg.addEventListener('dblclick', () => set(...base()));
  // teclado: + y − acercan, las flechas mueven, 0 vuelve al plano entero
  svg.addEventListener('keydown', (e) => {
    const v = vb(), mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (mv) set(v.x + mv[0] * v.width * 0.12, v.y + mv[1] * v.height * 0.12, v.width, v.height);
    else if (e.key === '+' || e.key === '=') { const r = svg.getBoundingClientRect(); zoomAt(r.x + r.width / 2, r.y + r.height / 2, 0.75); }
    else if (e.key === '-') { const r = svg.getBoundingClientRect(); zoomAt(r.x + r.width / 2, r.y + r.height / 2, 1 / 0.75); }
    else if (e.key === '0') set(...base());
    else return;
    e.preventDefault();
  });
  svg.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return; // clic derecho: no arrastra
    svg.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = Math.hypot(a[0] - b[0], a[1] - b[1]);
    }
  });
  svg.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 1) {
      const k = toPlan(0, 0)[2], v = vb();
      set(v.x - (e.clientX - prev[0]) / k, v.y - (e.clientY - prev[1]) / k, v.width, v.height);
    } else if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, pinch / d);
      pinch = d;
    }
  });
  const up = (e) => { pointers.delete(e.pointerId); if (pointers.size < 2) pinch = null; };
  svg.addEventListener('pointerup', up);
  svg.addEventListener('pointercancel', up);
  svg.addEventListener('lostpointercapture', up);
  // para los botones + y − (y el teclado): acercar o alejar desde el centro
  return {
    zoom(f) { const r = svg.getBoundingClientRect(); zoomAt(r.x + r.width / 2, r.y + r.height / 2, f); },
    reset() { set(...base()); },
  };
}

function zoneRange(zone) {
  const ns = FLOORS.filter((f) => f.zone === zone).map((f) => f.n);
  return ns.length > 1 ? `pisos ${ns[0]} al ${ns.at(-1)}` : `piso ${ns[0]}`;
}
const avail = (f) => f.units.filter((u) => u.status === 'disponible').length;
const bbox = (z) => { const xs = z.map((p) => p[0]), ys = z.map((p) => p[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; };

export function initBuilding({ lockScroll }) {
  const stage = $('#stage'), frame = $('#frame'), zonesSvg = $('#zones');
  const tip = $('#tip'), crumbs = $('#crumbs');
  const levels = { floor: $('#floorLevel'), unit: $('#unitLevel'), pano: $('#panoLevel') };
  let state = { level: 'building' }, live = false, hover = null, busy = false, pano = null, settling = false;

  /* ---------------- edificio ---------------- */
  const lit = $('#litImg'), litPoly = $('#litClip'), edge = $('#litEdge'), hole = $('#hole');
  const zoneEls = FLOORS.map((f, i) => {
    const p = svgEl('polygon', { points: pts(FLOOR_ZONES[f.n]), class: `zone${f.zone === 'club' ? ' is-club' : ''}` }, $('#zonePolys'));
    p.addEventListener('pointerenter', (e) => { if (e.pointerType !== 'touch' && !settling) setHover(i, e); });
    p.addEventListener('pointermove', (e) => { if (e.pointerType !== 'touch') placeTip(e.clientX, e.clientY); });
    p.addEventListener('pointerleave', (e) => { if (e.pointerType !== 'touch') setHover(null); });
    p.addEventListener('click', (e) => {
      if (f.zone === 'club') return;
      // en pantallas táctiles el primer toque muestra el piso y el segundo entra
      if (touchFirst && hover !== i) { setHover(i, e, true); return; }
      go({ level: 'floor', floor: f.n });
    });
    return p;
  });

  function setHover(i, e, touch = false) {
    hover = i;
    zonesSvg.classList.toggle('has-hover', i != null);
    floorBtns.forEach((b, k) => b.classList.toggle('is-hot', k === i));
    if (i == null) { tip.classList.remove('is-on', 'is-touch'); return; }
    const f = FLOORS[i], z = FLOOR_ZONES[f.n];
    litPoly.setAttribute('points', pts(z));
    edge.setAttribute('points', pts(z));
    hole.setAttribute('points', pts(z));
    const club = f.zone === 'club';
    tip.innerHTML = `<p class="tip__floor">Piso ${f.n}</p><p class="kicker tip__zone">${ZONES[f.zone].name}</p>
      <p class="tip__avail">${club ? 'Lobby, pileta, spa y gimnasio' : `${avail(f)} de ${f.units.length} unidades disponibles`}</p>
      ${club ? '' : touch ? '<div class="tip__go"><button class="btn btn--accent btn--sm" type="button">Entrar al piso</button></div>' : '<p class="tip__go">Hacé clic para ver la planta</p>'}`;
    tip.classList.toggle('is-touch', touch);
    tip.querySelector('button')?.addEventListener('click', () => go({ level: 'floor', floor: f.n }));
    tip.classList.add('is-on');
    if (touch || !e) {
      const [, y0, x1, y1] = bbox(z), pt = zonesSvg.createSVGPoint();
      pt.x = x1; pt.y = (y0 + y1) / 2;
      const s = pt.matrixTransform(zonesSvg.getScreenCTM());
      placeTip(Math.min(s.x, innerWidth - 260), s.y);
    } else placeTip(e.clientX, e.clientY);
  }
  function placeTip(x, y) {
    const w = tip.offsetWidth || 230, h = tip.offsetHeight || 120;
    const left = x + 22 + w > innerWidth - 90 ? x - w - 22 : x + 22;
    tip.style.transform = `translate(${Math.max(12, left)}px, ${Math.min(Math.max(80, y - h / 2), innerHeight - h - 12)}px)`;
  }
  document.addEventListener('pointerdown', (e) => {
    if (touchFirst && hover != null && !e.target.closest('.zone, .tip, .elevator')) setHover(null);
  });

  // resumen de disponibilidad en la tarjeta del edificio
  const all = FLOORS.flatMap((f) => f.units);
  $('#statAvail').textContent = all.filter((u) => u.status === 'disponible').length;
  $('#statUnits').textContent = all.length;

  /* ---------------- ascensor ---------------- */
  const rail = $('#rail'), cab = $('#cab'), floorBtns = [];
  let lastZone = null;
  for (let i = FLOORS.length - 1; i >= 0; i--) {
    const f = FLOORS[i], li = document.createElement('li');
    if (f.zone !== lastZone) { li.dataset.zone = ZONES[f.zone].name; lastZone = f.zone; }
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = String(f.n).padStart(2, '0');
    b.setAttribute('aria-label', `Piso ${f.n}, ${ZONES[f.zone].name}${f.zone === 'club' ? ', espacios comunes' : `, ${avail(f)} disponibles`}`);
    b.dataset.i = i;
    b.tabIndex = -1;
    if (f.zone === 'club') b.classList.add('is-club');
    b.addEventListener('pointerenter', () => { if (state.level === 'building') setHover(i); });
    b.addEventListener('pointerleave', () => { if (state.level === 'building') setHover(null); });
    b.addEventListener('focus', () => { if (state.level === 'building') setHover(i); });
    li.appendChild(b);
    rail.appendChild(li);
    floorBtns[i] = b;
  }
  rail.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    const f = FLOORS[+b.dataset.i];
    if (f.zone !== 'club') go({ level: 'floor', floor: f.n });
  });
  rail.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowDown: -1 }[e.key];
    if (!d) return;
    e.preventDefault();
    const cur = +document.activeElement.dataset.i || 0;
    const n = Math.max(0, Math.min(FLOORS.length - 1, cur + d));
    floorBtns.forEach((b, k) => { b.tabIndex = k === n ? 0 : -1; });
    floorBtns[n].focus();
  });
  floorBtns[11].tabIndex = 0;
  function markFloor(n) {
    const i = n ? FLOORS.findIndex((f) => f.n === n) : -1;
    floorBtns.forEach((b, k) => {
      b.setAttribute('aria-current', k === i ? 'true' : 'false');
      b.tabIndex = k === (i >= 0 ? i : 11) ? 0 : -1; // con Tab se llega al piso actual
    });
    cab.hidden = i < 0;
    if (i < 0) return;
    const r = floorBtns[i].getBoundingClientRect(), nr = $('#elevator').getBoundingClientRect();
    cab.style.top = `${r.top - nr.top + 1}px`;
    cab.style.height = `${r.height - 2}px`;
    cab.style.left = `${r.left - nr.left + 1}px`; // también horizontal: en pantallas bajas el ascensor tiene dos columnas
    cab.style.width = `${r.width - 2}px`;
    cab.style.right = 'auto';
  }

  /* ---------------- planta del piso ---------------- */
  const plate = $('#plate'), plateImg = $('#plateImg'), plateSvg = $('#plateUnits'), tags = $('#plateTags');
  let plateZone = null;
  function renderFloor(n) {
    const f = FLOORS.find((x) => x.n === n), meta = PLATES[f.zone];
    $('#fZone').textContent = ZONES[f.zone].name;
    $('#fTitle').textContent = `Piso ${f.n}`;
    $('#fText').textContent = `${ZONES[f.zone].text} Mira al ${bearingInfo(f.rot).dir.toLowerCase()}: la planta gira ${f.rot}° respecto del piso 3.`;
    $('#fUnits').textContent = f.units.length;
    $('#fAvail').textContent = avail(f);
    $('#fFront').textContent = bearingInfo(f.rot).dir;
    $('#fShare').textContent = `Misma distribución en los ${zoneRange(f.zone)}; lo que cambia es hacia dónde mira cada unidad.`;
    if (plateZone !== f.zone) {
      plateZone = f.zone;
      plateImg.src = `img/plate-${f.zone}.webp`;
      plateSvg.setAttribute('viewBox', `0 0 ${meta.w} ${meta.h}`);
    }
    const [x0, y0, x1, y1] = meta.box;
    const X = (x) => x0 + ((x + 13) / 26) * (x1 - x0), Y = (y) => y0 + ((y + 13) / 26) * (y1 - y0);
    plateSvg.innerHTML = '';
    tags.innerHTML = '';
    const list = $('#unitCards');
    list.innerHTML = '';
    f.units.forEach((u, k) => {
      const t = TYPES[u.type];
      const g = svgEl('g', { class: `u u--${u.status}`, tabindex: -1 }, plateSvg);
      const d = `M${u.poly.map(([x, y]) => `${X(x)} ${Y(y)}`).join('L')}Z` + (u.hole ? `M${u.hole.map(([x, y]) => `${X(x)} ${Y(y)}`).join('L')}Z` : '');
      svgEl('path', { d, class: 'u-veil', 'fill-rule': 'evenodd' }, g);
      const [cx, cy] = { TL: [-7.5, -7.5], TR: [7.5, -7.5], BR: [7.5, 7.5], BL: [-7.5, 7.5], LH: [-8, 0], RH: [8, 0], FULL: [0, -8] }[u.shape];
      const tag = document.createElement('div');
      tag.className = 'utag';
      tag.style.left = `${(X(cx) / meta.w) * 100}%`;
      tag.style.top = `${(Y(cy) / meta.h) * 100}%`;
      tag.style.rotate = `${-f.rot}deg`;
      tag.innerHTML = `<b>${u.id}</b><span class="chip chip--${u.status}">${cap(u.status)}</span>`;
      tags.appendChild(tag);
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.className = 'ucard';
      b.type = 'button';
      b.innerHTML = `<span class="ucard__id">${u.id}</span><span class="ucard__t">${cap(t.rooms)}<small>${t.name}, ${m2(t.covered + t.open)}</small></span><span class="chip chip--${u.status}">${cap(u.status)}</span>`;
      li.appendChild(b);
      list.appendChild(li);
      const hot = (v) => { g.classList.toggle('is-hot', v); b.classList.toggle('is-hot', v); };
      for (const el of [g, b]) {
        el.addEventListener('pointerenter', () => hot(true));
        el.addEventListener('pointerleave', () => hot(false));
        el.addEventListener('click', () => go({ level: 'unit', floor: f.n, unit: u.id }));
      }
      b.addEventListener('focus', () => hot(true));
      b.addEventListener('blur', () => hot(false));
    });
    plate.style.transform = `rotate(${f.rot}deg)`;
    markFloor(f.n);
  }

  /* ---------------- unidad ---------------- */
  const iso = $('#isoImg'), isoSpots = $('#isoSpots');
  let isModel = true;
  function renderUnit(n, id) {
    const f = FLOORS.find((x) => x.n === n), u = f.units.find((x) => x.id === id), t = TYPES[u.type];
    const b = bearingInfo(u.bearing);
    const balcony = t.plan.find((r) => r[5] === 'balcony')[0];
    $('#uKicker').textContent = `Piso ${f.n}, ${ZONES[f.zone].name}`;
    $('#uTitle').textContent = `Unidad ${u.id}`;
    $('#uType').textContent = `${t.name}: ${t.rooms}`;
    $('#uStatus').className = `chip chip--${u.status}`;
    $('#uStatus').textContent = cap(u.status);
    $('#uFacts').innerHTML = [
      ['Cubierta', m2(t.covered)], [balcony, m2(t.open)], ['Total', m2(t.covered + t.open)],
      ['Orientación', b.dir], ['Vista', cap(b.view)],
    ].map(([dt, dd]) => `<div><dt>${dt}</dt><dd>${dd}</dd></div>`).join('');
    const cta = $('#uCta');
    cta.textContent = u.status === 'vendida' ? 'Consultar por unidades similares' : `Consultar por la ${u.id}`;
    cta.href = `mailto:hola@lenga-ilen.com?subject=${encodeURIComponent(`Consulta por la unidad ${u.id} de Lenga`)}`;
    iso.src = `img/iso-${u.type}.webp`;
    iso.alt = `Maqueta 3D de la ${t.name}: ${t.rooms}`;
    isoSpots.innerHTML = '';
    for (const [key, label, x, y] of SPOTS[u.type]) {
      const s = document.createElement('button');
      s.className = 'spot';
      s.type = 'button';
      s.style.left = `${x}%`;
      s.style.top = `${y}%`;
      s.innerHTML = `<span>${label}</span>`;
      s.setAttribute('aria-label', `Recorrer ${label.toLowerCase()} en 360°`);
      s.addEventListener('click', () => go({ level: 'pano', floor: f.n, unit: u.id, room: key }));
      isoSpots.appendChild(s);
    }
    // el 360° es el del departamento modelo (2 suites): en las otras tipologías se aclara antes de entrar
    isModel = u.type === DEPTO.type;
    $('#tourLabel').textContent = isModel ? 'Recorrer en 360°' : 'Recorrer el modelo en 360°';
    $('#uNote').textContent = isModel
      ? 'Imágenes ilustrativas generadas para este proyecto.'
      : `El recorrido 360° muestra el departamento modelo de 2 suites (${TYPES[DEPTO.type].name}). Imágenes ilustrativas.`;
    drawPlan($('#plan2d'), t, { bearing: u.bearing });
    $('#plan2d').dataset.base = $('#plan2d').getAttribute('viewBox');
    setTab('iso');
  }
  function setTab(which) {
    $('#tabIso').setAttribute('aria-selected', String(which === 'iso'));
    $('#tabPlan').setAttribute('aria-selected', String(which === 'plan'));
    $('#isoView').hidden = which !== 'iso';
    $('#planView').hidden = which !== 'plan';
    $('.unit-hint').textContent = which === 'iso'
      ? (isModel ? 'Tocá un ambiente de la maqueta para recorrerlo en 360°.' : 'Tocá un ambiente para recorrer el departamento modelo en 360°.')
      : (touchFirst ? 'Pellizcá o usá + y − para acercar, y arrastrá para mover.' : 'Acercá con + y − (o la rueda) y arrastrá para mover. Doble clic para volver.');
  }
  const pz = planZoom($('#plan2d'));
  $('#planIn').addEventListener('click', () => pz.zoom(0.75));
  $('#planOut').addEventListener('click', () => pz.zoom(1 / 0.75));
  $('#tabIso').addEventListener('click', () => setTab('iso'));
  $('#tabPlan').addEventListener('click', () => setTab('plan'));
  $('#tourBtn').addEventListener('click', () => go({ ...state, level: 'pano', room: 'living' }));

  /* ---------------- 360 ----------------
     El recorrido es el del departamento modelo (tipo L2), renderizado en 3D: el mismo para todas las
     unidades, con su plano en el mini mapa para que la posición y la mirada sean exactas. */
  // fresh: se entra al 360° (se arma todo y se espera el primer panorama).
  // Si no, es un cambio de ambiente: se marca el destino y el recorrido sigue solo, sin bloquear la navegación.
  async function renderPano(st, fresh) {
    const views = DEPTO.views;
    const bar = $('#panoRooms');
    if (fresh) {
      const u = FLOORS.find((x) => x.n === st.floor).units.find((x) => x.id === st.unit);
      $('#pKicker').textContent = u.type === DEPTO.type ? `Unidad ${u.id}, departamento modelo` : `Departamento modelo de 2 suites`;
      $('#pTitle').textContent = views[st.room].label;
      bar.innerHTML = '';
      for (const [key, v] of Object.entries(views)) {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = v.label;
        b.dataset.room = key;
        b.addEventListener('click', () => go({ ...state, room: key }, { replace: true }));
        bar.appendChild(b);
      }
      drawPlan($('#panoMap'), TYPES[DEPTO.type], { areas: false });
      placeMe(st.room, views[st.room].start);
      $('#panoHint').textContent = touchFirst ? 'Arrastrá para mirar, pellizcá para acercar' : 'Arrastrá o usá las flechas para mirar en 360°';
      if (!pano) {
        const { createPano } = await import('./pano.js');
        pano = createPano($('#panoCanvas'), $('#panoSpots'), { reduced });
      }
      pano.reset();
    }
    // la barra marca adónde se va; el título dice dónde se está (en un salto largo se cruzan otros ambientes)
    bar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-current', String(b.dataset.room === st.room)));
    bar.querySelector('[aria-current="true"]')?.scrollIntoView({ inline: 'center', block: 'nearest' });
    const shown = pano.show(st.room, {
      onGo: (key) => go({ ...state, room: key }, { replace: true }),
      onLook: (yaw, room) => placeMe(room, yaw),
      onRoom: (room) => {
        $('#pTitle').textContent = views[room].label;
        // el punto tocado desaparece al llegar: el foco pasa al título para no perderse
        if (!document.activeElement || document.activeElement === document.body) $('#pTitle').focus({ preventScroll: true });
      },
    });
    if (fresh) await shown;
    else shown.catch(panoFailed);
  }
  function panoFailed(err) {
    console.error(err);
    if (state.level !== 'pano') return;
    go({ level: 'unit', floor: state.floor, unit: state.unit }, { replace: true, failed: true });
  }
  function placeMe(room, yaw) {
    const map = $('#panoMap');
    let g = map.querySelector('.me-g');
    if (!g) g = svgEl('g', { class: 'me-g' }, map);
    const v = DEPTO.views[room];
    if (!v) { g.innerHTML = ''; return; }
    const [x, y] = v.pos;
    g.innerHTML = `<path class="cone" d="M0 0 L-2.6 -4.6 A5.2 5.2 0 0 1 2.6 -4.6 Z" transform="translate(${x} ${y}) rotate(${yaw.toFixed(1)})"/><circle class="me" cx="${x}" cy="${y}" r=".55"/>`;
  }
  $('#zoomIn').addEventListener('click', () => pano?.zoom(-10));
  $('#zoomOut').addEventListener('click', () => pano?.zoom(10));

  /* ---------------- migas de pan ---------------- */
  function renderCrumbs() {
    const items = [['Edificio', { level: 'building' }]];
    if (state.floor) items.push([`Piso ${state.floor}`, { level: 'floor', floor: state.floor }]);
    if (state.unit) items.push([`Unidad ${state.unit}`, { level: 'unit', floor: state.floor, unit: state.unit }]);
    if (state.room) items.push(['Vista 360°', state]);
    crumbs.innerHTML = '';
    items.forEach(([label, to], i) => {
      if (i) crumbs.appendChild(document.createElement('i'));
      const last = i === items.length - 1;
      const el = document.createElement(last ? 'span' : 'button');
      el.textContent = label;
      if (last) el.setAttribute('aria-current', 'page');
      else { el.type = 'button'; el.addEventListener('click', () => goUp(to)); }
      crumbs.appendChild(el);
    });
    crumbs.classList.toggle('is-on', live || state.level !== 'building');
  }

  /* ---------------- router y transiciones ---------------- */
  const hashOf = (s) => s.level === 'building' ? '#edificio' : `#/piso/${s.floor}${s.unit ? `/${s.unit}` : ''}${s.room ? `/${s.room}` : ''}`;
  function parse(hash) {
    const m = hash.match(/^#\/piso\/(\d+)(?:\/(\w+))?(?:\/(\w+))?/);
    if (!m) return { level: 'building' };
    const f = FLOORS.find((x) => x.n === +m[1]);
    if (!f || f.zone === 'club') return { level: 'building' };
    const u = m[2] && f.units.find((x) => x.id === m[2]);
    if (!u) return { level: 'floor', floor: f.n };
    if (m[3] && Object.hasOwn(DEPTO.views, m[3])) return { level: 'pano', floor: f.n, unit: u.id, room: m[3] };
    return { level: 'unit', floor: f.n, unit: u.id };
  }

  // _on: lo último que se pidió para ese nivel (mostrar u ocultar); las transiciones viejas no lo pisan
  function show(el) { el._on = true; el.hidden = false; requestAnimationFrame(() => requestAnimationFrame(() => { if (el._on) el.classList.add('is-in'); })); }
  async function hide(el) { el._on = false; if (el.hidden) return; el.classList.remove('is-in'); await wait(380); if (!el._on) el.hidden = true; }

  // acerca el render al piso elegido antes de abrir su planta
  function zoomTo(n, on) {
    const z = FLOOR_ZONES[n], [x0, y0, x1, y1] = bbox(z);
    const r = frame.getBoundingClientRect();
    const fw = r.width / (frame._s || 1), fh = r.height / (frame._s || 1);
    const s = on ? 2.6 : 1;
    const px = ((x0 + x1) / 2 / RENDER.w) * fw, py = ((y0 + y1) / 2 / RENDER.h) * fh;
    const tx = on ? (fw / 2 - px) * s : 0, ty = on ? (fh / 2 - py) * s : 0;
    frame._s = s;
    frame.style.transition = reduced ? 'none' : 'transform .8s cubic-bezier(.65,0,.25,1), filter .8s';
    frame.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    frame.style.filter = on ? 'blur(2px) brightness(.7)' : '';
  }

  // Navegación. Si llega otro pedido durante una transición (atrás, Escape, un clic) se guarda el último
  // y se ejecuta al terminar, así la URL y lo que se ve nunca quedan distintos.
  let pending = null;
  async function go(next, opts = {}) {
    if (busy) { pending = [next, opts]; return; }
    busy = true;
    try { await step(next, opts); }
    catch (err) {
      console.error(err);
      // el 360° no pudo abrir (sin WebGL, sin conexión con la librería, panorama que no baja): volver a la unidad
      if (next.level === 'pano') pending ??= [{ level: 'unit', floor: next.floor, unit: next.unit }, { replace: true, failed: true }];
    } finally {
      busy = false;
      if (pending) { const [n, o] = pending; pending = null; go(n, o); }
    }
  }

  // historial propio: subir con Escape o con las migas vuelve atrás en el navegador si ese nivel está justo detrás,
  // así "atrás" después de subir no reabre lo que se acaba de cerrar
  const trail = [parse(location.hash)];
  const depth = () => history.state?.d ?? 0;
  function goUp(to) {
    const d = depth(), k = trail.findLastIndex((s, i) => i < d && s && hashOf(s) === hashOf(to));
    if (k >= 0) history.go(k - d);
    else go(to);
  }

  async function step(next, { push = true, replace = false, failed = false } = {}) {
    const prev = state;
    state = next;
    const d = depth();
    if (push) {
      const nd = replace ? d : d + 1;
      history[replace ? 'replaceState' : 'pushState']({ ...next, d: nd }, '', hashOf(next));
      trail[nd] = next;
      trail.length = nd + 1;
    } else {
      trail[d] = next;
      // enlace inválido (#/piso/99, #/piso/10/ZZ): la URL se corrige a lo que se muestra
      if (location.hash !== hashOf(next)) history.replaceState({ ...next, d }, '', hashOf(next));
    }
    setHover(null);
    // con un nivel abierto, lo de atrás (vuelo, fachada, atajo) queda fuera del teclado y del lector
    $('#top').inert = $('.skip').inert = next.level !== 'building';
    const order = ['building', 'floor', 'unit', 'pano'];
    const down = order.indexOf(next.level) > order.indexOf(prev.level);
    document.body.classList.toggle('in-level', next.level !== 'building');
    document.body.classList.toggle('show-elevator', live && (next.level === 'building' || next.level === 'floor'));
    lockScroll(next.level !== 'building');

    if (next.level === 'building') {
      // si la pantalla giró mientras se miraba un piso, el final del recorrido cambió: volver a él
      const end = $('#top').offsetHeight - innerHeight;
      if (Math.abs(scrollY - end) > 2) window.scrollTo(0, end);
      settling = true; // mientras la foto se aleja, los pisos que pasan bajo el mouse no abren el cartel
      await Promise.all(Object.values(levels).map(hide));
      pano?.pause();
      zoomTo(prev.floor || 12, false);
      setTimeout(() => { frame.style.transition = ''; frame.style.filter = ''; settling = false; }, 850);
      markFloor(null);
    } else {
      if (prev.level === 'building') { zoomTo(next.floor, true); await wait(down ? 520 : 0); }
      if (next.level === 'floor') {
        if (prev.level === 'floor' && prev.floor !== next.floor) renderFloor(next.floor);
        else { renderFloor(next.floor); show(levels.floor); }
        await Promise.all([hide(levels.unit), hide(levels.pano)]);
        pano?.pause();
      }
      if (next.level === 'unit') {
        if (prev.level !== 'unit' || prev.unit !== next.unit) renderUnit(next.floor, next.unit);
        if (prev.level === 'floor' || prev.level === 'building') renderFloor(next.floor);
        show(levels.unit);
        await hide(levels.pano);
        pano?.pause();
        if (!levels.floor.hidden) hide(levels.floor);
      }
      if (next.level === 'pano') {
        if (prev.level !== 'unit' && prev.level !== 'pano') renderUnit(next.floor, next.unit);
        show(levels.pano);
        await renderPano(next, prev.level !== 'pano');
        if (prev.level !== 'pano') { hide(levels.unit); hide(levels.floor); }
      }
    }
    renderCrumbs();
    const focusTarget = { floor: '#fTitle', unit: '#uTitle', pano: '#pTitle' }[next.level];
    if (focusTarget && prev.level !== next.level) $(focusTarget).focus({ preventScroll: true });
    if (failed) $('.unit-hint').textContent = 'No se pudo abrir el recorrido 360° en este navegador.';
  }

  window.addEventListener('popstate', () => go(parse(location.hash), { push: false }));
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const up = { floor: { level: 'building' }, unit: { level: 'floor', floor: state.floor }, pano: { level: 'unit', floor: state.floor, unit: state.unit } }[state.level];
    if (up) goUp(up);
  });
  window.addEventListener('resize', () => { if (state.floor) markFloor(state.floor); if (state.level !== 'building') zoomTo(state.floor, true); });

  return {
    setLive(v) {
      if (v === live) return;
      live = v;
      stage.classList.toggle('is-live', v);
      document.body.classList.toggle('show-elevator', v && (state.level === 'building' || state.level === 'floor'));
      if (v && state.floor) markFloor(state.floor);
      renderCrumbs();
      if (v && state.level === 'building') scan();
      if (!v) setHover(null);
    },
    openFromHash() {
      const s = parse(location.hash);
      if (s.level !== 'building') go(s, { push: false });
      else if (location.hash !== '#edificio') history.replaceState({ ...s, d: 0 }, '', '#edificio'); // #/piso/99 → #edificio
    },
  };

  // recorrido de luz por las losas, de abajo hacia arriba, para invitar a tocar
  function scan() {
    if (reduced) return;
    FLOORS.forEach((f, k) => {
      setTimeout(() => {
        const p = svgEl('polygon', { points: pts(FLOOR_ZONES[f.n]), class: 'scan' }, zonesSvg);
        p.animate([{ opacity: 0 }, { opacity: 1 }, { opacity: 0 }], { duration: 520, easing: 'ease-out' }).finished.then(() => p.remove());
      }, 250 + k * 55);
    });
  }
}
