"""Calibra el contorno de cada piso sobre la foto final de la torre (img/originales/torre-16x9.jpg).
Cada losa de la torre se sigue de punta a punta como el camino más marcado de una banda clara entre
ventanas oscuras (programación dinámica), así se respetan la perspectiva y las puntas redondeadas.
Las losas del podio son horizontales. Un piso es la franja entre su losa y la de arriba.
Escribe js/zones.js y un control visual en img/originales/zonas-control.jpg.
Uso: python -I tools/zonas.py"""
import json
import pathlib

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import uniform_filter1d

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'img' / 'originales' / 'torre-16x9.jpg'

im = Image.open(SRC).convert('RGB')
a = np.asarray(im).astype(float)
H, W, _ = a.shape
lum = a.mean(axis=2)
sat = a.max(axis=2) - a.min(axis=2)
lum = np.where(sat < 80, lum, lum * 0.6)  # la losa es gris claro: la madera y el cielo saturados cuentan menos
band = uniform_filter1d(lum, 9, axis=0)
score = band - 0.5 * (np.roll(band, 12, axis=0) + np.roll(band, -12, axis=0))  # claro con oscuro arriba y abajo

X0 = 1385  # columna de referencia, sobre el frente de la torre
# altura de cada losa de la torre en X0, del techo (0) a la losa del piso 3 sobre el podio (16)
SLABS = [173, 238, 292, 352, 410, 464, 520, 576, 636, 695, 754, 817, 878, 938, 998, 1056, 1114]
PODIUM = [1114.7, 1190.5, 1282.5]  # losas del podio: techo del piso 2, techo de planta baja, vereda
ks = np.arange(len(SLABS))
LEFT = np.interp(ks, [0, 16], [1138, 1090])   # bordes aproximados de la torre (se recortan solos)
RIGHT = np.interp(ks, [0, 16], [1650, 1688])
STEP, WIN, DMAX = 2, 16, 3


def trace(xs, prior):
    """camino de máximo puntaje dentro de prior ± WIN, con saltos de hasta DMAX px por paso
    y castigo por apartarse de la forma de la losa de arriba"""
    offs = np.arange(-WIN, WIN + 1)
    n, m = len(xs), len(offs)
    S = np.full((n, m), -1e9)
    B = np.zeros((n, m), int)
    for i, (x, py) in enumerate(zip(xs, prior)):
        ys = np.clip(np.round(py + offs).astype(int), 0, H - 1)
        s = score[ys, int(x)]
        if i == 0:
            S[0] = s
            continue
        jump = (py + offs[:, None]) - (prior[i - 1] + offs[None, :])  # [j actual, jj anterior]
        cand = np.where(np.abs(jump) <= DMAX, S[i - 1][None, :] - 0.8 * np.abs(jump - (py - prior[i - 1])), -1e9)
        B[i] = cand.argmax(axis=1)
        S[i] = cand.max(axis=1) + s
    j = int(S[-1].argmax())
    path = [j]
    for i in range(n - 1, 0, -1):
        j = B[i, j]
        path.append(j)
    ys = prior + offs[np.array(path[::-1])]
    return uniform_filter1d(ys.astype(float), 5)


def trim(xs, ys, thr=10, run=4):
    """corta las puntas donde el camino ya no va por una losa (cielo, árboles)"""
    s = uniform_filter1d(score[np.round(ys).astype(int), xs.astype(int)], 5)
    c = int(np.argmin(np.abs(xs - X0)))
    lo, hi = 0, len(xs) - 1
    for i in range(c, -1, -1):
        if (s[max(0, i - run + 1):i + 1] < thr).all():
            lo = i + run
            break
    for i in range(c, len(xs)):
        if (s[i:i + run] < thr).all():
            hi = i - 1
            break
    return xs[lo:hi + 1], ys[lo:hi + 1]


slabs, prev = [], None
for k, ye in enumerate(SLABS):
    xs = np.arange(int(LEFT[k]) - 6, int(RIGHT[k]) + 7, STEP).astype(float)
    prior = np.full(len(xs), float(ye)) if prev is None else np.interp(xs, *prev) + (ye - np.interp(X0, *prev))
    ys = trace(xs, prior)
    xs_t, ys_t = trim(xs, ys)
    slabs.append((xs_t, ys_t))
    prev = (xs, ys)  # la forma completa guía a la losa de abajo
    print(k, f'y en X0 {np.interp(X0, xs_t, ys_t):6.1f}  x {xs_t[0]:.0f}..{xs_t[-1]:.0f}')

def along(x, sl, other):
    """altura de la losa sl en x; pasada su punta copia la forma de la otra losa del piso (paralela),
    así la franja sigue la esquina redondeada en vez de salirse al cielo"""
    xs, ys = sl
    for end in (0, -1):
        if (x < xs[0]) if end == 0 else (x > xs[-1]):
            off = ys[end] - np.interp(xs[end], *other)
            return float(np.interp(x, *other) + off)
    return float(np.interp(x, xs, ys))


zones = {}
N = 24
for n in range(3, 19):
    top, bot = slabs[18 - n], slabs[19 - n]
    # a la izquierda manda la losa más larga (las de arriba se redondean antes); a la derecha la más corta,
    # así el piso no se sale de la fachada
    xl, xr = min(top[0][0], bot[0][0]), min(top[0][-1], bot[0][-1])
    if abs(top[0][0] - bot[0][0]) > 25:  # una losa termina mucho antes (esquina redondeada): no inventar la punta
        xl = max(top[0][0], bot[0][0])
    xs = np.linspace(xl, xr, N)
    poly = [[round(float(x), 1), round(along(x, top, bot), 1)] for x in xs]
    poly += [[round(float(x), 1), round(along(x, bot, top), 1)] for x in xs[::-1]]
    zones[n] = poly
# podio: piso 2 y planta baja, horizontales y más anchos que la torre
for n, (top, bot) in {2: (PODIUM[0], PODIUM[1]), 1: (PODIUM[1], PODIUM[2])}.items():
    xs = np.linspace(950, 1800, 8)
    zones[n] = [[round(float(x), 1), top] for x in xs] + [[round(float(x), 1), bot] for x in xs[::-1]]

(ROOT / 'js' / 'zones.js').write_text(
    '// Generado por tools/zonas.py\n'
    f'export const RENDER = {{ w: {W}, h: {H} }};\n'
    '// Contorno de cada piso sobre la foto final de la torre (px de la imagen), medido de las losas\n'
    f'export const FLOOR_ZONES = {json.dumps({str(k): v for k, v in sorted(zones.items())})};\n', encoding='utf-8')

ov = im.copy()
d = ImageDraw.Draw(ov, 'RGBA')
for n, poly in zones.items():
    col = (242, 182, 109, 70) if n % 2 else (120, 200, 255, 70)
    d.polygon([tuple(p) for p in poly], fill=col, outline=(255, 255, 255, 200))
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    d.text((cx - 6, cy - 6), str(n), fill=(255, 255, 255, 255))
ov.crop((850, 100, 1900, 1350)).save(ROOT / 'img' / 'originales' / 'zonas-control.jpg', quality=85)
print('listo', len(zones), 'pisos')
