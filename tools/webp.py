"""Convierte img/*.png a WebP (torre-src.png -> torre.webp). Uso: python -I webp.py <carpeta img>"""
import sys, pathlib
from PIL import Image
d = pathlib.Path(sys.argv[1])
for p in sorted(d.glob('*.png')):
    out = d / (('torre' if p.stem == 'torre-src' else p.stem) + '.webp')
    if out.exists() and out.stat().st_mtime > p.stat().st_mtime:
        continue
    Image.open(p).convert('RGB').save(out, 'WEBP', quality=82, method=6)
    print(out.name, round(out.stat().st_size / 1024), 'KB')
