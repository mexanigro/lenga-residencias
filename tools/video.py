"""Recorrido guiado en video: piloto del living y la cocina (sección 4.9 de 03-construccion-web.md).

Cada ambiente tiene tres ángulos fijos, elegidos como los de una foto (área 2 del método): nivelados, con shift en
vez de inclinar la cámara, 75° horizontales. Los TRAMOS unen ángulos vecinos (los de un ambiente en cadena, y un par
de ángulos entre ambientes); el sitio los encadena para ir de cualquier ángulo a cualquier otro. Cada tramo se
renderiza una vez: la escena está quieta y solo se mueve la cámara, así que el sentido contrario es el mismo video al
revés. Cada tramo empieza y termina exactamente en el cuadro de su ángulo (misma cámara, misma semilla).

  blender -b 3d/out/depto.blend --factory-startup -P tools/video.py -- angulos [MUESTRAS] [PCT]
  ... -- tramo living-1~living-2[,otro] [MUESTRAS] [PCT]   -> 3d/out/video/<tramo>/0001.png ...
  python tools/video.py codificar [-25]                    -> video/*.mp4 (ida y vuelta, 1080p y 720p), *.webp, js/video.js
"""
import json
import math
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / '3d' / 'out' / 'video'
WEB = ROOT / 'video'
FPS = 30
FOV = 75  # grados horizontales: 26 mm en 16:9

# nombre: ((x, y, z), rumbo en grados desde el norte en sentido horario, shift vertical)
ANGULOS = {
    'living-1': ((6.9, -4.75, 1.15), -50, -0.06),   # desde el paso a la cocina: el estar entero, hogar y lago
    'living-2': ((4.6, -4.6, 1.15), -56, -0.06),    # junto al sofá: el hogar, las butacas y el lago (a -50 asomaba un almohadón)
    'living-3': ((1.5, -4.85, 1.15), 42, -0.02),    # desde la entrada: el sofá de frente y el lago
    'kitchen-1': ((6.2, -4.6, 1.3), 55, -0.04),      # desde el living: la isla, el balcón y el lago
    'kitchen-2': ((7.6, -0.9, 1.3), 125, -0.04),    # desde la ventana: la isla con banquetas y la cocina al fondo
    'kitchen-3': ((12.45, -4.75, 1.3), 306, -0.04),  # desde el fondo: la isla, el hogar y el lago
}
LABELS = {'living': 'Living', 'kitchen': 'Cocina y comedor'}
NOMBRES = {'living-1': 'Living', 'living-2': 'Hogar', 'living-3': 'Hacia el lago',
           'kitchen-1': 'Cocina', 'kitchen-2': 'Comedor', 'kitchen-3': 'Isla y living'}  # botones del sitio
# a, b, puntos de paso (x, y) para esquivar muebles. La cocina 1 es el centro: queda al lado del living 1.
TRAMOS = [
    ('living-1', 'living-2', []),
    ('living-2', 'living-3', []),
    ('living-1', 'kitchen-1', []),
    ('kitchen-1', 'kitchen-2', []),
    ('kitchen-1', 'kitchen-3', [(8.3, -4.45), (11.0, -4.45)]),  # por el pasillo entre la isla y la mesada
]
HOLGURA = 0.25  # m: la cámara nunca pasa más cerca de un mueble o una pared


def nombre(a, b):
    return f'{a}~{b}'


def cuadros(a, b, via):
    """Poses de cámara de a hasta b: posición por una curva suave, arranca y frena despacio, el giro acompaña."""
    import depto as D
    from mathutils import Vector
    (pa, ya, sa), (pb, yb, sb) = ANGULOS[a], ANGULOS[b]
    poly, cum = D.dense_path([pa[:2], *via, pb[:2]])
    largo = cum[-1]
    giro = (yb - ya + 180) % 360 - 180
    seg = min(7.0, max(2.5, largo / 0.75, abs(giro) / 28))  # ~0,75 m/s y ~28°/s de promedio, como un gimbal
    n = round(seg * FPS) + 1
    out = []
    for k in range(n):
        t = k / (n - 1)
        e = t * t * (3 - 2 * t)
        p = D.at(poly, cum, e * largo) if 0 < k < n - 1 else Vector(pa[:2] if k == 0 else pb[:2])
        out.append(((p.x, p.y, pa[2] + (pb[2] - pa[2]) * e), ya + giro * e, sa + (sb - sa) * e))
    return out


