"""Auditoría de la escena contra las lecciones de referencias/hiperrealismo-metodo.md (las que se pueden medir).

Uso (desde la raíz del proyecto, sobre la escena guardada con `depto.py -- --save`):
  blender -b 3d/out/depto.blend -P tools/render/auditoria.py -- [--sin-albedo]

Escribe 3d/out/auditoria/informe.json e imprime un resumen por ambiente. Cada prueba nombra la lección que mide:
  albedo     lo que ve el visitante desde cada punto de 360° (pase DiffCol por objeto): nada por encima de ~0,85
  luces      potencias de lámparas y emisiones (veladores 10 W, difusores, nicho), una luz por ambiente
  costuras   vértices repetidos y bordes abiertos (respaldo: el decimado retorcía los canales)
  dorso      un rayo desde afuera choca primero con una cara al revés (bachas negras en el horneado)
  flota      el objeto no apoya en nada (almohadas, frazada levantada)
  vidrio     reflejo solo en la cara de entrada (Fresnel × (1 − Backfacing))
  barniz     capa de pulido con luces chicas cerca (el punto blanco de los listones)
  fino       piezas más finas que un texel del horneado (la junta blanca del placard)
  nodos      objetos de geometry nodes (las bolas verdes de Poly Haven)
"""
import json
import math
import pathlib
import sys
from collections import defaultdict

import bmesh
import bpy
import numpy as np
from mathutils import Vector

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import depto  # noqa: E402
import hornear as H  # noqa: E402

ROOT = TOOLS.parent
OUT = ROOT / '3d' / 'out' / 'auditoria'
OUT.mkdir(parents=True, exist_ok=True)
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
sc = bpy.context.scene
dg = bpy.context.evaluated_depsgraph_get()
FONDO = ('Vista', 'Lago')
COLGADO = ('Cuadro', 'Cortina', 'Colgante', 'pendant', 'Espejo', 'Luz', 'Toalla', 'Toallero', 'Repisa', 'Estante',
           'Techo', 'Downlight', 'Spot', 'Ducha', 'Nicho', 'Muro', 'Tabique', 'Listón', 'Listones', 'Revestimiento',
           'Mampara', 'Ventana', 'Marco', 'Puerta', 'Losa', 'Balcón', 'Baranda', 'Piso -', 'Zócalo', 'Campana')


def raiz(o):
    while o.parent:
        o = o.parent
    return o


def caja(objs):
    return H.caja(objs)


mallas = [o for o in sc.objects if o.type == 'MESH' and o.name not in FONDO and o.visible_get()]
por_raiz = defaultdict(list)
for o in mallas:
    por_raiz[raiz(o).name].append(o)
    o['raiz'] = raiz(o).name
zona = {r: H.zona_de((lambda lo_hi: (lo_hi[0] + lo_hi[1]) / 2)(caja(objs))) for r, objs in por_raiz.items()}
informe = {'objetos': {r: {'zona': zona[r], 'partes': len(objs)} for r, objs in por_raiz.items()}}


def marca(r, prueba, detalle):
    informe['objetos'].setdefault(r, {}).setdefault('fallas', []).append({'prueba': prueba, 'detalle': detalle})


# ---------------------------------------------------------------- luces y emisiones
luces = []
for o in sc.objects:
    if o.type == 'LIGHT':
        p = o.matrix_world.translation
        luces.append({'nombre': o.name, 'tipo': o.data.type, 'w': round(o.data.energy, 2), 'zona': H.zona_de(p),
                      'raiz': raiz(o).name})
emisiones = []
for m in bpy.data.materials:
    if not m.use_nodes or not m.users:
        continue
    for n in m.node_tree.nodes:
        if n.type == 'EMISSION' and n.inputs['Strength'].default_value > 0:
            emisiones.append({'material': m.name, 'fuerza': round(n.inputs['Strength'].default_value, 2)})
        elif n.type == 'BSDF_PRINCIPLED' and n.inputs['Emission Strength'].default_value > 0 and \
                (n.inputs['Emission Color'].is_linked or max(n.inputs['Emission Color'].default_value[:3]) > 0):
            emisiones.append({'material': m.name, 'fuerza': round(n.inputs['Emission Strength'].default_value, 2)})
informe['luces'], informe['emisiones'] = luces, emisiones
con_luz = {l['zona'] for l in luces if l['tipo'] != 'SUN'}
informe['ambientes_sin_luz'] = sorted(set(zona.values()) - con_luz - {'balcon'})

