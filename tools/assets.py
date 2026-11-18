"""Procesa los originales y deja los .webp del sitio en img/.
- img/originales/torre-16x9.jpg      -> img/torre.webp (foto final del vuelo, donde se calibran los pisos)
                                       y img/og.jpg (vista previa al compartir, 1200x630)
- img/originales/planta-<zona>.png   -> img/plate-<zona>.webp (fondo transparente) + caja de la losa
- img/originales/iso-*.png           -> img/iso-*.webp
- 3d/out/pano-<ambiente>.png         -> img/depto3d/pano-<ambiente>.webp (6144) y -m.webp (4096, celular):
                                       los 360° de Cycles que el recorrido 3D proyecta sobre el modelo (js/realismo.js)
(el modelo horneado del recorrido sale de tools/hornear.py, directo a img/depto3d/)
Escribe js/assets.js con las cajas de las plantas y el placeholder borroso del loader (primer cuadro del vuelo).
Uso: python -I tools/assets.py"""
import base64
import io
import json
import pathlib

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / 'img' / 'originales', ROOT / 'img'
Image.MAX_IMAGE_PIXELS = None


def save(im, path, q=82):
    path.parent.mkdir(parents=True, exist_ok=True)
    im.convert('RGB').save(path, 'WEBP', quality=q, method=6)
    print(f'{path.relative_to(ROOT)!s:32s} {im.size[0]}x{im.size[1]}  {path.stat().st_size // 1024} KB')


if (SRC / 'torre-16x9.jpg').exists():
    torre = Image.open(SRC / 'torre-16x9.jpg').convert('RGB')
    save(torre, OUT / 'torre.webp', 84)
    h = round(torre.width / 1.905)
    top = max(0, (torre.height - h) // 2 - 40)
    torre.crop((0, top, torre.width, top + h)).resize((1200, 630), Image.LANCZOS).save(OUT / 'og.jpg', quality=84, optimize=True, progressive=True)

for p in sorted(SRC.glob('iso-*.png')):
    save(Image.open(p), OUT / f'{p.stem}.webp')

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
    # fondo azul noche -> transparente, para que solo quede la losa (con borde suave)
    bg = np.median(np.concatenate([a[:20, :20].reshape(-1, 3), a[-20:, -20:].reshape(-1, 3)]), axis=0)
    dist = np.sqrt(((a - bg) ** 2).sum(axis=2))
    alpha = np.clip((dist - 14) / 26, 0, 1)
    out = OUT / f'plate-{zone}.webp'
    Image.fromarray(np.dstack([a, alpha * 255]).astype('uint8'), 'RGBA').save(out, 'WEBP', quality=85, method=6)
    print(f'plate-{zone}.webp (alfa)  {out.stat().st_size // 1024} KB')

# panoramas 360° de Cycles (tools/depto.py --pano all)
for p in sorted((ROOT / '3d' / 'out').glob('pano-*.png')):
    im = Image.open(p).convert('RGB')
    save(im.resize((6144, 3072), Image.LANCZOS) if im.size[0] != 6144 else im, OUT / 'depto3d' / f'{p.stem}.webp', 84)
    save(im.resize((4096, 2048), Image.LANCZOS), OUT / 'depto3d' / f'{p.stem}-m.webp', 82)

# placeholder borroso del primer cuadro del vuelo, embebido para que el loader tenga imagen al instante
lqip = ''
first = OUT / 'vuelo' / 'd' / '000.webp'
if first.exists():
    t = Image.open(first).convert('RGB').resize((48, 27), Image.LANCZOS)
    buf = io.BytesIO()
    t.save(buf, 'WEBP', quality=60)
    lqip = 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()

(ROOT / 'js' / 'assets.js').write_text(
    '// Generado por tools/assets.py\n'
    f'export const PLATES = {json.dumps(plates)};\n'
    f'export const LQIP = {json.dumps(lqip)};\n', encoding='utf-8')
print('js/assets.js listo', list(plates))
