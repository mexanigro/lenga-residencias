// Vuelo de dron por scroll: 240 cuadros (tools/vuelo.py) dibujados en un canvas.
// Entre dos cuadros se funde el siguiente según la fracción del scroll, así el movimiento no salta.
// En pantallas verticales se usa un recorte central 3:4 más liviano; en el resto, el cuadro 16:9.
const N = 240;
const SETS = { d: { w: 1600, h: 900 }, m: { w: 600, h: 800 } };
const FULL = 16 / 9; // proporción de la toma completa (los rótulos se ubican en % de ella)
const pad = (i) => String(i).padStart(3, '0');

export function createFlight(canvas, marks, { reduced = false } = {}) {
  const ctx = canvas.getContext('2d', { alpha: false });
  const portrait = matchMedia('(max-aspect-ratio: 4/5)');
  let set, imgs, ok, queue, critical, criticalTotal, criticalDone, lastKey = '';

  // orden de carga: el primero, uno de cada 16 (alcanza para bajar), después se van llenando los huecos
  function order() {
    const out = [], seen = new Set();
    const add = (i) => { if (!seen.has(i)) { seen.add(i); out.push(i); } };
    add(0);
    for (const s of [16, 8, 4, 2, 1]) {
      for (let i = 0; i < N; i += s) add(i);
      add(N - 1);
    }
    return out;
  }

  function useSet(next) {
    set = next;
    imgs = new Array(N);
    ok = new Uint8Array(N);
    const all = order();
    const crit = all.slice(0, all.indexOf(8));
    criticalTotal = crit.length;
    criticalDone = 0;
    queue = all.slice();
    let resolveCritical;
    critical = new Promise((r) => { resolveCritical = r; });
    const critSet = new Set(crit);
    let active = 0;
    const pump = () => {
      while (active < 6 && queue.length) {
        const i = queue.shift();
        const im = new Image();
        im.decoding = 'async';
        im.src = `img/vuelo/${set}/${pad(i)}.webp`;
        imgs[i] = im;
        active++;
        im.decode().then(() => { ok[i] = 1; }).catch(() => {}).finally(() => {
          active--;
          if (critSet.has(i) && ++criticalDone === criticalTotal) resolveCritical();
          lastKey = '';
          pump();
        });
      }
    };
    pump();
  }
  useSet(portrait.matches ? 'm' : 'd');

  let W = 1, H = 1, box = [0, 0, 1, 1];
  function resize() {
    const want = portrait.matches ? 'm' : 'd';
    if (want !== set) useSet(want);
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = Math.round(canvas.clientWidth * dpr);
    H = Math.round(canvas.clientHeight * dpr);
    canvas.width = W;
    canvas.height = H;
    const { w: iw, h: ih } = SETS[set];
    const s = Math.max(W / iw, H / ih);
    box = [(W - iw * s) / 2, (H - ih * s) / 2, iw * s, ih * s];
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

  return {
    critical: Promise.resolve().then(() => critical),
    ready: () => criticalDone / criticalTotal,
    intro() {
      if (!reduced) canvas.animate([{ transform: 'scale(1.08)', filter: 'blur(10px)' }, { transform: 'none', filter: 'none' }], { duration: 2400, easing: 'cubic-bezier(.2,.8,.2,1)' });
    },
    /** t: 0 = aérea alta, 1 = frente a la torre */
    draw(t) {
      const pos = Math.min(1, Math.max(0, t)) * (N - 1);
      const i = Math.floor(pos), f = pos - i;
      const a = nearest(i), b = nearest(Math.min(N - 1, i + 1));
      if (a < 0) return;
      const key = `${a}|${b}|${f.toFixed(3)}|${W}|${H}`;
      if (key === lastKey) return;
      lastKey = key;
      const [x, y, w, h] = box;
      ctx.globalAlpha = 1;
      ctx.drawImage(imgs[a], x, y, w, h);
      if (b !== a && f > 0.004) {
        ctx.globalAlpha = f;
        ctx.drawImage(imgs[b], x, y, w, h);
        ctx.globalAlpha = 1;
      }
    },
  };
}
