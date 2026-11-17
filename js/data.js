// Lenga — datos del edificio (locación ficticia: Puerto Ilén, lago Ilén)

export const TWIST_DEG = 4; // cada planta gira 4° sobre la de abajo (desde el piso 3)

// Polígonos de planta en metros. Cuadrado ±11.8, núcleo ±4.3.
// y negativo = norte (lago) cuando el piso no está rotado.
const O = 11.8, C = 4.3, g = 0.35;
const SHAPES = {
  TL: [[-O, -O], [-g, -O], [-g, -C], [-C, -C], [-C, -g], [-O, -g]],
  TR: [[g, -O], [O, -O], [O, -g], [C, -g], [C, -C], [g, -C]],
  BR: [[C, g], [O, g], [O, O], [g, O], [g, C], [C, C]],
  BL: [[-O, g], [-C, g], [-C, C], [-g, C], [-g, O], [-O, O]],
  LH: [[-O, -O], [-g, -O], [-g, -C], [-C, -C], [-C, C], [-g, C], [-g, O], [-O, O]],
  RH: [[g, -O], [O, -O], [O, O], [g, O], [g, C], [C, C], [C, -C], [g, -C]],
  FULL: [[-O, -O], [O, -O], [O, O], [-O, O]],
};
export const CORE = [[-C, -C], [C, -C], [C, C], [-C, C]];

// Tipologías. Ambientes: [nombre, x, y, ancho, prof, tipo] en metros.
export const TYPES = {
  B1: {
    name: 'Tipo B1', rooms: '2 dormitorios',
    plan: [
      ['Balcón', 0, -2, 10.4, 2, 'balcony'],
      ['Estar y comedor', 0, 0, 7.2, 5.2, 'living'],
      ['Cocina', 7.2, 0, 3.2, 3.4, 'wet'],
      ['Lavadero', 7.2, 3.4, 3.2, 1.8, 'wet'],
      ['Dormitorio', 0, 5.2, 4.4, 4, 'bed'],
      ['Baño', 4.4, 5.2, 2.4, 2.2, 'wet'],
      ['Paso', 4.4, 7.4, 2.4, 1.8, 'hall'],
      ['Dormitorio', 6.8, 5.2, 3.6, 4, 'bed'],
    ],
  },
  B2: {
    name: 'Tipo B2', rooms: '2 dormitorios y estudio',
    plan: [
      ['Balcón', 0, -2, 12, 2, 'balcony'],
      ['Estar y comedor', 0, 0, 7, 5.4, 'living'],
      ['Cocina', 7, 0, 5, 3.2, 'wet'],
      ['Estudio', 7, 3.2, 3, 2.2, 'bed'],
      ['Toilette', 10, 3.2, 2, 2.2, 'wet'],
      ['Suite', 0, 5.4, 4.6, 4.2, 'bed'],
      ['Vestidor', 4.6, 5.4, 2, 2, 'hall'],
      ['Baño', 4.6, 7.4, 2, 2.2, 'wet'],
      ['Paso', 6.6, 5.4, 1.6, 4.2, 'hall'],
      ['Dormitorio', 8.2, 5.4, 3.8, 4.2, 'bed'],
    ],
  },
  L2: {
    name: 'Tipo L2', rooms: '2 suites',
    plan: [
      ['Balcón', 0, -2.4, 13, 2.4, 'balcony'],
      ['Estar', 0, 0, 8, 5.6, 'living'],
      ['Cocina y comedor', 8, 0, 5, 5.6, 'wet'],
      ['Suite', 0, 5.6, 5, 4.4, 'bed'],
      ['Baño', 5, 5.6, 2.4, 2.4, 'wet'],
      ['Vestidor', 5, 8, 2.4, 2, 'hall'],
      ['Baño', 7.4, 5.6, 1.6, 4.4, 'wet'],
      ['Suite', 9, 5.6, 4, 4.4, 'bed'],
    ],
  },
  L3: {
    name: 'Tipo L3', rooms: '3 dormitorios',
    plan: [
      ['Balcón', 0, -2.4, 15, 2.4, 'balcony'],
      ['Estar y comedor', 0, 0, 9, 6, 'living'],
      ['Cocina', 9, 0, 4, 4, 'wet'],
      ['Lavadero', 13, 0, 2, 4, 'wet'],
      ['Baño', 9, 4, 2.6, 2, 'wet'],
      ['Paso', 11.6, 4, 3.4, 2, 'hall'],
      ['Suite', 0, 6, 5, 4.6, 'bed'],
      ['Baño', 5, 6, 2.4, 2.6, 'wet'],
      ['Vestidor', 5, 8.6, 2.4, 2, 'hall'],
      ['Dormitorio', 7.4, 6, 3.8, 4.6, 'bed'],
      ['Dormitorio', 11.2, 6, 3.8, 4.6, 'bed'],
    ],
  },
  C3: {
    name: 'Tipo C3', rooms: '3 dormitorios y estudio',
    plan: [
      ['Galería', 0, -3, 18, 3, 'balcony'],
      ['Estar', 0, 0, 9, 6.4, 'living'],
      ['Comedor', 9, 0, 4.5, 6.4, 'living'],
      ['Cocina', 13.5, 0, 4.5, 4.2, 'wet'],
      ['Lavadero', 13.5, 4.2, 4.5, 2.2, 'wet'],
      ['Suite', 0, 6.4, 5.4, 5, 'bed'],
      ['Baño', 5.4, 6.4, 2.6, 2.8, 'wet'],
      ['Vestidor', 5.4, 9.2, 2.6, 2.2, 'hall'],
      ['Estudio', 8, 6.4, 3.4, 2.6, 'bed'],
      ['Baño', 8, 9, 1.8, 2.4, 'wet'],
      ['Paso', 9.8, 9, 1.6, 2.4, 'hall'],
      ['Dormitorio', 11.4, 6.4, 3.4, 5, 'bed'],
      ['Dormitorio', 14.8, 6.4, 3.2, 5, 'bed'],
    ],
  },
  PH: {
    name: 'Penthouse', rooms: '3 dormitorios, biblioteca y terraza',
    plan: [
      ['Terraza', 0, -4, 22, 4, 'balcony'],
      ['Estar', 0, 0, 10, 7, 'living'],
      ['Comedor', 10, 0, 6, 7, 'living'],
      ['Cocina', 16, 0, 6, 5, 'wet'],
      ['Despensa', 16, 5, 6, 2, 'wet'],
      ['Suite', 0, 7, 7, 5.5, 'bed'],
      ['Vestidor', 7, 7, 3, 2.5, 'hall'],
      ['Baño', 7, 9.5, 3, 3, 'wet'],
      ['Biblioteca', 10, 7, 4, 3, 'bed'],
      ['Toilette', 10, 10, 2, 2.5, 'wet'],
      ['Paso', 12, 10, 2, 2.5, 'hall'],
      ['Dormitorio', 14, 7, 4, 5.5, 'bed'],
      ['Dormitorio', 18, 7, 4, 5.5, 'bed'],
    ],
  },
};

