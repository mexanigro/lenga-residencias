"""Placas de la obra: el terreno vacío, la base con la grúa y la estructura de hormigón, alineadas con la foto final.
Vienen de Google Flow (Nano Banana, editadas a partir de la foto final y descargadas en 2K, 2752x1536). Se
igualan en color con la foto y se pegan sobre ella solo donde cambian (torre, grúa, obrador, reflejos): el resto
queda con los píxeles originales, así el cielo, la cordillera y el lago no pierden nitidez.
Entrada: img/originales/obra/{terreno,base,estructura}.png y img/originales/torre-16x9.jpg
Salida: img/obra/{terreno,base,estructura}.webp y un control en img/originales/obra/control.jpg
Uso: python -I tools/obra.py"""
import pathlib

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import gaussian_filter, maximum_filter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'img' / 'originales' / 'obra'
OUT = ROOT / 'img' / 'obra'
F = Image.open(ROOT / 'img' / 'originales' / 'torre-16x9.jpg').convert('RGB')
W, H = F.size
f = np.asarray(F).astype(np.float32)
fb = gaussian_filter(f, (4, 4, 0))
OUT.mkdir(exist_ok=True)

# franja de la torre (px de la foto final): ahí siempre manda la placa
TOWER = (1040, 0, 1900, 1300)


def plate(name):
    p = Image.open(SRC / f'{name}.png').convert('RGB')
    if p.size != (W, H):  # ponytail: Flow las da en 2K (2752x1536); si llega una de 1K, se agranda y se afila
        p = p.resize((W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2.2, percent=70, threshold=2))
    a = np.asarray(p).astype(np.float32)
    ab = gaussian_filter(a, (4, 4, 0))
    # dónde cambia: diferencia suavizada, ensanchada y con borde blando
    d = np.abs(ab - fb).mean(axis=2)
    m = (d > 16).astype(np.float32)
    x0, y0, x1, y1 = TOWER
    m[y0:y1, x0:x1] = np.maximum(m[y0:y1, x0:x1], 1)
    m = maximum_filter(m, size=31)
    m = np.clip(gaussian_filter(m, 14) * 1.15, 0, 1)
    # mismo color que la foto donde no cambió (ganancia y desplazamiento por canal)
    keep = m < 0.02
    for c in range(3):
        x, y = a[..., c][keep], f[..., c][keep]
        g, o = np.polyfit(x[::7], y[::7], 1)
        a[..., c] = a[..., c] * g + o
    out = f * (1 - m[..., None]) + a * m[..., None]
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    img.save(OUT / f'{name}.webp', 'WEBP', quality=86, method=6)
    print(name, f'{(OUT / f"{name}.webp").stat().st_size / 1e6:.2f} MB', f'mascara {m.mean() * 100:.0f} %')
    return img, m


plates = [plate(n) for n in ('terreno', 'base', 'estructura')]
# control: las tres placas y sus máscaras, chicas
sheet = Image.new('RGB', (1376, 768))
for i, (img, m) in enumerate(plates):
    sheet.paste(img.resize((688, 384)), ((i % 2) * 688, (i // 2) * 384))
mm = Image.fromarray((np.stack([plates[k][1] for k in range(3)], -1) * 255).astype(np.uint8)).resize((688, 384))
sheet.paste(mm, (688, 384))
sheet.save(SRC / 'control.jpg', quality=88)
