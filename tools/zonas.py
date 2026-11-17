"""Calibra el contorno de cada piso sobre la foto final de la torre (img/originales/torre-16x9.jpg).
Busca las losas (bandas claras) en varias columnas, ajusta una recta por losa y arma un polígono por piso.
Escribe js/zones.js y un control visual en img/originales/zonas-control.jpg.
Uso: python -I tools/zonas.py"""
import json
import pathlib

import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'img' / 'originales' / 'torre-16x9.jpg'

im = Image.open(SRC).convert('RGB')
a = np.asarray(im).astype(float)
H, W, _ = a.shape
lum = a.mean(axis=2)
sat = a.max(axis=2) - a.min(axis=2)
bright = (lum > 150) & (sat < 70)

COLS = [1105, 1135, 1170, 1205, 1240, 1275, 1310, 1350, 1385, 1420, 1460, 1495, 1530, 1565, 1600, 1635]
X0 = 1385
# losas a lo largo de la columna central, de arriba (techo) hacia abajo (piso 3), + podio
EXPECTED = [173, 238, 292, 352, 410, 464, 520, 576, 636, 695, 754, 817, 878, 938, 998, 1056, 1114, 1190, 1282]


def runs(x, y0=140, y1=1320):
    col = bright[y0:y1, x - 8:x + 8].mean(axis=1) > 0.45
    out, s = [], None
    for i, v in enumerate(col):
        if v and s is None:
            s = i
        if not v and s is not None:
            if i - s >= 3:
                out.append(y0 + (s + i - 1) / 2)
            s = None
    return out


found = {x: runs(x) for x in COLS}
lines = []
prev = np.array([0.0, 0.08, 0.0])  # c2, c1, c0 relativos a X0 (c0 se reemplaza)
for k, ye in enumerate(EXPECTED):
    pts = []
    for x in COLS:
        guess = ye + np.polyval([prev[0], prev[1], 0], x - X0)
        c = [y for y in found[x] if abs(y - guess) < 13]
        if c:
            pts.append((x, min(c, key=lambda y: abs(y - guess))))
    # arriba las losas se curvan (cuadrática); de la losa 11 para abajo son casi rectas; el podio es horizontal
    deg = 2 if k < 11 else (1 if k < 16 else 0)
    if len(pts) >= deg + 4:
        xs, ys = np.array(pts, float).T
        keep = np.ones(len(xs), bool)
        for _ in range(4):
            c = np.polyfit(xs[keep] - X0, ys[keep], deg)
            r = np.abs(np.polyval(c, xs - X0) - ys)
            keep = r < max(3, np.percentile(r[keep], 75) * 1.6)
        coef = np.polyfit(xs[keep] - X0, ys[keep], deg)
        coef = np.concatenate([np.zeros(3 - len(coef)), coef])
    else:
        off = np.median([p[1] for p in pts if abs(p[0] - X0) < 120]) if any(abs(p[0] - X0) < 120 for p in pts) else ye
        coef = np.array([0.0, 0.0 if k >= 16 else lines[-1][1], off])
    if k < 16:
        prev = coef
    lines.append(coef)
    print(k, f'y@centro {coef[2]:6.1f}  puntos {len(pts)}')


def y_at(k, x):
    return float(np.polyval(lines[k], x - X0))


def edges(k):
    """Bordes izquierdo y derecho de la losa k: recorre la banda clara desde el centro."""
    lo, hi = (1060, 1700) if k < 16 else (930, 1820)
    out = []
    for direction in (-1, 1):
        x, gap, last = X0, 0, X0
        while lo < x < hi:
            y = int(round(y_at(k, x)))
            on = bright[y - 3:y + 4, x].any()
            gap = 0 if on else gap + 1
            if on:
                last = x
            if gap > 18:
                break
            x += direction
        out.append(last)
    return out


# bordes de la torre medidos sobre la foto (techo -> losa del piso 3); las losas se curvan en las puntas,
# así que el recorrido automático corta antes y se usa una recta entre estos dos extremos
ks = np.arange(16 + 1)
Lf = np.interp(ks, [0, 16], [1138, 1090])
Rf = np.interp(ks, [0, 16], [1650, 1688])

zones = {}
N = 8
for n in range(3, 19):
    top, bot = 18 - n, 19 - n
    xl = min(Lf[top], Lf[bot]) - 4
    xr = max(Rf[top], Rf[bot]) + 4
    xs = np.linspace(xl, xr, N)
    poly = [[round(float(x), 1), round(float(y_at(top, x)), 1)] for x in xs]
    poly += [[round(float(x), 1), round(float(y_at(bot, x)), 1)] for x in xs[::-1]]
    zones[n] = poly
# podio: piso 2 (losa 16 a 17) y planta baja (17 a 18)
for n, (top, bot) in {2: (16, 17), 1: (17, 18)}.items():
    xl, xr = 950, 1800
    xs = np.linspace(xl, xr, N)
    zones[n] = [[round(float(x), 1), round(float(y_at(top, x)), 1)] for x in xs] + \
               [[round(float(x), 1), round(float(y_at(bot, x)), 1)] for x in xs[::-1]]

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