for (const t of Object.values(TYPES)) {
  let covered = 0, open = 0;
  for (const [, , , w, h, k] of t.plan) (k === 'balcony' ? (open += w * h) : (covered += w * h));
  t.covered = Math.round(covered);
  t.open = Math.round(open);
}

export const ZONES = {
  club: { name: 'Club', text: 'Lobby, pileta, sauna, gimnasio y fogón. Los dos pisos que comparten todos.' },
  bosque: { name: 'Bosque', text: 'Cuatro unidades por piso, a la altura de las copas de las lengas.' },
  lago: { name: 'Lago', text: 'Tres unidades por piso. Desde acá el lago se ve entero.' },
  cumbre: { name: 'Cumbre', text: 'Dos unidades por piso, cada una con galería en tres frentes.' },
  ph: { name: 'Penthouse', text: 'Una sola unidad, con terraza y el valle completo alrededor.' },
};

const LAYOUTS = {
  bosque: [['TL', 'B2'], ['TR', 'B1'], ['BR', 'B2'], ['BL', 'B1']],
  lago: [['LH', 'L3'], ['TR', 'L2'], ['BR', 'L2']],
  cumbre: [['LH', 'C3'], ['RH', 'C3']],
  ph: [['FULL', 'PH']],
};

// Estado determinístico: el mismo piso siempre muestra la misma disponibilidad.
function status(n, i) {
  if (n === 18) return 'disponible';
  const r = Math.abs(Math.sin(n * 12.9898 + i * 78.233) * 43758.5453) % 1;
  return r < 0.42 ? 'vendida' : r < 0.58 ? 'reservada' : 'disponible';
}

const BEARINGS = [
  ['Norte', 'el lago Ilén de frente'],
  ['Noreste', 'el lago y la bahía'],
  ['Este', 'el bosque de lengas'],
  ['Sureste', 'la ladera del cerro'],
  ['Sur', 'el cerro Ilén y las pistas'],
  ['Suroeste', 'el valle del río'],
  ['Oeste', 'el pueblo y el muelle'],
  ['Noroeste', 'el lago y la península'],
];

// Ángulo en grados (0 = norte, horario) → orientación + vista
export function bearingInfo(deg) {
  const i = Math.round((((deg % 360) + 360) % 360) / 45) % 8;
  return { dir: BEARINGS[i][0], view: BEARINGS[i][1] };
}

function centroid(poly) {
  let x = 0, y = 0;
  for (const p of poly) { x += p[0]; y += p[1]; }
  return [x / poly.length, y / poly.length];
}

export const FLOORS = [];
for (let n = 1; n <= 18; n++) {
  const zone = n <= 2 ? 'club' : n <= 8 ? 'bosque' : n <= 14 ? 'lago' : n <= 17 ? 'cumbre' : 'ph';
  const rot = n <= 2 ? 0 : (n - 3) * TWIST_DEG; // grados, horario visto desde arriba
  const units = (LAYOUTS[zone] || []).map(([shape, type], i) => {
    const poly = SHAPES[shape];
    const [cx, cy] = shape === 'FULL' ? [0, -1] : centroid(poly);
    // dirección de la unidad: y negativo = norte
    const local = Math.atan2(cx, -cy) * 180 / Math.PI;
    return {
      id: `${n}${'ABCD'[i]}`, letter: 'ABCD'[i], shape, poly, hole: shape === 'FULL' ? CORE : null,
      type, status: status(n, i), bearing: local + rot,
    };
  });
  FLOORS.push({ n, zone, rot, units, front: bearingInfo(rot) });
}

