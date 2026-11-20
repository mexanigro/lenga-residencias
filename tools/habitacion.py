"""Un ambiente solo, trabajado para fotorrealismo (la suite principal de Lenga).

Arma el departamento con tools/depto.py, se queda con la suite y la rehace con calidad de render fijo:
cama armada con tela simulada, cielo HDRI nublado, veladores que brillan, objetos y revelado de cámara.

Fondo (sin ventana):
  blender -b --factory-startup -P tools/habitacion.py -- base            escena recortada -> 3d/out/suite/base.blend
  blender -b -P tools/habitacion.py -- todo render                         todos los pasos y un render de control
Con ventana (BlenderMCP): abrir base.blend y llamar a los pasos de a uno: cama(), luz(), detalles(), acabados(),
camara(), revelado(). luz(), ropa(), respaldo(), acabados() y camara() se pueden repetir sobre suite.blend para
ajustar: python tools/render/bmcp.py pasos ropa acabados. Pruebas y recortes: tools/render/prueba.py y hoja.py.
Es la implementación de referencia del método del manual: referencias/hiperrealismo-metodo.md.
"""
import math
import pathlib
import random
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import depto as D  # noqa: E402

OUT = D.OUT / 'suite'
HDRI = D.ASSETS / 'hdri' / 'overcast_soil_puresky_4k.hdr'  # Poly Haven, CC0
# la suite: x 0..5 (ventana al oeste), y -10..-5.6 (listones al sur); se deja un margen para muros y losas
CAJA = ((-0.6, -10.6), (5.4, -5.25))
CAMA_X, PARED_Y = 2.6, -9.853  # eje de la cama y frente de los listones
# sol de media tarde que entra por la ventana oeste; desde: grados desde el norte, horario (-90 = oeste).
# Sin sol directo la luz queda pareja y plana: la mancha de sol es lo que da profundidad.
# cielo: fuerza del HDRI de relleno; más alto apaga la mancha
SOL = dict(elev=24.0, desde=-60.0, fuerza=5.0, angulo=1.5, color=(1.0, 0.86, 0.7), cielo=1.4)
# albedo medio de la ropa de cama, lineal: blanco de tela, apenas cálido y por debajo de 0,85
BLANCOS = {'Sábana': (0.80, 0.78, 0.74), 'Acolchado lino': (0.78, 0.75, 0.69), 'Funda': (0.82, 0.80, 0.76)}
VELADOR = 10  # vatios de luz (no eléctricos) de cada velador
CAM_Z = 1.1


def sc():
    return bpy.context.scene


def wbox(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)])


def hijos(root):
    out, st = [], [root]
    while st:
        o = st.pop()
        out.append(o)
        st.extend(o.children)
    return out


def borrar(objs):
    bpy.data.batch_remove(list({o for o in objs}))


def mat(nombre):
    return bpy.data.materials.get(nombre)


def albedo(img):
    """Color medio de una textura, lineal (los píxeles de un JPG vienen en sRGB)."""
    buf = np.empty(len(img.pixels), np.float32)
    img.pixels.foreach_get(buf)
    c = buf.reshape(-1, 4)[::5, :3]
    if not img.is_float:
        c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return c.mean(0), np.percentile(c @ np.array([0.2126, 0.7152, 0.0722]), 99)


def ajustar_albedo(m, objetivo):
    """Que el color medio de la tela sea `objetivo` (lineal) y la foto aporte solo la trama.
    Multiplicar la foto por un tinte a ojo dejaba las sábanas en ~0,5 (grises) y el tapizado en ~1,4,
    más luz de la que recibe: ningún material real pasa de ~0,9."""
    N = m.node_tree.nodes
    tex = next(n for n in N if n.type == 'TEX_IMAGE' and n.image.colorspace_settings.name != 'Non-Color')
    media, p99 = albedo(tex.image)
    gan = next((n for n in N if n.type == 'MATH' and n.inputs[0].links
                and n.inputs[0].links[0].from_node.type == 'RGBTOBW'), None)
    mix = next(n for n in N if n.type == 'MIX')
    if gan:  # textura en grises por un color (D.pbr con tint)
        k = 1 / float(media @ np.array([0.2126, 0.7152, 0.0722]))
        gan.inputs[1].default_value = k
        mix.inputs[6].default_value = (*objetivo, 1)
    else:  # foto por un color (tela_mat): se neutraliza el tinte de la foto canal por canal
        k = np.array(objetivo) / media
        mix.inputs[7].default_value = (*k, 1)
        k = float(k.max())
    print(f'ALBEDO {m.name}: medio {tuple(np.round(objetivo, 2))}, picos {p99 * k * max(objetivo):.2f}')


def tapizado():
    """Lana cruda del respaldo y las europeas. Se crea si falta: el recorte de la escena purga lo que nadie usa."""
    m = mat('Lana cruda') or D.pbr('Lana cruda', D.tx('wool_cream', 'poly_wool_herringbone'), size=0.32,
                                   tint=(*D.LANA, 1.9), sheen=0.4, nstr=1.6)
    ajustar_albedo(m, (0.70, 0.64, 0.54))
    return m


# ------------------------------------------------------------------ paso 0: escena recortada
def base():
    D.build(real=False)
    (x0, y0), (x1, y1) = CAJA
    fuera = []
    for o in sc().objects:
        if o.name in ('Vista', 'Lago', 'Sol') or o.parent is not None:
            continue
        if o.type == 'LIGHT' and o.data.type == 'SUN':
            continue
        objs = [c for c in hijos(o) if c.type in ('MESH', 'LIGHT')]
        if not objs:
            continue
        lo = Vector([min(wbox(c)[0][i] for c in objs) for i in range(3)])
        hi = Vector([max(wbox(c)[1][i] for c in objs) for i in range(3)])
        if hi.x < x0 or lo.x > x1 or hi.y < y0 or lo.y > y1:
            fuera.extend(hijos(o))
    borrar(fuera)
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'base.blend'))
    print('BASE', len(sc().objects), 'objetos')


# ------------------------------------------------------------------ paso 1: la cama
def tela_mat(nombre, color, tex='linen_natural', size=0.35, sheen=0.5, rough=0.85):  # rough_linen tira a azul
    """color: el albedo medio buscado, lineal (un blanco de tela ronda 0,75-0,8)."""
    m = D.pbr(nombre, tex, size=size, sheen=sheen, nstr=0.6)
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    # la foto del lino aporta la trama; el color sale de ajustar_albedo
    mix = m.node_tree.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs[0].default_value = 1.0
    link = next(l for l in m.node_tree.links if l.to_socket == b.inputs['Base Color'])
    m.node_tree.links.new(link.from_socket, mix.inputs[6])
    m.node_tree.links.remove(link)
    m.node_tree.links.new(mix.outputs[2], b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = rough
    ajustar_albedo(m, color)
    return m


def simular(o, frames, gravedad=1.0, presion=0.0, calidad=8, rigidez=10, flexion=0.3, encoge=0.0, propia=True, pin=False,
            masa=0.3):
    """masa: kg por vértice. 0,3 (lo de Blender) sirve para telas que cuelgan; en algo cerrado que tiene que
    sostenerse con presión, una almohada de 2.400 vértices pesaría 700 kg y se desinfla."""
    cl = o.modifiers.new('tela', 'CLOTH')
    s = cl.settings
    s.quality = calidad
    s.mass = masa
    s.tension_stiffness = s.compression_stiffness = rigidez
    s.bending_stiffness = flexion
    s.shrink_min = encoge
    s.effector_weights.gravity = gravedad
    if pin:  # el borde marcado queda fijo: sin eso la tela se resbala del colchón y cae al piso
        s.vertex_group_mass = 'pin'
        s.pin_stiffness = 1.0
    if presion:
        s.use_pressure = True
        s.uniform_pressure_force = presion
    c = cl.collision_settings
    c.collision_quality = 4
    c.distance_min = 0.004
    c.use_self_collision = propia
    c.self_distance_min = 0.003
    cl.point_cache.frame_start, cl.point_cache.frame_end = 1, frames
    sc().frame_start, sc().frame_end = 1, frames
    for f in range(1, frames + 1):
        sc().frame_set(f)
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier='tela')
    sc().frame_set(1)


