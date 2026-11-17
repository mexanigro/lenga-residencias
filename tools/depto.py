"""Departamento modelo de Lenga (tipo L2, 2 suites) armado en Blender para los recorridos 360°.

Ejes: x = este (0..13 m), y = norte (la fachada vidriada está en y = 0, el balcón en y > 0), z = arriba.
Coincide con el plano del sitio (tipo L2 de js/data.js) con y invertida.

Uso (desde la raíz del proyecto):
  blender -b --factory-startup -P tools/depto.py -- --preview living         render rápido de control
  blender -b --factory-startup -P tools/depto.py -- --pano living --res 6144 panorama final
  blender -b --factory-startup -P tools/depto.py -- --move living suite      trayecto entre ambientes
  blender -b --factory-startup -P tools/depto.py -- --save                   guarda 3d/out/depto.blend
"""
import argparse
import json
import math
import os
import pathlib
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = pathlib.Path(__file__).resolve().parent.parent
# fuera del proyecto: las rutas de las texturas de Poly Haven superan el límite de 260 caracteres de Windows
ASSETS = pathlib.Path(os.environ.get('LENGA3D', pathlib.Path(os.environ.get('LOCALAPPDATA', '~')) / 'lenga3d')).expanduser() / 'assets'
OUT = ROOT / '3d' / 'out'
DIMS = json.loads((ASSETS / 'tex' / 'dims.json').read_text())

H = 2.75     # alto libre interior
EYE = 1.55   # altura de los ojos para los 360°
SLAB = 0.3

# Puntos de vista (x, y) y hacia dónde arranca mirando (grados desde el norte, horario)
VIEWS = {
    'living': ((6.3, -3.2), -55),
    'kitchen': ((9.7, -1.25), 150),
    'balcony': ((5.2, 1.25), 0),
    'suite': ((2.6, -6.9), -135),
    'bedroom': ((11.1, -6.8), 135),
    'bath': ((6.3, -6.95), 180),
}
# Trayectos entre ambientes: puntos intermedios (pasan por las puertas)
LINKS = {
    ('living', 'kitchen'): [],
    ('living', 'balcony'): [(4.5, -0.45), (4.4, 0.55), (4.8, 1.05)],
    ('kitchen', 'balcony'): [(9.1, -0.45), (9.0, 0.55), (7.6, 1.15)],
    ('living', 'suite'): [(4.8, -4.25), (4.5, -5.0), (4.5, -6.1), (3.6, -6.75)],
    ('suite', 'bath'): [(4.0, -6.55), (5.0, -6.45), (5.7, -6.65)],
    ('kitchen', 'bedroom'): [(10.8, -2.7), (11.0, -4.3), (12.25, -4.75), (12.25, -6.1)],
}


# ------------------------------------------------------------------ escena
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == 'OPTIX'
    c = sc.cycles
    c.device = 'GPU'
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.012
    c.use_denoising = True
    c.denoiser = 'OPENIMAGEDENOISE'
    try:
        c.denoising_use_gpu = True
    except AttributeError:
        pass
    c.max_bounces = 10
    c.diffuse_bounces = 5
    c.glossy_bounces = 4
    c.transparent_max_bounces = 12
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.sample_clamp_indirect = 8
    c.use_light_tree = True
    sc.render.use_persistent_data = True  # reusa la escena entre cuadros (los trayectos solo mueven la cámara)
    vs = sc.view_settings
    vs.view_transform = 'AgX'
    for look in ('AgX - Medium High Contrast', 'Medium High Contrast'):
        try:
            vs.look = look
            break
        except TypeError:
            pass
    vs.exposure = 0.75
    try:  # la luz de fin de tarde es muy cálida: se corrige un poco para que el blanco siga siendo blanco
        vs.use_white_balance = True
        vs.white_balance_temperature = 4600
    except AttributeError:
        pass
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '8'
    return sc


