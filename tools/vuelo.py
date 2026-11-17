"""Arma el vuelo del scroll: una sola toma continua desde la aérea alta hasta la torre.
Tramo 1: vuelo-c2 (aérea alta -> media distancia). Tramo 2: vuelo-a al revés (media distancia -> torre).
Reparte los cuadros según cuánto cambia la imagen, para que el scroll avance a velocidad visual pareja.
Salida: img/vuelo/d/NNN.webp (1600x900) y img/vuelo/m/NNN.webp (600x800, recorte central para celular).
Uso: python -I tools/vuelo.py [cuadros=240]"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
V = ROOT / 'img' / 'originales' / 'video'
OUT = ROOT / 'img' / 'vuelo'
N = int(sys.argv[1]) if len(sys.argv) > 1 else 240


def frames(path, dest):
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(path), str(dest / '%04d.png')], check=True)
    return sorted(dest.glob('*.png'))


tmp = pathlib.Path(tempfile.mkdtemp(prefix='vuelo-'))
try:
    c2 = frames(V / 'vuelo-c2-1080.mp4', tmp / 'c2')
    a = frames(V / 'vuelo-a-1080.mp4', tmp / 'a')
    seq = c2 + a[::-1][1:]  # el último cuadro de c2 y el último de a son la misma toma: no se repite
    print('cuadros', len(c2), '+', len(a), '->', len(seq))

    def small(p):
        return np.asarray(Image.open(p).convert('L').resize((192, 108)).filter(ImageFilter.GaussianBlur(1)), float)

    prev, motion = small(seq[0]), [0.0]
    for p in seq[1:]:
        cur = small(p)
        motion.append(float(np.abs(cur - prev).mean()))
        prev = cur
    m = np.array(motion)
    # el movimiento mínimo evita que un tramo casi quieto quede sin cuadros
    m = np.maximum(m, np.percentile(m[1:], 20))
    m[0] = 0
    cum = np.cumsum(m)
    cum /= cum[-1]
    pick = [int(np.argmin(np.abs(cum - t))) for t in np.linspace(0, 1, N)]
    print('costura en', len(c2) - 1, '| movimiento medio', round(float(m[1:].mean()), 2))

    for sub in ('d', 'm'):
        if (OUT / sub).exists():
            shutil.rmtree(OUT / sub)
        (OUT / sub).mkdir(parents=True)
    total = {'d': 0, 'm': 0}
    for i, k in enumerate(pick):
        im = Image.open(seq[k]).convert('RGB')
        d = im.resize((1600, 900), Image.LANCZOS)
        d.save(OUT / 'd' / f'{i:03d}.webp', 'WEBP', quality=70, method=6)
        w, h = im.size
        cw = int(h * 3 / 4)
        mob = im.crop(((w - cw) // 2, 0, (w + cw) // 2, h)).resize((600, 800), Image.LANCZOS)
        mob.save(OUT / 'm' / f'{i:03d}.webp', 'WEBP', quality=68, method=6)
        for sub in ('d', 'm'):
            total[sub] += (OUT / sub / f'{i:03d}.webp').stat().st_size
    print({k: f'{v / 1e6:.1f} MB' for k, v in total.items()}, N, 'cuadros')
finally:
    shutil.rmtree(tmp, ignore_errors=True)
