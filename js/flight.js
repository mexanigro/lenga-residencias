// Inicio por scroll en una sola toma, dibujada en un canvas:
// 1. Acercamiento: cuadros de un vuelo de dron (tools/vuelo.py) que termina frente al terreno vacío. Entre dos
//    cuadros se funde el siguiente según la fracción del scroll, así el movimiento no salta.
// 2. Obra: la cámara queda quieta y la torre se construye con el scroll a partir de cuatro placas alineadas con la
//    foto final (tools/obra.py): terreno, base con la grúa, estructura de hormigón y la torre terminada. La estructura
//    sube y la fachada se termina piso por piso, siguiendo el contorno real de cada losa (js/zones.js).
// En pantallas verticales el vuelo usa un recorte central 3:4 más liviano; las placas se recortan centradas.
import { FLOOR_ZONES, RENDER } from './zones.js';

const N = 168; // cuadros del acercamiento
const SETS = { d: { w: 1920, h: 1080 }, m: { w: 810, h: 1080 } };
const FULL = 16 / 9; // proporción de la toma completa (los rótulos se ubican en % de ella)
const pad = (i) => String(i).padStart(3, '0');
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const seg = (t, a, b) => clamp01((t - a) / (b - a));
const smooth = (x) => x * x * (3 - 2 * x);
// listo cuando se decodifica; si la pestaña está en segundo plano el navegador demora la decodificación,
// así que también alcanza con que haya bajado (se decodifica al dibujarlo)
const settle = (im) => Promise.race([
  im.decode(),
  new Promise((res, rej) => { im.addEventListener('load', () => setTimeout(res, 250)); im.addEventListener('error', rej); }),
]);

// tramos de t (0 = aérea alta, 1 = torre terminada)
const T = {
  fly: 0.4, // fin del acercamiento
  plate: [0.385, 0.415], // del último cuadro del video a la placa del terreno (son la misma toma)
  base: [0.46, 0.53], // obrador, grúa y basamento
  rise: [0.53, 0.75], // la estructura sube piso por piso
  site: [0.73, 0.78], // el obrador de la estructura (redes, acopios)
  skin: [0.78, 0.95], // fachada y luces, piso por piso
  done: [0.93, 0.995], // se va la grúa, se ordena el terreno, el lago refleja las luces
};

// pisos de la torre de abajo hacia arriba (1 y 2 son el basamento), más el remate de la terraza
const FLOORS = Object.keys(FLOOR_ZONES).map(Number).sort((a, b) => a - b).map((n) => FLOOR_ZONES[n]);
const TOP = FLOORS[FLOORS.length - 1];
const ROOF = (() => {
  const edge = TOP.slice(0, TOP.length / 2); // borde superior del último piso, de izquierda a derecha
  return [...edge.map(([x, y]) => [x, y - 34]), ...edge.slice().reverse()];
})();
const TOWER_FLOORS = FLOORS.slice(2).concat([ROOF]); // los que sube la estructura
const ALL_FLOORS = FLOORS.concat([ROOF]); // los que cierra la fachada

