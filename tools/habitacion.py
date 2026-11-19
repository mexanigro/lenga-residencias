"""Un ambiente solo, trabajado para fotorrealismo (la suite principal de Lenga).

Arma el departamento con tools/depto.py, se queda con la suite y la rehace con calidad de render fijo:
cama armada con tela simulada, cielo HDRI nublado, veladores que brillan, objetos y revelado de cámara.

Fondo (sin ventana):
  blender -b --factory-startup -P tools/habitacion.py -- base            escena recortada -> 3d/out/suite/base.blend
  blender -b -P tools/habitacion.py -- todo render                         todos los pasos y un render de control
Con ventana (BlenderMCP): abrir base.blend y llamar a los pasos de a uno: cama(), luz(), detalles(), camara(), revelado().
"""
import math
import pathlib
import random
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import depto as D  # noqa: E402

OUT = D.OUT / 'suite'
HDRI = D.ASSETS / 'hdri' / 'overcast_soil_puresky_4k.hdr'  # Poly Haven, CC0
# la suite: x 0..5 (ventana al oeste), y -10..-5.6 (listones al sur); se deja un margen para muros y losas
CAJA = ((-0.6, -10.6), (5.4, -5.25))
CAMA_X, PARED_Y = 2.6, -9.853  # eje de la cama y frente de los listones


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


def tapizado():
    """Lana cruda del respaldo y las europeas. Se crea si falta: el recorte de la escena purga lo que nadie usa."""
    return mat('Lana cruda') or D.pbr('Lana cruda', D.tx('wool_cream', 'poly_wool_herringbone'), size=0.32,
                                      tint=(*D.LANA, 1.9), sheen=0.4, nstr=1.6)


