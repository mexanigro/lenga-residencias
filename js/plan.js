// Dibujo de planos en SVG (metros como unidad). Muros, aberturas y equipamiento
// se derivan de la lista de ambientes de cada tipología.
import { CORE } from './data.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent?.appendChild(e);
  return e;
};
const m2 = (n) => `${n.toLocaleString('es-AR')} m²`;
const EPS = 0.01;

// Segmento compartido entre dos rectángulos (null si no se tocan lo suficiente)
function shared(a, b) {
  const [, ax, ay, aw, ah] = a, [, bx, by, bw, bh] = b;
  const ov = (a0, a1, b0, b1) => [Math.max(a0, b0), Math.min(a1, b1)];
  if (Math.abs(ax + aw - bx) < EPS || Math.abs(bx + bw - ax) < EPS) {
    const x = Math.abs(ax + aw - bx) < EPS ? ax + aw : ax;
    const [s, e] = ov(ay, ay + ah, by, by + bh);
    if (e - s > 0.85) return { v: true, x, s, e };
  }
  if (Math.abs(ay + ah - by) < EPS || Math.abs(by + bh - ay) < EPS) {
    const y = Math.abs(ay + ah - by) < EPS ? ay + ah : ay;
    const [s, e] = ov(ax, ax + aw, bx, bx + bw);
    if (e - s > 0.85) return { v: false, y, s, e };
  }
  return null;
}

