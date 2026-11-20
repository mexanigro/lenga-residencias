"""Una foto de cerca de cada objeto del departamento, con la luz de la escena, en hojas para revisarlos uno por uno.

  blender -b 3d/out/depto.blend --factory-startup -P tools/render/objetos.py -- [FILTRO] [MUESTRAS=48]
      -> 3d/out/objetos/NNN-nombre.jpg y la lista objetos.json
  python tools/render/objetos.py
      -> 3d/out/objetos/hoja-ZONA.jpg, 4 columnas con rótulo (el Python de Blender no trae PIL)
FILTRO: solo los objetos cuyo nombre empieza así (por ejemplo «Almohada,Europea»).

La cámara mira cada objeto desde el lado del punto de 360° de su ambiente, 20° desde arriba, y recorta con el plano
cercano lo que haya entre los dos (sofá delante de la mesa ratona). Saltea la arquitectura: muros, pisos y aberturas
se miran en los 360°.
"""
import json
import math
import re
import pathlib
import sys
from collections import defaultdict

OUT = pathlib.Path(__file__).resolve().parents[2] / '3d' / 'out' / 'objetos'
try:
    import bpy
    from mathutils import Vector
except ImportError:  # las hojas, con el Python del sistema
    from PIL import Image, ImageDraw, ImageFont
    fotos = defaultdict(list)
    for zona, nombre, archivo in json.loads((OUT / 'objetos.json').read_text(encoding='utf8')):
        fotos[zona].append((nombre, archivo))
    f = ImageFont.truetype('arial.ttf', 22)
    for zona, lista in fotos.items():
        hoja = Image.new('RGB', (4 * 650, math.ceil(len(lista) / 4) * 520), 'white')
        for k, (nombre, archivo) in enumerate(lista):
            x, y = (k % 4) * 650, (k // 4) * 520
            hoja.paste(Image.open(archivo), (x, y + 34))
            ImageDraw.Draw(hoja).text((x + 4, y + 4), nombre, fill='black', font=f)
        hoja.save(OUT / f'hoja-{zona}.jpg', quality=88)
        print(OUT / f'hoja-{zona}.jpg')
    sys.exit()

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import depto as D  # noqa: E402
import hornear as HO  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
filtro = tuple(a[0].split(',')) if a and a[0] != 'todo' else None
muestras = int(a[1]) if len(a) > 1 else 48
VISTA = {'living': 'living', 'cocina': 'kitchen', 'balcon': 'balcony', 'suite': 'suite', 'bano': 'bath',
         'suite2': 'bedroom'}
ARQ = ('Muro', 'Tabique', 'Techo', 'Piso', 'Zócalo', 'Frente', 'Ventana', 'Columna', 'Losa', 'Balcón', 'Baranda',
       'Pasamanos', 'Spot', 'Marco', 'Puerta', 'Revestimiento', 'Baño ', 'Junta', 'Vista', 'Lago', 'Sol', 'Choque',
       'Vivo', 'Luz', 'Pared', 'Listones fondo', 'Mampara perfil', 'Tierra', 'Placard junta', 'Cómoda junta')

sc = bpy.context.scene
pr = bpy.context.preferences.addons['cycles'].preferences  # con --factory-startup la placa no queda elegida
pr.compute_device_type = 'OPTIX'
pr.get_devices()
for d in pr.devices:
    d.use = d.type == 'OPTIX'
sc.cycles.device = 'GPU'
sc.cycles.samples = muestras
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 640, 480, 100
sc.render.use_persistent_data = True  # la escena se carga una vez; entre fotos solo se mueve la cámara
sc.render.image_settings.file_format = 'JPEG'


def raiz(o):
    while o.parent:
        o = o.parent
    return o


grupos = defaultdict(list)  # una foto por tipo y ambiente: las nueve tablas del respaldo, los dos veladores
for o in sc.objects:
    if o.type in ('MESH', 'CURVE') and o.visible_get():
        r = raiz(o)
        if r.name.startswith(ARQ) or (filtro and not r.name.startswith(filtro)):
            continue
        tipo = re.sub(r'(\.\d+|\s\d+)+$', '', r.name)
        grupos[(tipo, HO.zona_de(Vector(HO.caja([o])[0]) / 2 + Vector(HO.caja([o])[1]) / 2))].append(o)

cam = bpy.data.objects.new('Lupa', bpy.data.cameras.new('Lupa'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens_unit = 'FOV'
cam.data.angle = math.radians(40)
fotos = defaultdict(list)
for i, ((nombre, _z), objs) in enumerate(sorted(grupos.items())):
    lo, hi = (Vector(v) for v in HO.caja(objs))
    c, radio = (lo + hi) / 2, max((hi - lo).length / 2, 0.08)
    zona = HO.zona_de(c)
    (px, py), _ = D.VIEWS[VISTA[zona]]
    hacia = Vector((px - c.x, py - c.y, 0))
    hacia = hacia.normalized() if hacia.length > 0.05 else Vector((0, -1, 0))
    dist = 1.15 * radio / math.sin(cam.data.angle / 2)
    dirc = (hacia * math.cos(math.radians(20)) + Vector((0, 0, math.sin(math.radians(20))))).normalized()
    cam.location = c + dirc * dist
    cam.rotation_euler = (-dirc).to_track_quat('-Z', 'Y').to_euler()
    cam.data.clip_start = max(0.01, dist - radio * 1.3)
    archivo = OUT / f'{i:03d}-{nombre.replace(" ", "_")[:40]}.jpg'
    sc.render.filepath = str(archivo)
    bpy.ops.render.render(write_still=True)
    fotos[zona].append((nombre, archivo))
    print('OBJETO', i, nombre, zona, flush=True)

(OUT / 'objetos.json').write_text(json.dumps([(z, n, str(a)) for z, v in fotos.items() for n, a in v],
                                              ensure_ascii=False), encoding='utf8')
print('OBJETOS', {z: len(v) for z, v in fotos.items()})
