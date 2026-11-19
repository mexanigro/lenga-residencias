"""Revisar un 360°: lo corta en vistas como las vería alguien parado ahí, en una hoja con su rumbo.

  python tools/render/vistas.py pano.webp hoja.jpg [N=6] [CAMPO=75] [PITCH=-8]
      N vistas repartidas alrededor, de CAMPO grados horizontales, mirando PITCH grados hacia abajo.
      En el equirectangular, el centro de la imagen es 0°.
"""
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def vista(im, yaw, pitch, hfov, w, h):
    ph, pw = im.shape[:2]
    f = (w / 2) / np.tan(np.radians(hfov) / 2)
    x, y = np.meshgrid(np.arange(w) - w / 2 + .5, np.arange(h) - h / 2 + .5)
    d = np.stack([x, -y, np.full_like(x, f)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    p = np.radians(pitch)
    dx = d[..., 0]
    dy = d[..., 1] * np.cos(p) + d[..., 2] * np.sin(p)
    dz = -d[..., 1] * np.sin(p) + d[..., 2] * np.cos(p)
    lon = np.arctan2(dx, dz) + np.radians(yaw)
    lat = np.arcsin(np.clip(dy, -1, 1))
    u = ((lon / (2 * np.pi) + 0.5) % 1) * pw
    v = (0.5 - lat / np.pi) * ph
    return Image.fromarray(im[np.clip(v.astype(int), 0, ph - 1), np.clip(u.astype(int), 0, pw - 1)])


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    n, hfov, pitch = int(sys.argv[3]) if len(sys.argv) > 3 else 6, float(sys.argv[4]) if len(sys.argv) > 4 else 75, \
        float(sys.argv[5]) if len(sys.argv) > 5 else -8
    im = np.asarray(Image.open(src).convert('RGB'))
    w, h, cols = 900, 620, 2
    hoja = Image.new('RGB', (cols * w + 10, (n + cols - 1) // cols * (h + 10)), 'white')
    d = ImageDraw.Draw(hoja)
    try:
        fnt = ImageFont.truetype('arial.ttf', 26)
    except OSError:
        fnt = ImageFont.load_default()
    for i in range(n):
        yaw = i * 360 / n
        x, y = (i % cols) * (w + 10), (i // cols) * (h + 10)
        hoja.paste(vista(im, yaw, pitch, hfov, w, h), (x, y))
        d.text((x + 10, y + 8), f'{yaw:.0f}°', fill='white', font=fnt, stroke_width=2, stroke_fill='black')
    hoja.save(out, quality=88)