# ------------------------------------------------------------------ materiales
def _tree(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    return m, nt.nodes, nt.links


def pbr(name, tex=None, color=None, rough=0.5, size=None, tint=None, nstr=1.0, metal=0.0, coat=0.0,
        sheen=0.0, rough_gain=1.0, spec=0.5, emit=None, emit_strength=0.0):
    m, N, L = _tree(name)
    out = N.new('ShaderNodeOutputMaterial')
    b = N.new('ShaderNodeBsdfPrincipled')
    L.new(b.outputs[0], out.inputs[0])
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    b.inputs['Coat Weight'].default_value = coat
    b.inputs['Sheen Weight'].default_value = sheen
    b.inputs['Specular IOR Level'].default_value = spec
    if color:
        b.inputs['Base Color'].default_value = (*color, 1)
    if emit:
        b.inputs['Emission Color'].default_value = (*emit, 1)
        b.inputs['Emission Strength'].default_value = emit_strength
    if tex:
        s = size or DIMS.get(tex, [1, 1])[0]
        tc, mp = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeMapping')
        mp.inputs['Scale'].default_value = (1 / s, 1 / s, 1 / s)
        L.new(tc.outputs['Object'], mp.inputs['Vector'])

        def img(fn, data):
            p = ASSETS / 'tex' / tex / fn
            if not p.exists():
                return None
            n = N.new('ShaderNodeTexImage')
            n.image = bpy.data.images.load(str(p), check_existing=True)
            if data:
                n.image.colorspace_settings.name = 'Non-Color'
            n.projection = 'BOX'
            n.projection_blend = 0.3
            L.new(mp.outputs[0], n.inputs[0])
            return n

        # con color fijo y sin tinte, la textura solo aporta relieve y rugosidad
        d = None if (color and not tint) else img('Diffuse.jpg', False)
        if d and tint:
            # conserva el dibujo de la textura pero con el color pedido
            bw = N.new('ShaderNodeRGBToBW')
            L.new(d.outputs[0], bw.inputs[0])
            gain = N.new('ShaderNodeMath')
            gain.operation = 'MULTIPLY'
            gain.inputs[1].default_value = tint[3] if len(tint) > 3 else 2.0
            L.new(bw.outputs[0], gain.inputs[0])
            mix = N.new('ShaderNodeMix')
            mix.data_type = 'RGBA'
            mix.blend_type = 'MULTIPLY'
            mix.inputs['Factor'].default_value = 1
            mix.inputs['A'].default_value = (*tint[:3], 1)
            L.new(gain.outputs[0], mix.inputs['B'])
            L.new(mix.outputs['Result'], b.inputs['Base Color'])
        elif d:
            L.new(d.outputs[0], b.inputs['Base Color'])
        r = img('Rough.jpg', True)
        if r:
            g = N.new('ShaderNodeMath')
            g.operation = 'MULTIPLY'
            g.inputs[1].default_value = rough_gain
            L.new(r.outputs[0], g.inputs[0])
            L.new(g.outputs[0], b.inputs['Roughness'])
        n = img('nor_gl.jpg', True)
        if n:
            nm = N.new('ShaderNodeNormalMap')
            nm.inputs['Strength'].default_value = nstr
            L.new(n.outputs[0], nm.inputs['Color'])
            L.new(nm.outputs[0], b.inputs['Normal'])
    return m


def glass_mat(name='Vidrio', tint=(0.92, 0.96, 0.95)):
    """Vidrio fino: deja pasar el sol (rayos de sombra transparentes) y refleja según el ángulo."""
    m, N, L = _tree(name)
    out = N.new('ShaderNodeOutputMaterial')
    tr = N.new('ShaderNodeBsdfTransparent')
    tr.inputs[0].default_value = (*tint, 1)
    gl = N.new('ShaderNodeBsdfGlossy')
    gl.inputs['Roughness'].default_value = 0.0
    lw = N.new('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.12
    mix = N.new('ShaderNodeMixShader')
    L.new(lw.outputs['Fresnel'], mix.inputs[0])
    L.new(tr.outputs[0], mix.inputs[1])
    L.new(gl.outputs[0], mix.inputs[2])
    lp = N.new('ShaderNodeLightPath')
    mix2 = N.new('ShaderNodeMixShader')
    tr2 = N.new('ShaderNodeBsdfTransparent')
    L.new(lp.outputs['Is Shadow Ray'], mix2.inputs[0])
    L.new(mix.outputs[0], mix2.inputs[1])
    L.new(tr2.outputs[0], mix2.inputs[2])
    L.new(mix2.outputs[0], out.inputs[0])
    m.blend_method = 'BLEND' if hasattr(m, 'blend_method') else None
    return m


def emit_mat(name, color=(1.0, 0.82, 0.62), strength=8.0):
    m, N, L = _tree(name)
    out = N.new('ShaderNodeOutputMaterial')
    e = N.new('ShaderNodeEmission')
    e.inputs[0].default_value = (*color, 1)
    e.inputs[1].default_value = strength
    L.new(e.outputs[0], out.inputs[0])
    return m


def curtain_mat():
    m, N, L = _tree('Cortina')
    out = N.new('ShaderNodeOutputMaterial')
    d = N.new('ShaderNodeBsdfDiffuse')
    d.inputs[0].default_value = (0.93, 0.91, 0.87, 1)
    t = N.new('ShaderNodeBsdfTranslucent')
    t.inputs[0].default_value = (0.98, 0.94, 0.86, 1)
    tr = N.new('ShaderNodeBsdfTransparent')
    a = N.new('ShaderNodeMixShader')
    a.inputs[0].default_value = 0.45
    L.new(d.outputs[0], a.inputs[1])
    L.new(t.outputs[0], a.inputs[2])
    b = N.new('ShaderNodeMixShader')
    b.inputs[0].default_value = 0.25
    L.new(a.outputs[0], b.inputs[1])
    L.new(tr.outputs[0], b.inputs[2])
    L.new(b.outputs[0], out.inputs[0])
    return m


def photo_mat(name, path, crop=None):
    m, N, L = _tree(name)
    out = N.new('ShaderNodeOutputMaterial')
    b = N.new('ShaderNodeBsdfPrincipled')
    b.inputs['Roughness'].default_value = 0.35
    i = N.new('ShaderNodeTexImage')
    i.image = bpy.data.images.load(str(path), check_existing=True)
    L.new(i.outputs[0], b.inputs['Base Color'])
    L.new(b.outputs[0], out.inputs[0])
    return m


M = {}


def materials():
    M['piso'] = pbr('Piso roble', 'laminate_floor_02', rough_gain=0.85, nstr=0.6, coat=0.15)
    M['pared'] = pbr('Pared', 'white_plaster_02', size=1.4, color=(0.9, 0.88, 0.84), nstr=0.12, rough_gain=1.0)
    M['techo'] = pbr('Techo', color=(0.9, 0.89, 0.87), rough=0.9)
    M['roble'] = pbr('Roble', 'white_oak_veneer', size=0.9, rough_gain=0.9, coat=0.1)
    M['roble_osc'] = pbr('Roble ahumado', 'white_oak_veneer', size=0.9, tint=(0.36, 0.25, 0.17, 1.9), coat=0.15)
    M['piedra'] = pbr('Travertino', 'marble_01', size=1.8, rough_gain=0.6, coat=0.25)
    M['terrazo'] = pbr('Terrazo', 'terrazzo_tiles', size=2.4, rough_gain=0.7, coat=0.3)
    M['azulejo'] = pbr('Azulejo', 'long_white_tiles', size=1.0, rough_gain=0.5)
    M['cemento'] = pbr('Cemento alisado', 'smooth_concrete_floor', tint=(0.62, 0.6, 0.57, 1.6), rough_gain=0.8)
    M['deck'] = pbr('Deck', 'wood_floor_deck', tint=(0.46, 0.38, 0.30, 1.8), rough_gain=1.0, nstr=0.8)
    M['tela'] = pbr('Tela sofá', 'poly_wool_herringbone', size=0.32, tint=(0.80, 0.76, 0.69, 1.9), sheen=0.4, nstr=0.6)
    M['tela_osc'] = pbr('Tela salvia', 'poly_wool_herringbone', size=0.32, tint=(0.42, 0.45, 0.39, 1.9), sheen=0.4, nstr=0.6)
    M['alfombra'] = pbr('Alfombra', 'poly_wool_herringbone', size=0.5, tint=(0.74, 0.70, 0.63, 1.8), sheen=0.5, nstr=1.2)
    M['lino'] = pbr('Lino blanco', 'rough_linen', size=0.35, tint=(0.95, 0.93, 0.89, 1.7), sheen=0.3, nstr=0.8)
    M['lino_arena'] = pbr('Lino arena', 'rough_linen', size=0.35, tint=(0.70, 0.60, 0.48, 1.7), sheen=0.3, nstr=0.8)
    M['negro'] = pbr('Metal negro', color=(0.025, 0.025, 0.025), rough=0.35, metal=0.6)
    M['bronce'] = pbr('Bronce', color=(0.55, 0.38, 0.2), rough=0.25, metal=1.0)
    M['blanco'] = pbr('Laca blanca', color=(0.86, 0.85, 0.82), rough=0.4)
    M['vidrio'] = glass_mat()
    M['espejo'] = pbr('Espejo', color=(0.9, 0.9, 0.9), rough=0.0, metal=1.0)
    M['vitro'] = pbr('Vitrocerámica', color=(0.01, 0.01, 0.012), rough=0.08, coat=1.0)
    M['losa'] = pbr('Losa exterior', color=(0.84, 0.83, 0.8), rough=0.6)
    M['led'] = emit_mat('LED', strength=12)
    M['cortina'] = curtain_mat()
    M['sombra'] = pbr('Junta', color=(0.02, 0.02, 0.02), rough=0.9)


# ------------------------------------------------------------------ geometría
def _obj(name, mesh, mat=None, coll=None):
    o = bpy.data.objects.new(name, mesh)
    (coll or bpy.context.scene.collection).objects.link(o)
    if mat:
        o.data.materials.append(mat)
    return o


def box(name, x0, y0, z0, x1, y1, z1, mat=None, bevel=0.0, seg=3, parent=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = x0 + (v.co.x + 0.5) * (x1 - x0)
        v.co.y = y0 + (v.co.y + 0.5) * (y1 - y0)
        v.co.z = z0 + (v.co.z + 0.5) * (z1 - z0)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, mat)
    if bevel:
        md = o.modifiers.new('Bisel', 'BEVEL')
        md.width = bevel
        md.segments = seg
        md.limit_method = 'ANGLE'
        md.harden_normals = True
        for p in me.polygons:
            p.use_smooth = True
    if parent:
        o.parent = parent
    return o


def cyl(name, x, y, z0, z1, r, mat=None, seg=48, parent=None, bevel=0.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=z1 - z0)
    for v in bm.verts:
        v.co.x += x
        v.co.y += y
        v.co.z += (z0 + z1) / 2
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, mat)
    for p in me.polygons:
        p.use_smooth = True
    if bevel:
        md = o.modifiers.new('Bisel', 'BEVEL')
        md.width = bevel
        md.segments = 3
        md.limit_method = 'ANGLE'
        md.harden_normals = True
    if parent:
        o.parent = parent
    return o


def group(name, x=0, y=0, rot=0, z=0):
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.location = (x, y, z)
    e.rotation_euler = (0, 0, math.radians(rot))
    return e


def wall(name, a, b, t, openings=(), mat=None, z0=0.0, z1=H):
    """Muro de a a b (horizontal o vertical) con vanos [(desde, hasta, alto_dintel, alto_antepecho)] medidos desde a."""
    mat = mat or M['pared']
    (ax, ay), (bx, by) = a, b
    horiz = ay == by
    length = abs(bx - ax) if horiz else abs(by - ay)
    sgn = 1 if (bx - ax if horiz else by - ay) > 0 else -1
    cuts = sorted(openings)
    pos = 0.0
    segs = []
    for (s, e, top, sill) in cuts:
        if s > pos:
            segs.append((pos, s, z0, z1))
        if top < z1:
            segs.append((s, e, top, z1))
        if sill > z0:
            segs.append((s, e, z0, sill))
        pos = e
    if pos < length:
        segs.append((pos, length, z0, z1))
    for i, (s, e, za, zb) in enumerate(segs):
        if horiz:
            xa, xb = ax + sgn * s, ax + sgn * e
            box(f'{name}.{i}', min(xa, xb), ay - t / 2, za, max(xa, xb), ay + t / 2, zb, mat)
        else:
            ya, yb = ay + sgn * s, ay + sgn * e
            box(f'{name}.{i}', ax - t / 2, min(ya, yb), za, ax + t / 2, max(ya, yb), zb, mat)


def window(name, a, b, mullions=4, z0=0.0, z1=H, depth=0.0, open=()):
    """Paño vidriado de piso a techo con carpintería negra fina. open: tramos corridos (sin vidrio)."""
    (ax, ay), (bx, by) = a, b
    horiz = ay == by
    if horiz:
        x = min(ax, bx)
        for (o0, o1) in sorted(open) + [(max(ax, bx), max(ax, bx))]:
            if o0 > x:
                box(f'{name} vidrio', x, ay - 0.006, z0, o0, ay + 0.006, z1, M['vidrio'])
            if o1 > o0:
                # la hoja corrida queda delante del paño vecino, con su marco
                box(f'{name} hoja', o1 - 0.02, ay - 0.05, z0, o1 + (o1 - o0) - 0.04, ay - 0.038, z1, M['vidrio'])
                box(f'{name} hoja marco', o1 - 0.02, ay - 0.06, z0, o1 + 0.03, ay - 0.03, z1, M['negro'])
            x = o1
        box(f'{name} riel inf', min(ax, bx), ay - 0.05, z0, max(ax, bx), ay + 0.05, z0 + 0.03, M['negro'])
        box(f'{name} riel sup', min(ax, bx), ay - 0.05, z1 - 0.05, max(ax, bx), ay + 0.05, z1, M['negro'])
        for i in range(mullions + 1):
            x = min(ax, bx) + i * abs(bx - ax) / mullions
            box(f'{name} parante {i}', x - 0.022, ay - 0.05, z0, x + 0.022, ay + 0.05, z1, M['negro'])
    else:
        box(f'{name} vidrio', ax - 0.006, min(ay, by), z0, ax + 0.006, max(ay, by), z1, M['vidrio'])
        box(f'{name} riel inf', ax - 0.05, min(ay, by), z0, ax + 0.05, max(ay, by), z0 + 0.03, M['negro'])
        box(f'{name} riel sup', ax - 0.05, min(ay, by), z1 - 0.05, ax + 0.05, max(ay, by), z1, M['negro'])
        for i in range(mullions + 1):
            y = min(ay, by) + i * abs(by - ay) / mullions
            box(f'{name} parante {i}', ax - 0.05, y - 0.022, z0, ax + 0.05, y + 0.022, z1, M['negro'])


def curtain(name, a, b, z1=H - 0.02, folds=None, depth=0.06):
    """Cortina de voile con pliegues, a lo largo de a-b, colgando de z1 al piso."""
    (ax, ay), (bx, by) = a, b
    length = (Vector(b) - Vector(a)).length
    n = folds or max(4, int(length / 0.11))
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    cols = n * 6
    rows = 2
    vs = []
    d = (Vector(b) - Vector(a)).normalized()
    nrm = Vector((-d.y, d.x))
    for r in range(rows):
        z = 0.01 if r == 0 else z1
        row = []
        for c in range(cols + 1):
            t = c / cols
            p = Vector(a) + d * (t * length)
            off = math.sin(t * n * 2 * math.pi) * depth / 2
            row.append(bm.verts.new((p.x + nrm.x * off, p.y + nrm.y * off, z)))
        vs.append(row)
    for c in range(cols):
        bm.faces.new((vs[0][c], vs[0][c + 1], vs[1][c + 1], vs[1][c]))
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, M['cortina'])
    for p in me.polygons:
        p.use_smooth = True
    sol = o.modifiers.new('Espesor', 'SOLIDIFY')
    sol.thickness = 0.004
    return o