# ---------------------------------------------------------------- materiales: vidrio y barniz
for m in bpy.data.materials:
    if not m.use_nodes or not m.users:
        continue
    N = m.node_tree.nodes
    p = next((n for n in N if n.type == 'BSDF_PRINCIPLED'), None)
    vidrio = H.es_vidrio(m) or (p is not None and not p.inputs['Transmission Weight'].is_linked
                               and p.inputs['Transmission Weight'].default_value > 0.5)
    if vidrio:
        ok = any(n.type == 'NEW_GEOMETRY' and n.outputs['Backfacing'].is_linked for n in N)
        informe.setdefault('vidrios', {})[m.name] = 'ok' if ok else 'SIN el arreglo de la cara de salida'
    if p is not None and not p.inputs['Coat Weight'].is_linked and p.inputs['Coat Weight'].default_value > 0.05:
        informe.setdefault('barniz', {})[m.name] = {'coat': round(p.inputs['Coat Weight'].default_value, 2),
                                                    'usuarios': m.users}

# ---------------------------------------------------------------- geometría, objeto por objeto
for r, objs in por_raiz.items():
    for o in objs:
        if any(md.type == 'NODES' for md in o.modifiers):
            marca(r, 'nodos', o.name)
        me = o.data
        if len(me.vertices) > 400000:
            continue
        bm = bmesh.new()
        bm.from_mesh(me)
        n0 = len(bm.verts)
        abiertos = sum(1 for e in bm.edges if e.is_boundary)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        rep = n0 - len(bm.verts)
        cerrado_al_soldar = rep and not any(e.is_boundary for e in bm.edges)
        bm.free()
        if rep and cerrado_al_soldar and H.familia(o)[1]:  # los de catálogo vienen cortados por sus UV: normal
            marca(r, 'costuras', f'{o.name}: {rep} vértices repetidos, {abiertos} bordes abiertos que se cierran al soldar')
        # piezas finas (dos medidas chicas): menos de dos texels del horneado (~230 px/m)
        d = sorted(o.dimensions)
        if d[0] < 0.009 and d[1] < 0.05 and not all(H.es_vidrio(s.material) for s in o.material_slots):
            mats = ','.join(sorted({H.base(s.material.name) for s in o.material_slots if s.material}))
            marca(r, 'fino', f'{o.name}: {d[0] * 1000:.0f} × {d[1] * 1000:.0f} mm ({mats})')

# dorso: rayos desde 14 direcciones hacia el centro de cada objeto
DIRS = [Vector(v).normalized() for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
                                         (1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, 1, 1), (-1, 1, -1),
                                         (-1, -1, 1), (-1, -1, -1))]
SIN_DORSO = ('potted_plant', 'grass', 'shrub', 'Cortina', 'Hoja', 'Planta')
for r, objs in por_raiz.items():
    if r.startswith(SIN_DORSO):
        continue
    for o in objs:
        if all(H.es_vidrio(s.material) for s in o.material_slots if s.material) or len(o.data.polygons) < 6:
            continue
        lo, hi = caja([o])
        c, rad = Vector((lo + hi) / 2), float(np.linalg.norm(hi - lo)) / 2 + 0.05
        Mi = o.matrix_world.inverted()
        malos = 0
        for dvec in DIRS:
            org = c + dvec * rad
            ok, loc, nor, _ = o.ray_cast(Mi @ org, (Mi.to_3x3() @ -dvec).normalized())
            if ok and (Mi.to_3x3().transposed() @ nor).dot(-dvec) > 0.2:
                malos += 1
        if malos >= 3:
            marca(r, 'dorso', f'{o.name}: {malos} de 14 rayos desde afuera chocan con el dorso de una cara')

