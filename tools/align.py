"""Alinea una imagen "antes" (ej. el lote vacío) con el render final y la recorta al mismo encuadre.
Busca escala y desplazamiento por correlación de bordes, ignorando la zona de la torre.
Uso: python -I align.py <render.png> <antes.png> <salida.png>"""
import sys
import numpy as np
from PIL import Image, ImageFilter
from scipy.signal import fftconvolve

ref_path, src_path, out_path = sys.argv[1:4]
ref = Image.open(ref_path).convert('L')
src = Image.open(src_path).convert('L')
W, H = ref.size
K = 4  # trabajar a 1/4 de resolución


def edges(im):
    a = np.asarray(im.filter(ImageFilter.GaussianBlur(1)), float)
    gy, gx = np.gradient(a)
    return np.hypot(gx, gy)


T = edges(ref.resize((W // K, H // K)))
mask = np.ones_like(T)
mask[:, int(470 / K):int(1070 / K)] = 0  # sin la torre
mask[: int(60 / K)] = 0
Tm = (T - (T * mask).sum() / mask.sum()) * mask
tnorm = np.sqrt((Tm ** 2).sum())

best = (-1, None)
for s in np.arange(1.0, 1.32, 0.01):
    w = int(round(W * s / K))
    h = int(round(src.size[1] * w / src.size[0]))
    if h < T.shape[0]:
        continue
    L = edges(src.resize((w, h)))
    num = fftconvolve(L, Tm[::-1, ::-1], mode='valid')
    e2 = fftconvolve(L ** 2, mask[::-1, ::-1], mode='valid')
    e1 = fftconvolve(L, mask[::-1, ::-1], mode='valid')
    var = np.maximum(e2 - e1 ** 2 / mask.sum(), 1e-6)
    ncc = num / (tnorm * np.sqrt(var))
    iy, ix = np.unravel_index(np.argmax(ncc), ncc.shape)
    if ncc[iy, ix] > best[0]:
        best = (ncc[iy, ix], (s, ix * K, iy * K))
score, (s, dx, dy) = best
print(f'escala {s:.2f}  desplazamiento ({dx}, {dy})  ncc {score:.3f}')

# recorte final a resolución completa
big = Image.open(src_path).convert('RGB')
w = int(round(W * s))
h = int(round(big.size[1] * w / big.size[0]))
big = big.resize((w, h), Image.LANCZOS)
big.crop((dx, dy, dx + W, dy + H)).save(out_path)