# ------------------------------------------------------------------ modelos de Poly Haven
def ph_model(asset, x, y, rot=0, height=None, z=0.0, scale=None):
    path = ASSETS / 'models' / asset / f'{asset}.blend'
    before = set(bpy.data.images)
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        dst.objects = list(src.objects)
    for im in set(bpy.data.images) - before:
        name = pathlib.Path(im.filepath.replace('//', '')).name
        cand = list((ASSETS / 'models' / asset).rglob(name))
        if cand:
            im.filepath = str(cand[0])
            im.reload()
    objs = [o for o in dst.objects if o is not None]
    root = group(asset, x, y, rot, z)
    for o in objs:
        bpy.context.scene.collection.objects.link(o)
        if o.parent is None:
            o.parent = root
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == 'MESH' for c in o.bound_box]
    if pts:
        zmin = min(p.z for p in pts)
        zmax = max(p.z for p in pts)
        s = scale or (height / (zmax - zmin) if height else 1.0)
        root.scale = (s, s, s)
        bpy.context.view_layer.update()
        pts = [o.matrix_world @ Vector(c) for o in objs if o.type == 'MESH' for c in o.bound_box]
        cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
        cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
        root.location.x += x - cx
        root.location.y += y - cy
        root.location.z += z - min(p.z for p in pts)
    return root


# ------------------------------------------------------------------ muebles hechos a medida
def sofa(x, y, rot=0, w=2.8, d=1.02, mat=None):
    g = group('Sofá', x, y, rot)
    mat = mat or M['tela']
    hw, hd = w / 2, d / 2
    box('Sofá zócalo', -hw + 0.06, -hd + 0.06, 0, hw - 0.06, hd - 0.06, 0.1, M['sombra'], parent=g)
    box('Sofá base', -hw, -hd, 0.1, hw, hd, 0.4, mat, bevel=0.035, parent=g)
    box('Sofá respaldo', -hw, hd - 0.2, 0.4, hw, hd, 0.74, mat, bevel=0.05, parent=g)
    for s in (-1, 1):
        box('Sofá brazo', s * hw - (0.2 if s > 0 else 0), -hd, 0.4, s * hw + (0 if s > 0 else 0.2), hd, 0.6, mat,
            bevel=0.05, parent=g)
    n = 3
    cw = (w - 0.4) / n
    for i in range(n):
        x0 = -hw + 0.2 + i * cw
        box('Almohadón asiento', x0 + 0.006, -hd + 0.02, 0.4, x0 + cw - 0.006, hd - 0.2, 0.55, mat, bevel=0.06, seg=4,
            parent=g)
        b = box('Almohadón respaldo', x0 + 0.01, hd - 0.42, 0.52, x0 + cw - 0.01, hd - 0.2, 0.92, mat, bevel=0.08,
                seg=4, parent=g)
        b.rotation_euler.x = math.radians(-7)
    return g


