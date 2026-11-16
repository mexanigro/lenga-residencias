"""Procesa los originales de img/originales/ y deja los .webp del sitio en img/.
- aerea-*.png, torre-src.png, lote-alineado.png  -> webp
- planta-<zona>.png  -> plate-<zona>.webp + caja de la losa (para ubicar las unidades)
- pano-<ambiente>.png -> pano-<ambiente>.webp (costura fundida, 2048x1024, enfoque)
- iso-*.png -> webp
Escribe js/assets.js con las cajas de las plantas y el placeholder borroso del loader.
Uso: python -I tools/assets.py"""
import base64
import io
import json
import pathlib
import numpy as np
from PIL import Image, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / 'img' / 'originales', ROOT / 'img'


def save(im, name, q=82):
    p = OUT / name
    im.convert('RGB').save(p, 'WEBP', quality=q, method=6)
    print(f'{name:28s} {im.size[0]}x{im.size[1]}  {p.stat().st_size // 1024} KB')


for name, out in [('aerea-1.png', 'aerea-1.webp'), ('aerea-2.png', 'aerea-2.webp'),
                  ('torre-src.png', 'torre.webp'), ('lote-alineado.png', 'lote.webp')]:
    if (SRC / name).exists():
        save(Image.open(SRC / name), out)

for p in sorted(SRC.glob('iso-*.png')):
    save(Image.open(p), p.stem + '.webp')

plates = {}
for p in sorted(SRC.glob('planta-*.png')):
    im = Image.open(p).convert('RGB')
    a = np.asarray(im).astype(float)
    # la losa es clara sobre fondo azul noche: caja de los píxeles claros
    bright = a.mean(axis=2) > 70
    rows, cols = np.where(bright.any(axis=1))[0], np.where(bright.any(axis=0))[0]
    box = [int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])]
    zone = p.stem.split('-', 1)[1]
    plates[zone] = {'w': im.size[0], 'h': im.size[1], 'box': box}
    # fondo azul noche → transparente, para que solo quede la losa (con borde suave)
    bg = np.median(np.concatenate([a[:20, :20].reshape(-1, 3), a[-20:, -20:].reshape(-1, 3)]), axis=0)
    dist = np.sqrt(((a - bg) ** 2).sum(axis=2))
    alpha = np.clip((dist - 14) / 26, 0, 1)
    rgba = np.dstack([a, alpha * 255]).astype('uint8')
    out = OUT / f'plate-{zone}.webp'
    Image.fromarray(rgba, 'RGBA').save(out, 'WEBP', quality=85, method=6)
    print(f'plate-{zone}.webp (alfa)  {out.stat().st_size // 1024} KB')

for p in sorted(SRC.glob('pano-*.png')):
    a = np.asarray(Image.open(p).convert('RGB')).astype(float)
    n = 28  # funde los bordes izquierdo y derecho para que la vuelta completa no tenga costura
    for i in range(n):
        w = 0.5 * (1 - i / n)
        left, right = a[:, i].copy(), a[:, -1 - i].copy()
        a[:, i] = (1 - w) * left + w * right
        a[:, -1 - i] = (1 - w) * right + w * left
    im = Image.fromarray(a.clip(0, 255).astype('uint8')).resize((2048, 1024), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))
    save(im, p.stem + '.webp', 86)

# placeholder borroso de la primera toma, embebido para que el loader tenga imagen al instante
lqip = ''
if (SRC / 'aerea-1.png').exists():
    t = Image.open(SRC / 'aerea-1.png').convert('RGB').resize((48, 32), Image.LANCZOS)
    buf = io.BytesIO()
    t.save(buf, 'WEBP', quality=60)
    lqip = 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()

(ROOT / 'js' / 'assets.js').write_text(
    '// Generado por tools/assets.py\n'
    f'export const PLATES = {json.dumps(plates)};\n'
    f'export const LQIP = {json.dumps(lqip)};\n', encoding='utf-8')
print('js/assets.js listo', list(plates))