def plano(nombre, x0, x1, y0, y1, z, nx, ny, amp=0.0, seed=1, pin=None):
    """Tela plana con las coordenadas del mundo en la malla (objeto en el origen): la simulación de tela, al aplicarse,
    deja la malla donde terminó sin sumarle de nuevo la posición del objeto. pin: (eje, desde, hasta) del borde fijo."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=nx, y_subdivisions=ny, size=1, location=(0, 0, 0))
    o = bpy.context.object
    o.name = nombre
    o.data.transform(Matrix.Translation(((x0 + x1) / 2, (y0 + y1) / 2, z)) @ Matrix.Diagonal((x1 - x0, y1 - y0, 1, 1)))
    if pin:
        eje, a, b = pin
        g = o.vertex_groups.new(name='pin')
        g.add([v.index for v in o.data.vertices if a <= v.co[eje] <= b], 1.0, 'REPLACE')
    random.seed(seed)
    ph = [random.random() * 6 for _ in range(4)]
    for v in o.data.vertices:  # ondas suaves al empezar: si cae plano, queda como una tabla
        v.co.z += amp * (math.sin(v.co.x * 7 + ph[0]) * math.sin(v.co.y * 5 + ph[1])
                         + 0.5 * math.sin(v.co.x * 17 + ph[2]) * math.sin(v.co.y * 13 + ph[3]))
    return o


def terminar(o, material, grosor=0.008, arriba=False):
    so = o.modifiers.new('grosor', 'SOLIDIFY')
    so.thickness = grosor
    so.offset = 1.0 if arriba else -1.0
    o.modifiers.new('suave', 'SUBSURF').levels = 1
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.shade_smooth()
    o.data.materials.clear()
    o.data.materials.append(material)


def almohada(nombre, ancho, alto, grueso, material, lugar, presion=2.0, encoge=0.03, vivo=None, rigidez=15, flexion=0.05):
    """Almohada que se infla mientras cae sobre lo que ya hay en la cama (lugar: x, y, z, giro x, giro z en grados).
    Antes se inflaba en el aire y se ubicaba girada: flotaba, rígida, y todas iguales.
    vivo: material del cordón de la costura (almohadones y europeas); None, sin cordón.
    rigidez, flexion: las de la tela al asentarse; el cuero necesita ~3 y ~40 veces más o se dobla como una
    cartera vacía."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    o = bpy.context.object
    o.name = nombre
    o.data.transform(Matrix.Diagonal((ancho, alto, grueso, 1)))
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=19)  # 20 tramos: queda una fila de vértices justo en la costura
    bpy.ops.object.mode_set(mode='OBJECT')
    costura = o.vertex_groups.new(name='costura')
    costura.add([v.index for v in o.data.vertices if abs(v.co.z) < 1e-5], 1.0, 'REPLACE')
    x, y, z, rx, rz = lugar
    # coordenadas del mundo en la malla y el objeto en el origen (ver plano())
    o.data.transform(Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(rz), 4, 'Z')
                     @ Matrix.Rotation(math.radians(rx), 4, 'X'))
    # se infla sin peso, en su lugar; después se asienta con el peso real (~1 kg) sin perder el relleno
    # (el inflado es siempre de tela: con la rigidez del cuero no se infla y queda doblado)
    simular(o, 14, gravedad=0.0, presion=presion, calidad=6, rigidez=15, flexion=0.05, encoge=encoge, propia=False)
    simular(o, 40, gravedad=1.0, presion=0.3, calidad=6, rigidez=rigidez, flexion=flexion, propia=False,
            masa=1.0 / len(o.data.vertices))
    o.modifiers.new('choque', 'COLLISION')  # la que cae después se apoya en esta
    o.collision.thickness_outer = 0.004
    o.collision.cloth_friction = 40
    o.modifiers.new('suave', 'SUBSURF').levels = 1
    bpy.ops.object.shade_smooth()
    o.data.materials.append(material)
    asentar(o)
    if vivo:
        ribete(o, vivo)
    return o


def asentar(o, tope=0.2):
    """Baja una tela simulada hasta que toque lo que tiene abajo. Rayos hacia abajo desde los vértices del tercio de
    abajo de la malla evaluada (con su subsurf), arrancando 2 mm por encima de cada uno y salteando la propia malla y
    las copias de choque. Infladas contra el respaldo, el roce las dejaba colgadas: las europeas a 3,7 cm del colchón,
    las de dormir a 5 y el almohadón a 7. Mueve la malla, no el objeto (ver plano())."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    vs = [o.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    z0, z1 = min(v.z for v in vs), max(v.z for v in vs)
    abajo = [v for v in vs if v.z < z0 + 0.33 * (z1 - z0)]
    random.seed(0)
    gap = tope
    for p in random.sample(abajo, min(300, len(abajo))):
        org = p + Vector((0, 0, 0.002))
        for _ in range(8):
            ok, loc, _n, _i, ob, _m = sc().ray_cast(dg, org, Vector((0, 0, -1)))
            if not ok:
                break
            if ob.name == o.name or ob.name.startswith('Choque'):
                org = loc - Vector((0, 0, 1e-4))
                continue
            gap = min(gap, p.z - loc.z)
            break
    if 0.002 < gap < tope:
        o.data.transform(Matrix.Translation((0, 0, 0.001 - gap)))
        print(f'ASENTADO {o.name}: bajó {gap * 100:.1f} cm')


def ribete(o, material, radio=0.0045):
    """Cordón de 9 mm sobre la costura de un almohadón: la fila de vértices del grupo 'costura'."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(o.data)
    capa, k = bm.verts.layers.deform.active, o.vertex_groups['costura'].index
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if k not in v[capa]], context='VERTS')
    me = bpy.data.meshes.new(f'Vivo {o.name}')
    bm.to_mesh(me)
    bm.free()
    v = bpy.data.objects.new(f'Vivo {o.name}', me)
    sc().collection.objects.link(v)
    bpy.ops.object.select_all(action='DESELECT')
    v.select_set(True)
    bpy.context.view_layer.objects.active = v
    bpy.ops.object.convert(target='CURVE')
    for s in v.data.splines:  # curva suave, no un polígono de tramos rectos
        s.type = 'NURBS'
        s.order_u = 3
        s.use_cyclic_u = True
    v.data.bevel_depth = radio
    v.data.bevel_resolution = 3
    v.data.materials.append(material)
    return v


def poner(o, x, y, z, rx=0.0, rz=0.0):
    o.location = (x, y, z)
    o.rotation_euler = (math.radians(rx), 0, math.radians(rz))


def dentro(o, caja=CAJA):
    """El objeto, con sus hijos, cae dentro de la caja (planta). En el departamento entero se repiten los nombres:
    otra cama 'bed_king', los 'cushions' del sofá, el 'Respaldo' que es el salpicadero de la cocina."""
    ms = [c for c in hijos(o) if c.type in ('MESH', 'CURVE')] or ([o] if o.type == 'LIGHT' else [])
    if not ms:
        return False
    if o.type == 'LIGHT':
        c = o.matrix_world.translation
    else:
        c = sum(((wbox(m)[0] + wbox(m)[1]) / 2 for m in ms), Vector()) / len(ms)
    (x0, y0), (x1, y1) = caja
    return x0 <= c.x <= x1 and y0 <= c.y <= y1


def raices(prefijos, caja=CAJA):
    return [o for o in sc().objects if o.parent is None and o.name.startswith(prefijos) and dentro(o, caja)]


def con_choque(o, friccion=60, grosor=0.004):
    if 'choque' not in o.modifiers:
        o.modifiers.new('choque', 'COLLISION')
    o.collision.thickness_outer = grosor
    o.collision.cloth_friction = friccion


def cama():
    # fuera la cama de catálogo (una sola malla con la ropa de cama fundida), la manta-caja y los almohadones
    borrar([c for o in raices(('bed_king', 'cushions', 'Manta cama', 'Manta tela')) for c in hijos(o)])
    x0, x1 = CAMA_X - 1.0, CAMA_X + 1.0
    fondo, pie = PARED_Y + 0.11, PARED_Y + 0.11 + 2.12
    tapiz = tapizado()
    respaldo()
    base_ = D.box('Base cama', x0, fondo, 0.06, x1, pie, 0.36, tapiz, bevel=0.035, seg=8)
    # sin esto la base quedaba a 6 cm del piso sin nada abajo: una cama flotando. Zócalo hundido en sombra
    D.box('Base cama sombra', x0 + 0.06, fondo + 0.06, 0, x1 - 0.06, pie - 0.06, 0.06, mat('Junta'))
    colchon = D.box('Colchón', x0 + 0.035, fondo + 0.01, 0.36, x1 - 0.035, pie - 0.025, 0.6,
                    tela_mat('Sábana', BLANCOS['Sábana']), bevel=0.07, seg=8)
    for o in (base_, colchon):
        con_choque(o)
    tela_mat('Funda', BLANCOS['Funda'])
    # del tono de la frazada. Más claro o con el brillo de tela de las sábanas (0,5), a la luz se leía rosado
    tela_mat('Lino arcilla', (0.28, 0.13, 0.07), sheen=0.2)
    acolchado(CAMA_X, fondo, pie, 2.0, 0.6)
    ropa()
    print('CAMA LISTA')


def acolchado(cx, fondo, pie, ancho, z, sufijo='', doblez=0.66, solapa=0.32, r=0.03, grosor=0.025):
    """Acolchado tendido: cae sobre el colchón y cuelga por los costados y el pie, y la cabecera va doblada hacia los
    pies sobre sí misma (media vuelta de radio r armada antes de simular, con la solapa encima).
    Lo único fijo es la franja que apoya en el colchón junto al doblez, sin lo que cuelga: fija 4 cm en el aire, la
    cabecera quedaba levantada 8 cm, y fija de lado a lado, las esquinas quedaban paradas como una placa.
    La tela simulada no tiene espesor: la solapa cae pegada a la capa de abajo y el grosor de las dos capas se
    encimaba, sin doblez a la vista. Después de simular, la solapa se corre dos grosores hacia afuera (gradual en la
    media vuelta) y el doblez queda como un rollo de 5 cm."""
    x0, x1 = cx - ancho / 2, cx + ancho / 2
    yd, z0 = fondo + doblez, z + 0.008  # línea del doblez; apoyado, a la distancia de choque
    ac = plano(f'Acolchado{sufijo}', x0 - 0.3, x1 + 0.3, yd - math.pi * r - solapa, pie + 0.3, z0, 120, 150,
               amp=0.012, seed=2)
    pin, dob = ac.vertex_groups.new(name='pin'), ac.vertex_groups.new(name='doblez')
    for v in ac.data.vertices:
        s = yd - v.co.y
        if s > 0:
            a = min(s / r, math.pi)
            v.co.y = yd - r * math.sin(a) + max(0.0, s - math.pi * r)
            v.co.z += r * (1 - math.cos(a))
            dob.add([v.index], (1 - math.cos(a)) / 2, 'REPLACE')
        elif v.co.y <= yd + 0.12 and abs(v.co.x - cx) <= ancho / 2 - 0.12:  # sobre la parte plana del colchón
            v.co.z = z0  # apoyado: sin las ondas del arranque
            pin.add([v.index], 1.0, 'REPLACE')
    simular(ac, 60, calidad=8, encoge=0.015, pin=True)
    k = ac.vertex_groups['doblez'].index  # por nombre: la referencia de antes de aplicar la tela ya no vale
    ns = [v.normal.copy() for v in ac.data.vertices]  # en la solapa apuntan hacia la capa de abajo
    n_ = 0
    for v, n in zip(ac.data.vertices, ns):
        w = next((g.weight for g in v.groups if g.group == k), 0.0)
        if w:
            v.co = v.co - n * w * (2 * grosor - 0.003)
            n_ += 1
    print(f'DOBLEZ {ac.name}: {n_} vértices corridos')
    terminar(ac, mat('Acolchado lino') or tela_mat('Acolchado lino', BLANCOS['Acolchado lino']), grosor=grosor,
             arriba=True)
    return ac