def rug(x, y, w, d, rot=0, mat=None):
    g = group('Alfombra', x, y, rot)
    box('Alfombra', -w / 2, -d / 2, 0.0, w / 2, d / 2, 0.014, mat or M['alfombra'], bevel=0.006, parent=g)
    return g


def coffee_table(x, y, rot=0):
    g = group('Mesa ratona', x, y, rot)
    box('Mesa ratona base', -0.5, -0.24, 0, 0.5, 0.24, 0.3, M['piedra'], bevel=0.01, parent=g)
    box('Mesa ratona tapa', -0.68, -0.38, 0.3, 0.68, 0.38, 0.36, M['piedra'], bevel=0.012, parent=g)
    return g


def side_table(x, y, h=0.5, r=0.22, mat=None):
    g = group('Mesa auxiliar', x, y)
    cyl('Mesa auxiliar', 0, 0, 0, h, r, mat or M['roble_osc'], parent=g, bevel=0.01)
    return g


def floor_lamp(x, y, rot=0, h=1.6):
    g = group('Lámpara de pie', x, y, rot)
    cyl('Lámpara base', 0, 0, 0, 0.025, 0.16, M['negro'], parent=g)
    cyl('Lámpara vara', 0, 0, 0.025, h, 0.012, M['negro'], parent=g)
    cyl('Lámpara pantalla', 0, 0, h - 0.32, h, 0.21, M['lino'], parent=g)
    lamp_light(g, (0, 0, h - 0.16), 18)
    return g


def lamp_light(parent, co, watts, color=(1.0, 0.78, 0.55), radius=0.06):
    ld = bpy.data.lights.new('Luz', 'POINT')
    ld.energy = watts
    ld.color = color
    ld.shadow_soft_size = radius
    o = bpy.data.objects.new('Luz', ld)
    bpy.context.scene.collection.objects.link(o)
    o.parent = parent
    o.location = co
    return o


def downlight(x, y, watts=6.0):
    cyl('Spot', x, y, H - 0.005, H + 0.002, 0.045, M['led'])
    ld = bpy.data.lights.new('Spot', 'SPOT')
    ld.energy = watts
    ld.color = (1.0, 0.8, 0.6)
    ld.spot_size = math.radians(95)
    ld.spot_blend = 0.6
    ld.shadow_soft_size = 0.04
    o = bpy.data.objects.new('Spot', ld)
    bpy.context.scene.collection.objects.link(o)
    o.location = (x, y, H - 0.02)


def credenza(x, y, rot=0, w=2.4, d=0.45, h=0.62):
    g = group('Aparador', x, y, rot)
    box('Aparador cuerpo', -w / 2, -d / 2, 0.14, w / 2, d / 2, h, M['roble_osc'], bevel=0.006, parent=g)
    n = 4
    for i in range(1, n):
        xx = -w / 2 + i * w / n
        box('Aparador junta', xx - 0.002, -d / 2 - 0.001, 0.16, xx + 0.002, -d / 2 + 0.01, h - 0.02, M['sombra'], parent=g)
    for s in (-1, 1):
        box('Aparador pata', s * (w / 2 - 0.12) - 0.015, -0.015, 0, s * (w / 2 - 0.12) + 0.015, 0.015, 0.14, M['negro'],
            parent=g)
    return g


def dining(x, y, rot=0, w=2.2, d=1.0, chairs=3):
    g = group('Comedor', x, y, rot)
    box('Mesa tapa', -w / 2, -d / 2, 0.71, w / 2, d / 2, 0.75, M['roble'], bevel=0.008, parent=g)
    for s in (-1, 1):
        box('Mesa pata', s * (w / 2 - 0.25) - 0.04, -d / 2 + 0.12, 0, s * (w / 2 - 0.25) + 0.04, d / 2 - 0.12, 0.71,
            M['roble'], bevel=0.004, parent=g)
    for i in range(chairs):
        cx = -w / 2 + (i + 0.5) * w / chairs
        for side in (-1, 1):
            chair(g, cx, side * (d / 2 + 0.12), 0 if side < 0 else 180)
    return g


def chair(parent, x, y, rot):
    g = group('Silla', 0, 0, 0)
    g.parent = parent
    g.location = (x, y, 0)
    g.rotation_euler.z = math.radians(rot)
    box('Silla asiento', -0.23, -0.22, 0.42, 0.23, 0.22, 0.47, M['tela_osc'], bevel=0.02, parent=g)
    box('Silla respaldo', -0.22, -0.26, 0.47, 0.22, -0.23, 0.86, M['roble'], bevel=0.008, parent=g)
    for sx in (-1, 1):
        for sy in (-1, 1):
            box('Silla pata', sx * 0.19 - 0.015, sy * 0.19 - 0.015, 0, sx * 0.19 + 0.015, sy * 0.19 + 0.015, 0.42,
                M['roble'], parent=g)
    return g


def stool(x, y):
    g = group('Banqueta', x, y)
    cyl('Banqueta asiento', 0, 0, 0.66, 0.72, 0.19, M['tela_osc'], parent=g, bevel=0.015)
    for a in range(4):
        ang = a * math.pi / 2 + math.pi / 4
        o = box('Banqueta pata', -0.011, -0.011, 0, 0.011, 0.011, 0.68, M['negro'], parent=g)
        o.location = (math.cos(ang) * 0.13, math.sin(ang) * 0.13, 0)
    o = cyl('Banqueta aro', 0, 0, 0.28, 0.3, 0.15, M['negro'], parent=g)
    return g


def pendant(x, y, drop=0.9, r=0.13):
    z1 = H - drop
    cyl('Colgante cable', x, y, z1 + 0.25, H, 0.003, M['negro'])
    cyl('Colgante', x, y, z1, z1 + 0.25, r, M['bronce'])
    cyl('Colgante difusor', x, y, z1 - 0.004, z1 + 0.002, r * 0.86, M['led'])
    ld = bpy.data.lights.new('Colgante', 'SPOT')
    ld.energy = 25
    ld.color = (1.0, 0.78, 0.55)
    ld.spot_size = math.radians(110)
    ld.spot_blend = 0.8
    ld.shadow_soft_size = r * 0.8
    o = bpy.data.objects.new('Colgante luz', ld)
    bpy.context.scene.collection.objects.link(o)
    o.location = (x, y, z1 - 0.01)


