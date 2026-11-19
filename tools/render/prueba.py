"""Renders de control de la suite, en un proceso aparte (sin ventana).

  blender -b 3d/out/suite/suite.blend --factory-startup -P tools/render/prueba.py -- NOMBRE MUESTRAS PCT
      prueba rápida (50 128: ~1,5 min) o final (100 512: 10-18 min) -> 3d/out/suite/NOMBRE.png
  ... -P tools/render/prueba.py -- NOMBRE MUESTRAS zona X0 Y0 X1 Y1
      solo ese recorte, a resolución completa (píxeles de 1800x1350 desde arriba a la izquierda): para mirar
      almohadas, bordes o un objeto chico sin pagar el render entero
  ... -P tools/render/prueba.py -- NOMBRE MUESTRAS sol ELEV DESDE FUERZA
      diagnóstico: solo el sol (cielo y lámparas apagados), para ver dónde cae la mancha antes de elegir el ángulo

--factory-startup hace que no cargue el complemento BlenderMCP (chocaría con el puerto de la ventana abierta).
"""
import pathlib
import sys

import bpy

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import habitacion as H  # noqa: E402

a = sys.argv[sys.argv.index('--') + 1:]
nombre, muestras, modo = a[0], int(a[1]), a[2]
r = bpy.context.scene.render
if modo == 'zona':
    x0, y0, x1, y1 = (float(v) for v in a[3:7])
    r.use_border, r.use_crop_to_border = True, True
    r.border_min_x, r.border_max_x = x0 / r.resolution_x, x1 / r.resolution_x
    r.border_min_y, r.border_max_y = 1 - y1 / r.resolution_y, 1 - y0 / r.resolution_y
    H.render(nombre, muestras, 100)
elif modo == 'sol':
    H.SOL.update(elev=float(a[3]), desde=float(a[4]), fuerza=float(a[5]))
    H.luz()
    next(n for n in bpy.context.scene.world.node_tree.nodes if n.type == 'BACKGROUND').inputs[1].default_value = 0
    for o in bpy.context.scene.objects:
        if o.type == 'LIGHT' and o.data.type != 'SUN':
            o.data.energy = 0
    H.render(nombre, muestras, 40)
else:
    H.render(nombre, muestras, int(modo))