def preparar():
    import bpy
    sys.path.insert(0, str(ROOT / 'tools'))
    import depto as D
    import habitacion as H
    sc = bpy.context.scene
    # las colisiones de las simulaciones de tela dependen del tiempo: con ellas, cada cuadro vuelve a cargar toda la
    # escena (25 s de más por cuadro). Las telas ya están hechas, así que en el video sobran.
    for o in sc.objects:
        for m in [m for m in o.modifiers if m.type == 'COLLISION']:
            o.modifiers.remove(m)
    pr = bpy.context.preferences.addons['cycles'].preferences
    pr.compute_device_type = 'OPTIX'
    pr.get_devices()
    for d in pr.devices:
        d.use = d.type == 'OPTIX'
    sc.cycles.device = 'GPU'
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.fps = FPS
    sc.render.use_motion_blur = True  # obturador de 1/60 s a 30 cuadros: los giros se ven como en una cámara
    sc.render.motion_blur_shutter = 0.5
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '8'
    H.revelado()
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    co = D.camera(False, FOV)
    return sc, co


def poner(co, pos, rumbo, shift):
    co.location = pos
    co.rotation_euler = (math.radians(90), 0, math.radians(-rumbo))
    co.data.shift_y = shift


def holgura(cs):
    """Distancia mínima del camino a lo que lo rodea: rayos horizontales a la altura de la cámara y a 0,5 m (asientos
    y mesas, que la cámara no puede atravesar aunque pase por arriba)."""
    import bpy
    from mathutils import Vector
    dg = bpy.context.evaluated_depsgraph_get()
    sc = bpy.context.scene
    mins = 9.0
    for pos, _, _ in cs[::3]:
        for z in (pos[2], 0.5):
            for k in range(16):
                ang = k * math.pi / 8
                hit, loc, *_ = sc.ray_cast(dg, Vector((pos[0], pos[1], z)), Vector((math.cos(ang), math.sin(ang), 0)),
                                           distance=2.0)
                if hit:
                    mins = min(mins, (loc - Vector((pos[0], pos[1], z))).length)
    return mins


def blender(args):
    import bpy
    sc, co = preparar()
    modo = args[0]
    i = 1 if modo == 'angulos' else 2  # después del modo (y de la lista de tramos o candidatos): MUESTRAS y PCT
    muestras = int(args[i]) if len(args) > i else 256
    pct = int(args[i + 1]) if len(args) > i + 1 else 100
    sc.cycles.samples = muestras
    sc.render.resolution_percentage = pct
    sufijo = '' if pct == 100 else f'-{pct}'
    if modo == 'prueba':  # prueba nombre=x,y,z,rumbo,shift[;otro=...] MUESTRAS PCT: candidatos antes de fijar un ángulo
        for item in args[1].split(';'):
            n, v = item.split('=')
            x, y, z, rumbo, shift = (float(c) for c in v.split(','))
            poner(co, (x, y, z), rumbo, shift)
            sc.render.filepath = str(OUT / 'pruebas' / f'{n}.png')
            bpy.ops.render.render(write_still=True)
        return
    if modo == 'revisar':  # antes de renderizar: cuadros y holgura de cada tramo
        for a, b, v in TRAMOS:
            cs = cuadros(a, b, v)
            print('REVISAR', nombre(a, b), len(cs), 'cuadros', round(holgura(cs), 2), 'm', flush=True)
        return
    if modo == 'angulos':
        for n, (pos, rumbo, shift) in ANGULOS.items():
            poner(co, pos, rumbo, shift)
            sc.render.filepath = str(OUT / f'angulos{sufijo}' / f'{n}.png')
            bpy.ops.render.render(write_still=True)
            print('ANGULO', n, flush=True)
        return
    via = {nombre(a, b): v for a, b, v in TRAMOS}
    for t in args[1].split(','):
        a, b = t.split('~')
        cs = cuadros(a, b, via[t])
        cerca = holgura(cs)
        print('HOLGURA', t, round(cerca, 2), 'm', flush=True)
        if cerca < HOLGURA:
            raise SystemExit(f'{t}: la cámara pasa a {cerca:.2f} m de algo; mover los puntos de paso')
        for f, (pos, rumbo, shift) in enumerate(cs, 1):
            poner(co, pos, rumbo, shift)
            for path in ('location', 'rotation_euler'):
                co.keyframe_insert(path, frame=f)
            co.data.keyframe_insert('shift_y', frame=f)
        sc.frame_start, sc.frame_end = 1, len(cs)
        sc.render.use_overwrite = False  # se puede cortar y retomar
        sc.render.filepath = str(OUT / f'{t}{sufijo}' / '####')
        bpy.ops.render.render(animation=True)
        print('TRAMO', t, len(cs), 'cuadros', flush=True)
        co.animation_data_clear()
        co.data.animation_data_clear()