def kitchen():
    # columna alta (heladera + horno) y bajo mesada contra el muro del fondo (cara norte del tabique y = -5.6)
    yb = -5.6 + 0.06
    box('Columna', 8.06, yb, 0, 9.0, yb + 0.64, 2.45, M['roble'], bevel=0.004)
    box('Horno', 8.18, yb + 0.6, 1.05, 8.88, yb + 0.645, 1.62, M['vitro'], bevel=0.004)
    box('Columna junta', 8.06, yb + 0.64, 1.68, 9.0, yb + 0.645, 1.684, M['sombra'])
    box('Zócalo', 9.0, yb, 0, 11.55, yb + 0.56, 0.1, M['sombra'])
    box('Bajo mesada', 9.0, yb, 0.1, 11.55, yb + 0.62, 0.88, M['roble'], bevel=0.003)
    for i in range(1, 4):
        xx = 9.0 + i * 2.55 / 4
        box('Junta', xx - 0.002, yb + 0.6, 0.12, xx + 0.002, yb + 0.625, 0.86, M['sombra'])
    box('Mesada', 9.0, yb, 0.88, 11.55, yb + 0.65, 0.92, M['terrazo'], bevel=0.004)
    box('Respaldo', 9.0, yb, 0.92, 11.55, yb + 0.02, 1.55, M['terrazo'])
    box('Estante', 9.0, yb, 1.55, 11.55, yb + 0.28, 1.59, M['roble'], bevel=0.003)
    box('Tira LED', 9.02, yb + 0.25, 1.545, 11.53, yb + 0.27, 1.55, M['led'])
    box('Bacha', 10.55, yb + 0.12, 0.86, 11.25, yb + 0.5, 0.921, M['negro'])
    cyl('Grifería', 10.9, yb + 0.08, 0.92, 1.25, 0.012, M['negro'])
    box('Grifería pico', 10.885, yb + 0.08, 1.23, 10.915, yb + 0.3, 1.25, M['negro'])
    ph_model('ceramic_vase_03', 9.3, yb + 0.14, height=0.22, z=1.59)
    ph_model('ceramic_vase_02', 9.55, yb + 0.14, height=0.3, z=1.59)
    ph_model('potted_plant_04', 11.3, yb + 0.2, height=0.3, z=0.92)
    # isla con anafe y banquetas
    box('Isla', 8.5, -3.95, 0.08, 10.3, -3.0, 0.9, M['blanco'], bevel=0.004)
    box('Isla zócalo', 8.56, -3.9, 0, 10.24, -3.06, 0.08, M['sombra'])
    box('Isla tapa', 8.4, -4.0, 0.9, 10.4, -2.75, 0.95, M['terrazo'], bevel=0.005)
    box('Anafe', 8.85, -3.85, 0.95, 9.6, -3.35, 0.952, M['vitro'])
    for xx in (8.85, 9.45, 10.05):
        stool(xx, -2.45)
    for xx in (8.9, 9.4, 9.9):
        pendant(xx, -3.38)
    ph_model('wooden_bowl_01', 10.0, -3.35, height=0.09, z=0.95)


def clad(name, a, b, openings=(), mat=None):
    """Revestimiento fino (piedra, azulejo) sobre la cara de un muro."""
    wall(name, a, b, 0.012, openings, mat or M['piedra'])


def bed(x, y, rot=0, w=1.8, l=2.1, head_w=None):
    g = group('Cama', x, y, rot)
    hw = (head_w or w + 1.0) / 2
    box('Respaldo', -hw, -0.06, 0, hw, 0.0, 1.25, M['tela'], bevel=0.02, parent=g)
    box('Base cama', -w / 2, -l, 0.1, w / 2, -0.06, 0.38, M['tela'], bevel=0.02, parent=g)
    box('Base sombra', -w / 2 + 0.05, -l + 0.05, 0, w / 2 - 0.05, -0.1, 0.1, M['sombra'], parent=g)
    box('Colchón', -w / 2 + 0.02, -l + 0.02, 0.38, w / 2 - 0.02, -0.08, 0.6, M['lino'], bevel=0.05, seg=4, parent=g)
    box('Acolchado', -w / 2 - 0.02, -l - 0.02, 0.5, w / 2 + 0.02, -0.55, 0.64, M['lino'], bevel=0.06, seg=4, parent=g)
    box('Pie de cama', -w / 2 - 0.03, -l - 0.03, 0.55, w / 2 + 0.03, -l + 0.55, 0.66, M['lino_arena'], bevel=0.05, seg=4,
        parent=g)
    for s in (-1, 1):
        p = box('Almohada', s * w / 4 - 0.34, -0.5, 0.6, s * w / 4 + 0.34, -0.1, 0.76, M['lino'], bevel=0.07, seg=4,
                parent=g)
        p.rotation_euler.x = math.radians(18)
        box('Mesa de luz', s * (w / 2 + 0.3) - 0.25, -0.46, 0.3, s * (w / 2 + 0.3) + 0.25, -0.08, 0.52, M['roble_osc'],
            bevel=0.006, parent=g)
        lg = group('Velador', 0, 0, 0)
        lg.parent = g
        lg.location = (s * (w / 2 + 0.3), -0.27, 0.52)
        cyl('Velador base', 0, 0, 0, 0.3, 0.07, M['piedra'], parent=lg)
        cyl('Velador pantalla', 0, 0, 0.28, 0.5, 0.15, M['lino'], parent=lg)
        lamp_light(lg, (0, 0, 0.38), 9)
    return g


def wardrobe(x0, y0, x1, y1, h=2.45):
    box('Placard', x0, y0, 0, x1, y1, h, M['roble'], bevel=0.003)


def vanity():
    yb = -8.0 + 0.06
    box('Vanitory', 5.2, yb, 0.3, 7.3, yb + 0.5, 0.82, M['roble_osc'], bevel=0.004)
    box('Vanitory tapa', 5.2, yb, 0.82, 7.3, yb + 0.52, 0.86, M['piedra'], bevel=0.004)
    for xx in (5.75, 6.75):
        cyl('Bacha', xx, yb + 0.27, 0.86, 1.0, 0.2, M['blanco'], bevel=0.01)
        cyl('Grifería', xx, yb + 0.03, 0.86, 1.22, 0.01, M['negro'])
    box('Espejo', 5.3, yb + 0.002, 1.05, 7.2, yb + 0.012, 2.15, M['espejo'])
    box('Luz espejo', 5.32, yb + 0.012, 2.15, 7.18, yb + 0.02, 2.17, M['led'])


def shower():
    box('Receptáculo', 6.0, -6.9, 0, 7.34, -5.66, 0.02, M['cemento'])
    box('Mampara', 5.98, -6.9, 0.02, 6.0, -5.66, 2.1, M['vidrio'])
    box('Mampara perfil', 5.98, -6.9, 2.08, 6.0, -5.66, 2.11, M['negro'])
    cyl('Ducha', 6.7, -6.2, 2.3, 2.33, 0.15, M['negro'])
    cyl('Ducha caño', 6.7, -6.2, 2.33, H, 0.01, M['negro'])
    box('Nicho', 7.33, -6.6, 1.1, 7.36, -6.0, 1.4, M['sombra'])


