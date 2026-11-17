"""Procesa los originales y deja los .webp del sitio en img/.
- img/originales/torre-16x9.jpg      -> img/torre.webp (foto final del vuelo, donde se calibran los pisos)
- img/originales/planta-<zona>.png   -> img/plate-<zona>.webp (fondo transparente) + caja de la losa
- img/originales/iso-*.png           -> img/iso-*.webp
- 3d/out/pano-<ambiente>.png         -> img/pano/<ambiente>.webp (desktop) y <ambiente>-m.webp (celular)
- 3d/out/move/<a>-<b>/*.png          -> img/pano/move/<a>-<b>.mp4 (trayecto caminando entre ambientes)
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
    save(Image.open(SRC / 'torre-16x9.jpg'), OUT / 'torre.webp', 84)

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

# panoramas 360° renderizados en Blender (tools/depto.py)
for p in sorted((ROOT / '3d' / 'out').glob('pano-*.png')):
    view = p.stem.split('-', 1)[1]
    im = Image.open(p).convert('RGB')
    save(im.resize((6144, 3072), Image.LANCZOS) if im.size[0] > 6144 else im, OUT / 'pano' / f'{view}.webp', 84)
    save(im.resize((4096, 2048), Image.LANCZOS), OUT / 'pano' / f'{view}-m.webp', 82)

# trayectos entre ambientes: cuadros de Blender -> video H.264 liviano
import subprocess
for d in sorted((ROOT / '3d' / 'out' / 'move').glob('*-*')):
    frames = sorted(d.glob('*.png'))
    if not frames:
        continue
    out = OUT / 'pano' / 'move' / f'{d.name}.mp4'
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '24', '-i', str(d / '%03d.png'), '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'slow', '-movflags', '+faststart', '-an', str(out)], check=True)
    print(f'{out.relative_to(ROOT)!s:32s} {len(frames)} cuadros  {out.stat().st_size // 1024} KB')

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