export function createFlight(canvas, marks, { reduced = false } = {}) {
  const ctx = canvas.getContext('2d', { alpha: false });
  const portrait = matchMedia('(max-aspect-ratio: 4/5)');
  let set, imgs, ok, gen = 0, criticalTotal = 1, criticalDone = 0, lastKey = '';
  let resolveCritical;
  const critical = new Promise((r) => { resolveCritical = r; });

  // placas de la obra (la última es la foto final, la misma que usa el edificio interactivo)
  const plates = {};
  const plateOk = {};
  const loadPlate = (k, src) => {
    const im = new Image();
    im.decoding = 'async';
    im.src = src;
    plates[k] = im;
    return settle(im).then(() => { plateOk[k] = true; lastKey = ''; }).catch(() => {});
  };

  // orden de carga: el primero, uno de cada 16 (alcanza para bajar), después se van llenando los huecos
  function order() {
    const out = [], seen = new Set();
    const add = (i) => { if (!seen.has(i)) { seen.add(i); out.push(i); } };
    add(0);
    // con ahorro de datos o conexión lenta, uno de cada dos cuadros (el fundido entre vecinos disimula el resto)
    const c = navigator.connection, lite = c && (c.saveData || /(^|-)2g|3g/.test(c.effectiveType || ''));
    for (const s of lite ? [16, 8, 4, 2] : [16, 8, 4, 2, 1]) {
      for (let i = 0; i < N; i += s) add(i);
      add(N - 1);
    }
    return out;
  }

  function useSet(next) {
    set = next;
    // cada set tiene su propio estado: las cargas que siguen llegando del set anterior no cuentan
    const g = ++gen, mine = new Array(N), okMine = new Uint8Array(N);
    imgs = mine;
    ok = okMine;
    const all = order();
    const crit = new Set(all.slice(0, all.indexOf(8)));
    criticalTotal = crit.size;
    criticalDone = 0;
    const queue = all.slice();
    let active = 0, plateQueued = false;
    const pump = () => {
      while (g === gen && active < 6 && queue.length) {
        const i = queue.shift();
        const im = new Image();
        im.decoding = 'async';
        im.src = `img/vuelo/${next}/${pad(i)}.webp`;
        mine[i] = im;
        active++;
        settle(im).then(() => { okMine[i] = 1; }).catch(() => {}).finally(() => {
          active--;
          if (g !== gen) return;
          if (crit.has(i) && ++criticalDone === criticalTotal) resolveCritical();
          lastKey = '';
          // las placas de la obra se piden cuando el vuelo ya tiene su esqueleto (no compiten con el arranque)
          if (!plateQueued && criticalDone === criticalTotal) {
            plateQueued = true;
            ['terreno', 'base', 'estructura'].forEach((k) => plates[k] || loadPlate(k, `img/obra/${k}.webp`));
            plates.torre || loadPlate('torre', 'img/torre.webp');
          }
          pump();
        });
      }
    };
    pump();
  }
  useSet(portrait.matches ? 'm' : 'd');

  let W = 1, H = 1, box = [0, 0, 1, 1], pbox = [0, 0, 1, 1];
  const cover = (iw, ih) => {
    const s = Math.max(W / iw, H / ih);
    return [(W - iw * s) / 2, (H - ih * s) / 2, iw * s, ih * s];
  };
  function resize() {
    const want = portrait.matches ? 'm' : 'd';
    if (want !== set) useSet(want);
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = Math.round(canvas.clientWidth * dpr);
    H = Math.round(canvas.clientHeight * dpr);
    canvas.width = W;
    canvas.height = H;
    ctx.imageSmoothingQuality = 'high';
    box = cover(SETS[set].w, SETS[set].h);
    pbox = cover(RENDER.w, RENDER.h);
    // caja de los rótulos: la toma completa 16:9 a la misma escala, centrada
    const cssH = box[3] / dpr, cssW = cssH * FULL;
    Object.assign(marks.style, { width: `${cssW}px`, height: `${cssH}px`, left: `${(W / dpr - cssW) / 2}px`, top: `${box[1] / dpr}px` });
    lastKey = '';
  }
  addEventListener('resize', resize);
  resize();

  const nearest = (i) => {
    for (let d = 0; d < N; d++) {
      if (i - d >= 0 && ok[i - d]) return i - d;
      if (i + d < N && ok[i + d]) return i + d;
    }
    return -1;
  };

  /* ---- dibujo ---- */
  function frame(pos) {
    const i = Math.floor(pos), f = pos - i;
    const a = nearest(i), b = nearest(Math.min(N - 1, i + 1));
    if (a < 0) return false;
    const [x, y, w, h] = box;
    ctx.globalAlpha = 1;
    ctx.drawImage(imgs[a], x, y, w, h);
    if (b !== a && f > 0.004) {
      ctx.globalAlpha = f;
      ctx.drawImage(imgs[b], x, y, w, h);
      ctx.globalAlpha = 1;
    }
    return true;
  }
  // una placa entera con cierta opacidad
  function plate(k, alpha = 1) {
    if (!plateOk[k] || alpha <= 0.002) return false;
    ctx.globalAlpha = Math.min(1, alpha);
    ctx.drawImage(plates[k], ...pbox);
    ctx.globalAlpha = 1;
    return true;
  }
  // una placa recortada a los pisos [0, n): los completos de una vez, el que está entrando con su fundido
  function floors(k, list, n) {
    if (!plateOk[k] || n <= 0) return;
    const [x, y, w, h] = pbox, sx = w / RENDER.w, sy = h / RENDER.h;
    const path = (polys) => {
      ctx.beginPath();
      for (const poly of polys) {
        poly.forEach(([px, py], j) => (j ? ctx.lineTo : ctx.moveTo).call(ctx, x + px * sx, y + py * sy));
        ctx.closePath();
      }
    };
    const whole = Math.floor(n), part = n - whole;
    if (whole > 0) {
      ctx.save();
      path(list.slice(0, whole));
      ctx.clip();
      ctx.drawImage(plates[k], x, y, w, h);
      ctx.restore();
    }
    if (part > 0.002 && whole < list.length) {
      ctx.save();
      path([list[whole]]);
      ctx.clip();
      ctx.globalAlpha = smooth(part);
      ctx.drawImage(plates[k], x, y, w, h);
      ctx.restore();
    }
  }

  function drawBuild(t) {
    // fondo: terreno → base; durante la subida, la estructura entra por pisos sobre la base
    if (!plate('terreno')) return false;
    plate('base', smooth(seg(t, ...T.base)));
    floors('estructura', TOWER_FLOORS, seg(t, ...T.rise) * TOWER_FLOORS.length);
    plate('estructura', smooth(seg(t, ...T.site)));
    // fachada y luces de abajo hacia arriba; al final se va la grúa y aparecen los reflejos en el lago
    floors('torre', ALL_FLOORS, seg(t, ...T.skin) * ALL_FLOORS.length);
    plate('torre', smooth(seg(t, ...T.done)));
    return true;
  }

  return {
    critical,
    ready: () => Math.min(1, criticalDone / criticalTotal),
    intro() {
      if (!reduced) canvas.animate([{ transform: 'scale(1.08)', filter: 'blur(10px)' }, { transform: 'none', filter: 'none' }], { duration: 2400, easing: 'cubic-bezier(.2,.8,.2,1)' });
    },
    /** t: 0 = aérea alta, 1 = torre terminada (la misma foto que el edificio interactivo) */
    draw(t) {
      t = clamp01(t);
      const pos = seg(t, 0, T.fly) * (N - 1);
      // cada cuadro o placa que llega borra lastKey, así se redibuja aunque el scroll esté quieto
      const key = `${t.toFixed(5)}|${W}|${H}`;
      if (key === lastKey) return;
      lastKey = key;
      if (t <= T.plate[0] || !plateOk.terreno) {
        frame(pos);
        return;
      }
      if (t < T.plate[1]) {
        // empalme: el video termina en la misma toma que la placa del terreno
        frame(pos);
        ctx.globalAlpha = smooth(seg(t, ...T.plate));
        ctx.drawImage(plates.terreno, ...pbox);
        ctx.globalAlpha = 1;
        return;
      }
      drawBuild(t);
    },
  };
}