# ------------------------------------------------------------------ armado
def build():
    sc = reset()
    materials()
    t, te = 0.12, 0.25

    # pisos
    box('Piso', -te, -5.6, -0.2, 13 + te, 0, 0, M['piso'])
    box('Piso suites', -te, -10 - te, -0.2, 5, -5.6, 0, M['piso'])
    box('Piso suite 2', 9, -10 - te, -0.2, 13 + te, -5.6, 0, M['piso'])
    box('Piso baño', 5, -10 - te, -0.2, 9, -5.6, 0, M['piedra'])
    box('Techo', -te, -10 - te, H, 13 + te, 0, H + 0.25, M['techo'])

    # cerramientos exteriores
    window('Frente', (0, 0), (13, 0), mullions=5, open=[(2.6, 5.2), (7.8, 10.4)])
    wall('Muro oeste', (0, 0.0), (0, -10), te, [(6.0, 9.6, H, 0)])
    window('Ventana suite', (0, -6.0), (0, -9.6), mullions=2)
    wall('Muro este', (13, 0.0), (13, -10), te, [(0, 4.6, H, 0), (6.0, 9.6, H, 0)])
    window('Ventana cocina', (13, 0), (13, -4.6), mullions=2)
    window('Ventana suite 2', (13, -6.0), (13, -9.6), mullions=2)
    wall('Muro fondo', (-te, -10), (13 + te, -10), te)
    for x in (0, 13):
        box('Columna fachada', x - 0.2, -0.2, 0, x + 0.2, 0.05, H, M['pared'])

    # tabiques interiores
    wall('Tabique estar', (0, -5.6), (13, -5.6), t, [(4.05, 4.95, 2.2, 0), (11.8, 12.7, 2.2, 0)])
    wall('Tabique suite', (5, -5.6), (5, -10), t, [(0.45, 1.25, 2.2, 0), (3.0, 3.8, 2.2, 0)])
    wall('Tabique baño', (5, -8), (7.4, -8), t)
    wall('Tabique vestidor', (7.4, -5.6), (7.4, -10), t)
    wall('Tabique suite 2', (9, -5.6), (9, -10), t, [(0.6, 1.4, 2.2, 0)])

    # balcón y losas
    box('Balcón', -0.2, 0, -0.25, 13.2, 2.4, -0.05, M['deck'])
    box('Balcón canto', -0.2, 2.4, -0.4, 13.2, 2.5, 0.0, M['losa'], bevel=0.04)
    box('Losa superior', -0.3, 0.05, H + 0.25, 13.3, 2.55, H + 0.55, M['losa'], bevel=0.04)
    box('Baranda vidrio', -0.1, 2.33, -0.05, 13.1, 2.35, 1.05, M['vidrio'])
    box('Pasamanos', -0.1, 2.32, 1.05, 13.1, 2.36, 1.08, M['negro'])
    for k in range(1, 5):
        # balcones de los pisos de abajo, girados 4° cada uno como la torre
        g = group(f'Piso -{k}', -1.0, -11.0, -4 * k, -k * 3.3)
        box('Losa', 0.8, 10.9, -0.4, 14.4, 13.5, 0.0, M['losa'], bevel=0.04, parent=g)
        box('Baranda', 1.0, 13.33, 0.0, 14.1, 13.35, 1.05, M['vidrio'], parent=g)
        box('Pasamanos', 1.0, 13.32, 1.05, 14.1, 13.36, 1.08, M['negro'], parent=g)
    ph_model('outdoor_table_chair_set_01', 10.6, 1.25, rot=10, height=0.9, z=-0.05)
    ph_model('planter_box_01', 1.0, 2.0, height=0.55, z=-0.05)
    ph_model('planter_box_01', 2.2, 2.0, height=0.55, z=-0.05)

    # zócalos
    for (a, b) in [((0.07, -5.53), (13 - 0.07, -5.53))]:
        box('Zócalo', a[0], a[1] - 0.012, 0, b[0], a[1], 0.07, M['blanco'])

    # estar
    rug(2.9, -2.75, 3.4, 2.6)
    sofa(2.9, -4.25, 180, w=2.5)
    coffee_table(2.9, -2.65)
    ph_model('decorative_book_set_01', 2.6, -2.65, rot=8, height=0.12, z=0.36)
    ph_model('wooden_bowl_01', 3.25, -2.6, height=0.08, z=0.36)
    ph_model('mid_century_lounge_chair', 1.25, -1.6, rot=-130, height=0.82)
    ph_model('modern_arm_chair_01', 4.75, -2.35, rot=100, height=0.8)
    side_table(1.2, -4.1, 0.5)
    ph_model('ceramic_vase_02', 1.2, -4.1, height=0.32, z=0.5)
    floor_lamp(1.25, -4.85)
    credenza(0.24, -2.8, rot=-90)
    ph_model('standing_picture_frame_01', 0.26, -3.5, rot=-90, height=0.32, z=0.62)
    ph_model('ceramic_vase_03', 0.24, -2.1, height=0.4, z=0.62)
    ph_model('potted_plant_02', 0.55, -0.55, height=1.5)
    ph_model('potted_plant_04', 7.6, -5.15, height=0.9)
    # cuadro sobre el aparador
    art = ROOT / 'img' / 'originales' / 'aerea-2.png'
    if art.exists():
        box('Marco', 0.07, -3.55, 1.05, 0.11, -2.05, 2.05, M['roble_osc'])
        o = box('Cuadro', 0.11, -3.5, 1.1, 0.115, -2.1, 2.0, photo_mat('Foto', art))
        uv = o.data.uv_layers.new()
        for poly in o.data.polygons:
            for li in poly.loop_indices:
                co = o.data.vertices[o.data.loops[li].vertex_index].co
                uv.data[li].uv = ((co.y + 3.5) / 1.4, (co.z - 1.1) / 0.9)
    for (xx, yy) in [(0.6, -1.0), (0.6, -4.6), (7.3, -1.0), (7.3, -4.6)]:
        downlight(xx, yy, 5)
    curtain('Cortina oeste', (0.12, -0.15), (0.12, -1.1))
    curtain('Cortina frente', (11.6, -0.15), (12.85, -0.15))

    # cocina y comedor
    kitchen()
    dining(12.1, -1.75, rot=90, w=2.2, d=0.95, chairs=3)
    ph_model('ceramic_vase_03', 12.1, -1.75, height=0.36, z=0.75)
    for (xx, yy) in [(8.6, -1.0), (8.6, -4.6), (12.4, -4.6)]:
        downlight(xx, yy, 5)

    # suite principal
    bed(2.6, -9.94, 0, w=1.8)
    rug(2.6, -8.4, 2.8, 2.4)
    box('Banco', 1.75, -7.62, 0.0, 3.45, -7.2, 0.44, M['roble_osc'], bevel=0.006)
    ph_model('modern_arm_chair_01', 0.8, -6.45, rot=-60, height=0.8)
    ph_model('potted_plant_01', 0.45, -9.55, height=1.1)
    curtain('Cortina suite a', (0.12, -6.05), (0.12, -6.9))
    curtain('Cortina suite b', (0.12, -8.8), (0.12, -9.6))
    downlight(2.6, -6.3, 5)
    wardrobe(0.1, -6.3, 3.55, -5.66)
    for i in range(1, 6):
        xx = 0.1 + i * 3.45 / 6
        box('Placard junta', xx - 0.002, -6.305, 0.05, xx + 0.002, -6.29, 2.4, M['sombra'])
    art2 = ROOT / 'img' / 'originales' / 'aerea-1.png'
    if art2.exists():
        box('Marco cama', 1.7, -9.95, 1.45, 3.5, -9.92, 2.25, M['roble_osc'])
        o = box('Cuadro cama', 1.74, -9.92, 1.49, 3.46, -9.915, 2.21, photo_mat('Foto 2', art2))
        uv = o.data.uv_layers.new()
        for poly in o.data.polygons:
            for li in poly.loop_indices:
                co = o.data.vertices[o.data.loops[li].vertex_index].co
                uv.data[li].uv = ((co.x - 1.74) / 1.72, (co.z - 1.49) / 0.72)

    # baño en suite
    vanity()
    shower()
    clad('Baño oeste', (5.067, -5.66), (5.067, -7.94), [(0.39, 1.19, 2.2, 0)])
    clad('Baño este', (7.333, -5.66), (7.333, -7.94), [(0.34, 0.94, 1.4, 1.1)])
    clad('Baño sur', (5.06, -7.933), (7.34, -7.933), [(0.24, 2.04, 2.15, 0.86)])
    clad('Baño norte', (5.06, -5.667), (7.34, -5.667))
    box('Toallero', 5.2, -5.75, 1.2, 5.75, -5.7, 1.22, M['negro'])
    box('Toalla', 5.25, -5.78, 0.75, 5.7, -5.72, 1.21, M['lino'], bevel=0.02)
    box('Banco ducha', 6.5, -5.95, 0.0, 7.2, -5.68, 0.45, M['roble'], bevel=0.006)
    ph_model('potted_plant_01', 7.1, -7.6, height=0.6)
    for (xx, yy) in [(5.6, -6.4), (6.7, -7.3)]:
        downlight(xx, yy, 14)
    # vestidor y baño 2 (sin cámara, pero se ven por las puertas)
    wardrobe(5.1, -9.94, 7.34, -9.35)
    box('Vanitory 2', 7.5, -9.94, 0.3, 8.94, -9.45, 0.86, M['roble_osc'], bevel=0.004)

    # suite 2
    bed(11.0, -9.94, 0, w=1.6)
    rug(11.0, -8.4, 2.5, 2.2, mat=M['alfombra'])
    wardrobe(9.08, -9.94, 9.65, -7.4)
    ph_model('mid_century_lounge_chair', 12.3, -6.6, rot=-130, height=0.82)
    ph_model('potted_plant_04', 12.6, -9.55, height=0.9)
    curtain('Cortina suite 2 a', (12.88, -6.05), (12.88, -6.9))
    curtain('Cortina suite 2 b', (12.88, -8.8), (12.88, -9.6))
    downlight(11.0, -6.3, 5)
    # cómoda y cuadro en el muro norte (el que se ve al entrar)
    box('Cómoda', 9.35, -6.12, 0.12, 11.35, -5.66, 0.74, M['roble_osc'], bevel=0.005)
    box('Cómoda zócalo', 9.4, -6.07, 0, 11.3, -5.7, 0.12, M['sombra'])
    for i in range(1, 4):
        xx = 9.35 + i * 0.5
        box('Cómoda junta', xx - 0.002, -6.125, 0.14, xx + 0.002, -6.11, 0.72, M['sombra'])
    ph_model('ceramic_vase_02', 9.75, -5.9, height=0.3, z=0.74)
    art3 = ROOT / 'img' / 'originales' / 'vista-lago.jpg'
    if art3.exists():
        box('Marco suite 2', 9.6, -5.7, 1.1, 11.1, -5.66, 1.95, M['roble_osc'])
        o = box('Cuadro suite 2', 9.64, -5.705, 1.14, 11.06, -5.7, 1.91, photo_mat('Foto 3', art3))
        uv = o.data.uv_layers.new()
        for poly in o.data.polygons:
            for li in poly.loop_indices:
                co = o.data.vertices[o.data.loops[li].vertex_index].co
                uv.data[li].uv = (0.3 + 0.4 * (co.x - 9.64) / 1.42, 0.25 + 0.5 * (co.z - 1.14) / 0.77)

    # puertas abiertas (hojas contra el muro)
    for (x0, y0, x1, y1) in [(3.13, -5.54, 4.03, -5.5), (11.8, -5.66, 11.84, -6.55)]:
        box('Puerta', x0, y1, 0, x1, y0, 2.2, M['blanco'], bevel=0.003)

    sky_and_sun()
    backdrop()
    portals()
    return sc


