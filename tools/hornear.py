"""Hornea la luz de Cycles del departamento modelo (tools/depto.py) en texturas, para el recorrido en tiempo real.

Arma el mismo departamento, lo parte en zonas (una textura por zona) y hornea con Cycles por GPU cuatro pases:
irradiancia (DIFFUSE directa + indirecta, sin color), albedo (DIFFUSE color), emisión y normales (guía del
denoiser). La irradiancia se limpia con OIDN (nodo Denoise del compositor) y queda
    final = albedo × irradiancia + emisión,
guardado con el mismo manejo de color que los panoramas (AgX Medium High Contrast, exposición 0,75, balance 4600 K).
Así el denoiser nunca toca el dibujo de las texturas (madera, telas, fotos), solo la luz.
Los metales se hornean sin metalicidad (quedan con su color base iluminado, si no saldrían negros) y se exportan
como mallas aparte para que el visor les sume reflejos. Los brillos especulares no se hornean: dependen de la vista.

Cycles hace una pasada completa por cada objeto horneado (sincroniza la escena y recorre todo el atlas: ~7 s por
objeto a 4096²), así que cada zona se hornea como UN objeto: se pasa a coordenadas de mundo y sus materiales se
reescriben para dar lo mismo (coordenadas de objeto desde un Empty con el transform original, proyección por caja
resuelta por cara en los muebles girados 90°, UV con nombre, Object Info › Random fijo). Las caras que nunca se ven
(apoyadas contra otro objeto, dentro de otro, tapas sobre el cielorraso, bases sobre el piso) no ocupan atlas pero
quedan en la escena como oclusores.

Salida:
  img/depto3d/depto.glb       geometría en metros (UV 'bake' = TEXCOORD_0), un material por zona, Vidrio, Vista y Agua
  img/depto3d/<zona>.webp     textura horneada (4096², calidad 85) · <zona>-m.webp: 2048² para celulares
  img/depto3d/vista.webp      foto del fondo con el mismo manejo de color
  js/depto3d.js               zonas, metales, vidrio, ambientes, contorno caminable y cajas de colisión
  3d/out/hornear/             EXR crudos del horneado (para reprocesar sin volver a hornear)
  3d/out/bake-check/          hojas de control: referencia (izquierda) y vista horneada (derecha). La referencia es un
                              recorte del panorama; en las suites, un render nuevo de Cycles (los panoramas son de
                              antes de girar las camas)

Uso (desde la raíz del proyecto):
  blender -b --factory-startup -P tools/hornear.py --                  todo, y al final las hojas de control
  blender -b --factory-startup -P tools/hornear.py -- --rapido         prueba a 1024² con pocas muestras (3d/out/hornear-rapido)
  blender -b --factory-startup -P tools/hornear.py -- --zonas bano     vuelve a hornear solo esas zonas; el resto sale del caché
  blender -b --factory-startup -P tools/hornear.py -- --sin-hornear    rearma texturas, glb y js desde el caché
  blender -b --factory-startup -P tools/hornear.py -- --solo-revisar   solo las hojas de control
  blender -b --factory-startup -P tools/hornear.py -- --referencias    vuelve a renderizar las referencias de las suites
"""
import argparse
import json
import math
import pathlib
import re
import subprocess
import sys
import time
import zlib
from collections import defaultdict

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import depto  # noqa: E402  (solo corre main() bajo __main__)

ROOT = depto.ROOT
H, EYE = depto.H, depto.EYE
XS = 7.6  # límite entre living y cocina
ZONAS = ('living', 'cocina', 'balcon', 'suite', 'bano', 'suite2')
CORTES = (('y', 0.0), ('y', -5.6), ('x', XS), ('x', 5.0), ('x', 9.0))
# metales: se hornean con su color base y el visor les suma reflejos en tiempo real
METAL = {'Espejo': 'espejo', 'Bronce': 'bronce', 'Metal negro': 'metal', 'Vitrocerámica': 'vitro'}
VIDRIO = (0.92, 0.96, 0.95)
VISTA_FUERZA = 1.6  # emisión de la foto del fondo en depto.backdrop()
# no frenan el paso: alfombras, cortinas, pisos, techos, luces, fondo
NO_CHOCA = ('Alfombra', 'Cortina', 'Piso', 'Techo', 'Spot', 'Colgante', 'Lago', 'Vista', 'Balcón', 'Losa',
            'Zócalo', 'Receptáculo', 'Luz')
# los panoramas de las suites son de antes de girar las camas (quedaban detrás del muro): para esas hojas se renderiza
# una referencia nueva con Cycles desde el depto.py actual
REFERENCIAS = ('suite', 'bedroom')
CHEQUEO = (960, 600, 90, -12)  # ancho, alto, campo horizontal, inclinación de las vistas de control
REVISAR = {  # ambiente: giros (grados) para las hojas de control
    'living': (-55, 25, 120), 'kitchen': (150, -100, 60), 'suite': (-135, -45, 90),
    'bath': (180, 90, -60), 'bedroom': (135, -150, 45), 'balcony': (0, 120, -120),
}


def log(*a):
    print('[hornear]', *a, flush=True)


# ------------------------------------------------------------------ utilidades
def base(nombre):
    """'Bronce.001' -> 'Bronce'"""
    b, _, s = nombre.rpartition('.')
    return b if b and s.isdigit() else nombre


def es_vidrio(m):
    return m is not None and base(m.name) == 'Vidrio'


def tipo_mat(m):
    if m is None:
        return 'base'
    return METAL.get(base(m.name)) or ('metal' if m.get('metal') else 'base')


def tris(me):
    n = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get('loop_total', n)
    return int((n - 2).sum())


def caja(objs):
    pts = np.array([tuple(o.matrix_world @ Vector(c)) for o in objs for c in o.bound_box])
    return pts.min(0), pts.max(0)


def leer(img):
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def imagen(nombre, arr):
    h, w = arr.shape[:2]
    im = bpy.data.images.get(nombre)
    if im is None or tuple(im.size) != (w, h):
        if im:
            bpy.data.images.remove(im)
        im = bpy.data.images.new(nombre, w, h, alpha=True, float_buffer=True)
        im.colorspace_settings.name = 'Non-Color'  # datos crudos (sin esto puede quedar marcada sRGB)
    px = np.ones((h, w, 4), np.float32)
    px[..., :arr.shape[2]] = arr
    im.pixels.foreach_set(px.ravel())
    return im


def quitar_uv(me, salvo=None):
    for n in [L.name for L in me.uv_layers if L.name != salvo and not L.name.startswith('.')]:
        L = me.uv_layers.get(n)
        if L:
            me.uv_layers.remove(L)


