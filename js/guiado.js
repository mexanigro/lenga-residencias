// Recorrido guiado en video (piloto: living y cocina), renderizado en Cycles con tools/video.py.
// Cada ambiente tiene ángulos fijos; cada tramo une dos ángulos y empieza y termina exactamente en sus cuadros.
// Para ir de un ángulo a otro se encadenan tramos con dos <video> superpuestos: el que sigue arranca debajo y pasa
// adelante cuando ya muestra su primer cuadro, que es igual al último del anterior, así no hay corte.
import { VIDEO } from './video.js';

export function createGuiado(root, { reduced, onAngle }) {
  const suf = matchMedia('(max-width: 900px), (max-height: 560px)').matches ? '-m' : '';
  const still = root.querySelector('img');
  let [front, back] = root.querySelectorAll('video');
  const near = {};
  for (const k of Object.keys(VIDEO.moves)) { const [p, q] = k.split('~'); (near[p] ??= []).push(q); }

  // cada tramo se baja entero una sola vez (el sentido contrario es otro archivo)
  const blobs = new Map();
  const load = (k) => {
    if (!blobs.has(k)) {
      const p = fetch(`video/${k}${suf}.mp4`).then((r) => { if (!r.ok) throw new Error(`${k}: ${r.status}`); return r.blob(); })
        .then((b) => URL.createObjectURL(b));
      p.catch(() => blobs.delete(k));
      blobs.set(k, p);
    }
    return blobs.get(k);
  };
  const prefetch = (a) => near[a].forEach((b) => load(`${a}~${b}`).catch(() => {}));

  // camino más corto entre dos ángulos por los tramos
  function route(a, b) {
    const prev = { [a]: null }, queue = [a];
    while (queue.length) {
      const x = queue.shift();
      if (x === b) break;
      for (const y of near[x]) if (!(y in prev)) { prev[y] = x; queue.push(y); }
    }
    const path = [b];
    while (prev[path[0]]) path.unshift(prev[path[0]]);
    return path;
  }

  // gen: cada vez que se entra o se sale cambia, y un encadenado viejo que sigue esperando ya no toca nada
  let at = null, target = null, gen = 0, running = -1;
  const once = (el, ev) => new Promise((ok, ko) => {
    const off = () => { el.removeEventListener(ev, done); el.removeEventListener('error', fail); };
    const done = () => { off(); ok(); };
    const fail = () => { off(); ko(el.error); };
    el.addEventListener(ev, done);
    el.addEventListener('error', fail);
  });

  function arrive(k) {
    at = k;
    onAngle(k);
    prefetch(k);
  }
  async function jump(k) { // sin video: movimiento reducido, o un tramo que no bajó
    still.src = `video/${k}${suf}.webp`;
    await still.decode().catch(() => {});
    still.hidden = false;
    front.classList.remove('is-on');
    back.classList.remove('is-on');
    arrive(k);
  }
  async function run() {
    if (running === gen) return;
    const g = (running = gen);
    try {
      while (g === gen && at !== target) {
        if (reduced) { await jump(target); break; }
        const next = route(at, target)[1];
        try {
          const src = await load(`${at}~${next}`);
          if (g !== gen) return;
          back.src = src;
          const started = once(back, 'playing');
          await back.play();
          await started;
          await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); // primer cuadro pintado
          if (g !== gen) return;
          back.classList.add('is-on');
          front.classList.remove('is-on');
          still.hidden = true;
          [front, back] = [back, front];
          if (!front.ended) await once(front, 'ended');
          if (g !== gen) return;
          arrive(next);
        } catch (err) {
          console.error(err);
          if (g === gen) await jump(next);
        }
      }
    } finally { if (running === g) running = -1; }
  }

  return {
    // entra parado en un ángulo, con su cuadro fijo
    async open(k) {
      gen++;
      target = k;
      front.pause(); back.pause();
      await jump(k);
    },
    go(k) { // se bajan ya todos los tramos del camino, así no frena entre uno y otro
      if (at) route(at, k).forEach((x, i, p) => { if (i) load(`${p[i - 1]}~${x}`).catch(() => {}); });
      target = k;
      run();
    },
    pause() { gen++; front.pause(); back.pause(); },
    get angle() { return at; },
  };
}
