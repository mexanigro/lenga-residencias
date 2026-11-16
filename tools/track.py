"""Sigue cada losa del render de izquierda a derecha y exporta polilíneas (px de la imagen).
Uso: python -I track.py <imagen> <salida.json>"""
import json
import sys
import numpy as np
from PIL import Image

im = np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(float)
H, W, _ = im.shape
lum = im.mean(axis=2)
sat = im.max(axis=2) - im.min(axis=2)
bright = (lum > 150) & (sat < 60)
sky = (im[:, :, 2] > im[:, :, 0] + 25) & (lum < 175)

SEEDS = [112, 155, 191, 230, 269, 309, 350, 391, 433, 470, 511, 550, 586, 627, 665, 701, 740, 788]
X_SEED = 700


def band_center(x, y_guess, tol):
    lo, hi = int(y_guess - tol), int(y_guess + tol)
    col = bright[lo:hi, x - 1:x + 2].mean(axis=1)
    idx = np.where(col > 0.5)[0]
    if not len(idx):
        return None
    # tramo contiguo más cercano al valor esperado
    runs, s = [], idx[0]
    for a, b in zip(idx, idx[1:]):
        if b != a + 1:
            runs.append((s, a)); s = b
    runs.append((s, idx[-1]))
    best = min(runs, key=lambda r: abs(lo + (r[0] + r[1]) / 2 - y_guess))
    return lo + (best[0] + best[1]) / 2


def is_tower(x, y):
    # fuera de la torre = cielo (arriba) o borde de la imagen
    return not sky[int(y) - 3:int(y) + 4, x].all()


lines = []
for seed in SEEDS:
    pts = {X_SEED: band_center(X_SEED, seed, 8) or seed}
    for direction in (1, -1):
        y = pts[X_SEED]
        x = X_SEED
        misses = 0
        while 500 < x < 1040:
            x += 3 * direction
            c = band_center(x, y, 5)
            if c is None:
                misses += 1
                if misses > 6:
                    break
                continue
            misses = 0
            y = c
            pts[x] = y
    xs = sorted(pts)
    # recorte a la silueta: descarta puntos donde ya es cielo
    xs = [x for x in xs if is_tower(x, pts[x] + 2)]
    lines.append([[x, round(pts[x], 1)] for x in xs])

for i, ln in enumerate(lines):
    print(i, SEEDS[i], 'x', ln[0][0], '->', ln[-1][0], 'n', len(ln), 'y', ln[0][1], ln[len(ln) // 2][1], ln[-1][1])

json.dump({'w': W, 'h': H, 'lines': lines}, open(sys.argv[2], 'w'))