def respaldo(n=9):
    """Respaldo tapizado en canales verticales. Cada canal es un acolchado: el frente abombado ~2 cm y las
    costuras hundidas entre canales. Como cajas con bisel parecían tablones; además ninguno es idéntico."""
    borrar([c for o in raices('Respaldo') for c in hijos(o)])
    x0, x1 = CAMA_X - 1.04, CAMA_X + 1.04
    y0, y1, z0, z1 = PARED_Y + 0.01, PARED_Y + 0.11, 0.05, 1.3
    paso = (x1 - x0) / n
    tapiz = tapizado()
    random.seed(7)
    for i in range(n):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
        o = bpy.context.object
        o.name = 'Respaldo'
        w, d, h = paso - 0.004, y1 - y0 - 0.02, z1 - z0
        o.data.transform(Matrix.Diagonal((w, d, h, 1)))
        # primero el borde redondeado y después la subdivisión: al revés, el bisel no puede ser más ancho que
        # los tramos chicos y la punta de cada canal queda cuadrada
        bv, r = o.modifiers.new('borde', 'BEVEL'), 0.05
        bv.width, bv.segments, bv.limit_method = r, 8, 'ANGLE'
        bpy.ops.object.modifier_apply(modifier='borde')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.subdivide(number_cuts=8)
        # subdividir el bisel deja ~2.300 vértices repetidos (costuras abiertas): el decimado del horneado
        # retorcía los canales y el subsurf abre grietas en esas costuras
        bpy.ops.mesh.remove_doubles(threshold=1e-5)
        bpy.ops.object.mode_set(mode='OBJECT')
        comba, wf, hf = 0.02 * random.uniform(0.85, 1.15), w - 2 * r, h - 2 * r
        for v in o.data.vertices:
            if v.co.y > d / 2 - 1e-5:  # solo la cara del frente se abomba; los bordes redondeados quedan
                v.co.y += comba * max(0.0, 1 - (2 * v.co.x / wf) ** 2) * max(0.0, 1 - (2 * v.co.z / hf) ** 6)
        o.data.transform(Matrix.Translation((x0 + paso * (i + 0.5), (y0 + y1 - 0.02) / 2, (z0 + z1) / 2)))
        o.modifiers.new('suave', 'SUBSURF').levels = 1
        bpy.ops.object.shade_smooth()
        o.data.materials.append(tapiz)


def ropa(cx=CAMA_X, fondo=PARED_Y + 0.11, pie=PARED_Y + 0.11 + 2.12, ancho=2.0, z=0.6, sufijo='', caja=CAJA,
         respaldo='Respaldo', lumbar='Lino arcilla'):
    """Frazada y almohadas sobre una cama ya hecha (colchón con su tope en z, respaldo en y = fondo, acolchado
    'Acolchado{sufijo}' ya simulado). Se puede repetir: borra las anteriores de esa cama. lumbar: su tela."""
    borrar([c for o in raices(('Almohada', 'Europea', 'Lumbar', 'Cojín', 'Vivo', 'Choque'), caja) for c in hijos(o)]
           + [c for o in sc().objects if o.parent is None and o.name == f'Manta{sufijo}' for c in hijos(o)])
    x0, x1, k = cx - ancho / 2, cx + ancho / 2, ancho / 2.0
    # una copia quieta del acolchado, con su mismo espesor, hace de cuerpo de choque (tela contra tela simulada se
    # atraviesa)
    ac = sc().objects[f'Acolchado{sufijo}']
    choque = bpy.data.objects.new('Choque acolchado', ac.data.copy())
    sc().collection.objects.link(choque)
    so = choque.modifiers.new('grosor', 'SOLIDIFY')
    so.thickness, so.offset = ac.modifiers['grosor'].thickness, 1.0
    con_choque(choque, grosor=0.003)
    choque.hide_render = True
    for o in raices(respaldo, caja):  # las almohadas se apoyan en el respaldo
        for c in hijos(o):
            if c.type == 'MESH':
                con_choque(c, friccion=40)
    # frazada cruzada a los pies, colgando de los dos costados. Con un borde fijo para que no se resbalara,
    # ese borde quedaba levantado en el aire; repartida de los dos lados no tira para ninguno y no hace falta fijarla
    mt = plano(f'Manta{sufijo}', x0 - 0.30, x1 + 0.40, pie - 0.62, pie - 0.04, z + 0.14, 150, 34, amp=0.015, seed=5)
    simular(mt, 70, calidad=10, encoge=0.02)
    terminar(mt, mat('Manta a cuadros'), grosor=0.01, arriba=True)
    # almohadas como se arma una cama: europeas contra el respaldo, las de dormir delante, después los almohadones.
    # Cada una se infla y cae sobre las anteriores: se apoya, se aplasta donde toca y no hay dos iguales
    blanco = mat('Funda')
    # Las europeas casi paradas y finas: si sobresalen abajo, las de dormir quedan montadas sobre el borde del
    # acolchado y se ve una franja de sábana en sombra debajo, como si flotaran. Así el borde de abajo de las de
    # dormir apoya en la sábana, justo antes del doblez del acolchado (que empieza a 55 cm del respaldo)
    for i, s in enumerate((-1, 1)):
        almohada(f'Europea{sufijo} {i}', 0.65, 0.65, 0.12, blanco, (cx + s * 0.40 * k, fondo + 0.14, z + 0.35, -82, s * 2),
                 vivo=blanco)
    for i, s in enumerate((-1, 1)):
        almohada(f'Almohada{sufijo} {i}', 0.74, 0.5, 0.13, blanco, (cx + s * 0.42 * k, fondo + 0.45, z + 0.27, -55, -s * 3),
                 encoge=0.0)  # funda floja: arrugas
    # un solo almohadón, de lino, sobre el doblez del acolchado: el de cuero se leía como una piedra y el escocés,
    # parado en una punta, sobraba
    almohada(f'Lumbar{sufijo}', 0.55, 0.32, 0.11, mat(lumbar), (cx + 0.04, fondo + 0.70, z + 0.26, -66, 2),
             vivo=mat(lumbar))
    bpy.data.objects.remove(choque)
    print('ROPA LISTA', sufijo)


# ------------------------------------------------------------------ paso 2: luz
def luz():
    w = sc().world
    N, L = w.node_tree.nodes, w.node_tree.links
    N.clear()
    env = N.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(str(HDRI), check_existing=True)
    tc, mp = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeMapping')
    mp.inputs['Rotation'].default_value[2] = math.radians(90)  # la parte más clara del cielo entra por la ventana oeste
    L.new(tc.outputs['Generated'], mp.inputs['Vector'])
    L.new(mp.outputs[0], env.inputs[0])
    bg = N.new('ShaderNodeBackground')
    bg.inputs[1].default_value = SOL['cielo']  # relleno del cielo: más alto apaga la mancha de sol
    out = N.new('ShaderNodeOutputWorld')
    hs = N.new('ShaderNodeHueSaturation')  # el cielo nublado tiñe de azul lo blanco: se le baja el color
    hs.inputs['Saturation'].default_value = 0.4
    L.new(env.outputs[0], hs.inputs['Color'])
    L.new(hs.outputs[0], bg.inputs[0])
    L.new(bg.outputs[0], out.inputs[0])
    sol = bpy.data.objects['Sol']
    a, e = math.radians(SOL['desde']), math.radians(SOL['elev'])
    hacia = Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    sol.rotation_euler = hacia.to_track_quat('Z', 'Y').to_euler()
    sol.data.energy = SOL['fuerza']
    sol.data.angle = math.radians(SOL['angulo'])  # penumbra suave, la que el ojo lee como real
    sol.data.color = SOL['color']
    sc().view_settings.exposure = 1.0
    sc().view_settings.white_balance_temperature = 6500  # cielo nublado: se neutraliza el azul
    veladores(CAJA)
    print('LUZ LISTA')