def sky_and_sun(elev=11.0, azim=-48.0):
    """Cielo físico (luz) + sol de fin de tarde que entra por el noroeste (hemisferio sur: sol al norte)."""
    w = bpy.data.worlds.new('Cielo')
    bpy.context.scene.world = w
    w.use_nodes = True
    N, L = w.node_tree.nodes, w.node_tree.links
    N.clear()
    sky = N.new('ShaderNodeTexSky')
    sky.sky_type = 'NISHITA'
    sky.sun_disc = False
    sky.sun_elevation = math.radians(elev)
    sky.sun_rotation = math.radians(-azim)
    sky.altitude = 40
    sky.air_density = 1.2
    sky.dust_density = 2.5
    bg = N.new('ShaderNodeBackground')
    bg.inputs[1].default_value = 0.32
    out = N.new('ShaderNodeOutputWorld')
    L.new(sky.outputs[0], bg.inputs[0])
    L.new(bg.outputs[0], out.inputs[0])
    sd = bpy.data.lights.new('Sol', 'SUN')
    sd.energy = 4.6
    sd.color = (1.0, 0.72, 0.48)
    sd.angle = math.radians(0.8)
    so = bpy.data.objects.new('Sol', sd)
    bpy.context.scene.collection.objects.link(so)
    a, e = math.radians(azim), math.radians(elev)
    to_sun = Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    so.rotation_euler = to_sun.to_track_quat('Z', 'Y').to_euler()


def backdrop(radius=400.0):
    """Vista del lago y la cordillera: foto panorámica de 180° en un cilindro lejano (espejada atrás)."""
    p = ROOT / 'img' / 'originales' / 'vista-lago.jpg'
    if not p.exists():
        p = ROOT / 'img' / 'originales' / 'aerea-2.png'
    im = bpy.data.images.load(str(p), check_existing=True)
    iw, ih = im.size
    span = math.pi  # la foto cubre 180°
    height = radius * span * ih / iw
    zc = EYE
    me = bpy.data.meshes.new('Vista')
    bm = bmesh.new()
    segs = 256
    uvl = bm.loops.layers.uv.new()
    ring = []
    for i in range(segs + 1):
        th = -math.pi + 2 * math.pi * i / segs  # 0 = norte
        x, y = math.sin(th) * radius, math.cos(th) * radius
        u = 0.5 + th / span
        u = u if 0 <= u <= 1 else (-u if u < 0 else 2 - u)  # espejo para la mitad de atrás
        ring.append((bm.verts.new((6.5 + x, -5 + y, zc - height / 2)), bm.verts.new((6.5 + x, -5 + y, zc + height / 2)), u))
    for i in range(segs):
        (a0, a1, ua), (b0, b1, ub) = ring[i], ring[i + 1]
        f = bm.faces.new((a0, b0, b1, a1))
        for loop, uv in zip(f.loops, [(ua, 0), (ub, 0), (ub, 1), (ua, 1)]):
            loop[uvl].uv = uv
    bm.to_mesh(me)
    bm.free()
    m, N, L = _tree('Vista')
    out = N.new('ShaderNodeOutputMaterial')
    tex = N.new('ShaderNodeTexImage')
    tex.image = im
    tex.extension = 'EXTEND'
    em = N.new('ShaderNodeEmission')
    em.inputs[1].default_value = 1.6
    L.new(tex.outputs[0], em.inputs[0])
    L.new(em.outputs[0], out.inputs[0])
    o = _obj('Vista', me, m)
    o.visible_diffuse = False
    o.visible_shadow = False
    o.visible_volume_scatter = False
    # agua lejana bajo la foto, por si se mira muy abajo desde el balcón
    box('Lago', -800, -800, zc - height / 2 - 1, 800, 800, zc - height / 2, pbr('Agua', color=(0.05, 0.08, 0.1), rough=0.05))


def portals():
    for (x, y, w, rot) in [(6.5, 0.02, 13.0, 0), (12.98, -2.3, 4.6, -90), (0.02, -7.8, 3.6, 90), (12.98, -7.8, 3.6, -90)]:
        ld = bpy.data.lights.new('Portal', 'AREA')
        ld.shape = 'RECTANGLE'
        ld.size = w
        ld.size_y = H
        ld.cycles.is_portal = True
        o = bpy.data.objects.new('Portal', ld)
        bpy.context.scene.collection.objects.link(o)
        o.location = (x, y, H / 2)
        # el portal mira hacia adentro (-y desde la fachada)
        o.rotation_euler = (math.radians(-90), 0, math.radians(rot))