def codificar(origen=''):
    """Cada tramo a MP4 H.264 en los dos sentidos, para escritorio (1080p) y celular (720p); el cuadro de cada ángulo
    en WebP (lo que se ve al entrar, antes de moverse) y js/video.js. origen '-25': desde el borrador, para probar el sitio."""
    WEB.mkdir(exist_ok=True)

    def ff(*args):
        subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], check=True)

    moves = {}
    for a, b, _ in TRAMOS:
        src = OUT / (nombre(a, b) + origen) / '%04d.png'
        n = len(list((OUT / (nombre(a, b) + origen)).glob('*.png')))
        for p, q, rev in ((a, b, ''), (b, a, ',reverse')):
            for alto, crf, suf in ((1080, 23, ''), (720, 25, '-m')):
                ff('-framerate', str(FPS), '-i', str(src), '-vf', f'scale=-2:{alto}:flags=lanczos,format=yuv420p{rev}',
                   '-c:v', 'libx264', '-preset', 'slow', '-crf', str(crf), '-tune', 'film', '-g', str(FPS),
                   '-movflags', '+faststart', '-an', str(WEB / f'{p}~{q}{suf}.mp4'))
            moves[f'{p}~{q}'] = n
    for k in ANGULOS:
        a, b, _ = next(t for t in TRAMOS if k in t[:2])
        d = OUT / (nombre(a, b) + origen)
        png = d / '0001.png' if k == a else sorted(d.glob('*.png'))[-1]
        for ancho, suf in ((1920, ''), (1280, '-m')):
            ff('-i', str(png), '-vf', f'scale={ancho}:-2:flags=lanczos', '-c:v', 'libwebp', '-quality', '85',
               str(WEB / f'{k}{suf}.webp'))
    angulos = {k: {'room': k.split('-')[0], 'name': NOMBRES[k], 'pos': [v[0][0], -v[0][1]], 'yaw': v[1]}
               for k, v in ANGULOS.items()}
    data = {'fps': FPS, 'labels': LABELS, 'angles': angulos, 'moves': moves}
    (ROOT / 'js' / 'video.js').write_text(
        '// Generado por tools/video.py: recorrido guiado en video (piloto: living y cocina).\n'
        '// angles: ángulos fijos (pos en el plano, m; yaw en grados desde el norte). moves: tramos y sus cuadros.\n'
        f'export const VIDEO = {json.dumps(data, ensure_ascii=False)};\n', encoding='utf-8')
    for f in sorted(WEB.iterdir()):
        print(f.name, f.stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    if argv and argv[0] == 'codificar':
        codificar(*argv[1:2])
    else:
        sys.path.insert(0, str(ROOT / 'tools'))
        blender(argv)
