"""Habla con el Blender que tiene la ventana abierta, por el complemento BlenderMCP (puerto 9876).

  python tools/render/bmcp.py pasos luz acabados camara   corre esos pasos de habitacion.py, deja la vista en SOLID
                                                           mirando por la cámara y guarda 3d/out/suite/suite.blend
  python tools/render/bmcp.py rayo 443 231 [x y ...]       qué objeto hay en ese píxel del render (1800x1350) y qué
                                                           refleja: para encontrar el origen de un brillo raro
  python tools/render/bmcp.py code archivo.py              ejecuta ese código dentro de Blender
  python tools/render/bmcp.py get_scene_info               cualquier otro comando del complemento (params en JSON)

La ventana queda en SOLID a propósito: en vista Material, la placa de 6 GB no alcanza para la ventana y un render.
"""
import json
import pathlib
import socket
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
SUITE = TOOLS.parent / '3d' / 'out' / 'suite' / 'suite.blend'

PASOS = '''
import importlib, sys, bpy
sys.path.insert(0, {tools!r})
import depto, habitacion
importlib.reload(depto); importlib.reload(habitacion)
for paso in {pasos!r}:
    getattr(habitacion, paso)()
cam = bpy.data.objects.get('Cam suite')
if cam:
    bpy.context.scene.camera = cam
for win in bpy.context.window_manager.windows:
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            sp = area.spaces.active
            sp.shading.type = 'SOLID'
            sp.shading.color_type = 'TEXTURE'
            if cam:
                sp.region_3d.view_perspective = 'CAMERA'
            area.tag_redraw()
bpy.ops.wm.save_as_mainfile(filepath={suite!r})
print('ok', {pasos!r})
'''

RAYO = '''
import bpy
sc = bpy.context.scene
dg = bpy.context.evaluated_depsgraph_get()
cam = sc.camera
fr = [cam.matrix_world @ v for v in cam.data.view_frame(scene=sc)]  # sup-der, inf-der, inf-izq, sup-izq
o0 = cam.matrix_world.translation
for (px, py) in {pixeles!r}:
    u, v = px / sc.render.resolution_x, py / sc.render.resolution_y
    p = fr[3].lerp(fr[0], u).lerp(fr[2].lerp(fr[1], u), v)
    d = (p - o0).normalized()
    hit, loc, nrm, _, ob, _ = sc.ray_cast(dg, o0, d)
    if not hit:
        print((px, py), 'cielo')
        continue
    r = d - 2 * d.dot(nrm) * nrm  # rebote especular: lo que se ve reflejado ahí
    h2 = sc.ray_cast(dg, loc + nrm * 1e-3, r)
    print((px, py), ob.name, [round(c, 3) for c in loc], 'refleja', h2[4].name if h2[0] else 'cielo')
'''


def enviar(tipo, params):
    s = socket.create_connection(('127.0.0.1', 9876), timeout=1800)
    s.sendall(json.dumps({'type': tipo, 'params': params}).encode())
    buf = b''
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
        try:
            return json.loads(buf.decode())
        except ValueError:
            continue


if __name__ == '__main__':
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == 'pasos':
        r = enviar('execute_code', {'code': PASOS.format(tools=str(TOOLS), pasos=args, suite=str(SUITE))})
    elif cmd == 'rayo':
        pix = [(float(args[i]), float(args[i + 1])) for i in range(0, len(args), 2)]
        r = enviar('execute_code', {'code': RAYO.format(pixeles=pix)})
    elif cmd == 'code':
        r = enviar('execute_code', {'code': pathlib.Path(args[0]).read_text(encoding='utf-8')})
    else:
        r = enviar(cmd, json.loads(args[0]) if args else {})
    res = r.get('result', r)
    print(res.get('result', res) if isinstance(res, dict) else res)