# ------------------------------------------------------------------ cámaras y render
def camera(pano=True, lens=None):
    cd = bpy.data.cameras.new('Cam')
    if pano:
        cd.type = 'PANO'
        try:
            cd.panorama_type = 'EQUIRECTANGULAR'
        except AttributeError:
            cd.cycles.panorama_type = 'EQUIRECTANGULAR'
    else:
        cd.lens_unit = 'FOV'
        cd.sensor_fit = 'HORIZONTAL'
        cd.angle = math.radians(lens or 78)
    cd.clip_start = 0.05
    cd.clip_end = 2000
    co = bpy.data.objects.new('Cam', cd)
    bpy.context.scene.collection.objects.link(co)
    bpy.context.scene.camera = co
    return co


def aim(co, pos, yaw_deg, pitch_deg=0.0):
    """yaw: grados desde el norte, horario (90 = este)."""
    co.location = (pos[0], pos[1], EYE)
    co.rotation_euler = (math.radians(90 + pitch_deg), 0, math.radians(-yaw_deg))


def render_pano(view, res, samples, out):
    sc = bpy.context.scene
    co = camera(True)
    (pos, yaw) = VIEWS[view]
    aim(co, pos, 0)  # el panorama siempre arranca en el norte; el sitio decide hacia dónde mirar
    sc.render.resolution_x = res
    sc.render.resolution_y = res // 2
    sc.render.resolution_percentage = 100
    sc.cycles.samples = samples
    sc.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)


LABELS = {'living': 'Living', 'kitchen': 'Cocina y comedor', 'balcony': 'Balcón', 'suite': 'Suite principal',
          'bedroom': 'Segunda suite', 'bath': 'Baño en suite'}
MOVE_FOV = 96  # campo horizontal de los trayectos (el sitio iguala el 360° a este encuadre antes de reproducir)


def link_points(a, b):
    mid = LINKS[(a, b)] if (a, b) in LINKS else list(reversed(LINKS[(b, a)]))
    return [VIEWS[a][0], *mid, VIEWS[b][0]]


def dense_path(pts, per=24):
    """Curva suave (Catmull-Rom) que pasa por los puntos; devuelve una polilínea densa y su largo acumulado."""
    P = [Vector((x, y)) for x, y in pts]
    P = [P[0] * 2 - P[1]] + P + [P[-1] * 2 - P[-2]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(per):
            t = k / per
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2])
    cum = [0.0]
    for i in range(1, len(out)):
        cum.append(cum[-1] + (out[i] - out[i - 1]).length)
    return out, cum


def at(poly, cum, s):
    if s <= 0:
        return poly[0]
    if s >= cum[-1]:
        d = (poly[-1] - poly[-2]).normalized()
        return poly[-1] + d * (s - cum[-1])
    for i in range(1, len(cum)):
        if cum[i] >= s:
            t = (s - cum[i - 1]) / max(1e-6, cum[i] - cum[i - 1])
            return poly[i - 1].lerp(poly[i], t)
    return poly[-1]


def yaw_of(v):
    return math.degrees(math.atan2(v.x, v.y))


def move_frames(a, b, fps=24):
    poly, cum = dense_path(link_points(a, b))
    length = cum[-1]
    n = int(round(fps * min(3.0, max(1.5, length / 2.3))))
    frames = []
    for k in range(n):
        t = k / (n - 1)
        s = t * t * (3 - 2 * t) * length  # arranca y frena suave
        pos = at(poly, cum, s)
        frames.append(((pos.x, pos.y), yaw_of(at(poly, cum, s + 1.8) - pos)))
    return frames, length


def render_move(a, b, samples):
    sc = bpy.context.scene
    frames, length = move_frames(a, b)
    co = camera(False, MOVE_FOV)
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    draft = bool(os.environ.get('DRAFT'))  # pasada rápida para revisar el camino
    sc.render.resolution_percentage = 40 if draft else 100
    sc.cycles.samples = 12 if draft else samples
    d = OUT / ('move-draft' if draft else 'move') / f'{a}-{b}'
    d.mkdir(parents=True, exist_ok=True)
    for i, (pos, yaw) in enumerate(frames):
        f = d / f'{i:03d}.png'
        if f.exists():
            continue
        aim(co, pos, yaw)
        sc.render.filepath = str(f)
        bpy.ops.render.render(write_still=True)
    print('MOVE', a, b, len(frames), 'cuadros', round(length, 2), 'm')


def export_js():
    """Escribe js/depto.js: ambientes, puntos de paso (en coordenadas del panorama) y trayectos."""
    def uv(view, target, z):
        (px, py), _ = VIEWS[view]
        d = Vector((target[0] - px, target[1] - py))
        pitch = math.degrees(math.atan2(z - EYE, d.length))
        return round((0.5 + yaw_of(d) / 360) % 1 * 100, 2), round((0.5 - pitch / 180) * 100, 2)

    views = {}
    for v, ((x, y), yaw) in VIEWS.items():
        spots = []
        for (a, b) in LINKS:
            if v not in (a, b):
                continue
            other = b if v == a else a
            pts = link_points(v, other)
            # el punto va en la puerta (o en el otro ambiente si se ve directo), a la altura de la cadera
            # primer punto del camino a más de 1,5 m (la puerta), así no queda pegado a los pies
            tgt = next((q for q in pts[1:] if (Vector(q) - Vector((x, y))).length >= 1.5), pts[-1])
            spots.append([other, *uv(v, tgt, 0.95)])
        views[v] = {'label': LABELS[v], 'pos': [x, -y], 'start': yaw, 'spots': spots}
    moves = {}
    for (a, b) in LINKS:
        for (p, q) in ((a, b), (b, a)):
            fr, _ = move_frames(p, q)
            moves[f'{p}-{q}'] = {'from': round(fr[0][1], 2), 'to': round(fr[-1][1], 2), 'n': len(fr), 'fps': 24}
    data = {'type': 'L2', 'fov': MOVE_FOV, 'views': views, 'moves': moves}
    (ROOT / 'js' / 'depto.js').write_text(
        '// Generado por tools/depto.py: departamento modelo (tipo L2) renderizado en Blender.\n'
        '// pos: posición en el plano (m); start, from y to: grados desde el norte en sentido horario.\n'
        f'export const DEPTO = {json.dumps(data, ensure_ascii=False)};\n', encoding='utf-8')
    print('js/depto.js listo')


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('--preview')
    ap.add_argument('--pano')
    ap.add_argument('--move', help="pares a-b separados por coma, o 'all'")
    ap.add_argument('--res', type=int, default=6144)
    ap.add_argument('--samples', type=int, default=0)
    ap.add_argument('--save', action='store_true')
    ap.add_argument('--export', action='store_true')
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.export:
        export_js()
        if not (a.preview or a.pano or a.move or a.save):
            return
    build()
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'depto.blend'))
    if a.preview:
        for v in a.preview.split(','):
            render_pano(v, 2048, a.samples or 96, OUT / f'preview-{v}.png')
    if a.pano:
        for v in (list(VIEWS) if a.pano == 'all' else a.pano.split(',')):
            render_pano(v, a.res, a.samples or 256, OUT / f'pano-{v}.png')
    if a.move:
        pairs = ([(p, q) for (x, y) in LINKS for (p, q) in ((x, y), (y, x))] if a.move == 'all'
                 else [tuple(m.split('-')) for m in a.move.split(',')])
        for p, q in pairs:
            render_move(p, q, a.samples or 64)


if __name__ == '__main__':
    main()