function furniture(g, [name, x, y, w, h, kind]) {
  const f = (tag, a) => el(tag, { ...a, class: `fx ${a.class || ''}` }, g);
  const n = name.toLowerCase();
  if (kind === 'balcony') {
    for (let i = 0; i < Math.floor(w / 3.2); i++) {
      const cx = x + 1.6 + i * 3.2;
      f('circle', { cx, cy: y + h / 2, r: 0.35 });
      f('rect', { x: cx - 1.05, y: y + h / 2 - 0.3, width: 0.55, height: 0.6, rx: 0.12 });
      f('rect', { x: cx + 0.5, y: y + h / 2 - 0.3, width: 0.55, height: 0.6, rx: 0.12 });
    }
    return;
  }
  if (n.startsWith('estar') || n === 'comedor' || n.startsWith('cocina y')) {
    const dining = n.includes('comedor') || n.startsWith('cocina y');
    const sofaOnly = n === 'estar' || !dining;
    if (!n.startsWith('cocina') && n !== 'comedor') {
      // sofá contra el muro interior, mirando al ventanal
      const sw = Math.min(3.2, w * 0.45), sx = x + 0.5;
      f('rect', { x: sx, y: y + h - 1.15, width: sw, height: 0.9, rx: 0.15 });
      f('rect', { x: sx, y: y + h - 0.45, width: sw, height: 0.2, rx: 0.08, class: 'dk' });
      f('rect', { x: sx + sw * 0.2, y: y + h - 2.4, width: sw * 0.6, height: 0.8, rx: 0.1 });
      f('rect', { x: sx - 0.1, y: y + 0.6, width: sw + 0.2, height: 0.12, class: 'dk' }); // mueble TV
    }
    if (dining && !sofaOnly || n === 'comedor' || n.startsWith('cocina y')) {
      const tx = n === 'comedor' || n.startsWith('cocina y') ? x + w / 2 : x + w - 2.2, ty = y + h / 2 + 0.3;
      f('rect', { x: tx - 0.9, y: ty - 0.5, width: 1.8, height: 1, rx: 0.08 });
      for (const dx of [-0.5, 0.5]) for (const dy of [-0.85, 0.85]) f('circle', { cx: tx + dx, cy: ty + dy, r: 0.22 });
    }
    if (n.startsWith('cocina y')) {
      f('rect', { x: x + 0.15, y: y + 0.15, width: w - 0.3, height: 0.6, class: 'ct' });
      f('circle', { cx: x + 1.2, cy: y + 0.45, r: 0.16 }); f('circle', { cx: x + 1.7, cy: y + 0.45, r: 0.16 });
    }
    return;
  }
  if (kind === 'bed' && (n.includes('dormitorio') || n.includes('suite'))) {
    const dbl = n.includes('suite') || w > 3.6;
    const bw = w < 3 ? 0.9 : dbl ? 1.6 : 1.4, bl = 2;
    const bx = x + w / 2 - bw / 2, by = y + h - 0.15 - bl;
    f('rect', { x: bx, y: by, width: bw, height: bl, rx: 0.06 });
    f('rect', { x: bx + 0.1, y: by + bl - 0.55, width: bw / 2 - 0.15, height: 0.4, rx: 0.08, class: 'dk' });
    f('rect', { x: bx + bw / 2 + 0.05, y: by + bl - 0.55, width: bw / 2 - 0.15, height: 0.4, rx: 0.08, class: 'dk' });
    f('line', { x1: bx, y1: by + 0.6, x2: bx + bw, y2: by + 0.6 });
    if (w > bw + 1.2) { f('rect', { x: bx - 0.55, y: y + h - 0.6, width: 0.45, height: 0.45 }); f('rect', { x: bx + bw + 0.1, y: y + h - 0.6, width: 0.45, height: 0.45 }); }
    // placard sobre un lateral
    f('rect', { x: x + 0.12, y: y + 0.4, width: 0.6, height: Math.max(1.2, h - bl - 1.2), class: 'ct' });
    return;
  }
  if (n === 'estudio' || n === 'biblioteca') {
    f('rect', { x: x + 0.2, y: y + 0.2, width: Math.min(2, w - 0.4), height: 0.7 });
    f('circle', { cx: x + 1, cy: y + 1.3, r: 0.28 });
    f('rect', { x: x + w - 0.5, y: y + 0.3, width: 0.35, height: h - 0.6, class: 'ct' });
    return;
  }
  if (n === 'cocina') {
    f('rect', { x: x + 0.12, y: y + 0.12, width: w - 0.24, height: 0.62, class: 'ct' });
    f('rect', { x: x + 0.12, y: y + 0.74, width: 0.62, height: Math.max(0.6, h - 1.6), class: 'ct' });
    f('circle', { cx: x + w - 1.1, cy: y + 0.43, r: 0.15 }); f('circle', { cx: x + w - 0.65, cy: y + 0.43, r: 0.15 });
    f('rect', { x: x + 1.2, y: y + 0.24, width: 0.7, height: 0.4, rx: 0.12, class: 'dk' });
    if (w > 4.3 && h > 3.5) f('rect', { x: x + w / 2 - 0.9, y: y + h / 2 + 0.1, width: 1.8, height: 0.9, class: 'ct' });
    return;
  }
  if (n === 'baño' || n === 'toilette') {
    const vert = h > w;
    // inodoro
    const tx = x + (vert ? w / 2 : 0.55), ty = y + (vert ? h - 0.55 : h / 2);
    f('ellipse', { cx: tx, cy: ty, rx: 0.22, ry: 0.3 });
    // bacha
    const sx = x + (vert ? w / 2 : w - 0.7), sy = y + (vert ? 0.45 : 0.4);
    f('rect', { x: sx - 0.35, y: sy - 0.25, width: 0.7, height: 0.5, rx: 0.08 });
    f('circle', { cx: sx, cy: sy, r: 0.13 });
    if (n === 'baño' && w * h > 3.6) {
      const shw = Math.min(1.1, (vert ? w : h) - 0.3);
      const px = vert ? x + 0.15 : x + w / 2 - shw / 2 - 0.2, py = vert ? y + h / 2 - shw / 2 - 0.2 : y + 0.15;
      f('rect', { x: px, y: py, width: shw, height: shw, class: 'sh' });
      f('line', { x1: px, y1: py, x2: px + shw, y2: py + shw });
    }
    return;
  }
  if (n === 'lavadero') {
    f('rect', { x: x + 0.15, y: y + 0.15, width: 0.65, height: 0.65 }); f('circle', { cx: x + 0.475, cy: y + 0.475, r: 0.22 });
    f('rect', { x: x + 0.9, y: y + 0.15, width: 0.65, height: 0.65 }); f('circle', { cx: x + 1.225, cy: y + 0.475, r: 0.22 });
    return;
  }
  if (n === 'vestidor' || n === 'despensa') {
    f('rect', { x: x + 0.1, y: y + 0.1, width: w - 0.2, height: 0.5, class: 'ct' });
    f('rect', { x: x + 0.1, y: y + 0.6, width: 0.5, height: Math.max(0.3, h - 0.8), class: 'ct' });
  }
}

/**
 * Dibuja el plano de una tipología.
 * opts.bearing: orientación del ventanal (grados) para la flecha de norte.
 */