# ------------------------------------------------------------------ paso 0: escena recortada
def base():
    D.build()
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
    m = D.pbr(nombre, tex, size=size, sheen=sheen, nstr=0.6)
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    # el color del lino viene de la foto; se multiplica por el tono buscado para no quemar los blancos
    mix = m.node_tree.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs[0].default_value = 1.0
    mix.inputs[7].default_value = (*color, 1)
    link = next((l for l in m.node_tree.links if l.to_socket == b.inputs['Base Color']), None)
    if link:
        m.node_tree.links.new(link.from_socket, mix.inputs[6])
        m.node_tree.links.remove(link)
    else:
        mix.inputs[6].default_value = (1, 1, 1, 1)
    m.node_tree.links.new(mix.outputs[2], b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = rough
    return m


def simular(o, frames, gravedad=1.0, presion=0.0, calidad=8, rigidez=10, flexion=0.3, encoge=0.0, propia=True, pin=False):
    cl = o.modifiers.new('tela', 'CLOTH')
    s = cl.settings
    s.quality = calidad
    s.mass = 0.3
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


def almohada(nombre, ancho, alto, grueso, material, presion=2.0):
    """Almohada inflada: un cubo subdividido con presión, sin gravedad. Las costuras quedan pellizcadas."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    o = bpy.context.object
    o.name = nombre
    o.scale = (ancho, alto, grueso)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=18)
    bpy.ops.object.mode_set(mode='OBJECT')
    simular(o, 14, gravedad=0.0, presion=presion, calidad=6, rigidez=15, flexion=0.05, encoge=0.03, propia=False)
    lo, hi = wbox(o)
    o.data.transform(Matrix.Translation(-(lo + hi) / 2))  # centrada en su origen, para poder ubicarla
    o.location = (0, 0, 0)
    o.modifiers.new('suave', 'SUBSURF').levels = 1
    bpy.ops.object.shade_smooth()
    o.data.materials.append(material)
    return o


def poner(o, x, y, z, rx=0.0, rz=0.0):
    o.location = (x, y, z)
    o.rotation_euler = (math.radians(rx), 0, math.radians(rz))


def cama():
    # fuera la cama de catálogo (una sola malla con la ropa de cama fundida), la manta-caja y los almohadones
    viejos = [o for o in sc().objects if o.parent is None and (o.name.startswith(('bed_king', 'cushions', 'Manta cama'))
                                                                or o.name.startswith('Manta tela'))]
    borrar([c for o in viejos for c in hijos(o)])
    x0, x1 = CAMA_X - 1.0, CAMA_X + 1.0
    fondo, pie = PARED_Y + 0.11, PARED_Y + 0.11 + 2.12
    tapiz = tapizado()
    n = 9  # respaldo tapizado en canales verticales
    paso = (x1 - x0 + 0.08) / n
    for i in range(n):
        a = x0 - 0.04 + i * paso
        D.box('Respaldo', a + 0.002, PARED_Y + 0.01, 0.05, a + paso - 0.002, fondo, 1.3, tapiz, bevel=0.05, seg=8)
    base_ = D.box('Base cama', x0, fondo, 0.06, x1, pie, 0.36, tapiz, bevel=0.035, seg=8)
    colchon = D.box('Colchón', x0 + 0.035, fondo + 0.01, 0.36, x1 - 0.035, pie - 0.025, 0.6,
                    tela_mat('Sábana', (1.2, 1.17, 1.1)), bevel=0.07, seg=8)
    for o in (base_, colchon):
        o.modifiers.new('choque', 'COLLISION')
        o.collision.thickness_outer = 0.004
        o.collision.cloth_friction = 60
    # acolchado: cae sobre el colchón y cuelga por los costados y el pie; arranca a 55 cm del respaldo
    ac = plano('Acolchado', x0 - 0.3, x1 + 0.3, fondo + 0.55, pie + 0.3, 0.64, 120, 110, amp=0.02, seed=2,
               pin=(1, fondo + 0.5, fondo + 0.62))
    simular(ac, 60, calidad=8, encoge=0.015, pin=True)
    # una copia quieta del acolchado hace de cuerpo de choque para la manta (tela contra tela simulada se atraviesa)
    choque = ac.copy()
    choque.data = ac.data.copy()
    sc().collection.objects.link(choque)
    choque.modifiers.new('choque', 'COLLISION')
    choque.collision.thickness_outer = 0.03  # el acolchado terminado tiene 2,5 cm de alto
    choque.collision.cloth_friction = 60
    choque.hide_render = True
    terminar(ac, tela_mat('Acolchado lino', (1.15, 1.1, 1.0)), grosor=0.025, arriba=True)
    # manta tejida al pie, corrida hacia la ventana, que cuelga de un costado
    mt = plano('Manta', CAMA_X - 0.55, x1 + 0.32, pie - 0.66, pie + 0.06, 0.72, 110, 46, amp=0.02, seed=5,
               pin=(0, CAMA_X - 0.56, CAMA_X - 0.5))  # cuelga del lado de la cámara; el otro extremo queda fijo
    simular(mt, 50, calidad=10, encoge=0.02, pin=True)
    bpy.data.objects.remove(choque)
    terminar(mt, mat('Manta a cuadros'), grosor=0.01, arriba=True)
    # almohadas: dos para dormir apoyadas en el respaldo, dos europeas y un almohadón de cuero
    blanco = tela_mat('Funda', (1.25, 1.22, 1.15))
    for i, s in enumerate((-1, 1)):
        a = almohada(f'Almohada {i}', 0.74, 0.5, 0.12, blanco)
        poner(a, CAMA_X + s * 0.44, fondo + 0.21, 0.87, rx=-60)  # apoyada en el respaldo, sin hundirse en el colchón
        e = almohada(f'Europea {i}', 0.62, 0.62, 0.12, tapiz if i else mat('Manta verde'))
        poner(e, CAMA_X + s * 0.36, fondo + 0.52, 0.92, rx=-72, rz=s * -4)
    cuero = D.pbr('Cuero almohadón', D.tx('leather_cognac', 'leather_cognac'), size=0.6, rough=0.45)
    lum = almohada('Lumbar', 0.55, 0.32, 0.1, cuero)
    poner(lum, CAMA_X + 0.05, fondo + 0.8, 0.78, rx=-70, rz=3)
    print('CAMA LISTA')


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
    bg.inputs[1].default_value = 2.4  # la ventana manda: las lámparas acompañan
    out = N.new('ShaderNodeOutputWorld')
    hs = N.new('ShaderNodeHueSaturation')  # el cielo nublado tiñe de azul lo blanco: se le baja el color
    hs.inputs['Saturation'].default_value = 0.4
    L.new(env.outputs[0], hs.inputs['Color'])
    L.new(hs.outputs[0], bg.inputs[0])
    L.new(bg.outputs[0], out.inputs[0])
    sol = bpy.data.objects.get('Sol')
    if sol:
        sol.data.energy = 0.0
    sc().view_settings.exposure = 1.0
    sc().view_settings.white_balance_temperature = 6500  # cielo nublado: se neutraliza el azul
    # veladores: la pantalla deja pasar la luz y brilla
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
    for lz in [o for o in sc().objects if o.type == 'LIGHT' and o.data.type == 'POINT']:
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
        lz.data.energy = 30
        lz.data.shadow_soft_size = 0.05
    print('LUZ LISTA')


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
    # mesa de luz cercana: dos libros apilados en la esquina que mira a la cámara
    mesa = min((o for o in sc().objects if o.parent is None and o.name.startswith('nightstand')),
               key=lambda o: (Vector(o.location[:2]) - Vector((3.98, -9.645))).length)
    ms = [c for c in hijos(mesa) if c.type == 'MESH']
    lo = Vector([min(wbox(c)[0][i] for c in ms) for i in range(3)])
    hi = Vector([max(wbox(c)[1][i] for c in ms) for i in range(3)])
    z = hi.z
    for i, (w, d, h, col, rz) in enumerate([(0.24, 0.17, 0.032, (0.36, 0.33, 0.27), 6), (0.21, 0.15, 0.026, (0.62, 0.55, 0.45), -3)]):
        lib = D.box(f'Libro {i}', -w / 2, -d / 2, 0, w / 2, d / 2, h, D.pbr(f'Tapa libro {i}', color=col, rough=0.6), bevel=0.003)
        lib.location = (hi.x - 0.15, hi.y - 0.12, z)
        lib.rotation_euler.z = math.radians(rz)
        z += h
    # el tapizado del respaldo y de las europeas con la trama de la tela más marcada
    for n in tapizado().node_tree.nodes:
        if n.type == 'NORMAL_MAP':
            n.inputs['Strength'].default_value = 1.6
    print('DETALLES LISTOS')


# ------------------------------------------------------------------ paso 4: cámara de fotógrafo
def camara():
    co = D.camera(False, 72)
    co.name = 'Cam suite'
    co.location = (4.5, -6.4, 1.3)
    co.rotation_euler = (math.radians(90), 0, math.radians(145))
    co.data.shift_y = -0.05
    co.data.dof.use_dof = True
    co.data.dof.aperture_fstop = 5.6
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


def render(nombre='suite', samples=512):
    s = sc()
    s.cycles.samples = samples
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
        for paso in (cama, luz, detalles, camara, revelado):
            paso()
        bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'suite.blend'))
    if 'render' in args:
        render()