# flota: rayos hacia abajo desde la base de cada mueble
for r, objs in por_raiz.items():
    if any(r.startswith(p) for p in COLGADO):
        continue
    lo, hi = caja(objs)
    if lo[2] < 0.02:
        continue  # apoya en el piso
    puntos = [((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)] + [
        (lo[0] + (hi[0] - lo[0]) * a, lo[1] + (hi[1] - lo[1]) * b) for a in (0.2, 0.8) for b in (0.2, 0.8)]
    gap = 9.0
    for x, y in puntos:
        org = Vector((x, y, lo[2] + 0.01))
        for _ in range(8):
            ok, loc, nor, idx, ob, _ = sc.ray_cast(dg, org, Vector((0, 0, -1)))
            if not ok:
                break
            if raiz(ob).name == r:
                org = loc + Vector((0, 0, -1e-4))
                continue
            gap = min(gap, lo[2] - loc[2])
            break
    if gap > 0.012:
        marca(r, 'flota', f'la base queda a {gap * 100:.1f} cm de lo que tiene abajo' if gap < 9 else 'nada abajo')

# ---------------------------------------------------------------- albedo de lo que se ve desde cada 360°
if '--sin-albedo' not in argv:
    idx = {r: i + 1 for i, r in enumerate(sorted(por_raiz))}
    nombre = {i: r for r, i in idx.items()}
    for r, objs in por_raiz.items():
        for o in objs:
            o.pass_index = idx[r]
    vl = sc.view_layers[0]
    vl.use_pass_diffuse_color = True
    vl.use_pass_object_index = True
    sc.render.engine = 'CYCLES'
    try:
        pr = bpy.context.preferences.addons['cycles'].preferences
        pr.compute_device_type = 'OPTIX'
        pr.get_devices()
        for dv in pr.devices:
            dv.use = True
        sc.cycles.device = 'GPU'
    except Exception as e:  # noqa: BLE001
        print('sin GPU:', e)
    sc.cycles.samples, sc.cycles.use_denoising, sc.cycles.use_adaptive_sampling = 4, False, False
    sc.cycles.filter_width = 0.01
    sc.cycles.max_bounces = 0
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1536, 768, 100
    cam = bpy.data.objects.new('Cam auditoría', bpy.data.cameras.new('Cam auditoría'))
    sc.collection.objects.link(cam)
    cam.data.type = 'PANO'
    try:
        cam.data.panorama_type = 'EQUIRECTANGULAR'
    except AttributeError:
        cam.data.cycles.panorama_type = 'EQUIRECTANGULAR'
    sc.camera = cam
    sc.use_nodes = True
    nt = sc.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new('CompositorNodeRLayers')
    fo = nt.nodes.new('CompositorNodeOutputFile')
    fo.base_path = str(OUT)
    fo.format.file_format, fo.format.color_depth = 'OPEN_EXR', '32'
    fo.file_slots[0].path = 'col_'
    fo.file_slots.new('idx_')
    nt.links.new(rl.outputs['DiffCol'], fo.inputs[0])
    nt.links.new(rl.outputs['IndexOB'], fo.inputs[1])
    vistos = defaultdict(lambda: {'px': 0, 'lum': [], 'vistas': set()})
    for clave, ((x, y), _yaw) in depto.VIEWS.items():
        cam.location = (x, y, depto.EYE)
        cam.rotation_euler = (math.pi / 2, 0, 0)
        bpy.ops.render.render(write_still=False)
        imgs = {}
        for k in ('col_', 'idx_'):
            f = OUT / f'{k}{sc.frame_current:04d}.exr'
            im = bpy.data.images.load(str(f), check_existing=False)
            a = np.empty(im.size[0] * im.size[1] * 4, np.float32)
            im.pixels.foreach_get(a)
            imgs[k] = a.reshape(-1, 4)
            bpy.data.images.remove(im)
            f.unlink()
        lum = imgs['col_'][:, :3] @ np.array((0.2126, 0.7152, 0.0722), np.float32)
        ix = imgs['idx_'][:, 0]
        entero = np.abs(ix - np.round(ix)) < 0.02
        ix = np.round(ix).astype(int)
        for i in np.unique(ix[entero]):
            if i == 0:
                continue
            sel = entero & (ix == i)
            v = vistos[nombre[i]]
            v['px'] += int(sel.sum())
            v['vistas'].add(clave)
            v['lum'].append(lum[sel])
    for r, v in vistos.items():
        l = np.concatenate(v['lum'])
        o = informe['objetos'][r]
        o['visto_desde'] = sorted(v['vistas'])
        o['albedo'] = {'medio': round(float(l.mean()), 3), 'p95': round(float(np.percentile(l, 95)), 3),
                       'px': v['px']}
        if np.percentile(l, 95) > 0.86:
            marca(r, 'albedo', f'p95 {np.percentile(l, 95):.2f} (techo ~0,85)')

(OUT / 'informe.json').write_text(json.dumps(informe, indent=1, ensure_ascii=False, default=list), encoding='utf-8')

# ---------------------------------------------------------------- resumen
print('\nAUDITORIA ==============================')
for z in ('living', 'cocina', 'balcon', 'suite', 'bano', 'suite2'):
    print(f'\nAUDITORIA [{z}]')
    for r, o in sorted(informe['objetos'].items()):
        if o.get('zona') != z:
            continue
        al = o.get('albedo')
        txt = f"alb {al['medio']:.2f}/{al['p95']:.2f} desde {','.join(o['visto_desde'])}" if al else 'no se ve'
        fallas = '; '.join(f"{f['prueba']}: {f['detalle']}" for f in o.get('fallas', []))
        print(f'AUDITORIA   {r[:42]:42s} {txt:44s} {fallas}')
print('\nAUDITORIA luces:', json.dumps(luces, ensure_ascii=False))
print('AUDITORIA emisiones:', json.dumps(emisiones, ensure_ascii=False))
print('AUDITORIA sin luz:', informe['ambientes_sin_luz'])
print('AUDITORIA vidrios:', json.dumps(informe.get('vidrios'), ensure_ascii=False))
print('AUDITORIA barniz:', json.dumps(informe.get('barniz'), ensure_ascii=False))