def srgb_a_lineal(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def opciones(op, **kw):
    ok = {p.identifier for p in op.get_rna_type().properties}
    return {k: v for k, v in kw.items() if k in ok}


# ------------------------------------------------------------------ preparación de la geometría
def aplicar(objs):
    """Modificadores aplicados (Bisel, Espesor, los de Poly Haven) y datos de malla de un solo usuario."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    nuevos = []
    for o in objs:
        if o.modifiers:
            nuevos.append((o, bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True,
                                                              depsgraph=dg)))
        elif o.data.users > 1:
            nuevos.append((o, o.data.copy()))
    for o, me in nuevos:
        o.modifiers.clear()
        o.data = me


def familia(o):
    """Los modelos de catálogo (Poly Haven, ABO) van cada uno por su lado. Las piezas armadas a mano se juntan por
    nombre ('Respaldo.003' -> 'Respaldo', 'Almohada 1' -> 'Almohada'): cada canal del respaldo, por separado, se
    llevaba el presupuesto de un mueble entero y la suite pasó de 12 mil a 250 mil triángulos."""
    r = o['raiz']
    if es_modelo(o) or re.search(r' B0\w{8}', r):
        return r, False
    lo, hi = caja([o])
    return (re.sub(r'[ .]\d+$', '', r), zona_de((lo + hi) / 2)), True  # cada ambiente con su presupuesto


def aliviar(objs, tope=20000, por_metro=8000, tope_armado=10000, por_metro_armado=4000):
    """Decima los modelos pesados (Poly Haven, ABO) y las telas simuladas: presupuesto por grupo según su tamaño, y
    nunca más de `tope` por objeto. Las piezas armadas a mano son formas suaves y aguantan menos triángulos. Para el
    recorrido alcanza: cerca de cada punto de vista manda el panorama, que se renderiza sin decimar."""
    grupos = defaultdict(list)
    for o in objs:
        grupos[familia(o)].append(o)
    tocados = []
    for (raiz, armado), g in grupos.items():
        raiz = ' · '.join(raiz) if armado else raiz
        lo, hi = caja(g)
        t, pm = (tope_armado, por_metro_armado) if armado else (tope, por_metro)
        pres = min(t, max(2000, float(np.linalg.norm(hi - lo)) * pm))
        cuentas = [tris(o.data) for o in g]
        tot = sum(cuentas)
        if tot <= pres * 1.15 and max(cuentas) <= t:
            continue
        r = min(1.0, pres / tot)
        for o, n in zip(g, cuentas):
            ro = min(r, t / n) if n else 1.0
            if n < 300 or ro > 0.95:
                continue
            md = o.modifiers.new('Alivio', 'DECIMATE')
            md.ratio = ro
            md.use_collapse_triangulate = True
            tocados.append(o)
        log(f'decimado {raiz}: {tot} -> ~{int(pres)} triángulos')
    aplicar(tocados)


def enderezar(objs):
    """Sólidos cerrados armados al revés (una caja con x0 > x1, como la puerta abierta del living): las caras miran
    hacia adentro. Cycles los muestra bien en un render, pero al hornear cada cara se ilumina del lado de su normal
    (sale negra) y en el visor desaparecerían con el descarte de caras traseras. Se dan vuelta."""
    vueltos = []
    for o in objs:
        if es_modelo(o):
            continue
        me = o.data
        bm = bmesh.new()
        bm.from_mesh(me)
        if bm.edges and all(len(e.link_faces) == 2 for e in bm.edges) and \
                bm.calc_volume(signed=True) * o.matrix_world.determinant() < 0:
            bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
            bm.to_mesh(me)
            if me.has_custom_normals:
                me.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(me.loops))
            vueltos.append(o.name)
        bm.free()
    if vueltos:
        log('caras dadas vuelta en', ', '.join(vueltos))


def partir_caras(o, clave):
    """Separa las caras de `o` según clave(o, cara, M, N) y devuelve {etiqueta: objeto} (mismo transform y materiales)."""
    M = o.matrix_world
    N = M.to_3x3().inverted_safe().transposed()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    et = [clave(o, f, M, N) for f in bm.faces]
    uniq = sorted(set(et))
    if len(uniq) <= 1:
        bm.free()
        return {uniq[0]: o} if uniq else {}
    out = {}
    for e in uniq:
        b2 = bm.copy()
        b2.faces.ensure_lookup_table()
        bmesh.ops.delete(b2, geom=[f for f, x in zip(b2.faces, et) if x != e], context='FACES')
        me = bpy.data.meshes.new(f'{o.data.name}@{e}')
        b2.to_mesh(me)
        b2.free()
        for mat in o.data.materials:
            me.materials.append(mat)
        o2 = o.copy()
        o2.data = me
        for c in o.users_collection:
            c.objects.link(o2)
        o2.name = f'{o.name}@{e}'
        out[e] = o2
    bm.free()
    bpy.data.objects.remove(o)
    return out


class Contactos:
    """BVH de toda la geometría opaca (antes de recortar nada) para encontrar caras tapadas por otro objeto."""

    def __init__(self, objs):
        verts, polys, self.dueno, self.base, self.cerrado = [], [], [], {}, []
        for i, o in enumerate(objs):
            me, M = o.data, np.array(o.matrix_world)
            co = np.empty(len(me.vertices) * 3, np.float64)
            me.vertices.foreach_get('co', co)
            co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
            off = len(verts)
            verts.extend(map(tuple, co))
            self.base[o.name] = len(polys)
            polys.extend([off + v for v in p.vertices] for p in me.polygons)
            self.dueno.extend([i] * len(me.polygons))
            self.cerrado.append(not es_modelo(o))  # los modelos de Poly Haven tienen superficies abiertas
        self.bvh = BVHTree.FromPolygons(verts, polys)
        self.tapadas = 0

    @staticmethod
    def muestras(c, vs, paso=0.04):
        """Centro, esquinas y una grilla de puntos cada `paso` metros sobre la cara (abanico de triángulos), apenas
        hacia adentro de los bordes: una franja visible entre dos objetos que la tapan no se escapa."""
        yield c
        for v in vs:
            yield c + (v - c) * 0.98
        for i in range(1, len(vs) - 1):
            a, b, d = vs[0], vs[i], vs[i + 1]
            k = max(1, min(120, math.ceil(max((b - a).length, (d - a).length, (d - b).length) / paso)))
            for u in range(k + 1):
                for w in range(k + 1 - u):
                    p = a + (b - a) * (u / k) + (d - a) * (w / k)
                    yield c + (p - c) * 0.98

    def tapada(self, o, f, M, n):
        """Todas las muestras de la cara tocan una cara opuesta de otro objeto (a menos de 2,5 mm) o quedan adentro
        de otro sólido cerrado (el primer cruce hacia afuera es la cara de atrás de ese objeto)."""
        yo = self.dueno[self.base[o.name] + f.index]
        c = M @ f.calc_center_median()
        for p in self.muestras(c, [M @ v.co for v in f.verts]):
            pegada = any(self.dueno[i] != yo and nr.dot(n) < -0.9 for _, nr, i, _ in self.bvh.find_nearest_range(p, 0.0025))
            if not pegada:
                _, nr, i, _ = self.bvh.ray_cast(p + n * 1e-3, n, 0.3)
                if i is None or self.dueno[i] == yo or not self.cerrado[self.dueno[i]] or nr.dot(n) < 0.2:
                    return False
        self.tapadas += 1
        return True


_CONTACTOS = None


def clave_visible(o, f, M, N):
    """vidrio / descartar (vidrio decorativo) / oculta (cara que nunca se ve) / ok."""
    m = o.material_slots[f.material_index].material if o.material_slots else None
    if m is not None:
        if es_vidrio(m):
            return 'vidrio'
        if getattr(m, 'blend_method', '') == 'BLEND':
            return 'descartar'
    n = N @ f.normal
    if n.length < 1e-9:
        return 'ok'
    n.normalize()
    zs = [(M @ v.co).z for v in f.verts]
    if n.z > 0.9 and min(zs) >= H - 1e-3:   # tapas de muros, techo y losa: quedan dentro del cielorraso o encima
        return 'oculta'
    if n.z < -0.9 and max(zs) <= 1e-3:      # bases sobre el piso, fondos de losas
        return 'oculta'
    nm = o.name
    if ((nm.startswith('Muro oeste') and n.x < -0.9) or (nm.startswith('Muro este') and n.x > 0.9)
            or (nm.startswith('Muro fondo') and n.y < -0.9)):
        return 'oculta'                     # cara exterior de los muros ciegos
    if _CONTACTOS and _CONTACTOS.cerrado[_CONTACTOS.dueno[_CONTACTOS.base[o.name]]] and f.calc_area() > 0.004:
        if _CONTACTOS.tapada(o, f, M, n):   # contra un muro (placard, puertas), bajo el revestimiento, dentro de otro
            return 'oculta'
    return 'ok'


def zona_de(p):
    x, y, z = p
    if y > 0.0 or z < -0.3:
        return 'balcon'
    if y > -5.6:
        return 'living' if x < XS else 'cocina'
    return 'suite' if x < 5.0 else 'bano' if x < 9.0 else 'suite2'


def clave_zona(o, f, M, N):
    # la cara va con el ambiente al que mira
    n = (N @ f.normal).normalized()
    return zona_de(M @ f.calc_center_median() + n * 0.06)


def cortar(o, lo, hi):
    """Corta los objetos grandes (pisos, techo, muros, rieles) en los límites entre zonas."""
    M = o.matrix_world
    Mi, R = M.inverted(), M.to_3x3().transposed()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    hecho = False
    for eje, v in CORTES:
        i = 0 if eje == 'x' else 1
        if lo[i] + 0.02 < v < hi[i] - 0.02:
            co, no = Vector((0, 0, 0)), Vector((0, 0, 0))
            co[i], no[i] = v, 1.0
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-5,
                                   plane_co=Mi @ co, plane_no=(R @ no).normalized())
            hecho = True
    if hecho:
        bm.to_mesh(o.data)
    bm.free()


def densidad(o):
    """Densidad de texels relativa (1 = pisos y paredes)."""
    n, r = o.name, o.get('raiz', '')
    if r.startswith('Piso -'):
        return 0.35  # balcones de los pisos de abajo: se ven de lejos
    if n.startswith('Techo'):
        return 0.55
    if n.startswith('Cortina'):
        return 0.6  # voile: mucha superficie, luz pareja
    if r.startswith('potted_plant'):
        return 0.7  # hojas y tierra: mucha superficie, poco detalle de luz
    if n.startswith(('Losa superior', 'Balcón canto')):
        return 0.7
    if n.startswith('Cuadro') or r.startswith(('decorative_book_set', 'standing_picture_frame')):
        return 1.5
    if sorted(o.dimensions)[1] < 0.03 and any(s.material and base(s.material.name) == 'Junta' for s in o.material_slots):
        return 4.0  # juntas de 4 mm: a densidad 1 miden menos de un texel, quedan vacías y el relleno las pinta
        # con la isla vecina (una línea blanca en el placard)
    return 1.0


def preparar(sc):
    mallas = [o for o in sc.objects if o.type == 'MESH']
    for o in mallas:
        r = o
        while r.parent:
            r = r.parent
        o['raiz'] = r.name
    # todo en un solo nivel (sin padres), conservando la posición en el mundo
    mw = {o.name: o.matrix_world.copy() for o in mallas}
    for o in mallas:
        o.parent = None
        o.matrix_world = mw[o.name]
    fondo = [o for o in mallas if o.name in ('Vista', 'Lago')]
    resto = [o for o in mallas if o.name not in ('Vista', 'Lago')]
    gris = depto.pbr('Gris', color=(0.5, 0.5, 0.5))
    for o in resto:
        if not o.material_slots:
            o.data.materials.append(gris)
        for s in o.material_slots:
            if s.material is None:
                s.material = gris
    aplicar(resto)
    aliviar(resto)
    enderezar(resto)
    global _CONTACTOS
    _CONTACTOS = Contactos([o for o in resto if not all(es_vidrio(s.material) for s in o.material_slots)])
    hornear, vidrio, oclusores = [], [], []
    for o in resto:
        for e, p in partir_caras(o, clave_visible).items():
            (hornear if e == 'ok' else vidrio if e == 'vidrio' else oclusores).append(p)
    # lo que no se hornea ni se exporta igual queda en la escena: da sombra (juntado, para sincronizar menos objetos)
    n = len(oclusores)
    oclusores = agrupar(oclusores)
    log(f'{len(hornear)} objetos para hornear, {len(vidrio)} de vidrio, {n} oclusores -> {len(oclusores)} '
        f'({_CONTACTOS.tapadas} caras tapadas por otro objeto)')
    return hornear, vidrio, fondo


def repartir(objs):
    zonas = defaultdict(list)
    for o in objs:
        lo, hi = caja([o])
        if np.linalg.norm(hi - lo) > 1.5 and not es_modelo(o):
            cortar(o, lo, hi)
            for z, p in partir_caras(o, clave_zona).items():
                zonas[z].append(p)
        else:
            zonas[zona_de((lo + hi) / 2)].append(o)
    return zonas


# ------------------------------------------------------------------ UV de horneado
def area_uv_3d(me):
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    if not n:
        return 0.0, 0.0
    li = np.empty(n * 3, np.int32)
    me.loop_triangles.foreach_get('loops', li)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers['bake'].data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    a, b, c = uv[li[0::3]], uv[li[1::3]], uv[li[2::3]]
    auv = 0.5 * np.abs((b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0]).sum()
    ar = np.empty(n, np.float32)
    me.loop_triangles.foreach_get('area', ar)
    return float(auv), float(ar.sum())


def editar(objs, op, **kw):
    """Corre un operador de UV en modo edición sobre `objs` (todas las caras seleccionadas)."""
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    op(**opciones(op, **kw))
    bpy.ops.object.mode_set(mode='OBJECT')


def uv_de(me):
    L = me.uv_layers['bake']
    a = np.empty(len(L.data) * 2, np.float32)
    L.data.foreach_get('uv', a)
    return a.reshape(-1, 2)


def es_modelo(o):
    """Modelo de Poly Haven (muchas islas chicas): se empaqueta en un bloque propio que se mueve entero."""
    return (depto.ASSETS / 'models' / base(o.get('raiz', ''))).is_dir()


def desplegar(sc, zona, objs, res, margen_px):
    """UV 'bake' de toda la zona en un solo atlas, sobre copias en coordenadas de mundo (así la escala de las islas es
    la real). Esas copias son a la vez el objetivo del horneado y la malla que se exporta.
    1. la densidad relativa se aplica escalando la copia mientras se despliega (las islas salen del tamaño justo);
    2. muros, pisos y muebles armados: Smart UV Project de todos juntos (cada cara plana es una isla);
    3. cada modelo de Poly Haven: Smart UV Project propio con un margen chico, y un cuadrado temporal que tapa el
       bloque para que el empaquetado final lo mueva entero (merge_overlap): sus cientos de islas chicas no pagan
       margen cada una;
    4. cada grupo pasa a metros y a su casilla (sin superposiciones), y se empaqueta todo junto."""
    t0 = time.time()
    coll = bpy.data.collections.new(f'Desplegar {zona}')
    sc.collection.children.link(coll)
    sc.tool_settings.use_uv_select_sync = True
    tmp = []
    for o in objs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        if o.matrix_world.determinant() < 0:
            me.flip_normals()
        quitar_uv(me)
        me.uv_layers.new(name='bake')
        t = bpy.data.objects.new(f'{o.name}~', me)
        coll.objects.link(t)
        tmp.append(t)
    k = [densidad(o) for o in objs]
    area = [area_uv_3d(t.data)[1] for t in tmp]
    sp = dict(angle_limit=math.radians(60), margin_method='FRACTION', island_margin=0.002, area_weight=0.0,
              correct_aspect=True, scale_to_bounds=False)
    unidades = defaultdict(list)
    for o, t, kk, a in zip(objs, tmp, k, area):
        clave = o['raiz'] if es_modelo(o) else ''
        if not clave and len(o.data.vertices) > 3000:
            # muebles de tejido o de varillas (sillas de ratán, colgantes de fibra): miles de islas que, empaquetadas
            # con la zona, pagan margen cada una y dejan el atlas vacío; van en un bloque propio, como los modelos
            editar([t], bpy.ops.uv.smart_project, **sp)
            if area_uv_3d(t.data)[0] < 0.2:
                clave = o['raiz']
        unidades[clave].append((t, kk * kk * a))
    pesos = sorted(((kk * kk * a, o.get('raiz', o.name)) for o, kk, a in zip(objs, k, area)), reverse=True)
    suma = defaultdict(float)
    for w, r in pesos:
        suma[r] += w
    log(f'{zona}: {sum(suma.values()):.0f} m² ponderados; los que más ocupan: '
        + ', '.join(f'{r} {w:.1f}' for r, w in sorted(suma.items(), key=lambda x: -x[1])[:8]))
    for t, kk in zip(tmp, k):
        if kk != 1.0:
            t.data.transform(Matrix.Scale(kk, 4))
    est =res * math.sqrt(0.6 / max(1e-6, sum(a * kk * kk for a, kk in zip(area, k))))  # px/m estimado
    for clave, g in unidades.items():
        ts = [t for t, _ in g]
        if not clave:
            editar(ts, bpy.ops.uv.smart_project, **sp)
        else:
            lado = math.sqrt(sum(a for _, a in g) / 0.5) * est
            for margen in (min(0.01, max(0.0005, 0.75 / max(lado, 1.0))), 0.0):
                editar(ts, bpy.ops.uv.smart_project, angle_limit=math.radians(66), margin_method='FRACTION',
                       island_margin=margen, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
                if sum(area_uv_3d(t.data)[0] for t in ts) > 0.05:
                    break  # con miles de islas (hojas) hasta un margen chico las aplasta: se repite sin margen
    for t, kk in zip(tmp, k):
        if kk != 1.0:
            t.data.transform(Matrix.Scale(1 / kk, 4))
    # cada grupo a metros (× densidad) y a su casilla, en estantes
    bloques = []
    for clave, g in unidades.items():
        ts = [t for t, _ in g]
        uvs = [uv_de(t.data).astype(np.float64) for t in ts]
        au = sum(area_uv_3d(t.data)[0] for t in ts)
        a3 = sum(a for _, a in g)
        if au < 1e-9:
            log(f'AVISO {zona}: UV degenerada en {clave or "objetos armados"}')
            au = 1.0
        # ponytail: un bloque con islas muy sueltas (hojas, tejido) se achica como si llenara el 25 %: esas piezas pierden
        # resolución en vez de quitarle medio atlas al resto
        e = math.sqrt(a3 / (max(au, 0.25) if clave else au))
        todo = np.concatenate(uvs) * e
        lo, hi = todo.min(0), todo.max(0)
        relleno = a3 / max(1e-9, float(np.prod(hi - lo)))
        log(f'{zona}: bloque {clave or "objetos armados"}: {a3:.3f} m², UV {au:.4f}, '
            f'{hi[0] - lo[0]:.2f} × {hi[1] - lo[1]:.2f} m, relleno {relleno * 100:.0f} %')
        if relleno < 0.1:
            ext = sorted(((float(np.ptp(u, 0).max()), t.name) for t, u in zip(ts, uvs)), reverse=True)[:5]
            log(f'AVISO {zona}: bloque casi vacío; las UV más extendidas: ' + ', '.join(f'{n} {x:.3f}' for x, n in ext))
        bloques.append([clave, ts, [u * e - lo for u in uvs], hi - lo])
    ancho = max(math.sqrt(sum(float(b[3][0] * b[3][1]) for b in bloques)) * 1.3, max(float(b[3][0]) for b in bloques))
    x = y = fila = 0.0
    for b in bloques:
        c = b[3]
        if x + c[0] > ancho:
            x, y, fila = 0.0, y + fila + 0.2, 0.0
        b.append(np.array((x, y)))
        x += c[0] + 0.2
        fila = max(fila, float(c[1]))
    tope = max(float((b[4] + b[3]).max()) for b in bloques)
    caras0 = {t.name: len(t.data.polygons) for t in tmp}
    for clave, ts, uvs, c, off in bloques:
        for t, uv in zip(ts, uvs):
            t.data.uv_layers['bake'].data.foreach_set('uv', ((uv + off) / tope).astype(np.float32).ravel())
        if clave:
            # cuadrado temporal que tapa el bloque: el empaquetado lo trata como una sola isla
            x0, y0 = off / tope
            x1, y1 = (off + c) / tope
            me = ts[0].data
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.verts.ensure_lookup_table()
            p = bm.verts[0].co.copy()
            vs = [bm.verts.new(p + Vector(d)) for d in ((0, 0, 0), (1e-3, 0, 0), (1e-3, 1e-3, 0), (0, 1e-3, 0))]
            f = bm.faces.new(vs)
            capa = bm.loops.layers.uv['bake']
            for loop, co in zip(f.loops, ((x0, y0), (x1, y0), (x1, y1), (x0, y1))):
                loop[capa].uv = co
            bm.to_mesh(me)
            bm.free()
    t1 = time.time()
    editar(tmp, bpy.ops.uv.pack_islands, udim_source='CLOSEST_UDIM', rotate=True, rotate_method='ANY', scale=True,
           merge_overlap=True, margin_method='FRACTION', margin=2.0 * margen_px / res, pin=False,
           shape_method='CONCAVE')
    t_pack = time.time() - t1
    for t in tmp:
        me, n = t.data, caras0[t.name]
        if len(me.polygons) > n:
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.faces.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[bm.faces[i] for i in range(n, len(bm.faces))], context='FACES')
            bm.to_mesh(me)
            bm.free()
    suv = s3d = firma = 0.0
    for o, t, kk in zip(objs, tmp, k):
        if kk == 1.0:
            a, b = area_uv_3d(t.data)
            suv, s3d = suv + a, s3d + b
        uv = uv_de(t.data)
        firma += float(uv.astype(np.float64).sum())
        # la misma UV en el original (misma topología): se hornea sobre él, con sus materiales
        me = o.data
        assert len(me.loops) * 2 == uv.size, (o.name, len(me.loops), uv.size)
        render = next((x.name for x in me.uv_layers if x.active_render), None)
        dst = me.uv_layers.get('bake') or me.uv_layers.new(name='bake', do_init=False)
        dst.data.foreach_set('uv', uv.ravel())
        me.uv_layers.active = dst
        if render:
            me.uv_layers[render].active_render = True
    mallas = []
    for t in tmp:
        t.data.use_fake_user = True
        mallas.append(t.data)
        bpy.data.objects.remove(t)
    bpy.data.collections.remove(coll)
    dens = math.sqrt(suv / s3d) if s3d else 0.0
    log(f'{zona}: {len(objs)} objetos ({len(unidades) - ("" in unidades)} modelos), UV en {time.time() - t0:.0f} s '
        f'(empaquetado {t_pack:.0f} s), uso del atlas {sum(area_uv_3d(m)[0] for m in mallas) * 100:.0f} %')
    return mallas, dens, round(firma, 3)


# ------------------------------------------------------------------ horneado
SIN_UV = '__sin_uv__'   # UV inexistente: el Normal Map en espacio tangente queda sin efecto, como en los objetos sin UV
_VARIANTES = {}
_GRUPOS = {}
_VACIOS = {}
_SIN_VECTOR = ('ShaderNodeTexImage', 'ShaderNodeTexEnvironment', 'ShaderNodeTexSky', 'ShaderNodeTexCoord')


def _deps(nt):
    """Qué lee el material del objeto: 'objeto' (coordenadas de objeto), 'caja' (proyección por caja, usa la normal
    de objeto), 'azar' (Object Info › Random) u 'otro' (Generated, normales de objeto…: no se puede convertir)."""
    d = set()
    for n in nt.nodes:
        t = n.bl_idname
        if t == 'ShaderNodeTexCoord' and n.object is None:
            if n.outputs['Object'].is_linked:
                d.add('objeto')
            if n.outputs['Generated'].is_linked or n.outputs['Normal'].is_linked:
                d.add('otro')
        elif t == 'ShaderNodeTexImage':
            if n.projection != 'FLAT':
                d.add('caja' if n.projection == 'BOX' else 'otro')
        elif (t.startswith('ShaderNodeTex') and t not in _SIN_VECTOR and 'Vector' in n.inputs
              and not n.inputs['Vector'].is_linked and getattr(n, 'noise_dimensions', '3D') != '1D'):
            d.add('otro')  # procedural sin vector: usa Generated
        elif t == 'ShaderNodeObjectInfo':
            for o in n.outputs:
                if o.is_linked:
                    d.add('azar' if o.name == 'Random' else 'otro')
        elif t == 'ShaderNodeVectorTransform' and 'OBJECT' in (n.convert_from, n.convert_to):
            d.add('otro')
        elif t == 'ShaderNodeNormalMap' and n.space in ('OBJECT', 'BLENDER_OBJECT'):
            d.add('otro')
        elif t == 'ShaderNodeGroup' and n.node_tree:
            d |= _deps(n.node_tree)
    return d


def _tratar(nt, modo, vacio, azar):
    """Reescribe un árbol (ya copiado) para que no dependa del objeto. modo: 'sin_uv' (el objeto no tenía UV: el
    normal map no actúa, como en los panoramas), 'caja' (proyección por caja precalculada en la UV 'uvcaja') o el
    nombre de la UV que el material usaba sin nombrar. vacio: Empty con el transform original (coordenadas de
    objeto exactas). azar: valor fijo para Object Info › Random."""
    N, L = nt.nodes, nt.links
    con_uv = modo not in ('sin_uv', 'caja')

    def uv(nombre):
        u = N.new('ShaderNodeUVMap')
        u.uv_map = nombre
        return u.outputs['UV']

    for n in list(N):
        t = n.bl_idname
        if t == 'ShaderNodeTexCoord':
            if vacio is not None:
                n.object = vacio
            if modo == 'caja' and n.outputs['Object'].is_linked:
                s = uv('uvcaja')
                for l in list(n.outputs['Object'].links):
                    L.new(s, l.to_socket)
            if con_uv and n.outputs['UV'].is_linked:
                s = uv(modo)
                for l in list(n.outputs['UV'].links):
                    L.new(s, l.to_socket)
        elif t == 'ShaderNodeTexImage':
            if modo == 'caja':
                n.projection = 'FLAT'
            if con_uv and n.projection == 'FLAT' and not n.inputs['Vector'].is_linked:
                L.new(uv(modo), n.inputs['Vector'])
        elif t == 'ShaderNodeUVMap' and con_uv and not n.uv_map:
            n.uv_map = modo
        elif t == 'ShaderNodeNormalMap' and n.space == 'TANGENT' and not n.uv_map:
            n.uv_map = modo if con_uv else SIN_UV
        elif t == 'ShaderNodeTangent' and n.direction_type == 'UV_MAP' and not n.uv_map and con_uv:
            n.uv_map = modo
        elif t == 'ShaderNodeObjectInfo' and azar is not None and n.outputs['Random'].is_linked:
            v = N.new('ShaderNodeValue')
            v.outputs[0].default_value = azar
            for l in list(n.outputs['Random'].links):
                L.new(v.outputs[0], l.to_socket)
        elif t == 'ShaderNodeGroup' and n.node_tree:
            n.node_tree = _grupo(n.node_tree, modo, vacio, azar)


def _clave(nombre, modo, vacio, azar):
    return (nombre, modo, vacio.name if vacio else None, None if azar is None else round(azar, 6))


def _grupo(g, modo, vacio, azar):
    k = _clave(g.name, modo, vacio, azar)
    if k not in _GRUPOS:
        g2 = g.copy()
        _tratar(g2, modo, vacio, azar)
        _GRUPOS[k] = g2
    return _GRUPOS[k]


def variante(m, modo, vacio=None, azar=None):
    k = _clave(m.name, modo, vacio, azar)
    if k not in _VARIANTES:
        if not any(n.bl_idname in ('ShaderNodeTexCoord', 'ShaderNodeTexImage', 'ShaderNodeNormalMap', 'ShaderNodeUVMap',
                                   'ShaderNodeTangent', 'ShaderNodeObjectInfo', 'ShaderNodeGroup')
                   for n in m.node_tree.nodes):
            _VARIANTES[k] = m
        else:
            v = m.copy()
            v.name = f'{m.name} [{modo}]'
            _tratar(v.node_tree, modo, vacio, azar)
            _VARIANTES[k] = v
    return _VARIANTES[k]


def uv_caja(me):
    """UV 'uvcaja': la proyección por caja de Cycles (coordenadas y normal de objeto) resuelta cara por cara."""
    n = len(me.polygons)
    nor = np.empty(n * 3, np.float32)
    me.polygons.foreach_get('normal', nor)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', co)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get('vertex_index', lv)
    ls = np.empty(n, np.int32)
    me.polygons.foreach_get('loop_start', ls)
    lt = np.empty(n, np.int32)
    me.polygons.foreach_get('loop_total', lt)
    cara = np.zeros(len(me.loops), np.int32)
    for i, (s, t) in enumerate(zip(ls, lt)):
        cara[s:s + t] = i
    p = co.reshape(-1, 3)[lv]
    nn = nor.reshape(-1, 3)[cara]
    eje = np.abs(nn).argmax(1)
    s = np.sign(nn[np.arange(len(nn)), eje])
    # Cycles: X -> (N.x<0 ? 1-y : y, z) · Y -> (N.y>0 ? 1-x : x, z) · Z -> (N.z>0 ? 1-y : y, x); el 1 se va con la repetición
    u = np.where(eje == 0, np.where(s < 0, -p[:, 1], p[:, 1]),
                 np.where(eje == 1, np.where(s > 0, -p[:, 0], p[:, 0]), np.where(s > 0, -p[:, 1], p[:, 1])))
    v = np.where(eje == 2, p[:, 0], p[:, 2])
    L = me.uv_layers.get('uvcaja') or me.uv_layers.new(name='uvcaja', do_init=False)
    L.data.foreach_set('uv', np.stack([u, v], 1).astype(np.float32).ravel())


def vacio_para(M):
    clave = tuple(round(x, 5) for fila in M for x in fila)
    if clave not in _VACIOS:
        e = bpy.data.objects.new(f'coords {len(_VACIOS)}', None)
        bpy.context.scene.collection.objects.link(e)
        e.matrix_world = M
        _VACIOS[clave] = e
    return _VACIOS[clave]


def convertir(o):
    """Deja el objeto en coordenadas de mundo con materiales que dan lo mismo que en los panoramas (exacto, salvo la
    proyección por caja de los muebles girados: espejada a 180°, resuelta por cara a 90°).
    Devuelve False si no se puede: entonces se hornea aparte, con su transform."""
    me = o.data
    capas = [L.name for L in me.uv_layers if not L.name.startswith('.') and L.name not in ('bake', 'uvcaja')]
    activa = next((L.name for L in me.uv_layers if L.active_render and L.name in capas), capas[0] if capas else None)
    M = o.matrix_world.copy()
    identidad = all(abs(M[i][j] - (i == j)) < 1e-6 for i in range(4) for j in range(4))
    mats = [s.material for s in o.material_slots if s.material and s.material.use_nodes]
    deps = set().union(*(_deps(m.node_tree) for m in mats)) if mats else set()
    if 'otro' in deps:
        return False
    modo = activa or 'sin_uv'
    vacio = None
    azar = (zlib.crc32(o.name.encode()) & 0xffffffff) / 2 ** 32 if 'azar' in deps else None
    if not identidad and deps & {'objeto', 'caja'}:
        R = M.to_3x3().normalized()
        giro = abs(math.degrees(math.atan2(R[1][0], R[0][0]))) % 180
        if 'caja' in deps and min(giro, 180 - giro) > 15:
            if capas:
                return False
            uv_caja(me)            # girado 90° (aparador, comedor): proyección resuelta por cara
            modo = 'caja'
        else:
            vacio = vacio_para(M)  # coordenadas de objeto exactas
    for s in o.material_slots:
        if s.material and s.material.use_nodes:
            s.material = variante(s.material, modo, vacio, azar)
    if not identidad:
        me.transform(M)
        if M.determinant() < 0:
            me.flip_normals()
        o.matrix_world = Matrix.Identity(4)
    return True


def unificar(zona, objs):
    """Toda la zona en un objeto (más los que no se pueden convertir): Cycles hace una pasada entera por objeto
    horneado (sincroniza la escena y recorre el atlas completo), así que conviene hornear de a uno."""
    juntar, aparte = [], []
    for o in objs:
        (juntar if convertir(o) else aparte).append(o)
    capas = {L.name for o in juntar for L in o.data.uv_layers if not L.name.startswith('.')}
    if len(capas) > 8:  # tope de Blender: los modelos con UV de nombres raros van aparte
        cuenta = defaultdict(int)
        for o in juntar:
            for L in o.data.uv_layers:
                cuenta[L.name] += 1
        sobran = set(sorted(capas, key=lambda c: -cuenta[c])[8:])
        aparte += [o for o in juntar if any(L.name in sobran for L in o.data.uv_layers)]
        juntar = [o for o in juntar if o not in aparte]
    if len(juntar) > 1:
        with bpy.context.temp_override(active_object=juntar[0], selected_editable_objects=juntar,
                                       selected_objects=juntar):
            bpy.ops.object.join()
    p = juntar[0]
    p.name = f'horneado {zona}'
    p.data.uv_layers.active = p.data.uv_layers['bake']
    log(f'{zona}: {len(objs)} objetos -> 1 + {len(aparte)} aparte, UV {[L.name for L in p.data.uv_layers]}')
    return [p] + aparte


def agrupar(objs):
    """Junta los oclusores que comparten transform (menos objetos que sincronizar en cada pasada)."""
    grupos, out = defaultdict(list), []
    for o in objs:
        if [L for L in o.data.uv_layers if not L.name.startswith('.')]:
            out.append(o)
            continue
        grupos[tuple(round(v, 5) for fila in o.matrix_world for v in fila)].append(o)
    for g in grupos.values():
        if len(g) > 1:
            with bpy.context.temp_override(active_object=g[0], selected_editable_objects=g, selected_objects=g):
                bpy.ops.object.join()
        out.append(g[0])
    return out


def sin_metalicidad():
    """Metallic a 0 para el horneado DIFFUSE (si no, los metales salen negros). Marca los materiales metálicos."""
    def imagen_arriba(sock, prof=4):
        for l in sock.links:
            n = l.from_node
            if n.bl_idname == 'ShaderNodeTexImage' and n.image:
                return n.image
            if prof:
                for s in n.inputs:
                    if s.is_linked:
                        im = imagen_arriba(s, prof - 1)
                        if im:
                            return im
        return None

    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        for n in m.node_tree.nodes:
            if n.bl_idname != 'ShaderNodeBsdfPrincipled':
                continue
            s = n.inputs['Metallic']
            if s.is_linked:
                im = imagen_arriba(s)
                if im and im.size[0]:
                    if leer(im)[..., 0].mean() > 0.5:
                        m['metal'] = True
                for l in list(s.links):
                    m.node_tree.links.remove(l)
            elif s.default_value > 0.3:
                m['metal'] = True
            s.default_value = 0.0


PASES = (  # nombre, tipo, filtro, muestras (None = las del argumento)
    ('irr', 'DIFFUSE', {'DIRECT', 'INDIRECT'}, None),
    ('alb', 'DIFFUSE', {'COLOR'}, 16),
    ('emi', 'EMIT', None, 4),
    ('nor', 'NORMAL', None, 1),
)


def hornear_zona(sc, zona, objs, res, muestras, margen, cache):
    nodos = []
    for m in {s.material for o in objs for s in o.material_slots if s.material}:
        m.use_nodes = True
        nt = m.node_tree
        n = nt.nodes.get('HORNEAR') or nt.nodes.new('ShaderNodeTexImage')
        n.name = 'HORNEAR'
        nodos.append((nt, n))
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    tiempos = {}
    for nombre, tipo, filtro, mu in PASES:
        img = bpy.data.images.new(f'{zona}-{nombre}', res, res, alpha=True, float_buffer=True)
        # datos crudos: si queda marcada sRGB, el EXR se guarda convertido y se vuelve a leer como lineal
        img.colorspace_settings.name = 'Non-Color'
        for nt, n in nodos:
            n.image = img
            nt.nodes.active = n
        sc.cycles.samples = mu or muestras
        kw = dict(type=tipo, margin=margen, margin_type='ADJACENT_FACES', use_clear=True, target='IMAGE_TEXTURES',
                  uv_layer='bake')
        if filtro:
            kw['pass_filter'] = filtro
        if tipo == 'NORMAL':
            kw['normal_space'] = 'OBJECT'
        t0 = time.time()
        bpy.ops.object.bake(**kw)
        tiempos[nombre] = round(time.time() - t0)
        img.filepath_raw = str(cache / f'{zona}-{nombre}.exr')
        img.file_format = 'OPEN_EXR'
        img.save()
        bpy.data.images.remove(img)
        log(f'{zona} {nombre}: {tiempos[nombre]} s')
    return tiempos


def rellenar(a, m):
    """Push-pull: completa los texels vacíos (m == False) con el color de las islas más cercanas, a todas las escalas.
    Evita que los mipmaps mezclen negro en los bordes de las islas."""
    col, w = a * m[..., None], m.astype(np.float32)
    pir = []
    while True:
        pir.append((col, w))
        h, wd = col.shape[:2]
        if h <= 1 or wd <= 1:
            break
        col = col.reshape(h // 2, 2, wd // 2, 2, -1).sum((1, 3))
        w = w.reshape(h // 2, 2, wd // 2, 2).sum((1, 3))
    lleno = pir[-1][0] / np.maximum(pir[-1][1], 1e-8)[..., None]
    for col, w in reversed(pir[:-1]):
        arriba = np.repeat(np.repeat(lleno, 2, 0), 2, 1)
        lleno = np.where((w > 0)[..., None], col / np.maximum(w, 1e-8)[..., None], arriba)
    return lleno.astype(np.float32)


def denoise(irr, nor, archivo):
    """OIDN (nodo Denoise del compositor) sobre la irradiancia, con las normales horneadas de guía y albedo blanco
    (la irradiancia es la luz que vería una superficie blanca). Se corre en una escena aparte, sin nada que renderizar."""
    res = irr.shape[0]
    d = bpy.data.scenes.get('Denoise') or bpy.data.scenes.new('Denoise')
    d.render.engine = 'CYCLES'
    d.cycles.device = 'CPU'
    d.cycles.samples = 1
    d.render.resolution_x = d.render.resolution_y = res
    d.render.resolution_percentage = 100
    d.render.use_compositing = True
    d.render.use_sequencer = False
    if d.camera is None:
        cam = bpy.data.objects.new('Cam denoise', bpy.data.cameras.new('Cam denoise'))
        d.collection.objects.link(cam)
        d.camera = cam
    d.use_nodes = True
    nt = d.node_tree
    nt.nodes.clear()

    def nodo(nombre, arr):
        n = nt.nodes.new('CompositorNodeImage')
        n.image = imagen(nombre, arr)
        return n

    a = nodo('dn color', irr)
    b = nodo('dn normal', nor)
    c = nodo('dn albedo', np.ones((res, res, 3), np.float32))
    dn = nt.nodes.new('CompositorNodeDenoise')
    dn.use_hdr = True
    dn.prefilter = 'NONE'
    try:
        dn.quality = 'HIGH'
    except (AttributeError, TypeError):
        pass
    if 'HDR' in dn.inputs:
        dn.inputs['HDR'].default_value = True
    nt.links.new(a.outputs['Image'], dn.inputs['Image'])
    nt.links.new(b.outputs['Image'], dn.inputs['Normal'])
    nt.links.new(c.outputs['Image'], dn.inputs['Albedo'])
    out = nt.nodes.new('CompositorNodeComposite')
    nt.links.new(dn.outputs['Image'], out.inputs['Image'])
    s = d.render.image_settings
    s.file_format = 'OPEN_EXR'
    s.color_depth = '32'
    s.exr_codec = 'ZIP'
    d.render.filepath = str(archivo)
    bpy.ops.render.render(write_still=True, scene=d.name)
    im = bpy.data.images.load(str(archivo), check_existing=False)
    r = leer(im)[..., :3].copy()
    bpy.data.images.remove(im)
    return r


def guardar(sc, arr, ruta, calidad=85):
    """Guarda una imagen lineal (escena) con el manejo de color de la escena: AgX, look, exposición y balance."""
    h, w = arr.shape[:2]
    im = bpy.data.images.new('salida', w, h, alpha=False, float_buffer=True)
    im.colorspace_settings.name = 'Linear Rec.709'  # lineal de escena: recién ahí entra AgX
    px = np.ones((h, w, 4), np.float32)
    px[..., :3] = arr
    im.pixels.foreach_set(px.ravel())
    s = sc.render.image_settings
    fmt = 'WEBP' if str(ruta).endswith('.webp') else 'PNG'
    s.file_format = fmt
    s.color_mode = 'RGB'
    s.color_depth = '8'
    s.quality = calidad
    s.compression = 15
    im.save_render(str(ruta), scene=sc)
    bpy.data.images.remove(im)


def componer(sc, zona, cache, dest):
    t0 = time.time()
    capas = {}
    for nombre in ('irr', 'alb', 'emi', 'nor'):
        archivo = cache / f'{zona}-{nombre}.exr'
        if not archivo.exists() and nombre == 'emi':
            capas[nombre] = np.zeros_like(capas['irr'])
            continue
        im = bpy.data.images.load(str(archivo), check_existing=False)
        capas[nombre] = leer(im)
        bpy.data.images.remove(im)
    mask = capas['irr'][..., 3] > 0.5
    irr = rellenar(capas['irr'][..., :3], mask)
    alb = rellenar(capas['alb'][..., :3], mask)
    emi = rellenar(capas['emi'][..., :3], mask)
    nor = rellenar(capas['nor'][..., :3] * 2 - 1, mask)
    del capas
    irr = np.maximum(denoise(irr, nor, cache / f'{zona}-irr-dn.exr'), 0)
    final = alb * irr + emi
    res = final.shape[0]
    guardar(sc, final, dest / f'{zona}.webp', 85)
    m = final.reshape(res // 2, 2, res // 2, 2, 3).mean((1, 3))
    guardar(sc, m, dest / f'{zona}-m.webp', 85)
    log(f'{zona}: compuesto en {time.time() - t0:.0f} s (cobertura {mask.mean() * 100:.0f} %)')


def fondo_vista(sc, dest):
    """La foto del fondo pasa por el mismo manejo de color que en los panoramas (emisión × 1,6 → AgX)."""
    p = ROOT / 'img' / 'originales' / 'vista-lago.jpg'
    im = bpy.data.images.load(str(p), check_existing=True)
    a = srgb_a_lineal(leer(im)[..., :3]) * VISTA_FUERZA
    w = a.shape[1]
    if w > 4096:
        raise SystemExit('vista-lago.jpg más ancha que 4096: hay que achicarla')
    guardar(sc, a, dest / 'vista.webp', 85)
    # agua: el color de la franja de abajo de la foto, para que el plano del lago siga a la foto sin corte
    fila = a[: max(2, a.shape[0] // 30)].reshape(-1, 3).mean(0)
    tmp = dest / '_agua.png'
    guardar(sc, fila[None, None, :].repeat(2, 0).repeat(2, 1), tmp)
    c = bpy.data.images.load(str(tmp), check_existing=False)
    rgb = leer(c)[0, 0, :3]
    bpy.data.images.remove(c)
    tmp.unlink()
    return '#' + ''.join(f'{int(round(v * 255)):02x}' for v in rgb), rgb


# ------------------------------------------------------------------ exportación
def material_plano(nombre, color=(1, 1, 1), alpha=1.0, rough=1.0):
    m = bpy.data.materials.new(nombre)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = 0.0
    if alpha < 1:
        b.inputs['Alpha'].default_value = alpha
        for k, v in (('blend_method', 'BLEND'), ('surface_render_method', 'BLENDED')):
            try:
                setattr(m, k, v)
            except (AttributeError, TypeError):
                pass
    return m


def unir(objs, nombre):
    if len(objs) > 1:
        with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
            bpy.ops.object.join()
    o = objs[0]
    o.name = o.data.name = nombre
    return o


def mundo(o, coll):
    me = o.data.copy()
    me.transform(o.matrix_world)
    t = bpy.data.objects.new(o.name + '~', me)
    coll.objects.link(t)
    return t


def exportar(sc, dest, mallas_zona, vidrio, fondo, agua_lin):
    # los materiales de la escena dejan libres los nombres que lleva el glb
    for m in bpy.data.materials:
        if m.name in ('Vidrio', 'Vista', 'Agua', *ZONAS):
            m.name = m.name + ' (escena)'
    coll = bpy.data.collections.new('Exportar')
    sc.collection.children.link(coll)
    salida, cuentas, metales = [], {}, {}
    for zona in ZONAS:
        objs = []
        for me in mallas_zona[zona]:
            t = bpy.data.objects.new(me.name, me)
            coll.objects.link(t)
            objs.append(t)
        o = unir(objs, zona)
        tipos = [tipo_mat(s.material) for s in o.material_slots]
        mat = material_plano(zona)
        cuentas[zona] = 0
        for tipo, p in partir_caras(o, lambda ob, f, M, N: tipos[f.material_index] if tipos else 'base').items():
            p.data.materials.clear()
            p.data.materials.append(mat)
            p.data.polygons.foreach_set('material_index', np.zeros(len(p.data.polygons), np.int32))
            quitar_uv(p.data, 'bake')
            p.name = p.data.name = zona if tipo == 'base' else f'{zona}-{tipo}'
            if tipo != 'base':
                metales[p.name] = tipo
            cuentas[zona] += tris(p.data)
            salida.append(p)
    v = unir([mundo(o, coll) for o in vidrio], 'Vidrio')
    v.data.materials.clear()
    v.data.materials.append(material_plano('Vidrio', VIDRIO, alpha=0.15, rough=0.05))
    quitar_uv(v.data)
    salida.append(v)
    for o in fondo:
        t = mundo(o, coll)
        nombre = o.name
        o.name = o.data.name = nombre + ' (escena)'
        t.name = t.data.name = nombre
        t.data.materials.clear()
        t.data.materials.append(material_plano('Vista') if nombre == 'Vista' else
                                material_plano('Agua', tuple(float(c) for c in agua_lin)))
        salida.append(t)
    for o in sc.objects:
        o.select_set(False)
    for o in salida:
        o.select_set(True)
    bpy.context.view_layer.objects.active = salida[0]
    glb = dest / 'depto.glb'
    bpy.ops.export_scene.gltf(**opciones(
        bpy.ops.export_scene.gltf, filepath=str(glb), export_format='GLB', use_selection=True,
        export_texcoords=True, export_normals=False, export_tangents=False, export_materials='EXPORT',
        export_image_format='NONE', export_apply=True, export_yup=True, export_cameras=False, export_lights=False,
        export_extras=False, export_vertex_color='NONE', export_attributes=False, export_animations=False,
        export_skins=False, export_morph=False))
    cuentas['Vidrio'] = tris(v.data)
    cuentas['fondo'] = sum(tris(o.data) for o in salida if o.name in ('Vista', 'Lago'))
    return cuentas, metales


# ------------------------------------------------------------------ colisiones y manifiesto
def cajas_colision(sc):
    """Rectángulos [x0, y0, x1, y1] (planta de Blender) de todo lo que frena el paso entre 0,1 y 1,7 m de altura.
    Los muebles armados (grupos y modelos) van en una sola caja; los objetos girados usan su caja en planta."""
    grupos = defaultdict(list)
    for o in sc.objects:
        if o.type != 'MESH':
            continue
        r = o
        while r.parent:
            r = r.parent
        if o.name.startswith(NO_CHOCA) or r.name.startswith(NO_CHOCA):
            continue
        lo, hi = caja([o])
        if hi[2] < 0.1 or lo[2] > 1.7 or (hi - lo)[:2].min() <= 0:
            continue
        grupos[r.name if r is not o else o.name].append((lo, hi))
    cajas = []
    for g in grupos.values():
        lo = np.min([a for a, _ in g], 0)
        hi = np.max([b for _, b in g], 0)
        cajas.append([round(float(lo[0]), 2), round(float(lo[1]), 2), round(float(hi[0]), 2), round(float(hi[1]), 2)])
    # bordes del balcón (más allá de la baranda no hay losa)
    cajas += [[-0.3, 0.0, -0.2, 2.45], [13.2, 0.0, 13.3, 2.45]]
    cajas = sorted({tuple(c) for c in cajas})
    dentro = lambda a, b: a != b and b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]  # noqa: E731
    return [list(a) for a in cajas if not any(dentro(a, b) for b in cajas)]


def escribir_js(ruta, rel, res, dens, cuentas, metales, agua, cajas, tiempos):
    data = {
        'glb': f'{rel}/depto.glb',
        'eye': EYE,
        'height': H,
        'chunks': [{'name': z, 'tex': f'{rel}/{z}.webp', 'texM': f'{rel}/{z}-m.webp', 'res': res,
                    'tris': cuentas[z], 'tpm': round(dens[z] * res)} for z in ZONAS],
        'metal': metales,
        'glass': {'mesh': 'Vidrio', 'material': 'Vidrio', 'color': [round(c, 3) for c in VIDRIO], 'opacity': 0.15},
        'backdrop': {'vista': {'mesh': 'Vista', 'material': 'Vista', 'tex': f'{rel}/vista.webp'},
                     'agua': {'mesh': 'Lago', 'material': 'Agua', 'color': agua}},
        'views': {v: {'label': depto.LABELS[v], 'pos': [x, y], 'yaw': yaw} for v, ((x, y), yaw) in depto.VIEWS.items()},
        'walk': [[-0.2, 2.33], [13.2, 2.33], [13.2, 0], [13, 0], [13, -10], [0, -10], [0, 0], [-0.2, 0]],
        'boxes': cajas,
    }
    txt = ('// Generado por tools/hornear.py: recorrido en tiempo real del departamento modelo (tipo L2), luz horneada en Cycles.\n'
           '// Coordenadas de Blender en metros: x = este, y = norte, z = arriba. En three.js (glTF, Y arriba): (x, z, -y).\n'
           '// views.yaw: grados desde el norte en sentido horario (three.js: camera.rotation.y = -yaw en radianes).\n'
           '// chunks: un material por zona en el glb; textura con flipY = false y colorSpace sRGB, y se muestra tal cual\n'
           '// (MeshBasicMaterial, sin tone mapping). texM: versión 2048 para celulares. tpm: texels por metro en pisos y paredes.\n'
           '// metal: mallas que conviene reflejar (la textura tiene su color base iluminado). glass: transparente.\n'
           '// boxes: rectángulos [x0, y0, x1, y1] que frenan el paso (z entre 0,1 y 1,7 m). walk: contorno caminable.\n'
           f'export const DEPTO3D = {json.dumps(data, ensure_ascii=False, separators=(",", ":"))};\n')
    ruta.write_text(txt, encoding='utf-8')
    log(f'{ruta.relative_to(ROOT)} listo ({len(cajas)} cajas)')


# ------------------------------------------------------------------ control visual
def recorte_pano(pano, pos, yaw, pitch, hfov, W, Hh):
    """Vista en perspectiva sacada del panorama equirectangular (pano: arreglo de arriba hacia abajo)."""
    ph, pw = pano.shape[:2]
    t = math.tan(math.radians(hfov) / 2)
    ps, pc = math.radians(yaw), math.radians(pitch)
    f = np.array([math.sin(ps) * math.cos(pc), math.cos(ps) * math.cos(pc), math.sin(pc)])
    r = np.array([math.cos(ps), -math.sin(ps), 0.0])
    u = np.cross(r, f)
    xs = (2 * (np.arange(W) + 0.5) / W - 1) * t
    ys = (1 - 2 * (np.arange(Hh) + 0.5) / Hh) * t * Hh / W
    d = f + xs[None, :, None] * r + ys[:, None, None] * u
    lon = np.arctan2(d[..., 0], d[..., 1])
    lat = np.arctan2(d[..., 2], np.hypot(d[..., 0], d[..., 1]))
    px = ((0.5 + lon / (2 * np.pi)) % 1.0) * pw - 0.5
    py = np.clip((0.5 - lat / np.pi) * ph - 0.5, 0, ph - 1.001)
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    fx, fy = (px - x0)[..., None], (py - y0)[..., None]
    x0, x1, y1 = x0 % pw, (x0 + 1) % pw, y0 + 1
    return ((pano[y0, x0] * (1 - fx) + pano[y0, x1] * fx) * (1 - fy)
            + (pano[y1, x0] * (1 - fx) + pano[y1, x1] * fx) * fy)


def referencias(salida):
    """Render de Cycles (escena original) de las vistas de control de REFERENCIAS."""
    W, Hh, fov, pitch = CHEQUEO
    sc = depto.build()
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, Hh, 100
    sc.cycles.samples = 128
    cam = depto.camera(False, fov)
    salida.mkdir(parents=True, exist_ok=True)
    for vista in REFERENCIAS:
        for k, yaw in enumerate(REVISAR[vista]):
            depto.aim(cam, depto.VIEWS[vista][0], yaw, pitch)
            sc.render.filepath = str(salida / f'ref-{vista}-{k}.png')
            bpy.ops.render.render(write_still=True)
    log('referencias listas')


def faltan_referencias(salida):
    t = (pathlib.Path(depto.__file__)).stat().st_mtime
    fs = [salida / f'ref-{v}-{k}.png' for v in REFERENCIAS for k in range(len(REVISAR[v]))]
    return any(not f.exists() or f.stat().st_mtime < t for f in fs)


def revisar(dest, salida):
    sc = depto.reset()
    sc.render.use_persistent_data = False
    vs = sc.view_settings
    vs.view_transform, vs.look, vs.exposure, vs.gamma = 'Standard', 'None', 0.0, 1.0
    vs.use_white_balance = False
    c = sc.cycles
    c.samples, c.use_denoising, c.use_adaptive_sampling = 24, False, False
    c.max_bounces = 0
    bpy.ops.import_scene.gltf(filepath=str(dest / 'depto.glb'))
    texturas = {}
    for o in list(sc.objects):
        if o.type != 'MESH':
            continue
        for s in o.material_slots:
            m, b = s.material, base(s.material.name)
            if b == 'Vidrio':
                o.hide_render = True
                continue
            nt = m.node_tree
            col = tuple(nt.nodes['Principled BSDF'].inputs['Base Color'].default_value) if b == 'Agua' else None
            nt.nodes.clear()
            e = nt.nodes.new('ShaderNodeEmission')
            nt.links.new(e.outputs[0], nt.nodes.new('ShaderNodeOutputMaterial').inputs[0])
            if col:
                e.inputs[0].default_value = col
                continue
            ruta = dest / ('vista.webp' if b == 'Vista' else f'{b}.webp')
            if ruta not in texturas:
                texturas[ruta] = bpy.data.images.load(str(ruta))
            t = nt.nodes.new('ShaderNodeTexImage')
            t.image = texturas[ruta]
            t.extension = 'EXTEND'
            nt.links.new(t.outputs[0], e.inputs[0])
    W, Hh, fov, pitch = CHEQUEO
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, Hh, 100
    cam = depto.camera(False, fov)
    salida.mkdir(parents=True, exist_ok=True)
    for vista, giros in REVISAR.items():
        (pos, _) = depto.VIEWS[vista]
        im = bpy.data.images.load(str(depto.OUT / f'pano-{vista}.png'))
        pano = leer(im)[::-1, :, :3].copy()
        bpy.data.images.remove(im)
        filas = []
        for k, yaw in enumerate(giros):
            depto.aim(cam, pos, yaw, pitch)
            f = salida / f'_{vista}-{k}.png'
            sc.render.filepath = str(f)
            bpy.ops.render.render(write_still=True)
            r = bpy.data.images.load(str(f), check_existing=False)
            horneado = leer(r)[::-1, :, :3].copy()
            bpy.data.images.remove(r)
            f.unlink()
            fr = salida / f'ref-{vista}-{k}.png'
            if vista in REFERENCIAS and fr.exists():
                r = bpy.data.images.load(str(fr), check_existing=False)
                ref = leer(r)[::-1, :, :3].copy()
                bpy.data.images.remove(r)
            else:
                ref = recorte_pano(pano, pos, yaw, pitch, fov, W, Hh)
            sep = np.full((Hh, 8, 3), 0.08, np.float32)
            filas.append(np.concatenate([ref, sep, horneado], 1))
            filas.append(np.full((8, W * 2 + 8, 3), 0.08, np.float32))
        hoja = np.concatenate(filas[:-1], 0)
        h, w = hoja.shape[:2]
        out = bpy.data.images.new(f'hoja {vista}', w, h, alpha=False)
        px = np.ones((h, w, 4), np.float32)
        px[..., :3] = hoja[::-1]
        out.pixels.foreach_set(px.ravel())
        out.filepath_raw = str(salida / f'{vista}.jpg')
        out.file_format = 'JPEG'
        sc.render.image_settings.quality = 88
        out.save()
        log(f'hoja de control: {(salida / f"{vista}.jpg").relative_to(ROOT)}')


# ------------------------------------------------------------------ principal
def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='hornear.py')
    ap.add_argument('--res', type=int, default=4096, help='lado del atlas de cada zona')
    ap.add_argument('--muestras', type=int, default=512, help='muestras de la irradiancia')
    ap.add_argument('--zonas', help='zonas a hornear, separadas por coma (las demás salen del caché)')
    ap.add_argument('--sin-hornear', action='store_true', help='todo desde el caché de EXR')
    ap.add_argument('--rapido', action='store_true', help='prueba a 1024² con 48 muestras en 3d/out/hornear-rapido')
    ap.add_argument('--sin-revisar', action='store_true', help='no armar las hojas de control al final')
    ap.add_argument('--solo-revisar', action='store_true')
    ap.add_argument('--referencias', action='store_true', help='renders de Cycles para las hojas de las suites')
    a = ap.parse_args(argv)
    if a.rapido:
        a.res, a.muestras = 1024, 48
        dest = depto.OUT / 'hornear-rapido'
        cache, js, check = dest / 'cache', dest / 'depto3d.js', dest / 'check'
    else:
        dest, cache = ROOT / 'img' / 'depto3d', depto.OUT / 'hornear'
        js, check = ROOT / 'js' / 'depto3d.js', depto.OUT / 'bake-check'
    for d in (dest, cache):
        d.mkdir(parents=True, exist_ok=True)
    if a.referencias:
        referencias(check)
        return
    if a.solo_revisar:
        revisar(dest, check)
        return

    t_ini = time.time()
    margen_px = max(2, round(a.res / 800))
    sc = depto.build()
    sc.render.use_persistent_data = False
    cajas = cajas_colision(sc)
    hornear, vidrio, fondo = preparar(sc)
    zonas = repartir(hornear)
    mallas, dens, firmas = {}, {}, {}
    for z in ZONAS:
        mallas[z], dens[z], firmas[z] = desplegar(sc, z, zonas[z], a.res, margen_px)
        log(f'{z}: {dens[z] * a.res:.0f} texels/m en pisos y paredes')
    sin_metalicidad()
    for z in ZONAS:
        zonas[z] = unificar(z, zonas[z])

    meta_f = cache / 'firmas.json'
    previas = json.loads(meta_f.read_text()) if meta_f.exists() else {}
    pedir = set(ZONAS) if not (a.zonas or a.sin_hornear) else set(a.zonas.split(',')) if a.zonas else set()
    tiempos = {}
    t_bake = time.time()
    for z in ZONAS:
        if z in pedir:
            tiempos[z] = hornear_zona(sc, z, zonas[z], a.res, a.muestras, margen_px, cache)
            previas[z] = {'firma': firmas[z], 'res': a.res, 'muestras': a.muestras}
            meta_f.write_text(json.dumps(previas, indent=1))
        elif previas.get(z, {}).get('firma') != firmas[z] or previas[z].get('res') != a.res:
            log(f'AVISO {z}: la UV no coincide con la del caché; conviene volver a hornearla')
    t_bake = time.time() - t_bake
    for z in ZONAS:
        componer(sc, z, cache, dest)
    agua, agua_lin = fondo_vista(sc, dest)
    cuentas, metales = exportar(sc, dest, mallas, vidrio, fondo, agua_lin)
    rel = dest.relative_to(ROOT).as_posix()
    escribir_js(js, rel, a.res, dens, cuentas, metales, agua, cajas, tiempos)

    log('triángulos:', json.dumps(cuentas), 'total', sum(cuentas.values()))
    log('tiempos de horneado (s):', json.dumps(tiempos))
    log(f'horneado {t_bake / 60:.1f} min, total {(time.time() - t_ini) / 60:.1f} min')
    tam = {p.name: p.stat().st_size for p in sorted(dest.iterdir()) if p.is_file()}
    log('archivos:', ', '.join(f'{k} {v / 1e6:.2f} MB' for k, v in tam.items()))
    log(f'escritorio: {sum(v for k, v in tam.items() if not k.endswith("-m.webp")) / 1e6:.1f} MB · '
        f'celular: {sum(v for k, v in tam.items() if k.endswith("-m.webp") or not k.endswith(".webp") or k == "vista.webp") / 1e6:.1f} MB')
    if not a.sin_revisar:
        cmd = [bpy.app.binary_path, '-b', '--factory-startup', '-P', __file__, '--'] + (['--rapido'] if a.rapido else [])
        if faltan_referencias(check):
            subprocess.run(cmd + ['--referencias'], check=False)
        subprocess.run(cmd + ['--solo-revisar'], check=False)


if __name__ == '__main__':
    main()
