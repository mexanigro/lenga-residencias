// Edificio fotorrealista: zonas por piso sobre el render, ascensor, planta y ficha de unidad.
import { FLOORS, TYPES, ZONES, bearingInfo } from './data.js';
import { FLOOR_ZONES } from './zones.js';
import { drawPlan, drawPlate } from './plan.js';
import { openTour } from './tour.js';

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const NS = 'http://www.w3.org/2000/svg';
const m2 = (n) => `${n.toLocaleString('es-AR')} m²`;
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const pts = (arr) => arr.map((p) => p.join(',')).join(' ');
const ISO = { B1: 1, B2: 1, L2: 1, L3: 1, C3: 1, PH: 1 }; // renders 3D disponibles

function zoneRange(zone) {
  const ns = FLOORS.filter((f) => f.zone === zone).map((f) => f.n);
  return ns.length > 1 ? `pisos ${ns[0]} al ${ns.at(-1)}` : `piso ${ns[0]}`;
}

export function initBuilding({ lockScroll }) {
  const bld = $('#bld'), svg = $('#zones'), polys = $('#zonePolys');
  const selClip = $('#selClipPoly'), edge = $('#edge'), hole = $('#hole'), drawer = $('#drawer');
  const leader = $('#leader'), leaderText = $('#leaderText');
  const rail = $('#rail'), cab = $('#cab'), elevator = $('#elevator');
  const card = {
    floor: $('#cFloor'), zone: $('#cZone'), text: $('#cText'), units: $('#cUnits'), avail: $('#cAvail'),
    front: $('#cFront'), needle: $('#compassNeedle'), open: $('#openPlate'),
  };
  let selected = 11, hover = null, live = false, overlay = null;

  /* zonas sobre el render */
  const zoneEls = FLOORS.map((f, i) => {
    const p = document.createElementNS(NS, 'polygon');
    p.setAttribute('points', pts(FLOOR_ZONES[f.n]));
    p.setAttribute('class', 'zone');
    p.addEventListener('pointerenter', () => setHover(i));
    p.addEventListener('pointerleave', () => setHover(null));
    p.addEventListener('click', () => (i === selected ? openPlate() : select(i)));
    polys.appendChild(p);
    return p;
  });

  /* ascensor */
  const floorBtns = [];
  let lastZone = null;
  for (let i = FLOORS.length - 1; i >= 0; i--) {
    const f = FLOORS[i];
    const li = document.createElement('li');
    if (f.zone !== lastZone) { li.dataset.zone = ZONES[f.zone].name; lastZone = f.zone; }
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = String(f.n).padStart(2, '0');
    b.setAttribute('aria-label', `Piso ${f.n}, ${ZONES[f.zone].name}`);
    b.dataset.i = i;
    b.tabIndex = -1;
    b.addEventListener('pointerenter', () => setHover(i));
    b.addEventListener('pointerleave', () => setHover(null));
    li.appendChild(b);
    rail.appendChild(li);
    floorBtns[i] = b;
  }
  rail.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) select(+b.dataset.i); });
  rail.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowDown: -1, PageUp: 3, PageDown: -3 }[e.key];
    if (d) { e.preventDefault(); select(selected + d, true); }
    if (e.key === 'Home') { e.preventDefault(); select(FLOORS.length - 1, true); }
    if (e.key === 'End') { e.preventDefault(); select(0, true); }
    if (e.key === 'Enter' && !overlay) { e.preventDefault(); openPlate(); }
  });
  // arrastrar la cabina del ascensor
  let railDrag = false;
  const railPick = (y) => {
    const r = rail.getBoundingClientRect();
    const k = Math.floor(Math.min(0.999, Math.max(0, (y - r.top) / r.height)) * FLOORS.length);
    select(FLOORS.length - 1 - k);
  };
  rail.addEventListener('pointerdown', (e) => { if (e.pointerType === 'mouse') return; railDrag = true; rail.setPointerCapture(e.pointerId); });
  rail.addEventListener('pointermove', (e) => { if (railDrag) railPick(e.clientY); });
  rail.addEventListener('pointerup', () => { railDrag = false; });
  rail.addEventListener('pointercancel', () => { railDrag = false; });

  function setHover(i) {
    hover = i;
    zoneEls.forEach((z, k) => z.classList.toggle('is-hot', k === i && k !== selected));
    floorBtns.forEach((b, k) => b.classList.toggle('is-hot', k === i));
    placeLeader(i ?? selected);
  }

  function select(i, focus = false) {
    i = Math.max(0, Math.min(FLOORS.length - 1, i));
    const changed = i !== selected;
    if (changed && live) bld.classList.add('is-touched');
    selected = i;
    const f = FLOORS[i], club = f.zone === 'club';
    card.floor.textContent = String(f.n).padStart(2, '0');
    card.zone.textContent = ZONES[f.zone].name;
    card.text.textContent = ZONES[f.zone].text;
    card.units.textContent = club ? '—' : f.units.length;
    card.avail.textContent = club ? '—' : f.units.filter((u) => u.status === 'disponible').length;
    card.front.textContent = bearingInfo(f.rot).dir;
    card.needle.style.transform = `rotate(${f.rot}deg)`;
    card.open.hidden = club;
    floorBtns.forEach((b, k) => { b.setAttribute('aria-current', k === i ? 'true' : 'false'); b.tabIndex = k === i ? 0 : -1; });
    const b = floorBtns[i], r = b.getBoundingClientRect(), rr = rail.getBoundingClientRect();
    cab.style.top = `${r.top - rr.top + rail.offsetTop + 2}px`;
    cab.style.height = `${Math.max(12, r.height - 4)}px`;
    if (focus) b.focus();
    // el piso elegido "sale" de la fachada como un cajón
    const z = FLOOR_ZONES[f.n];
    selClip.setAttribute('points', pts(z));
    edge.setAttribute('points', pts(z));
    hole.setAttribute('points', pts(z));
    if (changed) drawer.animate([{ transform: 'translateX(0) scale(1)' }, { transform: 'translateX(-14px) scale(1.035)' }], { duration: 520, easing: 'cubic-bezier(.22,.8,.2,1)' });
    drawer.style.transform = 'translateX(-14px) scale(1.035)';
    zoneEls.forEach((zz, k) => zz.classList.toggle('is-hot', k === hover && k !== i));
    placeLeader(hover ?? i);
    if (overlay === 'plate') club ? closePlate() : renderPlate();
  }

  function placeLeader(i) {
    if (i == null || !live || innerWidth < 640) return;
    const f = FLOORS[i], z = FLOOR_ZONES[f.n];
    const half = z.length / 2;
    const right = [z[half - 1], z[half]]; // último punto del borde superior y primero del inferior
    const pt = svg.createSVGPoint();
    pt.x = Math.max(right[0][0], right[1][0]);
    pt.y = (right[0][1] + right[1][1]) / 2;
    const s = pt.matrixTransform(svg.getScreenCTM());
    const end = $('#elevator').getBoundingClientRect().left - 120;
    leader.style.left = `${s.x + 6}px`;
    leader.style.top = `${s.y}px`;
    leader.style.width = `${Math.max(40, end - s.x)}px`;
    const club = f.zone === 'club';
    const avail = f.units.filter((u) => u.status === 'disponible').length;
    leaderText.innerHTML = `Piso ${f.n}<small>${club ? 'Club y espacios comunes' : `${ZONES[f.zone].name}, ${avail} de ${f.units.length} disponibles`}</small>`;
  }
  window.addEventListener('resize', () => select(selected));

  /* planta */
  const plate = $('#plate'), plateSvg = $('#plateSvg'), unitList = $('#unitList');
  let plateRot = null, plateUnits = [];
  card.open.addEventListener('click', openPlate);
  $('#plateBack').addEventListener('click', closePlate);
  function openPlate() {
    if (FLOORS[selected].zone === 'club') return;
    overlay = 'plate';
    plate.hidden = false;
    plate.appendChild(elevator); // el ascensor sigue disponible para cambiar de piso desde la planta
    document.body.classList.add('plate-open', 'overlay-open');
    lockScroll(true);
    renderPlate();
    $('#plateBack').focus();
  }
  function closePlate() {
    closeUnit(false);
    overlay = null;
    plate.hidden = true;
    bld.appendChild(elevator);
    plateRot = null;
    document.body.classList.remove('plate-open', 'overlay-open');
    lockScroll(false);
    card.open.focus({ preventScroll: true });
  }
  function renderPlate() {
    const f = FLOORS[selected];
    $('#pZone').textContent = ZONES[f.zone].name;
    $('#pTitle').textContent = `Piso ${f.n}`;
    $('#pText').textContent = `${ZONES[f.zone].text} Frente al ${bearingInfo(f.rot).dir.toLowerCase()}, girado ${f.rot}° respecto del piso 3.`;
    $('#pShare').textContent = `Planta típica de los ${zoneRange(f.zone)}: cambia la orientación, no la distribución.`;
    plateUnits = drawPlate(plateSvg, f, TYPES, { onUnit: (k) => openUnit(k) });
    const g = plateSvg.querySelector('.plate');
    g.removeAttribute('transform');
    g.style.transform = `rotate(${f.rot}deg)`;
    if (plateRot !== null && plateRot !== f.rot) {
      g.animate([{ transform: `rotate(${plateRot}deg)`, opacity: 0.4 }, { transform: `rotate(${f.rot}deg)`, opacity: 1 }], { duration: 650, easing: 'cubic-bezier(.22,.8,.2,1)' });
    }
    plateRot = f.rot;
    unitList.innerHTML = '';
    f.units.forEach((u, k) => {
      const t = TYPES[u.type];
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button';
      b.innerHTML = `<b>${u.id}</b><span>${t.rooms}<small>${t.name}, ${m2(t.covered + t.open)} totales</small></span><em class="st-${u.status}">${cap(u.status)}</em>`;
      const hot = (v) => { plateUnits[k]?.classList.toggle('is-hot', v); b.classList.toggle('is-hot', v); };
      b.addEventListener('pointerenter', () => hot(true));
      b.addEventListener('pointerleave', () => hot(false));
      b.addEventListener('focus', () => hot(true));
      b.addEventListener('blur', () => hot(false));
      b.addEventListener('click', () => openUnit(k));
      plateUnits[k]?.addEventListener('pointerenter', () => hot(true));
      plateUnits[k]?.addEventListener('pointerleave', () => hot(false));
      li.appendChild(b);
      unitList.appendChild(li);
    });
  }

  /* ficha de unidad */
  const unit = $('#unit'), tab2d = $('#tab2d'), tab3d = $('#tab3d');
  let current = null;
  function openUnit(k) {
    const f = FLOORS[selected], u = f.units[k], t = TYPES[u.type];
    current = { f, u, t, k };
    const b = bearingInfo(u.bearing);
    const balcony = t.plan.find((r) => r[5] === 'balcony')[0];
    $('#uKicker').textContent = `Piso ${f.n}, ${ZONES[f.zone].name}`;
    $('#uTitle').textContent = `Unidad ${u.id}`;
    $('#uType').textContent = `${t.name}: ${t.rooms}`;
    $('#uFacts').innerHTML = [
      ['Superficie cubierta', m2(t.covered)], [balcony, m2(t.open)], ['Total', m2(t.covered + t.open)],
      ['Orientación', b.dir], ['Vista a', b.view], ['Estado', cap(u.status)],
    ].map(([dt, dd]) => `<div><dt>${dt}</dt><dd>${dd}</dd></div>`).join('');
    const cta = $('#uCta');
    cta.textContent = u.status === 'vendida' ? 'Consultar por unidades similares' : `Consultar por la ${u.id}`;
    cta.href = `mailto:hola@lenga-ilen.com?subject=${encodeURIComponent(`Consulta por la unidad ${u.id} de Lenga`)}`;
    drawPlan($('#plan2d'), t, { bearing: u.bearing });
    $('#plan2d').setAttribute('aria-label', `Plano ${t.name}, ${t.rooms}`);
    const iso = $('#iso');
    tab3d.hidden = !ISO[u.type];
    iso.src = `img/iso-${u.type}.webp`;
    iso.alt = `Render 3D de la ${t.name}, ${t.rooms}, con equipamiento`;
    setTab(false);
    overlay = 'unit';
    unit.hidden = false;
    $('#unitBack').focus();
  }
  function closeUnit(focusBack = true) {
    if (unit.hidden) return;
    unit.hidden = true;
    overlay = 'plate';
    if (focusBack && current) unitList.querySelectorAll('button')[current.k]?.focus();
  }
  $('#unitBack').addEventListener('click', () => closeUnit());
  function setTab(three) {
    tab2d.setAttribute('aria-selected', String(!three));
    tab3d.setAttribute('aria-selected', String(three));
    $('#view2d').hidden = three;
    $('#view3d').hidden = !three;
  }
  tab2d.addEventListener('click', () => setTab(false));
  tab3d.addEventListener('click', () => setTab(true));
  $('.unit__tabs').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const three = tab2d.getAttribute('aria-selected') === 'true';
    setTab(three);
    (three ? tab3d : tab2d).focus();
  });
  $('#tourOpen').addEventListener('click', () => {
    overlay = 'tour';
    openTour(current, () => { overlay = 'unit'; $('#tourOpen').focus(); });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !overlay || overlay === 'tour') return;
    if (overlay === 'unit') closeUnit(); else if (overlay === 'plate') closePlate();
  });

  // recorrido inicial de las losas, de abajo hacia arriba, para mostrar que se pueden tocar
  function scan() {
    zoneEls.forEach((z, k) => {
      setTimeout(() => { z.classList.add('is-scan'); setTimeout(() => z.classList.remove('is-scan'), 260); }, 200 + k * 55);
    });
  }

  select(selected);
  return {
    setLive(v) {
      if (v === live) return;
      live = v;
      bld.classList.toggle('is-live', v);
      bld.classList.toggle('has-sel', v);
      bld.classList.toggle('has-floor', v);
      if (v) { select(selected); scan(); }
    },
  };
}