def veladores(caja, vatios=VELADOR):
    """Las lámparas de mesa dentro de la caja: la pantalla deja pasar la luz y brilla, a una potencia de lámpara."""
    pant = bpy.data.materials.get('Pantalla translúcida') or bpy.data.materials.new('Pantalla translúcida')
    pant.use_nodes = True
    T = pant.node_tree
    T.nodes.clear()
    o_ = T.nodes.new('ShaderNodeOutputMaterial')
    mx = T.nodes.new('ShaderNodeMixShader')
    p = T.nodes.new('ShaderNodeBsdfPrincipled')
    p.inputs['Base Color'].default_value = (0.82, 0.76, 0.66, 1)
    p.inputs['Roughness'].default_value = 0.9
    t = T.nodes.new('ShaderNodeBsdfTranslucent')
    t.inputs['Color'].default_value = (1.0, 0.85, 0.66, 1)
    mx.inputs[0].default_value = 0.55
    T.links.new(p.outputs[0], mx.inputs[1])
    T.links.new(t.outputs[0], mx.inputs[2])
    T.links.new(mx.outputs[0], o_.inputs[0])
    for lz in [o for o in sc().objects if o.type == 'LIGHT' and o.data.type == 'POINT' and dentro(o, caja)]:
        q = lz.matrix_world.translation
        cand = [o for o in sc().objects if o.type == 'MESH' and all(wbox(o)[0][i] - 0.01 <= q[i] <= wbox(o)[1][i] + 0.01 for i in range(3))
                and (wbox(o)[1] - wbox(o)[0]).length < 0.9]
        if not cand:
            continue
        sh = max(cand, key=lambda o: (wbox(o)[1] - wbox(o)[0]).length)
        if pant.name not in [m.name for m in sh.data.materials if m]:
            sh.data.materials.append(pant)
        k = [m.name if m else '' for m in sh.data.materials].index(pant.name)
        for pg in sh.data.polygons:
            if (sh.matrix_world @ pg.center).z > q.z - 0.13:
                pg.material_index = k
        lz.data.energy = vatios  # de día acompañan: una pantalla encendida, no un foco
        lz.data.shadow_soft_size = 0.05


# ------------------------------------------------------------------ paso 3: detalles
def detalles():
    blanco = mat('Laca blanca')
    # zócalos: donde la pared llega al piso (muro este con sus dos puertas, muro norte junto al placard)
    for (a, b) in [((4.94, -9.85), (4.94, -9.4)), ((4.94, -8.6), (4.94, -6.85)), ((4.94, -6.05), (4.94, -5.66))]:
        D.box('Zócalo', a[0] - 0.012, b[1], 0, a[0] + 0.0, a[1], 0.08, blanco, bevel=0.002)
    # planta grande en el rincón de la ventana, libros y florero en las mesas de luz
    D.ph_model('potted_plant_02', 0.45, -9.45, rot=30, height=1.35)
    # z fija: apoyo() mide desde arriba y, junto al velador, toca la pantalla y no la mesa
    D.ph_model('ceramic_vase_03', 1.0, -9.6, rot=0, height=0.18, z=0.6)
    libros()
    # el tapizado del respaldo y de las europeas con la trama de la tela más marcada
    for n in tapizado().node_tree.nodes:
        if n.type == 'NORMAL_MAP':
            n.inputs['Strength'].default_value = 1.6
    print('DETALLES LISTOS')


def hojas_mat():
    """Canto de las hojas: papel crema con las líneas de las páginas en relieve."""
    m = D.pbr('Hojas', color=(0.70, 0.66, 0.56), rough=0.85)
    N, L = m.node_tree.nodes, m.node_tree.links
    tc, wv, bump = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeTexWave'), N.new('ShaderNodeBump')
    wv.wave_type, wv.bands_direction = 'BANDS', 'Z'
    wv.inputs['Scale'].default_value = 900
    wv.inputs['Distortion'].default_value = 3
    bump.inputs['Strength'].default_value = 0.35
    L.new(tc.outputs['Object'], wv.inputs['Vector'])
    L.new(wv.outputs['Fac'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], next(n for n in N if n.type == 'BSDF_PRINCIPLED').inputs['Normal'])
    return m


def libros():
    """Dos libros de tapa dura en la esquina de la mesa de luz cercana que mira a la cámara: tapas y lomo que
    sobresalen 3 mm del bloque de hojas. Las cajas lisas de antes parecían jabones."""
    borrar([c for o in sc().objects if o.parent is None and o.name.startswith('Libro') for c in hijos(o)])
    mesa = min((o for o in sc().objects if o.parent is None and o.name.startswith('nightstand')),
               key=lambda o: (Vector(o.location[:2]) - Vector((3.98, -9.645))).length)
    ms = [c for c in hijos(mesa) if c.type == 'MESH']
    hi = Vector([max(wbox(c)[1][i] for c in ms) for i in range(3)])
    hojas = mat('Hojas') or hojas_mat()
    z, t, e = hi.z, 0.0022, 0.003
    for i, (w, d, h, col, rz) in enumerate([(0.24, 0.17, 0.032, (0.10, 0.11, 0.09), 6),
                                              (0.21, 0.15, 0.026, (0.48, 0.42, 0.33), -3)]):
        g = D.group(f'Libro {i}', hi.x - 0.15, hi.y - 0.12, rz, z)
        tapa = mat(f'Tapa libro {i}') or D.pbr(f'Tapa libro {i}', color=col, rough=0.6)
        for nombre, caja in (('tapa', (-w / 2, -d / 2, h - t, w / 2, d / 2, h)),
                             ('contratapa', (-w / 2, -d / 2, 0, w / 2, d / 2, t)),
                             ('lomo', (-w / 2, -d / 2, 0, -w / 2 + t, d / 2, h))):
            D.box(f'Libro {i} {nombre}', *caja, tapa, bevel=0.0008, seg=2, parent=g)
        D.box(f'Libro {i} hojas', -w / 2 + t, -d / 2 + e, t, w / 2 - e, d / 2 - e, h - t, hojas, parent=g)
        z += h


