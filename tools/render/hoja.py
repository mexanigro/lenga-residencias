"""Hojas para mirar un render con lupa antes de entregarlo.

  python tools/render/hoja.py recortes render.png salida.jpg X0,Y0,X1,Y1 [X0,Y0,X1,Y1 ...]
      recortes ampliados a 600 px de ancho, en dos columnas (telas, apoyos, bordes, objetos chicos, puntos raros)
  python tools/render/hoja.py comparar salida.jpg antes.png "Antes" ahora.png "Ahora"
      dos imágenes lado a lado con su rótulo
"""
import sys

from PIL import Image, ImageDraw, ImageFont


def recortes(src, out, cajas):
    im = Image.open(src).convert('RGB')
    tiles = []
    for c in cajas:
        x0, y0, x1, y1 = (int(v) for v in c.split(','))
        tiles.append(im.crop((x0, y0, x1, y1)).resize((600, round(600 * (y1 - y0) / (x1 - x0)))))
    cols = [tiles[0::2], tiles[1::2]]
    alto = max(sum(t.size[1] + 10 for t in col) for col in cols)
    hoja = Image.new('RGB', (1210, alto), 'white')
    for i, col in enumerate(cols):
        y = 0
        for t in col:
            hoja.paste(t, (i * 610, y))
            y += t.size[1] + 10
    hoja.save(out, quality=90)


def comparar(out, a, ra, b, rb):
    ia, ib = (Image.open(p).convert('RGB') for p in (a, b))
    ib = ib.resize((round(ib.size[0] * ia.size[1] / ib.size[1]), ia.size[1]))
    hoja = Image.new('RGB', (ia.size[0] + ib.size[0] + 10, ia.size[1] + 55), 'white')
    hoja.paste(ia, (0, 55))
    hoja.paste(ib, (ia.size[0] + 10, 55))
    d = ImageDraw.Draw(hoja)
    try:
        f = ImageFont.truetype('arial.ttf', 30)
    except OSError:
        f = ImageFont.load_default()
    d.text((10, 12), ra, fill='black', font=f)
    d.text((ia.size[0] + 20, 12), rb, fill='black', font=f)
    hoja.save(out, quality=90)


if __name__ == '__main__':
    if sys.argv[1] == 'recortes':
        recortes(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        comparar(*sys.argv[2:7])
