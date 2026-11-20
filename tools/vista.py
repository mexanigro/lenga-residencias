"""La vista por las ventanas: una foto real con el lago renderizado.

La foto de antes (img/originales/vista-lago.jpg) medía 2752 × 1536, la medida de Nano Banana: casi seguro de IA, y la
regla 1 no deja mostrar en la web final nada generado. Esta sale de la panorámica `montorfano` de Poly Haven (CC0,
tomada sobre el Lago Maggiore: lago y montañas boscosas, como un lago patagónico), bajada por tools/polyhaven.py.

Escena chica: el mundo es la panorámica tonemapeada (sRGB, con la vista Standard los píxeles salen iguales) y un plano
de agua a la altura del lago, ALTO metros abajo de los ojos, que tapa el suelo de la foto y refleja las montañas. Se
renderiza un 360° equirectangular mirando al norte y se pasa a la proyección del cilindro de depto.backdrop(): 180° de
ancho y alto lineal en tan(φ), de −TAN a +TAN.

  blender -b --factory-startup -P tools/vista.py -- [MUESTRAS=64]   -> assets/fotos/vista.jpg (depto.VISTA)
  ... -- cilindro                                                  solo la proyección, sobre 3d/out/vista/360.png
"""
import math
import pathlib
import sys

import bpy
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import depto as D  # noqa: E402

FOTO = D.ASSETS / 'fotos' / 'montorfano.jpg'
GIRO = 90.0  # grados: el borde de la panorámica (lago y cordillera; en el centro hay un cerro) queda al norte
ALTO = 32.5  # m del lago a los ojos: piso 10, ~3,1 m por piso, más 1,55
TAN = 0.877  # medio alto del cilindro / radio: el de la foto vieja (±41°)


def escena(muestras):
    D.reset()
    sc = bpy.context.scene
    w = bpy.data.worlds.new('Panorámica')
    sc.world = w
    w.use_nodes = True
    N, L = w.node_tree.nodes, w.node_tree.links
    tc, mp, env = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeMapping'), N.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(str(FOTO))
    mp.inputs['Rotation'].default_value[2] = math.radians(GIRO)
    L.new(tc.outputs['Generated'], mp.inputs['Vector'])
    L.new(mp.outputs['Vector'], env.inputs['Vector'])
    L.new(env.outputs['Color'], N['Background'].inputs['Color'])
    N['Background'].inputs['Strength'].default_value = 1.0
    # agua calma con ondas de viento: casi un espejo, oscura donde no refleja
    bpy.ops.mesh.primitive_plane_add(size=200000, location=(0, 0, -ALTO))
    agua = bpy.context.object
    agua.name = 'Agua'
    m = bpy.data.materials.new('Agua')
    m.use_nodes = True
    MN, ML = m.node_tree.nodes, m.node_tree.links
    b = MN['Principled BSDF']
    b.inputs['Base Color'].default_value = (0.012, 0.022, 0.026, 1)
    b.inputs['Roughness'].default_value = 0.025
    b.inputs['IOR'].default_value = 1.33
    co, ruido, bump = MN.new('ShaderNodeTexCoord'), MN.new('ShaderNodeTexNoise'), MN.new('ShaderNodeBump')
    esc = MN.new('ShaderNodeMapping')
    esc.inputs['Scale'].default_value = (0.08, 0.25, 1)  # ondas alargadas, de 4 a 12 m
    ML.new(co.outputs['Object'], esc.inputs['Vector'])
    ML.new(esc.outputs['Vector'], ruido.inputs['Vector'])
    ruido.inputs['Detail'].default_value = 6
    bump.inputs['Strength'].default_value = 0.1
    bump.inputs['Distance'].default_value = 0.05
    ML.new(ruido.outputs['Fac'], bump.inputs['Height'])
    ML.new(bump.outputs['Normal'], b.inputs['Normal'])
    agua.data.materials.append(m)
    cam = bpy.data.objects.new('Ojo', bpy.data.cameras.new('Ojo'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = 'PANO'
    cam.data.panorama_type = 'EQUIRECTANGULAR'
    cam.rotation_euler = (math.radians(90), 0, 0)  # mira al norte (+y): el centro del 360° es el norte
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 8192, 4096, 100
    sc.cycles.samples = muestras
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '16'
    sc.render.filepath = str(D.OUT / 'vista' / '360.png')
    bpy.ops.render.render(write_still=True)
    return D.OUT / 'vista' / '360.png'


def cilindro(src, dest, ancho=4096):
    """Equirectangular (centro = norte) a cilindro central de 180°: columnas lineales en el rumbo, filas en tan(φ)."""
    im = bpy.data.images.load(str(src))
    im.colorspace_settings.name = 'Non-Color'  # los valores tal cual (sRGB), sin pasarlos a lineal
    w, h = im.size
    px = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(px)
    eq = px.reshape(h, w, 4)[::-1, :, :3]  # Blender guarda de abajo hacia arriba
    alto = round(ancho * 2 * TAN / math.pi)
    a = (np.arange(ancho) + 0.5) / ancho * math.pi - math.pi / 2
    t = (0.5 - (np.arange(alto) + 0.5) / alto) * 2 * TAN
    phi = np.arctan(t)
    u = (0.5 + a / (2 * math.pi)) * w - 0.5
    v = (0.5 - phi / math.pi) * h - 0.5
    uu, vv = np.meshgrid(u, v)
    x0, y0 = np.floor(uu).astype(int), np.floor(vv).astype(int)
    fx, fy = (uu - x0)[..., None], (vv - y0)[..., None]
    x1, y1 = np.clip(x0 + 1, 0, w - 1), np.clip(y0 + 1, 0, h - 1)
    x0, y0 = np.clip(x0, 0, w - 1), np.clip(y0, 0, h - 1)
    out = (eq[y0, x0] * (1 - fx) * (1 - fy) + eq[y0, x1] * fx * (1 - fy)
           + eq[y1, x0] * (1 - fx) * fy + eq[y1, x1] * fx * fy)
    res = bpy.data.images.new('Vista cilindro', ancho, alto, alpha=False)
    res.colorspace_settings.name = 'Non-Color'  # antes de cargarle los píxeles: cambiarlo después la regenera negra
    flat = np.concatenate([out[::-1], np.ones((alto, ancho, 1))], axis=2).astype(np.float32).ravel()
    res.pixels.foreach_set(flat)  # los píxeles del PNG ya están en sRGB: se guardan tal cual
    res.filepath_raw = str(dest)
    res.file_format = 'JPEG'
    bpy.context.scene.render.image_settings.quality = 92
    res.save()
    print('VISTA', dest, ancho, 'x', alto)


if __name__ == '__main__':
    a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    (D.OUT / 'vista').mkdir(parents=True, exist_ok=True)
    # «cilindro»: solo rehace la proyección sobre el 360° ya renderizado
    cilindro(D.OUT / 'vista' / '360.png' if 'cilindro' in a else escena(int(a[0]) if a else 64), D.VISTA)