export function drawPlan(svg, t, { bearing = 0, areas = true } = {}) {
  svg.innerHTML = '';
  const rooms = t.plan;
  const covered = rooms.filter((r) => r[5] !== 'balcony');
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [, x, y, w, h] of rooms) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h); }
  const W = Math.max(...covered.map((r) => r[1] + r[3])), D = Math.max(...covered.map((r) => r[2] + r[4]));
  const pad = 1.6;
  svg.setAttribute('viewBox', `${x0 - pad} ${y0 - pad - 0.8} ${x1 - x0 + pad * 2} ${y1 - y0 + pad * 2 + 1.6}`);
  svg.classList.add('plan2d');

  const defs = el('defs', {}, svg);
  const pat = el('pattern', { id: 'deck', width: 0.25, height: 2, patternUnits: 'userSpaceOnUse' }, defs);
  el('rect', { width: 0.25, height: 2, class: 'deck-bg' }, pat);
  el('line', { x1: 0, y1: 0, x2: 0, y2: 2, class: 'deck-ln' }, pat);
  const tiles = el('pattern', { id: 'tiles', width: 0.6, height: 0.6, patternUnits: 'userSpaceOnUse' }, defs);
  el('rect', { width: 0.6, height: 0.6, class: 'tile-bg' }, tiles);
  el('path', { d: 'M0 0H0.6V0.6', class: 'tile-ln' }, tiles);
  const wood = el('pattern', { id: 'wood', width: 6, height: 0.18, patternUnits: 'userSpaceOnUse' }, defs);
  el('rect', { width: 6, height: 0.18, class: 'wood-bg' }, wood);
  el('line', { x1: 0, y1: 0.18, x2: 6, y2: 0.18, class: 'wood-ln' }, wood);

  // pisos
  for (const [, x, y, w, h, kind] of rooms) {
    const fill = kind === 'balcony' ? 'url(#deck)' : kind === 'wet' ? 'url(#tiles)' : kind === 'hall' ? 'var(--p-hall, #ECEFEE)' : 'url(#wood)';
    el('rect', { x, y, width: w, height: h, fill, class: 'floor' }, svg);
  }
  // equipamiento
  const fx = el('g', { class: 'furn' }, svg);
  rooms.forEach((r) => furniture(fx, r));

  // tabiques
  const walls = el('g', { class: 'walls' }, svg);
  for (const [, x, y, w, h, kind] of covered) el('rect', { x, y, width: w, height: h, class: 'wall-in' }, walls);
  // muro perimetral
  el('rect', { x: 0, y: 0, width: W, height: D, class: 'wall-out' }, walls);

  // aberturas: puertas (con barrido) y vanos abiertos
  const cut = el('g', { class: 'cuts' }, svg);
  const door = (seg, room, width = 0.85) => {
    const mid = (seg.s + seg.e) / 2, a = mid - width / 2, b = mid + width / 2;
    const [, rx, ry, rw, rh] = room;
    if (seg.v) {
      el('rect', { x: seg.x - 0.09, y: a, width: 0.18, height: width, class: 'gap' }, cut);
      const inward = rx + rw / 2 > seg.x ? 1 : -1;
      el('path', { d: `M${seg.x} ${a} L${seg.x + inward * width} ${a} A${width} ${width} 0 0 ${inward > 0 ? 1 : 0} ${seg.x} ${b}`, class: 'swing' }, cut);
    } else {
      el('rect', { x: a, y: seg.y - 0.09, width, height: 0.18, class: 'gap' }, cut);
      const inward = ry + rh / 2 > seg.y ? 1 : -1;
      el('path', { d: `M${a} ${seg.y} L${a} ${seg.y + inward * width} A${width} ${width} 0 0 ${inward > 0 ? 0 : 1} ${b} ${seg.y}`, class: 'swing' }, cut);
    }
  };
  const opening = (seg) => {
    const len = Math.min(seg.e - seg.s - 0.4, 2.4), mid = (seg.s + seg.e) / 2;
    if (seg.v) el('rect', { x: seg.x - 0.09, y: mid - len / 2, width: 0.18, height: len, class: 'gap' }, cut);
    else el('rect', { x: mid - len / 2, y: seg.y - 0.09, width: len, height: 0.18, class: 'gap' }, cut);
  };
  const isLiving = (r) => r[5] === 'living';
  const isHall = (r) => r[5] === 'hall' && r[0] === 'Paso';
  for (const r of covered) {
    if (isLiving(r) || isHall(r)) continue;
    const name = r[0].toLowerCase();
    const prefs = name.startsWith('cocina') ? covered.filter(isLiving) : name === 'vestidor' || (name === 'baño' && covered.some((s) => s[0] === 'Suite' && shared(r, s)))
      ? covered.filter((s) => s[0] === 'Suite' || s[0] === 'Vestidor')
      : [...covered.filter(isHall), ...covered.filter(isLiving), ...covered.filter((s) => s[0] === 'Cocina y comedor' || s[0] === 'Estudio')];
    for (const s of prefs) {
      if (s === r) continue;
      const seg = shared(r, s);
      if (!seg) continue;
      if (name.startsWith('cocina') && isLiving(s)) opening(seg); else door(seg, r);
      break;
    }
  }
  // living conectado con comedor/cocina abierta
  for (const a of covered) for (const b of covered) if (a !== b && isLiving(a) && isLiving(b) && a[0] < b[0]) { const s = shared(a, b); if (s) opening(s); }
  // ventanal continuo hacia el balcón
  el('line', { x1: 0.15, y1: 0, x2: W - 0.15, y2: 0, class: 'glass' }, svg);
  el('line', { x1: 0.15, y1: 0, x2: W - 0.15, y2: 0, class: 'glass-in' }, svg);
  // baranda
  const bal = rooms.find((r) => r[5] === 'balcony');
  if (bal) el('line', { x1: bal[1], y1: bal[2] + 0.05, x2: bal[1] + bal[3], y2: bal[2] + 0.05, class: 'rail' }, svg);
  // acceso desde el palier: por el lado del pasillo (o del living) que toque el perímetro
  let entry = null;
  for (const r of [...covered.filter(isHall), ...covered.filter(isLiving)]) {
    const [, x, y, w, h] = r;
    if (Math.abs(y + h - D) < EPS) { entry = { r, side: 'b', c: x + w / 2 }; break; }
    if (Math.abs(x + w - W) < EPS) { entry = { r, side: 'r', c: y + h / 2 }; break; }
    if (Math.abs(x) < EPS) { entry = { r, side: 'l', c: y + h / 2 }; break; }
  }
  if (entry) {
    const { r, side, c } = entry;
    if (side === 'b') {
      door({ v: false, y: D, s: c - 0.5, e: c + 0.5 }, r, 0.95);
      el('path', { d: `M${c - 0.35} ${D + 1.15} L${c} ${D + 0.55} L${c + 0.35} ${D + 1.15}`, class: 'entry' }, svg);
      el('text', { x: c, y: D + 1.6, class: 'entry-t' }, svg).textContent = 'Acceso';
    } else {
      const x = side === 'r' ? W : 0, k = side === 'r' ? 1 : -1;
      door({ v: true, x, s: c - 0.5, e: c + 0.5 }, r, 0.95);
      el('path', { d: `M${x + k * 1.15} ${c - 0.35} L${x + k * 0.55} ${c} L${x + k * 1.15} ${c + 0.35}`, class: 'entry' }, svg);
      el('text', { x: x + k * 1.25, y: c + 0.95, class: 'entry-t' }, svg).textContent = 'Acceso';
    }
  }

  // rótulos
  const lab = el('g', { class: 'labels' }, svg);
  for (const [name, x, y, w, h, kind] of rooms) {
    if (w < 1.7 || h < 1.5) continue;
    const words = name.split(' ');
    const lines = name.length * 0.26 > w - 0.4 && words.length > 1 ? [words.slice(0, Math.ceil(words.length / 2)).join(' '), words.slice(Math.ceil(words.length / 2)).join(' ')] : [name];
    const cy = kind === 'balcony' ? y + h / 2 : y + h / 2 - 0.2;
    const tg = el('g', { class: 'tag' }, lab);
    lines.forEach((ln, j) => { el('text', { x: x + w / 2, y: cy + (j - (lines.length - 1) / 2) * 0.52, class: 'lbl' }, tg).textContent = ln; });
    if (areas) el('text', { x: x + w / 2, y: cy + (lines.length - 1) * 0.26 + 0.55, class: 'lbl-a' }, tg).textContent = m2(Math.round(w * h * 10) / 10);
  }
  // norte
  const g = el('g', { class: 'north', transform: `translate(${x1 + pad - 1} ${y0 - pad + 0.4}) rotate(${-bearing})` }, svg);
  el('circle', { cx: 0, cy: 0, r: 0.75 }, g);
  el('path', { d: 'M0 -0.62 L0.28 0.35 L0 0.18 L-0.28 0.35 Z' }, g);
  el('text', { x: 0, y: -0.9 }, g).textContent = 'N';
  // escala gráfica
  const sc = el('g', { class: 'scale', transform: `translate(${x0} ${y1 + pad + 0.3})` }, svg);
  for (let i = 0; i < 4; i++) el('rect', { x: i, y: 0, width: 1, height: 0.18, class: i % 2 ? 'sc-b' : 'sc-w' }, sc);
  el('text', { x: 0, y: 0.75 }, sc).textContent = '0';
  el('text', { x: 4, y: 0.75 }, sc).textContent = '4 m';
}

