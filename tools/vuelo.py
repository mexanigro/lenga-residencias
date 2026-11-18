"""Arma el acercamiento del scroll: una sola toma de dron desde lo alto del lago hasta el terreno vacío.
El video (Google Flow, Veo 3.1 Quality con cuadro inicial y final, escalado a 1080p) termina en la misma toma
que la placa del terreno (img/obra/terreno.webp), así el canvas empalma el video con la obra sin corte.
Reparte los cuadros según cuánto cambia la imagen, para que el scroll avance a velocidad visual pareja.
Salida: img/vuelo/d/NNN.webp (1920x1080) y img/vuelo/m/NNN.webp (810x1080, recorte central para celular).
Uso: python -I tools/vuelo.py [cuadros=168]  (el número tiene que coincidir con N en js/flight.js)"""
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
N = int(sys.argv[1]) if len(sys.argv) > 1 else 168
SRC = next(p for p in (V / 'acercamiento-1080.mp4', V / 'acercamiento-720.mp4') if p.exists())

tmp = pathlib.Path(tempfile.mkdtemp(prefix='vuelo-'))
try:
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(SRC), str(tmp / '%04d.png')], check=True)
    seq = sorted(tmp.glob('*.png'))
    print(SRC.name, len(seq), 'cuadros')

    def small(p):
        return np.asarray(Image.open(p).convert('L').resize((192, 108)).filter(ImageFilter.GaussianBlur(1)), float)

    prev, motion = small(seq[0]), [0.0]
    for p in seq[1:]:
        cur = small(p)
        motion.append(float(np.abs(cur - prev).mean()))
        prev = cur
    m = np.array(motion)
    # el movimiento mínimo evita que un tramo casi quieto (el final, que frena) quede sin cuadros
    m = np.maximum(m, np.percentile(m[1:], 25))
    m[0] = 0
    cum = np.cumsum(m)
    cum /= cum[-1]
    pick = [int(np.argmin(np.abs(cum - t))) for t in np.linspace(0, 1, N)]
    pick[-1] = len(seq) - 1  # el último es el cuadro final del video (la toma del terreno)

    for sub in ('d', 'm'):
        if (OUT / sub).exists():
            shutil.rmtree(OUT / sub)
        (OUT / sub).mkdir(parents=True)
    total = {'d': 0, 'm': 0}
    for i, k in enumerate(pick):
        im = Image.open(seq[k]).convert('RGB')
        d = im.resize((1920, 1080), Image.LANCZOS) if im.size != (1920, 1080) else im
        d.save(OUT / 'd' / f'{i:03d}.webp', 'WEBP', quality=80, method=6)
        w, h = d.size
        cw = int(h * 3 / 4)
        d.crop(((w - cw) // 2, 0, (w + cw) // 2, h)).save(OUT / 'm' / f'{i:03d}.webp', 'WEBP', quality=76, method=6)
        for sub in ('d', 'm'):
            total[sub] += (OUT / sub / f'{i:03d}.webp').stat().st_size
    print({k: f'{v / 1e6:.1f} MB' for k, v in total.items()}, N, 'cuadros')
finally:
    shutil.rmtree(tmp, ignore_errors=True)
