"""Ajusta cada losa (polinomio robusto), arma los polígonos por piso y dibuja un overlay.
Uso: python -I fit.py <imagen> <lines.json> <floors.json> <overlay.png>"""
import json
import sys
import numpy as np
from PIL import Image, ImageDraw

img_path, lines_path, out_json, out_png = sys.argv[1:5]
data = json.load(open(lines_path))
lines = data['lines']
N = len(lines)

# extremos de la torre por línea: residenciales acotadas, podio más ancho
def bounds(i, pts):
    xs = [p[0] for p in pts]
    if i >= 16:  # techo del podio y losa intermedia
        return 506, 1030
    t = i / 15  # 0 = techo, 1 = piso 3
    left = 646 * (1 - t) + 578 * t if i == 0 else 616 * (1 - t) + 578 * t
    right = 934 * (1 - t) + 952 * t
    return max(left, min(xs) if i == 0 else left), right

fits = []
for i, pts in enumerate(lines):
    lo, hi = bounds(i, pts)
    P = np.array([p for p in pts if lo - 2 <= p[0] <= hi + 2])
    x, y = P[:, 0], P[:, 1]
    keep = np.ones(len(x), bool)
    for _ in range(5):
        c = np.polyfit(x[keep], y[keep], 3)
        r = np.abs(np.polyval(c, x) - y)
        thr = max(2.5, np.percentile(r[keep], 80) * 1.5)
        keep = r < thr
    fits.append((c, lo, hi, keep.mean()))
    print(i, f'{lo:.0f}-{hi:.0f}', f'inliers {keep.mean():.2f}', 'y@lo/mid/hi', *[round(float(np.polyval(c, v)), 1) for v in (lo, (lo + hi) / 2, hi)])

def poly(i, n=12, lo=None, hi=None):
    c, flo, fhi, _ = fits[i]
    xs = np.linspace(lo or flo, hi or fhi, n)
    return [[round(float(v), 1), round(float(np.polyval(c, v)), 1)] for v in xs]

GROUND = [[506, 846], [1030, 846]]
floors = []
for n in range(1, 19):
    if n == 1:
        top, bot = poly(17), GROUND
    elif n == 2:
        top, bot = poly(16), poly(17)
    elif n == 3:  # la losa de abajo es el techo del podio: recortarla al ancho de la torre
        top = poly(15)
        bot = poly(16, lo=top[0][0], hi=top[-1][0])
    else:
        top, bot = poly(18 - n), poly(19 - n)
    floors.append({'n': n, 'pts': top + bot[::-1]})

json.dump({'w': data['w'], 'h': data['h'], 'floors': floors}, open(out_json, 'w'))

im = Image.open(img_path).convert('RGB')
ov = Image.new('RGBA', im.size, (0, 0, 0, 0))
d = ImageDraw.Draw(ov)
for f in floors:
    col = (226, 162, 59, 70) if f['n'] % 2 else (80, 200, 220, 70)
    d.polygon([tuple(p) for p in f['pts']], fill=col, outline=(255, 255, 255, 200))
out = Image.alpha_composite(im.convert('RGBA'), ov).crop((480, 80, 1060, 880))
out.save(out_png)
