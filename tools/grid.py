"""Dibuja una grilla con porcentajes sobre una imagen para ubicar puntos a ojo.
Uso: python -I tools/grid.py <imagen> <salida.jpg> [ancho]"""
import sys
from PIL import Image, ImageDraw
im = Image.open(sys.argv[1]).convert('RGB')
W = int(sys.argv[3]) if len(sys.argv) > 3 else 900
im = im.resize((W, round(im.size[1] * W / im.size[0])))
d = ImageDraw.Draw(im)
w, h = im.size
for i in range(0, 101, 5):
    x, y = w * i / 100, h * i / 100
    c = (255, 80, 80) if i % 10 == 0 else (255, 200, 80)
    d.line([(x, 0), (x, h)], fill=c, width=1)
    d.line([(0, y), (w, y)], fill=c, width=1)
    if i % 10 == 0:
        d.text((x + 2, 2), str(i), fill=(255, 255, 255))
        d.text((2, y + 2), str(i), fill=(255, 255, 255))
im.save(sys.argv[2], quality=85)