/**
 * Planta del piso: losa, núcleo y unidades por estado. El dibujo gira con el piso;
 * las referencias del entorno (lago, cerro) quedan fijas.
 */
export function drawPlate(svg, floor, types, { onUnit } = {}) {
  svg.innerHTML = '';
  svg.setAttribute('viewBox', '-24 -24 48 48');
  const defs = el('defs', {}, svg);
  const h = el('pattern', { id: 'sold', width: 0.9, height: 0.9, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
  el('line', { x1: 0, y1: 0, x2: 0, y2: 0.9, class: 'sold-ln' }, h);

  // entorno fijo
  const ctx = el('g', { class: 'ctx' }, svg);
  el('circle', { cx: 0, cy: 0, r: 20.5, class: 'ring' }, ctx);
  for (let a = 0; a < 360; a += 15) {
    const r1 = a % 90 === 0 ? 19.3 : 19.9, rad = (a * Math.PI) / 180;
    el('line', { x1: Math.sin(rad) * r1, y1: -Math.cos(rad) * r1, x2: Math.sin(rad) * 20.5, y2: -Math.cos(rad) * 20.5, class: 'tick' }, ctx);
  }
  const ctxLab = [['Lago Ilén', 0, -21.9, 'water'], ['Cerro Ilén', 0, 22.9, ''], ['Pueblo y muelle', -22.4, 0, 'v'], ['Bosque de lengas', 22.4, 0, 'v']];
  for (const [t, x, y, c] of ctxLab) {
    const tx = el('text', { x, y, class: `ctx-t ${c}` }, ctx);
    if (c.includes('v')) tx.setAttribute('transform', `rotate(${x < 0 ? -90 : 90} ${x} ${y})`);
    tx.textContent = t;
  }
  el('text', { x: 0, y: -18.2, class: 'ctx-n' }, ctx).textContent = 'N';

  // losa rotada
  const g = el('g', { class: 'plate', transform: `rotate(${floor.rot})` }, svg);
  el('rect', { x: -13, y: -13, width: 26, height: 26, rx: 3.2, class: 'slab' }, g);
  el('rect', { x: -11.6, y: -11.6, width: 23.2, height: 23.2, rx: 1.8, class: 'glazing' }, g);
  const units = [];
  floor.units.forEach((u, k) => {
    const ug = el('g', { class: `unit u-${u.status}`, tabindex: 0, role: 'button', 'aria-label': `Unidad ${u.id}, ${types[u.type].rooms}, ${u.status}` }, g);
    const d = `M${u.poly.map((p) => p.join(' ')).join('L')}Z` + (u.hole ? `M${u.hole.map((p) => p.join(' ')).join('L')}Z` : '');
    el('path', { d, class: 'u-fill', 'fill-rule': 'evenodd' }, ug);
    if (u.status === 'vendida') el('path', { d, fill: 'url(#sold)', 'fill-rule': 'evenodd', class: 'u-hatch' }, ug);
    el('path', { d, class: 'u-edge', 'fill-rule': 'evenodd' }, ug);
    // punto del rótulo: el centro "útil" de cada forma, lejos del núcleo
    const [cx, cy] = { TL: [-7.5, -7.5], TR: [7.5, -7.5], BR: [7.5, 7.5], BL: [-7.5, 7.5], LH: [-8, 0], RH: [8, 0], FULL: [0, -8] }[u.shape];
    // el texto se contra-rota para quedar derecho
    const tg = el('g', { transform: `translate(${cx} ${cy}) rotate(${-floor.rot})`, class: 'u-tag' }, ug);
    el('text', { x: 0, y: -0.2, class: 'u-id' }, tg).textContent = u.letter;
    el('text', { x: 0, y: 1.5, class: 'u-st' }, tg).textContent = u.status;
    ug.addEventListener('click', () => onUnit?.(k));
    ug.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onUnit?.(k); } });
    units.push(ug);
  });
  // núcleo: ascensores y escalera
  const core = el('g', { class: 'core' }, g);
  el('path', { d: `M${CORE.map((p) => p.join(' ')).join('L')}Z`, class: 'core-bg' }, core);
  for (const x of [-3.4, -1.6]) { el('rect', { x, y: -3.4, width: 1.6, height: 1.8, class: 'lift' }, core); el('path', { d: `M${x} -3.4L${x + 1.6} -1.6M${x + 1.6} -3.4L${x} -1.6`, class: 'lift-x' }, core); }
  for (let i = 0; i < 9; i++) el('line', { x1: 0.6 + i * 0.32, y1: -3.4, x2: 0.6 + i * 0.32, y2: 0.4, class: 'stair' }, core);
  el('rect', { x: -3.4, y: 0.9, width: 6.8, height: 2.5, class: 'lobby' }, core);
  return units;
}