# ------------------------------------------------------------------ paso 3b: acabados
def listones():
    """Cada listón con su veta y su tono. Con la textura corrida de muro a muro parecían una tabla rayada."""
    m = mat('Madera listones')
    if not m:
        m = mat('Madera miel').copy()
        m.name = 'Madera listones'
        N, L = m.node_tree.nodes, m.node_tree.links
        azar = N.new('ShaderNodeObjectInfo').outputs['Random']
        corre = N.new('ShaderNodeCombineXYZ')  # cada listón toma otro pedazo de la foto de la madera
        for i, k in enumerate((13.7, 5.3, 29.1)):
            x = N.new('ShaderNodeMath')
            x.operation = 'MULTIPLY'
            x.inputs[1].default_value = k
            L.new(azar, x.inputs[0])
            L.new(x.outputs[0], corre.inputs[i])
        L.new(corre.outputs[0], next(n for n in N if n.type == 'MAPPING').inputs['Location'])
        b = next(n for n in N if n.type == 'BSDF_PRINCIPLED')
        antes = b.inputs['Base Color'].links[0].from_socket
        hs = N.new('ShaderNodeHueSaturation')
        rango = N.new('ShaderNodeMapRange')  # ±8 % de valor, como tablas de distintos troncos
        rango.inputs['To Min'].default_value, rango.inputs['To Max'].default_value = 0.92, 1.08
        L.new(azar, rango.inputs['Value'])
        L.new(rango.outputs['Result'], hs.inputs['Value'])
        L.new(antes, hs.inputs['Color'])
        L.new(hs.outputs['Color'], b.inputs['Base Color'])
    # madera aceitada, satinada: con barniz, la luz chica del techo se reflejaba como un punto blanco en el muro
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs['Coat Weight'].default_value = 0.0
    b.inputs['Roughness'].links[0].from_node.inputs[1].default_value = 1.35
    fondo = sc().objects.get('Listones fondo')
    if fondo:
        fb = next(n for n in fondo.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        fb.inputs['Coat Weight'].default_value = 0.0
        if not fb.inputs['Roughness'].links:
            fb.inputs['Roughness'].default_value = 0.8
    random.seed(11)
    for o in sc().objects:
        if o.name.startswith('Listón'):
            o.data.materials[0] = m
            o.location.y = random.uniform(-0.0008, 0.0008)  # ni el carpintero los deja todos al ras


def superficies():
    """Pintura de verdad: albedo ~0,75 (con 0,86 la pared rebota tanta luz que aplana el cuarto), una variación
    de tono de ±3 % a escala de metros y piel de naranja apenas visible."""
    for nombre, color in (('Pared', (0.74, 0.70, 0.63)), ('Techo', (0.78, 0.76, 0.72))):
        m = mat(nombre)
        N, L = m.node_tree.nodes, m.node_tree.links
        b = next(n for n in N if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = (*color, 1)
        if any(n.name == 'Piel de naranja' for n in N):
            continue
        tc = N.new('ShaderNodeTexCoord')
        lento = N.new('ShaderNodeTexNoise')
        lento.inputs['Scale'].default_value = 0.7
        lento.inputs['Detail'].default_value = 2
        L.new(tc.outputs['Object'], lento.inputs['Vector'])
        rango = N.new('ShaderNodeMapRange')
        rango.inputs['From Min'].default_value, rango.inputs['From Max'].default_value = 0.3, 0.7
        rango.inputs['To Min'].default_value, rango.inputs['To Max'].default_value = 0.97, 1.03
        L.new(lento.outputs['Fac'], rango.inputs['Value'])
        mix = N.new('ShaderNodeMix')
        mix.data_type, mix.blend_type = 'RGBA', 'MULTIPLY'
        mix.inputs[0].default_value = 1
        mix.inputs[6].default_value = (*color, 1)
        L.new(rango.outputs['Result'], mix.inputs[7])
        L.new(mix.outputs[2], b.inputs['Base Color'])
        fino = N.new('ShaderNodeTexNoise')
        fino.name = 'Piel de naranja'
        fino.inputs['Scale'].default_value = 420
        fino.inputs['Detail'].default_value = 3
        L.new(tc.outputs['Object'], fino.inputs['Vector'])
        bump = N.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.12
        bump.inputs['Distance'].default_value = 0.0004
        L.new(fino.outputs['Fac'], bump.inputs['Height'])
        if b.inputs['Normal'].links:
            L.new(b.inputs['Normal'].links[0].from_socket, bump.inputs['Normal'])
        L.new(bump.outputs['Normal'], b.inputs['Normal'])


def piso(ancho=0.185, largo=1.9, junta=0.0008):
    """Piso de tablas de 18,5 × 190 cm: cada tabla toma otro pedazo de la foto, ±7 % de tono y ±10 % de rugosidad, con
    una junta oscura de menos de 1 mm y un bisel de 2 mm. La foto sola traía tablas de 9 cm con juntas casi
    invisibles y repartidas a intervalos irregulares: el piso se leía como una sola superficie. Se agranda al doble
    y sus juntas quedan como vetas dentro de cada tabla. Las tablas corren a lo largo de x, hacia las ventanas."""
    m = mat('Piso madera miel')
    N, L = m.node_tree.nodes, m.node_tree.links
    if any(n.name == 'Tablas' for n in N):
        return
    b = next(n for n in N if n.type == 'BSDF_PRINCIPLED')
    mp = next(n for n in N if n.type == 'MAPPING')
    mp.inputs['Scale'].default_value = (1 / 2.4,) * 3

    def op(tipo, a, c=None, rango=None):
        if rango:  # MapRange: a de (desde, hasta) a (en, a)
            n = N.new('ShaderNodeMapRange')
            for k, v in zip(('From Min', 'From Max', 'To Min', 'To Max'), rango):
                n.inputs[k].default_value = v
            L.new(a, n.inputs['Value'])
            return n.outputs['Result']
        n = N.new('ShaderNodeMath')
        n.operation = tipo
        for i, v in enumerate((a, c)):
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            elif v is not None:
                L.new(v, n.inputs[i])
        return n.outputs[0]

    p = N.new('ShaderNodeSeparateXYZ')
    L.new(mp.inputs['Vector'].links[0].from_socket, p.inputs[0])
    fy = op('DIVIDE', p.outputs['Y'], ancho)
    fila = op('FLOOR', fy)
    corrida = N.new('ShaderNodeTexWhiteNoise')  # cada fila arranca en otro lugar
    corrida.noise_dimensions = '1D'
    L.new(fila, corrida.inputs['W'])
    u = op('ADD', op('DIVIDE', p.outputs['X'], largo), corrida.outputs['Value'])
    cid = N.new('ShaderNodeCombineXYZ')
    L.new(fila, cid.inputs[0])
    L.new(op('FLOOR', u), cid.inputs[1])
    azar = N.new('ShaderNodeTexWhiteNoise')
    azar.name = 'Tablas'
    L.new(cid.outputs[0], azar.inputs['Vector'])
    corre = N.new('ShaderNodeVectorMath')  # otro pedazo de la foto
    corre.operation = 'MULTIPLY'
    corre.inputs[1].default_value = (17.3, 9.1, 0.0)
    L.new(azar.outputs['Color'], corre.inputs[0])
    L.new(corre.outputs[0], mp.inputs['Location'])
    rgb = N.new('ShaderNodeSeparateColor')
    L.new(azar.outputs['Color'], rgb.inputs[0])
    # distancia al borde de la tabla, en metros
    dy = op('MULTIPLY', op('MINIMUM', op('FRACT', fy), op('SUBTRACT', 1.0, op('FRACT', fy))), ancho)
    dx = op('MULTIPLY', op('MINIMUM', op('FRACT', u), op('SUBTRACT', 1.0, op('FRACT', u))), largo)
    canto = op('MINIMUM', dx, dy)
    hs = N.new('ShaderNodeHueSaturation')
    L.new(b.inputs['Base Color'].links[0].from_socket, hs.inputs['Color'])
    L.new(op(None, rgb.outputs['Red'], rango=(0, 1, 0.93, 1.07)), hs.inputs['Value'])
    oscuro = N.new('ShaderNodeMix')
    oscuro.data_type, oscuro.blend_type = 'RGBA', 'MULTIPLY'
    oscuro.inputs[7].default_value = (0.45, 0.45, 0.45, 1)
    L.new(op(None, canto, rango=(junta * 0.5, junta, 1, 0)), oscuro.inputs[0])
    L.new(hs.outputs['Color'], oscuro.inputs[6])
    L.new(oscuro.outputs[2], b.inputs['Base Color'])
    rs = b.inputs['Roughness'].links[0].from_socket
    L.new(op('MULTIPLY', rs, op(None, rgb.outputs['Green'], rango=(0, 1, 0.9, 1.1))), b.inputs['Roughness'])
    bump = N.new('ShaderNodeBump')  # bisel de 2 mm en el canto de cada tabla
    bump.inputs['Strength'].default_value = 0.5
    bump.inputs['Distance'].default_value = 0.0008
    L.new(op(None, canto, rango=(0, 0.002, 0, 1)), bump.inputs['Height'])
    if b.inputs['Normal'].links:
        L.new(b.inputs['Normal'].links[0].from_socket, bump.inputs['Normal'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    L.new(bump.outputs['Normal'], b.inputs['Coat Normal'])


def banco():
    """Banco al pie de la cama hecho acá: el de catálogo traía el asiento como una placa marrón lisa."""
    borrar([c for o in raices(('bed_bench', 'Banco')) for c in hijos(o)])
    x0, x1, y0, y1, alto = 1.95, 3.25, -7.52, -7.1, 0.46
    roble = mat('Roble banco') or D.pbr('Roble banco', D.tx('white_oak_veneer', 'oak_slats'), size=0.8,
                                        tint=(*D.LENGA, 1.9), rough=0.5, nstr=0.5)
    pata, g = 0.045, 0.004
    for (a, b) in ((x0, y0), (x1 - pata, y0), (x0, y1 - pata), (x1 - pata, y1 - pata)):
        D.box('Banco pata', a, b, 0, a + pata, b + pata, alto - 0.13, roble, bevel=g)  # termina bajo la tabla
    for (ya, yb) in ((y0, y0 + 0.02), (y1 - 0.02, y1)):
        D.box('Banco larguero', x0 + pata, ya, alto - 0.19, x1 - pata, yb, alto - 0.13, roble, bevel=g)
    D.box('Banco tabla', x0, y0, alto - 0.13, x1, y1, alto - 0.11, roble, bevel=g)
    # asiento de cuero, el del almohadón: una lana lisa en primer plano se leía como una placa gris de fieltro
    cuero = mat('Cuero almohadón') or D.pbr('Cuero almohadón', D.tx('leather_cognac', 'leather_cognac'),
                                             size=0.6, rough=0.45)
    # el relieve de la foto a fuerza 1 arrugaba el asiento como papel; un cuero de tapicería es casi liso
    next(n for n in cuero.node_tree.nodes if n.type == 'NORMAL_MAP').inputs['Strength'].default_value = 0.35
    # chato, bordes redondeados y una comba de 2 cm al centro (la almohada inflada parecía eso)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    asiento = bpy.context.object
    asiento.name = 'Banco asiento'
    w, d, t = x1 - x0, y1 - y0, 0.08
    asiento.data.transform(Matrix.Diagonal((w, d, t, 1)))
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=12)
    bpy.ops.object.mode_set(mode='OBJECT')
    for v in asiento.data.vertices:
        if v.co.z > 0:
            v.co.z += 0.02 * (1 - (2 * v.co.x / w) ** 2) * (1 - (2 * v.co.y / d) ** 2)
    bv = asiento.modifiers.new('borde', 'BEVEL')
    bv.width, bv.segments, bv.limit_method = 0.03, 5, 'ANGLE'
    asiento.modifiers.new('suave', 'SUBSURF').levels = 1
    bpy.ops.object.shade_smooth()
    asiento.data.materials.append(cuero)
    poner(asiento, (x0 + x1) / 2, (y0 + y1) / 2, alto - 0.11 + t / 2)
    print('BANCO LISTO')


def alfombra():
    """Alfombra de lana tejida en canasta (trama de 45 cm, bloques de ~2 cm) con un ribete de algodón de 3 cm y el
    tono que varía un poco. La bereber lisa se leía como una placa gris; la medida y el canto están en D.rug()."""
    m = mat('Alfombra de lana')
    N, L = m.node_tree.nodes, m.node_tree.links
    next(n for n in N if n.type == 'MAPPING').inputs['Scale'].default_value = (1 / 0.45,) * 3
    next(n for n in N if n.type == 'NORMAL_MAP').inputs['Strength'].default_value = 1.6
    ajustar_albedo(m, (0.60, 0.56, 0.48))
    if any(n.name == 'Manchado' for n in N):
        return
    b = next(n for n in N if n.type == 'BSDF_PRINCIPLED')
    # ribete: a menos de 3 cm del canto (media medida en la propiedad 'medio' de cada alfombra)
    tc, medio = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeAttribute')
    medio.attribute_type, medio.attribute_name = 'OBJECT', 'medio'
    p, h = N.new('ShaderNodeSeparateXYZ'), N.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Object'], p.inputs[0])
    L.new(medio.outputs['Vector'], h.inputs[0])
    lados = []
    for eje in 'XY':
        ab = N.new('ShaderNodeMath')
        ab.operation = 'ABSOLUTE'
        L.new(p.outputs[eje], ab.inputs[0])
        resta = N.new('ShaderNodeMath')
        resta.operation = 'SUBTRACT'
        L.new(h.outputs[eje], resta.inputs[0])
        L.new(ab.outputs[0], resta.inputs[1])
        lados.append(resta.outputs[0])
    canto = N.new('ShaderNodeMath')
    canto.operation = 'MINIMUM'
    L.new(lados[0], canto.inputs[0])
    L.new(lados[1], canto.inputs[1])
    borde = N.new('ShaderNodeMapRange')
    borde.inputs['From Min'].default_value, borde.inputs['From Max'].default_value = 0.029, 0.031
    borde.inputs['To Min'].default_value, borde.inputs['To Max'].default_value = 1.0, 0.0
    L.new(canto.outputs[0], borde.inputs['Value'])
    rib = N.new('ShaderNodeMix')
    rib.data_type = 'RGBA'
    rib.inputs[7].default_value = (0.42, 0.38, 0.31, 1)  # algodón crudo, más oscuro que la lana
    L.new(borde.outputs['Result'], rib.inputs[0])
    L.new(b.inputs['Base Color'].links[0].from_socket, rib.inputs[6])
    L.new(rib.outputs[2], b.inputs['Base Color'])
    b = next(n for n in N if n.type == 'BSDF_PRINCIPLED')
    antes = b.inputs['Base Color'].links[0].from_socket
    tc, rz = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeTexNoise')
    rz.name = 'Manchado'
    rz.inputs['Scale'].default_value = 1.2
    L.new(tc.outputs['Object'], rz.inputs['Vector'])
    rango = N.new('ShaderNodeMapRange')
    rango.inputs['From Min'].default_value, rango.inputs['From Max'].default_value = 0.3, 0.7
    rango.inputs['To Min'].default_value, rango.inputs['To Max'].default_value = 0.95, 1.05
    L.new(rz.outputs['Fac'], rango.inputs['Value'])
    mix = N.new('ShaderNodeMix')
    mix.data_type, mix.blend_type = 'RGBA', 'MULTIPLY'
    mix.inputs[0].default_value = 1
    L.new(antes, mix.inputs[6])
    L.new(rango.outputs['Result'], mix.inputs[7])
    L.new(mix.outputs[2], b.inputs['Base Color'])


def lino_cortina():
    """Lino semitransparente: la trama del lino, luz que pasa (translúcido, del color de la tela) y 22 % de
    transparencia. El ruedo y el cabezal son de tela doble: dejan pasar menos y a contraluz se leen como bandas."""
    m = mat('Cortina lino')
    if m:
        return m
    m = tela_mat('Cortina lino', (0.78, 0.75, 0.69), size=0.25, sheen=0.3, rough=0.9)
    N, L = m.node_tree.nodes, m.node_tree.links
    b = next(n for n in N if n.type == 'BSDF_PRINCIPLED')
    out = next(n for n in N if n.type == 'OUTPUT_MATERIAL')
    tl = N.new('ShaderNodeBsdfTranslucent')
    L.new(b.inputs['Base Color'].links[0].from_socket, tl.inputs['Color'])
    m1 = N.new('ShaderNodeMixShader')
    m1.inputs[0].default_value = 0.45
    L.new(b.outputs[0], m1.inputs[1])
    L.new(tl.outputs[0], m1.inputs[2])
    z = N.new('ShaderNodeSeparateXYZ')
    L.new(N.new('ShaderNodeNewGeometry').outputs['Position'], z.inputs[0])
    bandas = []
    for desde, hasta, en, a in ((0.10, 0.11, 1, 0), (D.H - 0.14, D.H - 0.13, 0, 1)):  # ruedo y cabezal
        r = N.new('ShaderNodeMapRange')
        for k, v in zip(('From Min', 'From Max', 'To Min', 'To Max'), (desde, hasta, en, a)):
            r.inputs[k].default_value = v
        L.new(z.outputs['Z'], r.inputs['Value'])
        bandas.append(r.outputs['Result'])
    doble = N.new('ShaderNodeMath')
    doble.operation = 'MAXIMUM'
    L.new(bandas[0], doble.inputs[0])
    L.new(bandas[1], doble.inputs[1])
    paso = N.new('ShaderNodeMapRange')
    paso.inputs['To Min'].default_value, paso.inputs['To Max'].default_value = 0.22, 0.06
    L.new(doble.outputs[0], paso.inputs['Value'])
    m2 = N.new('ShaderNodeMixShader')
    L.new(paso.outputs['Result'], m2.inputs[0])
    L.new(m1.outputs[0], m2.inputs[1])
    L.new(N.new('ShaderNodeBsdfTransparent').outputs[0], m2.inputs[2])
    L.new(m2.outputs[0], out.inputs[0])
    return m


def cortina(nombre, a, b, m, onda=0.09, hondo=0.10, paso=0.012, filas=54):
    """Paño de lino que cuelga de un riel de techo en ondas de `onda` m y `hondo` m de fondo, con el ruedo a 1,5 cm
    del piso. Las columnas van a paso parejo sobre la tela (no sobre el riel). Hacia abajo los pliegues se abren un
    poco, cada uno con su fondo, y la onda deriva apenas: con la onda perfecta de arriba abajo se leía como una chapa.
    ponytail: sin simular; una cortina con peso cuelga recta, la variación de los pliegues va armada."""
    a, b = Vector(a), Vector(b)
    largo = (b - a).length
    d = (b - a) / largo
    nrm = Vector((-d.y, d.x))
    lam = largo / max(3, round(largo / onda))
    A = hondo / 2
    ts = np.linspace(0, largo, 3000)
    s = np.concatenate([[0], np.cumsum(np.hypot(np.diff(ts), np.diff(A * np.sin(2 * np.pi * ts / lam))))])
    nc = int(s[-1] / paso)
    tj = np.interp(np.linspace(0, s[-1], nc + 1), s, ts)
    z1, z0 = D.H - 0.035, 0.015
    random.seed(sum(map(ord, nombre)))
    ph = [random.uniform(0, 2 * math.pi) for _ in range(3)]
    vs = []
    for i in range(filas + 1):
        u = i / filas  # 0 arriba, 1 en el ruedo
        for t in tj:
            fondo = 1 + u * (0.15 + 0.12 * math.sin(2 * math.pi * t / (2.7 * lam) + ph[0])
                             + 0.08 * math.sin(2 * math.pi * t / (1.3 * lam) + ph[1]))
            tt = t + u * 0.12 * lam * math.sin(2 * math.pi * t / (3.4 * lam) + ph[2])
            q = a + d * t + nrm * (A * math.sin(2 * math.pi * tt / lam) * fondo)
            vs.append((q.x, q.y, z1 - u * (z1 - z0)))
    w = nc + 1
    caras = [(i * w + j, i * w + j + 1, (i + 1) * w + j + 1, (i + 1) * w + j) for i in range(filas) for j in range(nc)]
    # una sola cara, sin espesor: tiene que mirar al cuarto, porque el visor del recorrido descarta las caras de atrás
    # y el horneado ilumina cada cara de su lado. Así armadas miran a nrm; si el centro del departamento queda del otro
    # lado, se dan vuelta (ponytail: vale para cortinas en ventanas del perímetro)
    techo = sc().objects['Techo']
    centro = sum((techo.matrix_world @ Vector(c) for c in techo.bound_box), Vector()) / 8
    if (centro.xy - a).dot(nrm) < 0:
        caras = [c[::-1] for c in caras]
    me = bpy.data.meshes.new(nombre)
    me.from_pydata(vs, [], caras)
    me.shade_smooth()
    D._obj(nombre, me, m)
    # riel de techo, laqueado como el cielorraso
    lo, hi = a - d * 0.03, b + d * 0.03
    x0, x1 = sorted((lo.x, hi.x))
    y0, y1 = sorted((lo.y, hi.y))
    D.box(f'{nombre} riel', x0 - abs(nrm.x) * 0.012, y0 - abs(nrm.y) * 0.012, D.H - 0.016,
          x1 + abs(nrm.x) * 0.012, y1 + abs(nrm.y) * 0.012, D.H, mat('Laca blanca'), bevel=0.002)


def cortinas():
    """Rehace las cortinas del armado crudo (D.curtain: una onda rígida de dos filas de vértices) con lino_cortina()
    y cortina(), sobre la misma línea: el primer y el último vértice de la fila de abajo están en sus extremos."""
    m = lino_cortina()
    for o in [o for o in sc().objects if o.name.startswith('Cortina') and 'Espesor' in o.modifiers]:
        vs, w = o.data.vertices, len(o.data.vertices) // 2
        a, b = (o.matrix_world @ vs[0].co).xy, (o.matrix_world @ vs[w - 1].co).xy
        nombre = o.name
        bpy.data.objects.remove(o)
        cortina(nombre, a, b, m)
    print('CORTINAS LISTAS')


CAJA2 = ((9.0, -10.0), (13.0, -5.6))  # segunda suite
LIVING = ((0.0, -5.6), (7.6, 0.0))


def suite2():
    """La segunda suite con el mismo método. La cama de catálogo traía la ropa de cama fundida en un bloque: cama
    hecha acá (cabecera de tablas de madera sobre la pared verde), acolchado, almohadas y frazada simulados."""
    borrar([c for o in raices(('bed_king', 'Almohada', 'Pie de cama', 'cushions'), CAJA2) for c in hijos(o)])
    cx, ancho, pared = 11.27, 1.95, -9.869
    fondo, pie, z = pared + 0.09, pared + 0.09 + 2.1, 0.58
    madera = mat('Madera miel')
    for i in range(5):  # cabecera de cinco tablas horizontales, con su junta
        z0 = 0.30 + i * 0.172
        D.box('Cabecera', cx - ancho / 2 - 0.05, pared + 0.005, z0, cx + ancho / 2 + 0.05, fondo, z0 + 0.166, madera,
              bevel=0.003)
    base_ = D.box('Base cama 2', cx - ancho / 2, fondo, 0.08, cx + ancho / 2, pie, 0.34, madera, bevel=0.006)
    D.box('Base cama 2 sombra', cx - ancho / 2 + 0.06, fondo + 0.06, 0, cx + ancho / 2 - 0.06, pie - 0.06, 0.08,
          mat('Junta'))
    colchon = D.box('Colchón 2', cx - ancho / 2 + 0.03, fondo + 0.01, 0.34, cx + ancho / 2 - 0.03, pie - 0.025, z,
                    mat('Sábana'), bevel=0.07, seg=8)
    for o in (base_, colchon):
        con_choque(o)
    acolchado(cx, fondo, pie, ancho, z, sufijo=' 2')
    ropa(cx, fondo, pie, ancho, z, sufijo=' 2', caja=CAJA2, respaldo='Cabecera', lumbar='Manta a cuadros')
    veladores(CAJA2)
    print('SUITE 2 LISTA')


BANO = ((5.0, -8.0), (7.4, -5.6))  # baño en suite


def granito():
    """Piedra negra de una sola pieza (mesada, isla, banco del hogar): la foto de granito traía juntas de baldosa
    y la isla se veía partida. Ruido fino para el moteado, rugosidad que varía y una capa de pulido."""
    m = mat('Granito negro')
    N, L = m.node_tree.nodes, m.node_tree.links
    N.clear()
    b = N.new('ShaderNodeBsdfPrincipled')
    L.new(b.outputs[0], N.new('ShaderNodeOutputMaterial').inputs[0])
    tc = N.new('ShaderNodeTexCoord')
    mota = N.new('ShaderNodeTexNoise')
    mota.inputs['Scale'].default_value = 220
    mota.inputs['Detail'].default_value = 6
    L.new(tc.outputs['Object'], mota.inputs['Vector'])
    rampa = N.new('ShaderNodeValToRGB')
    rampa.color_ramp.elements[0].position, rampa.color_ramp.elements[0].color = 0.5, (0.012, 0.012, 0.013, 1)
    rampa.color_ramp.elements[1].position, rampa.color_ramp.elements[1].color = 0.62, (0.07, 0.068, 0.064, 1)
    L.new(mota.outputs['Fac'], rampa.inputs['Fac'])
    L.new(rampa.outputs['Color'], b.inputs['Base Color'])
    lento = N.new('ShaderNodeTexNoise')
    lento.inputs['Scale'].default_value = 3
    L.new(tc.outputs['Object'], lento.inputs['Vector'])
    rango = N.new('ShaderNodeMapRange')
    rango.inputs['To Min'].default_value, rango.inputs['To Max'].default_value = 0.22, 0.38
    L.new(lento.outputs['Fac'], rango.inputs['Value'])
    L.new(rango.outputs['Result'], b.inputs['Roughness'])
    b.inputs['Coat Weight'].default_value = 0.3
    b.inputs['Coat Roughness'].default_value = 0.08


def bacha(x, y, z, r=0.2, h=0.14):
    """Bacha de apoyo de cerámica, hueca: el cilindro blanco liso de antes parecía de plástico."""
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=r * 0.9, radius2=r, depth=h)
    arriba = max(bm.faces, key=lambda f: f.calc_center_median().z)
    bmesh.ops.inset_individual(bm, faces=[arriba], thickness=0.012)
    for v in arriba.verts:  # el fondo se cierra al 85 %: si no, la pared de adentro asoma por fuera de la de afuera
        v.co.z -= h - 0.02
        v.co.x *= 0.85
        v.co.y *= 0.85
    for v in bm.verts:
        v.co += Vector((x, y, z + h / 2))
    me = bpy.data.meshes.new('Bacha')
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new('Bacha', me)
    sc().collection.objects.link(o)
    bv = o.modifiers.new('borde', 'BEVEL')
    bv.width, bv.segments, bv.limit_method = 0.004, 3, 'ANGLE'
    for p in me.polygons:
        p.use_smooth = True
    o.data.materials.append(mat('Cerámica') or D.pbr('Cerámica', color=(0.80, 0.80, 0.78), rough=0.12, coat=0.6))
    return o


def toalla():
    """Toalla de rizo colgando del toallero, simulada: la de antes era una caja. Queda fija solo la fila de arriba,
    la que apoya sobre la barra."""
    borrar([c for o in raices('Toalla', BANO) for c in hijos(o)])
    rizo = mat('Toalla rizo') or D.pbr('Toalla rizo', D.tx('terry_towel', 'rough_linen'), size=0.25,
                                       tint=(0.8, 0.78, 0.74, 1.9), sheen=0.6, rough=0.95, nstr=1.5)
    ajustar_albedo(rizo, (0.78, 0.76, 0.72))
    x0, x1, y, z0, z1 = 5.27, 5.68, -5.765, 0.76, 1.235
    t = plano('Toalla', x0, x1, z0, z1, 0, 40, 46, amp=0.0)
    for v in t.data.vertices:  # el plano nace horizontal: se para en x-z, delante de la barra
        v.co.y, v.co.z = y + 0.004 * math.sin(v.co.x * 41) * math.sin(v.co.y * 23), v.co.y
    g = t.vertex_groups.new(name='pin')
    g.add([v.index for v in t.data.vertices if v.co.z > z1 - 0.012], 1.0, 'REPLACE')
    simular(t, 30, calidad=8, encoge=0.03, pin=True)
    terminar(t, rizo, grosor=0.006)


def nicho():
    """Nicho de la ducha con fondo, piso y costados de la misma piedra y una luz chica arriba: era un rectángulo
    negro plano. El tabique tiene el hueco desde depto.build()."""
    borrar([c for o in raices('Nicho', BANO) for c in hijos(o)])
    cal = mat('Caliza baño')
    x0, x1, y0, y1, z0, z1 = 7.333, 7.395, -6.6, -6.0, 1.1, 1.4
    D.box('Nicho fondo', x1, y0 - 0.01, z0 - 0.01, x1 + 0.012, y1 + 0.01, z1 + 0.01, cal)
    for (a, b_, c, d) in ((y0, y1, z0 - 0.012, z0), (y0, y1, z1, z1 + 0.012)):
        D.box('Nicho piso', x0, a, c, x1, b_, d, cal)
    for (a, b_) in ((y0 - 0.012, y0), (y1, y1 + 0.012)):
        D.box('Nicho lado', x0, a, z0, x1, b_, z1, cal)
    luz = mat('Nicho luz') or D.emit_mat('Nicho luz', color=(1.0, 0.86, 0.68), strength=0.6)  # tenue: con 2,5 el nicho era una caja de luz
    D.box('Nicho luz', x0 + 0.004, y0 + 0.01, z1 - 0.008, x1 - 0.01, y1 - 0.01, z1 - 0.002, luz)
    # del lado del baño 2 el hueco del tabique se tapa con la pared (por la puerta de la segunda suite se veía)
    D.box('Nicho tapa', 7.452, y0 - 0.02, z0 - 0.02, 7.462, y1 + 0.02, z1 + 0.02, mat('Pared'))
    for (yy, h, r) in ((-6.42, 0.19, 0.028), (-6.33, 0.15, 0.025)):
        D.cyl('Nicho frasco', 7.37, yy, z0, z0 + h, r, mat('Cerámica'), bevel=0.004)


def mata(asset, parte, x, y, z, alto, rot=0.0):
    """Una sola mata de un modelo de Poly Haven. Los de plantas traen todas las variantes y sus niveles de detalle
    en fila, más un objeto de geometry nodes que se renderiza como una bola: con ph_model() quedaban bolas
    verdes flotando en el balcón. Se carga solo el objeto f'{asset}_{parte}' y se apoya con su base en (x, y, z)."""
    path = D.ASSETS / 'models' / asset / f'{asset}.blend'
    imgs = set(bpy.data.images)
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n == f'{asset}_{parte}']
    for im in set(bpy.data.images) - imgs:
        cand = list((path.parent).rglob(pathlib.Path(im.filepath.replace('//', '')).name))
        if cand:
            im.filepath = str(cand[0])
            im.reload()
    o = dst.objects[0]
    sc().collection.objects.link(o)
    o.parent = None
    o.location, o.rotation_euler, o.scale = (0, 0, 0), (0, 0, math.radians(rot)), (1, 1, 1)
    bpy.context.view_layer.update()
    lo, hi = wbox(o)
    k = alto / (hi.z - lo.z)
    o.scale = (k, k, k)
    bpy.context.view_layer.update()
    lo, hi = wbox(o)
    o.location = (x - (lo.x + hi.x) / 2, y - (lo.y + hi.y) / 2, z - lo.z)
    return o


def jardineras():
    """Las jardineras del balcón tenían el fondo negro a la vista: tierra, pasto y un arbusto (Poly Haven, CC0)."""
    tierra = mat('Tierra') or D.pbr('Tierra', color=(0.05, 0.038, 0.026), rough=0.95)
    for o in [o for o in sc().objects if o.parent is None and o.name.startswith('planter_box_01')]:
        ms = [c for c in hijos(o) if c.type == 'MESH']
        lo = Vector([min(wbox(c)[0][i] for c in ms) for i in range(3)])
        hi = Vector([max(wbox(c)[1][i] for c in ms) for i in range(3)])
        D.box('Tierra', lo.x + 0.03, lo.y + 0.03, hi.z - 0.14, hi.x - 0.03, hi.y - 0.03, hi.z - 0.05, tierra)
        cy, w, z = (lo.y + hi.y) / 2, hi.x - lo.x, hi.z - 0.06
        for (t, asset, parte, alto) in ((0.22, 'grass_medium_01', 'large_a_LOD0', 0.38),
                                        (0.5, 'shrub_04', 'c_LOD0', 0.42),
                                        (0.78, 'grass_medium_01', 'large_c_LOD0', 0.34)):
            mata(asset, parte, lo.x + t * w, cy + random.uniform(-0.03, 0.03), z, alto, rot=random.uniform(0, 360))


def aparador_living():
    """La pared grande entre la suite y la cocina estaba vacía: aparador bajo, cerámicas y una foto enmarcada."""
    D.credenza(6.25, -5.31, rot=0, w=2.1, d=0.42, h=0.62)
    D.ph_model('ceramic_vase_01', 5.6, -5.3, height=0.34, z=0.62)
    D.ph_model('ceramic_vase_02', 5.85, -5.28, height=0.22, z=0.62)
    D.ph_model('decorative_book_set_01', 6.85, -5.3, rot=8, height=0.08, z=0.62)
    foto = D.ROOT / 'img' / 'originales' / 'vista-lago.jpg'
    if foto.exists():
        D.box('Marco living', 5.45, -5.54, 1.05, 7.05, -5.5, 2.05, mat('Madera tostada'), bevel=0.004)
        o = D.box('Cuadro living', 5.5, -5.501, 1.1, 7.0, -5.497, 2.0, D.photo_mat('Foto living', foto))
        uv = o.data.uv_layers.new()
        for poly in o.data.polygons:  # un recorte vertical de la foto: la cordillera de la izquierda
            for li in poly.loop_indices:
                co = o.data.vertices[o.data.loops[li].vertex_index].co
                uv.data[li].uv = (0.05 + 0.33 * (co.x - 5.5) / 1.5, 0.3 + 0.55 * (co.z - 1.1) / 0.9)


def arreglos():
    """Los defectos de la revisión del departamento (interiorismo/revision-hiperrealismo.md), por número."""
    # 2 el fuego del hogar: tres planos con llamas de ruido. Quemado a blanco parecía dibujado, y anaranjado y
    # suave, de cerca, también. No aguanta la mirada: hogar apagado, como en cualquier foto de día
    # (se borran, no se ocultan: el horneado del recorrido toma todas las mallas, visibles o no)
    borrar([o for o in sc().objects if o.name.startswith('Llama')])
    for o in sc().objects:
        if o.name.startswith('Hogar luz'):
            o.data.energy = 0.0
    # 3 colgantes de la cocina: el disco de abajo usaba el LED de los spots (12) y se veía quemado
    dif = mat('Difusor') or D.emit_mat('Difusor', color=(1.0, 0.86, 0.68), strength=1.2)
    for o in sc().objects:
        if o.name.startswith('Colgante difusor'):
            o.data.materials[0] = dif
    # 3 mesada, isla y banco del hogar de una sola pieza
    granito()
    # 1 la pared vacía del living
    aparador_living()
    # 5 jardineras con tierra y plantas
    random.seed(3)
    jardineras()
    # 10 el baño 2 sin luz se veía como un cuarto negro por la puerta de la segunda suite
    D.downlight(8.2, -7.2, 6)
    # 11 la piedra del baño, pulida, reflejaba el espejo y su tira de luz como una raya blanca: piedra apomazada
    for nombre, ganancia in (('Caliza baño', 1.0), ('Piedra baño', 0.85)):
        m = mat(nombre)
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Coat Weight'].default_value = 0.0
        if b.inputs['Roughness'].links:
            b.inputs['Roughness'].links[0].from_node.inputs[1].default_value = ganancia
    # 12 baño: bachas de cerámica, toalla colgada, nicho con fondo
    yb = -8.0 + 0.06
    borrar([c for o in raices('Bacha', BANO) for c in hijos(o)])
    for xx in (5.75, 6.75):
        bacha(xx, yb + 0.27, 0.86)
    toalla()
    nicho()
    # el banco de la ducha era una caja de roble: el modelo no daba para más. Taburete plegable de listones (Poly
    # Haven, CC0), el que se usa en una ducha porque escurre
    borrar([c for o in raices('Banco ducha', BANO) for c in hijos(o)])
    D.ph_model('folding_wooden_stool', 6.95, -5.97, rot=7, z=0.02)
    # auditoría del 19-nov-2026 (tools/render/auditoria.py)
    # barniz satinado: con la rugosidad de Blender (0,03) la capa es un espejo y el piso devolvía la tira LED de la
    # cocina como una raya blanca y cada spot como un punto
    for n in ('Piso madera miel', 'Madera miel'):
        next(x for x in mat(n).node_tree.nodes if x.type == 'BSDF_PRINCIPLED').inputs['Coat Roughness'].default_value = 0.3
    # los veladores del dormitorio 2 quedaban a 1,4 cm de la mesa de luz y el jarrón del comedor a 7,7 cm de la mesa
    for o in [o for o in sc().objects if o.parent is None and o.name.startswith(APOYADOS)]:
        apoyar(o)
    print('ARREGLOS LISTOS')


APOYADOS = ('table_lamp', 'decor', 'ceramic_vase', 'wooden_bowl', 'decorative_book_set', 'standing_picture_frame')


def apoyar(o, tope=0.1):
    """Baja un objeto con sus hijos hasta lo que tiene abajo, si queda en el aire (hasta `tope`). Se mide con rayos
    hacia abajo en el centro y en cuatro puntos de la huella. Los rayos arrancan 2 cm por encima de la base y saltean
    el objeto: desde abajo de la base, lo que apoya justo al ras arranca adentro del mueble y se hundía."""
    bpy.context.view_layer.update()
    ms = [c for c in hijos(o) if c.type == 'MESH']
    pts = [c.matrix_world @ Vector(v) for c in ms for v in c.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    dg = bpy.context.evaluated_depsgraph_get()
    gap = tope
    mios = {c.name for c in ms}
    for a, b in ((0.5, 0.5), (0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7)):
        org = Vector((lo.x + (hi.x - lo.x) * a, lo.y + (hi.y - lo.y) * b, lo.z + 0.02))
        for _ in range(12):
            ok, loc, _n, _i, ob, _m = sc().ray_cast(dg, org, Vector((0, 0, -1)))
            if not ok:
                break
            if ob.name in mios:
                org = loc - Vector((0, 0, 1e-4))
                continue
            gap = min(gap, lo.z - loc.z)
            break
    if 0.001 < gap < tope:
        o.location.z -= gap
        print(f'APOYADO {o.name}: bajó {gap * 100:.1f} cm')


def departamento():
    """El método aplicado al departamento entero; lo llama depto.build(). La suite trabajada, luz de día con sol
    suave, albedos y pintura reales, la segunda suite vestida y los arreglos de cada ambiente
    (interiorismo/revision-hiperrealismo.md). Los 360° y el recorrido horneado salen de acá."""
    cama()
    detalles()
    acabados()
    cortinas()
    luz()
    suite2()
    veladores(LIVING)
    arreglos()
    # los cordones son curvas: a malla, que es lo único que toma el horneado del recorrido
    curvas = [o for o in sc().objects if o.type == 'CURVE' and o.name.startswith('Vivo')]
    if curvas:
        bpy.ops.object.select_all(action='DESELECT')
        for o in curvas:
            o.select_set(True)
        bpy.context.view_layer.objects.active = curvas[0]
        bpy.ops.object.convert(target='MESH')
    print('DEPARTAMENTO LISTO')


def acabados():
    for nombre, c in BLANCOS.items():
        ajustar_albedo(mat(nombre), c)
    tapizado()
    listones()
    superficies()
    piso()
    alfombra()
    banco()
    print('ACABADOS LISTOS')


# ------------------------------------------------------------------ paso 4: cámara de fotógrafo
def camara():
    co = bpy.data.objects.get('Cam suite') or D.camera(False, 72)  # ~25 mm: lo que usan los fotógrafos de dormitorios
    co.name = 'Cam suite'
    co.location = (4.5, -6.4, CAM_Z)  # a ~45 cm sobre la cama, no a la altura de los ojos
    co.rotation_euler = (math.radians(90), 0, math.radians(145))  # nivelada: las verticales quedan verticales
    co.data.shift_y = -0.08
    co.data.dof.use_dof = True
    co.data.dof.aperture_fstop = 8  # en interiores casi todo en foco
    co.data.dof.focus_distance = (Vector((CAMA_X, -8.4, 0.7)) - Vector(co.location)).length
    sc().camera = co
    r = sc().render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1800, 1350, 100
    print('CAMARA LISTA')


# ------------------------------------------------------------------ paso 5: revelado de cámara
def revelado():
    s = sc()
    s.use_nodes = True
    T = s.node_tree
    T.nodes.clear()
    rl = T.nodes.new('CompositorNodeRLayers')
    gl = T.nodes.new('CompositorNodeGlare')  # halo suave en lámparas y ventana, como un lente real
    gl.glare_type = 'FOG_GLOW'
    gl.quality = 'HIGH'
    gl.threshold = 1.2
    gl.size = 7
    gl.mix = -0.75
    ld = T.nodes.new('CompositorNodeLensdist')  # dispersión mínima en los bordes
    ld.inputs['Dispersion'].default_value = 0.006
    ld.use_fit = True
    comp = T.nodes.new('CompositorNodeComposite')
    T.links.new(rl.outputs['Image'], gl.inputs['Image'])
    T.links.new(gl.outputs['Image'], ld.inputs['Image'])
    T.links.new(ld.outputs['Image'], comp.inputs['Image'])
    print('REVELADO LISTO')


def render(nombre='suite', samples=512, pct=100):
    """pct < 100: prueba rápida de luz y encuadre antes del render largo."""
    s = sc()
    s.cycles.samples = samples
    s.render.resolution_percentage = pct
    s.render.filepath = str(OUT / f'{nombre}.png')
    bpy.ops.render.render(write_still=True)
    print('RENDER', s.render.filepath)


if __name__ == '__main__':
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if 'base' in args:
        base()
    if 'todo' in args:
        if not bpy.data.filepath:
            bpy.ops.wm.open_mainfile(filepath=str(OUT / 'base.blend'))
        for paso in (cama, luz, detalles, acabados, camara, revelado):
            paso()
        bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'suite.blend'))
    if 'render' in args:
        render()
