# -*- coding: utf-8 -*-
"""Lenga - Residencias sobre el lago Ilen. Generador del legajo de planos.

Estudio Ilen Sur Arquitectos (ficticio) - Proyecto 2026-014 - Comitente: Lenga Desarrollos S.A. (ficticio).

Uso, desde la raiz del repositorio:
    python -I planos/fuente/generar.py               laminas PDF, PDF combinado y DXF
    python -I planos/fuente/generar.py --png DIR     ademas, vistas previas PNG de cada lamina en DIR

Fuentes que lee (no las modifica):
    js/data.js         pisos, giro por planta, tipologias (ambientes y superficies), unidades por piso
    js/building.js     encuadre de la losa en el sitio (+-13 m)
    tools/depto.py     departamento modelo L2: muros, aberturas, equipamiento y puntos 360 (se lee con ast)
Requiere reportlab, pypdf y shapely. Opcionales: ezdxf (DXF) y pypdfium2 (PNG).
"""
import argparse
import ast
import json
import math
import pathlib
import re
import sys

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from shapely.geometry import LineString, Point, Polygon, box as sbox
from shapely.ops import unary_union
from shapely import affinity

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / 'planos'
MM = 72.0 / 25.4  # puntos por mm

# ===================================================================== datos del proyecto
STUDIO = 'ILÉN SUR ARQUITECTOS'
STUDIO_SUB = 'Arquitectura y urbanismo · Puerto Ilén, Patagonia'
PROJECT = 'LENGA'
PROJECT_SUB = 'Residencias sobre el lago Ilén'
PROJECT_KIND = 'Torre de viviendas con club · 18 niveles'
CLIENT = 'Lenga Desarrollos S.A.'
PROJ_NO = '2026-014'
ADDRESS = 'Av. Costanera del Ilén s/n° · Puerto Ilén · Patagonia · Argentina'
CATASTRO = 'Circ. I · Secc. B · Manz. 12 · Parc. 4a'
PHASE = 'Legajo de planos · documentación para comercialización'
DRAWN, CHECKED, APPROVED = 'L.B. / T.R.', 'M.O.', 'M.O.'
REVISIONS = [
    ('A', '16/03/2026', 'Anteproyecto'),
    ('B', '22/06/2026', 'Ajuste de tipologías y núcleo'),
    ('C', '28/09/2026', 'Emisión para comercialización'),
]
REV, REV_DATE = REVISIONS[-1][0], REVISIONS[-1][1]
FICTION = 'Proyecto ficticio para portfolio: locación, marca, comitente y estudio ficticios.'

# ===================================================================== lectura de js/data.js
JS_ROUND = lambda v: math.floor(v + 0.5)  # Math.round de JS (mitad hacia arriba)


def load_site():
    src = (ROOT / 'js' / 'data.js').read_text(encoding='utf-8')
    S = {}
    S['twist'] = float(re.search(r'TWIST_DEG\s*=\s*([\d.]+)', src).group(1))
    O, C, g = map(float, re.search(r'const O = ([\d.]+), C = ([\d.]+), g = ([\d.]+);', src).groups())
    S['O'], S['C'], S['g'] = O, C, g
    sub = lambda txt: re.sub(r'\b([OCg])\b', lambda m: repr({'O': O, 'C': C, 'g': g}[m.group(1)]), txt)
    blk = re.search(r'const SHAPES = \{(.*?)\n\};', src, re.S).group(1)
    S['shapes'] = {k: ast.literal_eval(sub(v)) for k, v in re.findall(r'(\w+): (\[\[.*?\]\]),', blk)}
    S['core'] = ast.literal_eval(sub(re.search(r'export const CORE = (\[\[.*?\]\]);', src).group(1)))
    blk = re.search(r'export const TYPES = \{(.*?)\n\};', src, re.S).group(1)
    types = {}
    for part in re.split(r'\n  (?=\w+: \{)', blk):
        m = re.match(r"\s*(\w+): \{\s*name: '([^']*)', rooms: '([^']*)'", part)
        if not m:
            continue
        rooms = [(n, float(x), float(y), float(w), float(h), k) for n, x, y, w, h, k in
                 re.findall(r"\['([^']*)',\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+),\s*'(\w+)'\]", part)]
        cov = sum(w * h for _, _, _, w, h, k in rooms if k != 'balcony')
        opn = sum(w * h for _, _, _, w, h, k in rooms if k == 'balcony')
        types[m.group(1)] = dict(key=m.group(1), name=m.group(2), rooms_txt=m.group(3), plan=rooms,
                                 covered_exact=cov, open_exact=opn, covered=JS_ROUND(cov), open=JS_ROUND(opn))
    S['types'] = types
    blk = re.search(r'const LAYOUTS = \{(.*?)\n\};', src, re.S).group(1)
    S['layouts'] = {z: re.findall(r"\['(\w+)', '(\w+)'\]", body) for z, body in re.findall(r'(\w+): \[(.*?)\],\n', blk + '\n')}
    blk = re.search(r'export const ZONES = \{(.*?)\n\};', src, re.S).group(1)
    S['zones'] = {k: dict(name=n, text=t) for k, n, t in re.findall(r"(\w+): \{ name: '([^']*)', text: '([^']*)' \}", blk)}
    blk = re.search(r'const BEARINGS = \[(.*?)\n\];', src, re.S).group(1)
    S['bearings'] = re.findall(r"\['([^']*)', '([^']*)'\]", blk)
    m = re.search(r"const zone = n <= (\d+) \? 'club' : n <= (\d+) \? 'bosque' : n <= (\d+) \? 'lago' : n <= (\d+) \? 'cumbre' : 'ph';", src)
    lim = list(map(int, m.groups()))
    nfl = int(re.search(r'for \(let n = 1; n <= (\d+); n\+\+\)', src).group(1))
    m = re.search(r'const rot = n <= (\d+) \? 0 : \(n - (\d+)\) \* TWIST_DEG;', src)
    r0, r1 = map(int, m.groups())
    assert "shape === 'FULL' ? [0, -1]" in src, 'cambió el centroide especial del penthouse en data.js'
    floors = []
    for n in range(1, nfl + 1):
        zone = 'club' if n <= lim[0] else 'bosque' if n <= lim[1] else 'lago' if n <= lim[2] else 'cumbre' if n <= lim[3] else 'ph'
        rot = 0.0 if n <= r0 else (n - r1) * S['twist']
        units = []
        for i, (shape, typ) in enumerate(S['layouts'].get(zone, [])):
            poly = S['shapes'][shape]
            cx, cy = (0.0, -1.0) if shape == 'FULL' else (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
            local = math.degrees(math.atan2(cx, -cy))
            units.append(dict(id=f'{n}{"ABCD"[i]}', letter='ABCD'[i], shape=shape, type=typ, bearing=local + rot, local=local))
        floors.append(dict(n=n, zone=zone, rot=rot, units=units))
    S['floors'] = floors
    S['zone_floors'] = {z: [f['n'] for f in floors if f['zone'] == z] for z in ('club', 'bosque', 'lago', 'cumbre', 'ph')}
    bsrc = (ROOT / 'js' / 'building.js').read_text(encoding='utf-8')
    m = re.search(r'\(\(x \+ ([\d.]+)\) / ([\d.]+)\)', bsrc)
    S['slab_half'] = float(m.group(1)) if m else 13.0
    return S


def bearing_info(S, deg):
    i = math.floor(((math.fmod(deg, 360) + 360) % 360) / 45 + 0.5) % 8
    return S['bearings'][i]


# ===================================================================== lectura de tools/depto.py
class _NoEval(Exception):
    pass


def load_depto():
    src = (ROOT / 'tools' / 'depto.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    D = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm in ('H', 'EYE', 'SLAB', 'VIEWS', 'LINKS', 'MOVE_FOV', 'LABELS'):
                D[nm] = ast.literal_eval(node.value)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def ev(n, env):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            raise _NoEval(n.id)
        if isinstance(n, (ast.Tuple, ast.List)):
            return type([])(ev(e, env) for e in n.elts) if isinstance(n, ast.List) else tuple(ev(e, env) for e in n.elts)
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand, env)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left, env), ev(n.right, env)
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b}[type(n.op)]()
        if isinstance(n, ast.Subscript):
            if isinstance(n.value, ast.Name) and n.value.id == 'M':
                return ('M', ev(n.slice, env))
            return ev(n.value, env)[ev(n.slice, env)]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'range':
            return list(range(*[ev(a, env) for a in n.args]))
        raise _NoEval(ast.dump(n)[:40])

    calls = []

    def record(call, env, fn):
        if not isinstance(call.func, ast.Name):
            return
        args = []
        for a in call.args:
            try:
                args.append(ev(a, env))
            except (_NoEval, KeyError, TypeError, IndexError):
                args.append(None)
        kw = {}
        for k in call.keywords:
            try:
                kw[k.arg] = ev(k.value, env)
            except (_NoEval, KeyError, TypeError, IndexError):
                kw[k.arg] = None
        calls.append(dict(fn=call.func.id, args=args, kw=kw, where=fn, line=call.lineno))

    def bind(target, val, env):
        if isinstance(target, ast.Name):
            env[target.id] = val
        elif isinstance(target, (ast.Tuple, ast.List)):
            for t, v in zip(target.elts, val):
                bind(t, v, env)

    def walk(stmts, env, fn):
        for s in stmts:
            if isinstance(s, ast.Assign):
                if isinstance(s.value, ast.Call):
                    record(s.value, env, fn)
                else:
                    try:
                        v = ev(s.value, env)
                        for t in s.targets:
                            bind(t, v, env)
                    except (_NoEval, KeyError, TypeError, IndexError):
                        pass
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                record(s.value, env, fn)
            elif isinstance(s, ast.For):
                try:
                    it = ev(s.iter, env)
                except (_NoEval, KeyError, TypeError, IndexError):
                    continue
                for v in it:
                    e2 = dict(env)
                    bind(s.target, v, e2)
                    walk(s.body, e2, fn)
            elif isinstance(s, ast.If):
                walk(s.body, env, fn)

    base = {'H': D['H'], 'EYE': D['EYE'], 'SLAB': D['SLAB']}
    walk(funcs['build'].body, dict(base), 'build')
    for fn in ('kitchen', 'vanity', 'shower', 'hogar'):
        walk(funcs[fn].body, dict(base), fn)
    D['calls'] = calls
    # firmas de los muebles hechos a medida (valores por defecto)
    D['defaults'] = {}
    for name in ('sofa', 'bed', 'credenza', 'dining', 'floor_lamp', 'side_table', 'pendant', 'downlight', 'rug', 'window', 'curtain'):
        f = funcs[name]
        a = f.args
        defs = []
        for dn in a.defaults:
            try:
                defs.append(ev(dn, base))
            except (_NoEval, KeyError, TypeError, IndexError):
                defs.append(None)
        names = [x.arg for x in a.args]
        D['defaults'][name] = dict(zip(names[len(names) - len(defs):], defs))
    return D


def dcalls(D, fn, name=None):
    out = [c for c in D['calls'] if c['fn'] == fn]
    if name is not None:
        out = [c for c in out if c['args'] and c['args'][0] == name]
    return out


# ===================================================================== geometría
def rot(p, deg, c=(0.0, 0.0)):
    a = math.radians(deg)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * math.cos(a) - y * math.sin(a), c[1] + x * math.sin(a) + y * math.cos(a))


def rounded_square(a, r, n=10):
    pts = []
    for cx, cy, a0 in ((a - r, a - r, 0), (-a + r, a - r, 90), (-a + r, -a + r, 180), (a - r, -a + r, 270)):
        for i in range(n + 1):
            t = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def circle_pts(c, r, n=72):
    return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def fnum(v, nd=2):
    s = f'{v:,.{nd}f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


def flevel(z):
    if abs(z) < 0.005:
        return '±0,00'
    return ('+' if z > 0 else '-') + fnum(abs(z))


def farea(v, nd=2):
    return f'{fnum(v, nd)} m²'


# ===================================================================== modelo de dibujo
# Plumas (mm en papel) y su equivalente DXF (centésimas de mm)
PEN = dict(xhv=0.70, hv=0.50, md=0.35, th=0.25, fn=0.18, xf=0.13, hr=0.09)
LW = {0.70: 70, 0.50: 50, 0.35: 35, 0.25: 25, 0.18: 18, 0.13: 13, 0.09: 9}
DASH = dict(dash=(3.0, 1.5), hidden=(1.4, 0.9), dot=(0.3, 0.9), axis=(9.0, 1.5, 1.0, 1.5), long=(6.0, 2.0))
LT = dict(dash='DASHED', hidden='DASHED2', dot='DOT', axis='CENTER', long='DASHEDX2')
LAYERS = {  # nombre: (color ACI, grosor por defecto)
    'MUROS': (7, 50), 'ABERTURAS': (4, 25), 'COTAS': (2, 13), 'TEXTOS': (7, 18), 'EJES': (1, 13),
    'MOBILIARIO': (8, 13), 'LOSAS': (5, 35), 'ESTRUCTURA': (7, 50), 'SOLADOS': (9, 9), 'RAYADOS': (8, 9),
    'ENTORNO': (3, 13), 'CIRCULACION': (6, 18),
}
BLACK, WHITE = (0, 0, 0), (1, 1, 1)
GRAY = lambda v: (v, v, v)


class Dwg:
    """Dibujo en coordenadas de modelo (metros, y hacia arriba del papel)."""

    def __init__(self, scale):
        self.scale = scale
        self.items = []

    def mm(self, v):  # mm de papel -> m de modelo
        return v * self.scale / 1000.0

    def _add(self, it, z):
        it['z'] = z
        self.items.append(it)

    def line(self, pts, pen='fn', layer='MUROS', dash=None, color=BLACK, z=2):
        self._add(dict(k='line', pts=[tuple(p) for p in pts], pen=pen, layer=layer, dash=dash, color=color), z)

    def poly(self, pts, pen='fn', layer='MUROS', fill=None, stroke=True, dash=None, color=BLACK, z=2, hatch=None):
        self._add(dict(k='poly', rings=[[tuple(p) for p in pts]], pen=pen, layer=layer, fill=fill, stroke=stroke,
                       dash=dash, color=color, hatch=hatch), z)

    def geom(self, g, pen='fn', layer='MUROS', fill=None, stroke=True, hatch=None, color=BLACK, z=2, dash=None):
        """Polígono shapely (con huecos) con relleno, rayado (ángulo, separación mm, pluma, gris) y borde."""
        for p in getattr(g, 'geoms', [g]):
            if p.is_empty or p.geom_type != 'Polygon':
                continue
            rings = [list(p.exterior.coords)[:-1]] + [list(i.coords)[:-1] for i in p.interiors]
            self._add(dict(k='poly', rings=rings, pen=pen, layer=layer, fill=fill, stroke=stroke, hatch=hatch,
                           color=color, dash=dash), z)

    def circle(self, c, r, pen='fn', layer='MOBILIARIO', fill=None, stroke=True, dash=None, color=BLACK, z=2):
        self._add(dict(k='circle', c=tuple(c), r=r, pen=pen, layer=layer, fill=fill, stroke=stroke, dash=dash, color=color), z)

    def arc(self, c, r, a0, a1, pen='xf', layer='ABERTURAS', dash=None, color=BLACK, z=2):
        self._add(dict(k='arc', c=tuple(c), r=r, a0=a0, a1=a1, pen=pen, layer=layer, dash=dash, color=color), z)

    def text(self, p, s, size=2.5, layer='TEXTOS', angle=0.0, align='c', valign='m', font='Helvetica', color=BLACK,
             halo=False, z=5):
        self._add(dict(k='text', p=tuple(p), s=str(s), size=size, layer=layer, angle=angle, align=align, valign=valign,
                       font=font, color=color, halo=halo), z)

    # ---- anotaciones compuestas
    def dim(self, p1, p2, off, text=None, layer='COTAS', size=2.0, ext=True, tick=1.4, z=4):
        """Cota alineada de p1 a p2, desplazada off metros (a la izquierda del vector p1->p2)."""
        (x1, y1), (x2, y2) = p1, p2
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-6:
            return
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        nx, ny = -uy, ux
        a = (x1 + nx * off, y1 + ny * off)
        b = (x2 + nx * off, y2 + ny * off)
        sgn = 1 if off >= 0 else -1
        gap, over = self.mm(1.0), self.mm(1.5)
        if ext:
            for (px, py), (qx, qy) in (((x1, y1), a), ((x2, y2), b)):
                d = math.hypot(qx - px, qy - py)
                if d > gap:
                    self.line([(px + nx * sgn * gap, py + ny * sgn * gap), (qx + nx * sgn * over, qy + ny * sgn * over)],
                              'hr', layer, z=z)
        ex = self.mm(1.2)
        self.line([(a[0] - ux * ex, a[1] - uy * ex), (b[0] + ux * ex, b[1] + uy * ex)], 'xf', layer, z=z)
        t = self.mm(tick) / 2
        for (qx, qy) in (a, b):
            dx, dy = (ux + nx) * t, (uy + ny) * t
            self.line([(qx - dx, qy - dy), (qx + dx, qy + dy)], 'fn', layer, z=z)
        s = fnum(L) if text is None else text
        ang = math.degrees(math.atan2(uy, ux))
        if ang > 90.01 or ang < -89.99:
            ang += 180
        tw = self.mm(stringWidth(s, 'Helvetica', size))
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        # el texto va del lado exterior de la línea de cota; si no entra, se corre fuera del tramo
        k = self.mm(0.9 + size * 0.36)
        tx, ty = mid[0] + nx * sgn * k, mid[1] + ny * sgn * k
        if tw + self.mm(1.0) > L:
            shift = L / 2 + tw / 2 + self.mm(1.6)
            tx, ty = tx + ux * shift, ty + uy * shift
        self.text((tx, ty), s, size, layer, angle=ang, z=z + 1)

    def chain(self, pts, off, layer='COTAS', size=2.0, horizontal=True, z=4):
        """Cadena de cotas a lo largo de una recta (pts ordenados)."""
        for p, q in zip(pts, pts[1:]):
            self.dim(p, q, off, layer=layer, size=size, z=z)

    def bubble(self, p, label, r_mm=4.0, layer='EJES', size=3.2):
        r = self.mm(r_mm)
        self.circle(p, r, 'fn', layer, fill=WHITE, z=4)
        self.text(p, label, size, layer, font='Helvetica-Bold', z=5)

    def axis_line(self, p, q, label_a=None, label_b=None, r_mm=4.0):
        self.line([p, q], 'xf', 'EJES', dash='axis', color=GRAY(0.25), z=1)
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        r = self.mm(r_mm)
        if label_a:
            self.bubble((p[0] - ux * r, p[1] - uy * r), label_a, r_mm)
        if label_b:
            self.bubble((q[0] + ux * r, q[1] + uy * r), label_b, r_mm)

    def level_plan(self, p, txt, size=2.0, layer='COTAS'):
        """Nivel en planta: rótulo en recuadro con cruz."""
        w = self.mm(stringWidth(txt, 'Helvetica', size) + 3.0)
        h = self.mm(size + 2.0)
        x, y = p
        self.poly(rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2), 'xf', layer, fill=WHITE, z=4)
        self.text((x, y), txt, size, layer, z=5)

    def level_section(self, p, txt, size=2.2, side='r', layer='COTAS', leader=0.0):
        """Nivel en corte/vista: triángulo sobre línea y valor."""
        x, y = p
        t = self.mm(1.6)
        self.poly([(x, y), (x - t, y + t * 1.3), (x + t, y + t * 1.3)], 'xf', layer, fill=BLACK, z=4)
        L = self.mm(14.0)
        if side == 'r':
            self.line([(x - t * 1.5, y), (x + L, y)], 'hr', layer, z=4)
            self.text((x + self.mm(2.5), y + t * 1.3 + self.mm(1.6)), txt, size, layer, align='l', z=5)
        else:
            self.line([(x - L, y), (x + t * 1.5, y)], 'hr', layer, z=4)
            self.text((x - self.mm(2.5), y + t * 1.3 + self.mm(1.6)), txt, size, layer, align='r', z=5)

    def north(self, p, deg=0.0, size_mm=16.0, layer='TEXTOS'):
        """Flecha de norte; deg = rumbo del norte en el papel, horario desde arriba."""
        r = self.mm(size_mm / 2)
        self.circle(p, r, 'fn', layer, z=4)
        tip = rot((0, r * 0.92), -deg)
        l = rot((-r * 0.36, -r * 0.62), -deg)
        rr = rot((r * 0.36, -r * 0.62), -deg)
        m = rot((0, -r * 0.30), -deg)
        P = lambda q: (p[0] + q[0], p[1] + q[1])
        self.poly([P(tip), P(l), P(m)], 'xf', layer, fill=BLACK, z=4)
        self.poly([P(tip), P(m), P(rr)], 'xf', layer, fill=WHITE, z=4)
        n = rot((0, r + self.mm(3.0)), -deg)
        self.text(P(n), 'N', 3.2, layer, font='Helvetica-Bold', z=5)

    def section_mark(self, p, q, label, look, layer='TEXTOS'):
        """Línea de corte de p a q; look = vector hacia donde se mira."""
        self.line([p, q], 'md', layer, dash='axis', color=BLACK, z=4)
        r = self.mm(4.5)
        L = math.hypot(look[0], look[1])
        lx, ly = look[0] / L, look[1] / L
        for e in (p, q):
            self.circle(e, r, 'fn', layer, fill=WHITE, z=4)
            self.text(e, label, 3.4, layer, font='Helvetica-Bold', z=5)
            tip = (e[0] + lx * r * 2.2, e[1] + ly * r * 2.2)
            s1 = (e[0] + ly * r * 0.8 + lx * r * 0.9, e[1] - lx * r * 0.8 + ly * r * 0.9)
            s2 = (e[0] - ly * r * 0.8 + lx * r * 0.9, e[1] + lx * r * 0.8 + ly * r * 0.9)
            self.poly([tip, s1, s2], 'xf', layer, fill=BLACK, z=4)

    def scalebar(self, p, total_m, step_m, layer='TEXTOS'):
        x, y = p
        h = self.mm(1.6)
        n = int(round(total_m / step_m))
        for i in range(n):
            self.poly(rect(x + i * step_m, y, x + (i + 1) * step_m, y + h), 'xf', layer,
                      fill=BLACK if i % 2 == 0 else WHITE, z=4)
        for i in range(n + 1):
            v = i * step_m
            self.text((x + v, y + h + self.mm(2.0)), fnum(v, 0) if v == int(v) else fnum(v, 1), 1.8, layer, z=5)
        self.text((x + n * step_m + self.mm(3.0), y + h / 2), 'm', 1.8, layer, align='l', z=5)


# ===================================================================== salida PDF
def _setdash(c, dash, scale_hint=1.0):
    if dash:
        c.setDash([v for v in DASH[dash]], 0)
    else:
        c.setDash([], 0)


def render(c, d, frame, center, clip=True):
    """Dibuja el Dwg d en el recuadro frame=(x, y, w, h) mm del papel, con el punto center del modelo al centro."""
    s = 1000.0 / d.scale
    fx, fy, fw, fh = frame
    ox, oy = fx + fw / 2 - center[0] * s, fy + fh / 2 - center[1] * s
    T = lambda p: (ox + p[0] * s, oy + p[1] * s)
    c.saveState()
    if clip:
        pa = c.beginPath()
        pa.rect(fx, fy, fw, fh)
        c.clipPath(pa, stroke=0, fill=0)
    c.setLineJoin(1)
    c.setLineCap(1)
    for it in sorted(d.items, key=lambda i: i['z']):
        k = it['k']
        col = it.get('color', BLACK)
        if k in ('line', 'poly', 'circle', 'arc'):
            c.setLineWidth(PEN[it['pen']])
            c.setStrokeColorRGB(*col)
            _setdash(c, it.get('dash'))
        if k == 'line':
            pa = c.beginPath()
            pts = [T(p) for p in it['pts']]
            pa.moveTo(*pts[0])
            for q in pts[1:]:
                pa.lineTo(*q)
            c.drawPath(pa, stroke=1, fill=0)
        elif k == 'poly':
            rings = [[T(p) for p in r] for r in it['rings']]

            def mk():
                pa = c.beginPath()
                for r in rings:
                    pa.moveTo(*r[0])
                    for q in r[1:]:
                        pa.lineTo(*q)
                    pa.close()
                return pa
            if it.get('fill') is not None:
                c.setFillColorRGB(*it['fill'])
                c.drawPath(mk(), stroke=0, fill=1, fillMode=0)
            if it.get('hatch'):
                ang, sp, hpen, hcol = it['hatch']
                c.saveState()
                c.clipPath(mk(), stroke=0, fill=0, fillMode=0)
                xs = [q[0] for r in rings for q in r]
                ys = [q[1] for r in rings for q in r]
                cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                R = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / 2 + sp
                a = math.radians(ang)
                ux, uy = math.cos(a), math.sin(a)
                nx, ny = -uy, ux
                # rayado anclado al origen del papel para que tramos vecinos queden alineados
                d0 = cx * nx + cy * ny
                k0 = math.floor((d0 - R) / sp)
                c.setLineWidth(PEN[hpen])
                c.setStrokeColorRGB(*hcol)
                c.setDash([], 0)
                pa = c.beginPath()
                kk = k0
                while kk * sp <= d0 + R:
                    off = kk * sp
                    bx, by = nx * off + ux * (cx * ux + cy * uy), ny * off + uy * (cx * ux + cy * uy)
                    pa.moveTo(bx - ux * R, by - uy * R)
                    pa.lineTo(bx + ux * R, by + uy * R)
                    kk += 1
                c.drawPath(pa, stroke=1, fill=0)
                c.restoreState()
                c.setLineWidth(PEN[it['pen']])
                c.setStrokeColorRGB(*col)
                _setdash(c, it.get('dash'))
            if it.get('stroke', True):
                c.drawPath(mk(), stroke=1, fill=0)
        elif k == 'circle':
            x, y = T(it['c'])
            r = it['r'] * s
            if it.get('fill') is not None:
                c.setFillColorRGB(*it['fill'])
            c.circle(x, y, r, stroke=1 if it.get('stroke', True) else 0, fill=1 if it.get('fill') is not None else 0)
        elif k == 'arc':
            x, y = T(it['c'])
            r = it['r'] * s
            a0, a1 = it['a0'], it['a1']
            pa = c.beginPath()
            pa.arc(x - r, y - r, x + r, y + r, startAng=a0, extent=a1 - a0)
            c.drawPath(pa, stroke=1, fill=0)
        elif k == 'text':
            x, y = T(it['p'])
            size = it['size']
            font = it['font']
            w = stringWidth(it['s'], font, size)
            dx = {'l': 0, 'c': -w / 2, 'r': -w}[it['align']]
            dy = {'b': 0, 'm': -size * 0.35, 't': -size * 0.72}[it['valign']]
            c.saveState()
            c.translate(x, y)
            if it['angle']:
                c.rotate(it['angle'])
            if it.get('halo'):
                t = c.beginText(dx, dy)
                t.setFont(font, size)
                t.setTextRenderMode(1)
                c.setStrokeColorRGB(1, 1, 1)
                c.setLineWidth(size * 0.28)
                c.setLineJoin(1)
                t.textOut(it['s'])
                t.setTextRenderMode(0)  # el modo de render persiste en el estado gráfico del PDF
                c.drawText(t)
            c.setFillColorRGB(*it['color'])
            t = c.beginText(dx, dy)
            t.setFont(font, size)
            t.setTextRenderMode(0)
            t.textOut(it['s'])
            c.drawText(t)
            c.restoreState()
    c.restoreState()


# ===================================================================== salida DXF
def write_dxf(d, path, title):
    try:
        import ezdxf
        from ezdxf.enums import TextEntityAlignment
    except ImportError:
        return False
    doc = ezdxf.new('R2010', setup=True)
    doc.units = ezdxf.units.M
    doc.header['$INSUNITS'] = 6
    doc.header['$MEASUREMENT'] = 1
    doc.header['$LTSCALE'] = 1.0
    if 'ARQ' not in doc.styles:
        doc.styles.new('ARQ', dxfattribs={'font': 'arial.ttf'})
    for nm, (col, lw) in LAYERS.items():
        doc.layers.add(nm, color=col, lineweight=lw)
    msp = doc.modelspace()
    ltk = d.scale / 1000.0 * 4.0
    AL = {('l', 'b'): TextEntityAlignment.BOTTOM_LEFT, ('c', 'b'): TextEntityAlignment.BOTTOM_CENTER,
          ('r', 'b'): TextEntityAlignment.BOTTOM_RIGHT, ('l', 'm'): TextEntityAlignment.MIDDLE_LEFT,
          ('c', 'm'): TextEntityAlignment.MIDDLE_CENTER, ('r', 'm'): TextEntityAlignment.MIDDLE_RIGHT,
          ('l', 't'): TextEntityAlignment.TOP_LEFT, ('c', 't'): TextEntityAlignment.TOP_CENTER,
          ('r', 't'): TextEntityAlignment.TOP_RIGHT}

    def attrs(it):
        a = {'layer': it['layer'], 'lineweight': LW.get(PEN.get(it.get('pen', 'fn'), 0.18), 18)}
        if it.get('dash'):
            a['linetype'] = LT[it['dash']]
            a['ltscale'] = ltk
        col = it.get('color', BLACK)
        if col != BLACK:
            a['color'] = 8 if col[0] < 0.5 else 9
        return a

    for it in sorted(d.items, key=lambda i: i['z']):
        k = it['k']
        if k == 'line':
            msp.add_lwpolyline(it['pts'], dxfattribs=attrs(it))
        elif k == 'poly':
            if it.get('fill') is not None or it.get('hatch'):
                h = msp.add_hatch(dxfattribs={'layer': 'RAYADOS'})
                if it.get('hatch'):
                    ang, sp, _, _ = it['hatch']
                    h.set_pattern_fill('ANSI31', scale=sp * d.scale / 1000.0 / 3.175, angle=ang - 45)
                elif it['fill'] == WHITE:
                    h = None
                else:
                    v = it['fill'][0]
                    h.set_solid_fill(color=250 + min(5, int(v * 6)) if v > 0.05 else 7)
                if h is not None:
                    for i, r in enumerate(it['rings']):
                        h.paths.add_polyline_path(r, is_closed=True, flags=1 if i == 0 else 0)
            if it.get('stroke', True):
                for r in it['rings']:
                    msp.add_lwpolyline(r, close=True, dxfattribs=attrs(it))
        elif k == 'circle':
            msp.add_circle(it['c'], it['r'], dxfattribs=attrs(it))
        elif k == 'arc':
            msp.add_arc(it['c'], it['r'], it['a0'], it['a1'], dxfattribs=attrs(it))
        elif k == 'text':
            t = msp.add_text(it['s'], height=d.mm(it['size']) * 0.72, rotation=it['angle'],
                             dxfattribs={'layer': it['layer'], 'style': 'ARQ'})
            t.set_placement(it['p'], align=AL[(it['align'], it['valign'])])
    doc.header['$PROJECTNAME'] = title[:60]
    doc.saveas(path)
    return True


# ===================================================================== lámina: marco, rótulo, tablas
PAGE = (841.0, 594.0)  # A1 apaisada
FR = (20.0, 10.0, 831.0, 584.0)  # marco (margen de encuadernación a la izquierda)
TB_X = 651.0  # columna del rótulo
DA = (FR[0] + 4, FR[1] + 4, TB_X - FR[0] - 8, FR[3] - FR[1] - 8)  # área de dibujo (x, y, w, h)


def txt(c, x, y, s, size=2.5, font='Helvetica', align='l', color=BLACK, angle=0):
    c.saveState()
    c.setFillColorRGB(*color)
    c.setFont(font, size)
    c.translate(x, y)
    if angle:
        c.rotate(angle)
    w = stringWidth(s, font, size)
    c.drawString({'l': 0, 'c': -w / 2, 'r': -w}[align], 0, s)
    c.restoreState()


def wrap(s, font, size, width):
    out, line = [], ''
    for word in s.split(' '):
        cand = (line + ' ' + word).strip()
        if stringWidth(cand, font, size) <= width or not line:
            line = cand
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def para(c, x, y, s, size=2.2, width=100, font='Helvetica', lead=1.38, color=BLACK):
    """Párrafo con ajuste de línea; devuelve la y final."""
    for ln in wrap(s, font, size, width):
        txt(c, x, y, ln, size, font, color=color)
        y -= size * lead
    return y


def hline(c, x0, x1, y, w=0.18, col=BLACK):
    c.setLineWidth(w)
    c.setStrokeColorRGB(*col)
    c.setDash([], 0)
    c.line(x0, y, x1, y)


def vline(c, x, y0, y1, w=0.18, col=BLACK):
    c.setLineWidth(w)
    c.setStrokeColorRGB(*col)
    c.setDash([], 0)
    c.line(x, y0, x, y1)


def table(c, x, y, cols, rows, head=None, size=2.1, rowh=None, head_size=None, zebra=False, bold_last=False,
          aligns=None, lw=0.13, bold_rows=()):
    """Tabla con la esquina superior izquierda en (x, y). cols = anchos (mm). Devuelve la y inferior."""
    rowh = rowh or size * 2.05
    head_size = head_size or size
    W = sum(cols)
    aligns = aligns or ['l'] * len(cols)
    yy = y
    if head:
        nl = max(h.count('\n') + 1 for h in head)
        hh = max(rowh * 1.25, nl * head_size * 1.25 + 1.8)
        c.setFillColorRGB(0.12, 0.12, 0.12)
        c.rect(x, yy - hh, W, hh, stroke=0, fill=1)
        xx = x
        for w, h, al in zip(cols, head, aligns):
            lines = h.split('\n')
            ty = yy - (hh - len(lines) * head_size * 1.22) / 2 - head_size * 0.92
            for ln in lines:
                tx = {'l': xx + 1.2, 'c': xx + w / 2, 'r': xx + w - 1.2}[al]
                txt(c, tx, ty, ln, head_size, 'Helvetica-Bold', al, color=WHITE)
                ty -= head_size * 1.22
            xx += w
        yy -= hh
    for i, r in enumerate(rows):
        bold = (bold_last and i == len(rows) - 1) or i in bold_rows
        if zebra and i % 2 == 1:
            c.setFillColorRGB(0.94, 0.94, 0.94)
            c.rect(x, yy - rowh, W, rowh, stroke=0, fill=1)
        if bold:
            c.setFillColorRGB(0.86, 0.86, 0.86)
            c.rect(x, yy - rowh, W, rowh, stroke=0, fill=1)
        xx = x
        for w, v, al in zip(cols, r, aligns):
            tx = {'l': xx + 1.2, 'c': xx + w / 2, 'r': xx + w - 1.2}[al]
            txt(c, tx, yy - rowh / 2 - size * 0.35, str(v), size, 'Helvetica-Bold' if bold else 'Helvetica', al)
            xx += w
        yy -= rowh
        hline(c, x, x + W, yy, lw, GRAY(0.55) if not bold else BLACK)
    c.setLineWidth(0.25)
    c.setStrokeColorRGB(0, 0, 0)
    c.rect(x, yy, W, y - yy, stroke=1, fill=0)
    xx = x
    for w in cols[:-1]:
        xx += w
        vline(c, xx, yy, y, lw, GRAY(0.55))
    return yy


def caption(c, x, y, num, title, scale_txt, sub=None):
    """Título de dibujo: número en círculo, título subrayado y escala."""
    r = 5.0
    c.setLineWidth(0.35)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(1, 1, 1)
    c.circle(x + r, y, r, stroke=1, fill=1)
    txt(c, x + r, y - 1.4, str(num), 4.0, 'Helvetica-Bold', 'c')
    tx = x + 2 * r + 3
    txt(c, tx, y + 0.6, title, 4.0, 'Helvetica-Bold')
    w = stringWidth(title, 'Helvetica-Bold', 4.0)
    hline(c, tx, tx + w, y - 1.0, 0.5)
    txt(c, tx, y - 5.0, scale_txt + (('   ·   ' + sub) if sub else ''), 2.5)


def logo(c, x, y, s=12.0):
    """Marca del estudio: un cuadrado y, adentro, otro girado."""
    c.saveState()
    c.translate(x + s / 2, y + s / 2)
    c.setLineWidth(0.5)
    c.setStrokeColorRGB(0, 0, 0)
    c.rect(-s / 2, -s / 2, s, s, stroke=1, fill=0)
    c.rotate(-12)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.rect(-s * 0.3, -s * 0.3, s * 0.6, s * 0.6, stroke=0, fill=1)
    c.restoreState()


GENERAL_NOTES = [
    'Cotas en metros. Las cotas prevalecen sobre la escala del dibujo; verificar en obra.',
    'Niveles referidos a ±0,00 = NPT de planta baja = 771,50 m s.n.m. (nivel medio del lago Ilén: 768,20).',
    'Numeración de pisos según comercialización: nivel 1 = planta baja; unidades 3A a 18A.',
]


class Sheet:
    def __init__(self, code, title, scale_txt, notes=(), sub=None, kind='Arquitectura', general=True):
        self.code, self.title, self.scale_txt, self.sub, self.kind = code, title, scale_txt, sub, kind
        self.notes = list(notes) + (GENERAL_NOTES if general else [])
        self.keyplan = None  # callable(c, frame)

    def frame(self, c, idx, total):
        x0, y0, x1, y1 = FR
        c.setLineWidth(0.7)
        c.setStrokeColorRGB(0, 0, 0)
        c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=0)
        c.setLineWidth(0.35)
        c.rect(TB_X, y0, x1 - TB_X, y1 - y0, stroke=1, fill=0)
        for i in range(1, 8):  # zonas del marco
            xx = x0 + (TB_X - x0) * i / 8
            vline(c, xx, y1, y1 + 3, 0.25)
            vline(c, xx, y0 - 3, y0, 0.25)
        for i, ch in enumerate('ABCDEF'):
            yy = y1 - (y1 - y0) * (i + 0.5) / 6
            txt(c, x0 - 3.2, yy - 0.9, ch, 2.4, align='c')
        for i in range(8):
            xx = x0 + (TB_X - x0) * (i + 0.5) / 8
            txt(c, xx, y1 + 1.4, str(i + 1), 2.4, align='c')
        X, R = TB_X, x1
        Wd = R - X
        pad = 3.5
        y = y1
        # estudio
        logo(c, X + pad, y - 16.5, 12)
        txt(c, X + pad + 16, y - 8.4, STUDIO, 4.6, 'Helvetica-Bold')
        txt(c, X + pad + 16, y - 13.4, STUDIO_SUB, 2.3)
        y -= 21
        hline(c, X, R, y, 0.35)
        # obra
        txt(c, X + pad, y - 4.6, 'OBRA', 2.0, 'Helvetica-Bold', color=GRAY(0.35))
        txt(c, X + pad, y - 13.5, PROJECT, 9.0, 'Helvetica-Bold')
        txt(c, X + pad + stringWidth(PROJECT, 'Helvetica-Bold', 9.0) + 3, y - 13.5, PROJECT_SUB, 3.6)
        txt(c, X + pad, y - 19.0, PROJECT_KIND, 2.5)
        txt(c, X + pad, y - 23.5, ADDRESS, 2.3)
        txt(c, X + pad, y - 28.0, 'Nomenclatura catastral: ' + CATASTRO, 2.3)
        txt(c, X + pad, y - 32.5, 'Comitente: ' + CLIENT, 2.5, 'Helvetica-Bold')
        txt(c, R - pad, y - 32.5, 'Proyecto N° ' + PROJ_NO, 2.5, 'Helvetica-Bold', 'r')
        y -= 36
        hline(c, X, R, y, 0.35)
        # notas
        txt(c, X + pad, y - 4.6, 'NOTAS', 2.0, 'Helvetica-Bold', color=GRAY(0.35))
        yy = y - 9.0
        for i, n in enumerate(self.notes):
            ln = wrap(n, 'Helvetica', 2.1, Wd - 2 * pad - 5)
            txt(c, X + pad, yy, f'{i + 1}.', 2.1)
            for l in ln:
                txt(c, X + pad + 5, yy, l, 2.1)
                yy -= 2.9
            yy -= 0.9
        yb = y0
        box_h = 62.0
        rev_h = 6 + 4.6 * len(REVISIONS) + 3
        key_top = yb + box_h + rev_h
        limit = key_top
        if self.keyplan:
            kh = 96.0
            hline(c, X, R, key_top + kh, 0.35)
            txt(c, X + pad, key_top + kh - 4.6, 'PLANO LLAVE Y ORIENTACIÓN', 2.0, 'Helvetica-Bold', color=GRAY(0.35))
            self.keyplan(c, (X + 3, key_top + 3, Wd - 6, kh - 11))
            limit = key_top + kh
        if yy < limit + 1:
            print(f'  ! {self.code}: las notas no entran en el rótulo', file=sys.stderr)
        # revisiones
        hline(c, X, R, key_top, 0.35)
        ry = key_top - 4.6
        txt(c, X + pad, ry, 'REVISIONES', 2.0, 'Helvetica-Bold', color=GRAY(0.35))
        ry -= 5
        for r in REVISIONS:
            txt(c, X + pad + 1, ry, r[0], 2.2, 'Helvetica-Bold')
            txt(c, X + pad + 9, ry, r[1], 2.2)
            txt(c, X + pad + 31, ry, r[2], 2.2)
            ry -= 4.6
        hline(c, X, R, yb + box_h, 0.35)
        # datos de la lámina
        y = yb + box_h
        txt(c, X + pad, y - 4.6, 'LÁMINA', 2.0, 'Helvetica-Bold', color=GRAY(0.35))
        ty = y - 10.6
        lines = wrap(self.title, 'Helvetica-Bold', 4.2, Wd - 2 * pad)[:2]
        for ln in lines:
            txt(c, X + pad, ty, ln, 4.2, 'Helvetica-Bold')
            ty -= 5.0
        if self.sub:
            txt(c, X + pad, ty + 0.4, self.sub, 2.4)
        gy = yb + 33.0
        hline(c, X, R, gy, 0.25)
        cells = [('Escala', self.scale_txt), ('Fecha', REV_DATE), ('Revisión', REV),
                 ('Dibujó', DRAWN), ('Revisó', CHECKED), ('Aprobó', APPROVED)]
        cw = (R - X - 52) / 3
        for i, (k, v) in enumerate(cells):
            cx = X + (i % 3) * cw
            cy = gy - (i // 3) * 11.5
            txt(c, cx + 2.5, cy - 3.6, k.upper(), 1.8, 'Helvetica-Bold', color=GRAY(0.35))
            sz = 2.6 if stringWidth(v, 'Helvetica', 2.6) < cw - 4 else 2.0
            txt(c, cx + 2.5, cy - 8.6, v, sz)
            if i % 3:
                vline(c, cx, cy - 11.5, cy, 0.18)
        hline(c, X, R - 52, gy - 11.5, 0.18)
        hline(c, X, R - 52, gy - 23.0, 0.25)
        vline(c, R - 52, yb, gy, 0.35)
        txt(c, R - 26, yb + 16.0, self.code, 11.0, 'Helvetica-Bold', 'c')
        txt(c, R - 26, yb + 10.0, f'Hoja {idx} de {total}', 2.4, align='c')
        txt(c, R - 26, yb + 27.5, self.kind.upper(), 1.9, 'Helvetica-Bold', 'c', color=GRAY(0.35))
        txt(c, X + pad, yb + 5.8, PHASE, 2.2)
        txt(c, X + pad, yb + 2.3, FICTION, 1.75, color=GRAY(0.3))
        txt(c, R - 2.5, yb + 2.3, f'{PROJ_NO}_{self.code}', 1.9, align='r', color=GRAY(0.3))


# ===================================================================== edificio: valores del proyecto
class B:
    """Valores de proyecto. Los que vienen del sitio se completan en setup()."""
    FTF = 3.30           # piso a piso típico (H libre + losa + contrapiso y piso + cielorraso)
    FIN = 0.10           # contrapiso y solado
    CEIL = 0.15          # pleno de cielorraso suspendido
    H_PB, H_P1 = 4.80, 4.20
    R_SLAB = 2.50        # radio de las esquinas de la losa
    R_PAL = 5.20         # radio libre del palier circular
    T_PAL = 0.20         # muro de unidad hacia el palier
    T_PARTY = 0.15       # muro de unidad hacia el pleno entre unidades
    CORE = 2.80          # medio lado del núcleo fijo (5,60 x 5,60)
    CORE_T = 0.25
    COL_D = 0.50         # columnas de la torre (circulares, inclinadas)
    COLS = [(0, 7.6), (0, 11.4), (0, -7.6), (0, -11.4), (7.6, 0), (11.4, 0), (-7.6, 0), (-11.4, 0)]
    POD = (-23.1, -15.5, 23.1, 15.5)
    GX = [(-22.8, 'A'), (-15.2, 'B'), (-11.4, 'C'), (-7.6, 'D'), (0.0, 'E'), (7.6, 'F'), (11.4, 'G'), (15.2, 'H'), (22.8, 'J')]
    GY = [(-15.2, '1'), (-11.4, '2'), (-7.6, '3'), (0.0, '4'), (7.6, '5'), (11.4, '6'), (15.2, '7')]
    BAY = None


def setup(S, D):
    B.H = D['H']
    B.SLAB = D['SLAB']
    assert abs(B.H + B.SLAB + B.FIN + B.CEIL - B.FTF) < 1e-9, 'el piso a piso no cierra con H y losa de depto.py'
    B.A = S['slab_half']      # medio lado de la losa (13,00): encuadre de building.js
    B.O = S['O']              # medio lado del cerramiento (11,80): data.js
    B.g = S['g']              # medio ancho del pleno entre unidades (0,35): data.js
    B.C = S['C']              # medio lado de la zona de núcleo en data.js (4,30)
    B.TW = S['twist']
    B.NPT = {1: 0.0, 2: B.H_PB}
    for n in range(3, 20):
        B.NPT[n] = B.H_PB + B.H_P1 + (n - 3) * B.FTF
    B.ROOF = B.NPT[19]
    B.TOP = B.ROOF + 3.80
    B.ROT = {f['n']: f['rot'] for f in S['floors']}
    B.ROT[19] = (19 - 3) * B.TW
    B.BAY = (B.O - B.g) / 5.0
    # chequeo de giro: el núcleo fijo (5,60 x 5,60) nunca se acerca a menos de 1,20 m del palier
    hd = math.hypot(B.CORE, B.CORE)
    B.CLEAR = B.R_PAL - hd
    assert B.CLEAR >= 1.20


def gx(lbl):
    return dict((l, v) for v, l in B.GX)[lbl]


# ===================================================================== dibujo de plantas: ayudante
def door_leaf(d, hinge, w, along, into, pen='fn', double=False, layer='ABERTURAS'):
    """Puerta abatible: bisagra en hinge, hoja de ancho w; along = versor del vano (de la bisagra al otro jamba),
    into = versor hacia donde abre."""
    hx, hy = hinge
    tip = (hx + into[0] * w, hy + into[1] * w)
    d.line([hinge, tip], pen, layer, z=3)
    a0 = math.degrees(math.atan2(into[1], into[0]))
    a1 = math.degrees(math.atan2(along[1], along[0]))
    da = (a1 - a0 + 540) % 360 - 180
    d.arc(hinge, w, min(a0, a0 + da), max(a0, a0 + da), 'hr', layer, z=3)


class Plan:
    """Muros por segmentos con vanos, carpinterías, puertas y locales."""

    def __init__(self, d):
        self.d = d
        self.walls = []      # (geom, kind)
        self.cuts = []       # geoms a restar a los muros (vanos)
        self.glass = []      # (p, q, t)
        self.doors = []
        self.rooms = []

    def wall(self, p, q, t=0.15, kind='mamp', ext=None):
        ext = t / 2 if ext is None else ext
        L = LineString([p, q])
        (x0, y0), (x1, y1) = p, q
        Ln = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / Ln, (y1 - y0) / Ln
        L = LineString([(x0 - ux * ext, y0 - uy * ext), (x1 + ux * ext, y1 + uy * ext)])
        self.walls.append((L.buffer(t / 2, cap_style=2, join_style=2), kind))

    def wall_poly(self, g, kind='mamp'):
        self.walls.append((g, kind))

    def gap(self, center, w, vertical, t=0.6):
        x, y = center
        if vertical:
            self.cuts.append(sbox(x - t / 2, y - w / 2, x + t / 2, y + w / 2))
        else:
            self.cuts.append(sbox(x - w / 2, y - t / 2, x + w / 2, y + t / 2))

    def glazing(self, p, q, t=0.08, mull=None, frame=True):
        self.glass.append((p, q, t, mull))

    def door(self, center, w, vertical, swing, hinge=-1, double=False, kind='abrir', t=0.6, gap=True):
        """center del vano; vertical: el muro es vertical; swing: +1/-1 hacia donde abre (x o y);
        hinge: -1 bisagra en el extremo menor, +1 en el mayor."""
        if gap:
            self.gap(center, w, vertical, t)
        self.doors.append((center, w, vertical, swing, hinge, double, kind))

    def room(self, name, poly, area=True, lpos=None, sub=None, size=2.2, angle=0, finish=None):
        self.rooms.append(dict(name=name, poly=poly, area=area, lpos=lpos, sub=sub, size=size, angle=angle, finish=finish))

    def draw(self, wall_fill=GRAY(0.25), hatch_mamp=True, labels=True, area_nd=2):
        d = self.d
        cut = unary_union(self.cuts) if self.cuts else None
        groups = {}
        for g, kind in self.walls:
            groups.setdefault(kind, []).append(g)
        for kind, gs in groups.items():
            u = unary_union(gs)
            if cut is not None:
                u = u.difference(cut)
            if kind == 'ha':
                d.geom(u, 'hv', 'MUROS', fill=GRAY(0.12), z=2.2)
            elif kind == 'mamp':
                d.geom(u, 'md', 'MUROS', fill=WHITE, hatch=(45, 0.9, 'hr', GRAY(0.2)) if hatch_mamp else None, z=2.1)
            elif kind == 'tab':
                d.geom(u, 'th', 'MUROS', fill=GRAY(0.62), z=2.0)
            elif kind == 'low':
                d.geom(u, 'fn', 'MUROS', fill=WHITE, z=2.0)
        for p, q, t, mull in self.glass:
            (x0, y0), (x1, y1) = p, q
            L = math.hypot(x1 - x0, y1 - y0)
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            nx, ny = -uy, ux
            h = t / 2
            d.poly([(x0 + nx * h, y0 + ny * h), (x1 + nx * h, y1 + ny * h), (x1 - nx * h, y1 - ny * h),
                    (x0 - nx * h, y0 - ny * h)], 'fn', 'ABERTURAS', fill=WHITE, z=2.3)
            d.line([p, q], 'xf', 'ABERTURAS', z=2.4)
            if mull:
                n = max(1, int(round(L / mull)))
                for i in range(n + 1):
                    m = (x0 + ux * L * i / n, y0 + uy * L * i / n)
                    d.poly([(m[0] + nx * h * 1.6 - ux * 0.04, m[1] + ny * h * 1.6 - uy * 0.04),
                            (m[0] + nx * h * 1.6 + ux * 0.04, m[1] + ny * h * 1.6 + uy * 0.04),
                            (m[0] - nx * h * 1.6 + ux * 0.04, m[1] - ny * h * 1.6 + uy * 0.04),
                            (m[0] - nx * h * 1.6 - ux * 0.04, m[1] - ny * h * 1.6 - uy * 0.04)],
                           'xf', 'ABERTURAS', fill=BLACK, z=2.5)
        for (x, y), w, vertical, swing, hinge, double, kind in self.doors:
            if kind == 'corrediza':
                # hoja corrediza: rectángulo fino desplazado
                if vertical:
                    d.poly(rect(x - 0.06 + swing * 0.07, y - w / 2, x + 0.06 + swing * 0.07, y + w / 2 + w * 0.2), 'fn', 'ABERTURAS', fill=WHITE, z=3)
                else:
                    d.poly(rect(x - w / 2, y - 0.06 + swing * 0.07, x + w / 2 + w * 0.2, y + 0.06 + swing * 0.07), 'fn', 'ABERTURAS', fill=WHITE, z=3)
                continue
            if kind == 'auto':
                for s in (-1, 1):
                    if vertical:
                        d.poly(rect(x - 0.04, y + s * w / 4 - w / 4, x + 0.04, y + s * w / 4 + w / 4), 'fn', 'ABERTURAS', fill=WHITE, z=3)
                    else:
                        d.poly(rect(x + s * w / 4 - w / 4, y - 0.04, x + s * w / 4 + w / 4, y + 0.04), 'fn', 'ABERTURAS', fill=WHITE, z=3)
                continue
            leaves = [(-1, w / 2), (1, w / 2)] if double else [(hinge, w)]
            for hs, lw in leaves:
                if vertical:
                    hp = (x, y + hs * w / 2)
                    door_leaf(d, hp, lw, (0, -hs), (swing, 0))
                else:
                    hp = (x + hs * w / 2, y)
                    door_leaf(d, hp, lw, (-hs, 0), (0, swing))
        if labels:
            for r in self.rooms:
                P = Polygon(r['poly'])
                c = r['lpos'] or (P.representative_point().x, P.representative_point().y)
                if r['lpos'] is None:
                    c = (P.centroid.x, P.centroid.y) if P.contains(P.centroid) else c
                lines = [r['name'].upper()]
                d.text(c, lines[0], r['size'], 'TEXTOS', angle=r['angle'], font='Helvetica-Bold', halo=True)
                dy = d.mm(r['size'] * 1.25)
                k = 1
                if r['area']:
                    off = rot((0, -dy * k), r['angle'])
                    d.text((c[0] + off[0], c[1] + off[1]), farea(P.area, area_nd), r['size'] * 0.82, 'TEXTOS', angle=r['angle'], halo=True)
                    k += 1
                if r['sub']:
                    off = rot((0, -dy * k), r['angle'])
                    d.text((c[0] + off[0], c[1] + off[1]), r['sub'], r['size'] * 0.75, 'TEXTOS', angle=r['angle'],
                           color=GRAY(0.25), halo=True)


def column(d, p, kind='sq', s=0.5, rot_deg=0.0):
    if kind == 'sq':
        pts = [rot(q, rot_deg, (0, 0)) for q in rect(-s / 2, -s / 2, s / 2, s / 2)]
        d.poly([(p[0] + q[0], p[1] + q[1]) for q in pts], 'md', 'ESTRUCTURA', fill=BLACK, z=2.6)
    else:
        d.circle(p, s / 2, 'md', 'ESTRUCTURA', fill=BLACK, z=2.6)


# ===================================================================== núcleo fijo
def core_parts():
    """Geometría del núcleo en el marco del sitio (x este, y norte), centrado en el eje de giro."""
    k, t = B.CORE, B.CORE_T
    i = k - t
    ring = sbox(-k, -k, k, k).difference(sbox(-i, -i, i, i))
    inner = [sbox(-i, 0.55, i, 0.75), sbox(-0.10, 0.75, 0.10, i), sbox(-1.95, 0.75, -1.75, i), sbox(1.75, 0.75, 1.95, i)]
    walls = unary_union([ring] + inner)
    openings = [sbox(-1.375, i - 0.05, -0.475, k + 0.05), sbox(0.475, i - 0.05, 1.375, k + 0.05),
                sbox(-2.50, i - 0.05, -2.00, k + 0.05), sbox(2.00, i - 0.05, 2.50, k + 0.05),
                sbox(-k - 0.05, -0.40, -i + 0.05, 0.50)]
    return walls.difference(unary_union(openings))


def draw_core(d, level='typ', angle=0.0, center=(0.0, 0.0), detail=True, labels=True):
    """Dibuja el núcleo (ascensores, escalera presurizada, montantes) rotado 'angle' grados (antihorario)."""
    k, t = B.CORE, B.CORE_T
    i = k - t
    T = lambda pts: [(center[0] + q[0], center[1] + q[1]) for q in (rot(p, angle) for p in pts)]
    Tp = lambda p: T([p])[0]
    g = affinity.translate(affinity.rotate(core_parts(), angle, origin=(0, 0)), center[0], center[1])
    d.geom(g, 'hv', 'MUROS', fill=GRAY(0.12), z=2.2)
    if not detail:
        return
    # ascensores: cabina y cruz de pasadizo
    for sx in (-1, 1):
        x0, x1 = (-1.75, -0.10) if sx < 0 else (0.10, 1.75)
        d.line(T([(x0, 0.75), (x1, i)]), 'hr', 'CIRCULACION', z=1.5)
        d.line(T([(x0, i), (x1, 0.75)]), 'hr', 'CIRCULACION', z=1.5)
        cx = (x0 + x1) / 2
        d.poly(T(rect(cx - 0.55, 0.95, cx + 0.55, 2.35)), 'fn', 'CIRCULACION', fill=WHITE, z=1.6)
        d.line(T([(cx - 0.45, i + 0.02), (cx + 0.45, i + 0.02)]), 'fn', 'ABERTURAS', z=2.4)
        d.line(T([(cx - 0.45, i + 0.10), (cx + 0.45, i + 0.10)]), 'fn', 'ABERTURAS', z=2.4)
        if labels:
            d.text(Tp((cx, 1.65)), 'ASC.', 1.6, angle=angle, font='Helvetica-Bold', halo=True)
    for sx in (-1, 1):
        x0, x1 = (-i, -1.95) if sx < 0 else (1.95, i)
        d.poly(T(rect(x0, 0.75, x1, i)), 'xf', 'MUROS', hatch=(45, 0.7, 'hr', GRAY(0.4)), z=1.5)
        d.line(T([((x0 + x1) / 2 - 0.25, i + 0.06), ((x0 + x1) / 2 + 0.25, i + 0.06)]), 'fn', 'ABERTURAS', z=2.4)
    # escalera presurizada: tramo S sube hacia el este, tramo N llega desde abajo
    n_tread = {'typ': 9, 'pb': 7, 'p1': 6, 'top': 9}[level]
    run = 0.28
    xs = -1.30
    d.line(T([(xs, -2.55), (xs, 0.55)]), 'xf', 'CIRCULACION', z=1.6)
    for yy0, yy1, draw in ((-i, -1.15, level != 'top'), (-0.85, 0.55, level != 'pb')):
        if not draw:
            continue
        for j in range(n_tread + 1):
            x = xs + j * run
            d.line(T([(x, yy0), (x, yy1)]), 'xf', 'CIRCULACION', z=1.6)
        d.line(T([(xs, yy0 if yy0 > -i else yy1), (xs + n_tread * run, yy0 if yy0 > -i else yy1)]), 'xf', 'CIRCULACION', z=1.6)
    d.poly(T(rect(xs, -1.15, xs + n_tread * run, -0.85)), 'fn', 'CIRCULACION', z=1.7)
    if level not in ('top',):
        # línea de corte del tramo que sube
        xb = xs + 5.5 * run
        d.line(T([(xb - 0.12, -i), (xb + 0.12, -1.15)]), 'fn', 'CIRCULACION', z=1.8)
    if labels:
        ay = -1.85
        if level != 'top':
            d.line(T([(xs - 0.6, ay), (xs + 1.4, ay)]), 'xf', 'CIRCULACION', z=1.9)
            d.poly(T([(xs + 1.4, ay - 0.10), (xs + 1.62, ay), (xs + 1.4, ay + 0.10)]), 'xf', 'CIRCULACION', fill=BLACK, z=1.9)
            d.circle(Tp((xs - 0.6, ay)), 0.06, 'xf', 'CIRCULACION', fill=BLACK, z=1.9)
            d.text(Tp((xs + 2.05, ay)), 'SUBE', 1.5, angle=angle, align='l', halo=True)
        if level != 'pb':
            by = -0.15
            d.line(T([(xs - 0.6, by), (xs + 1.4, by)]), 'xf', 'CIRCULACION', z=1.9)
            d.poly(T([(xs + 1.4, by - 0.10), (xs + 1.62, by), (xs + 1.4, by + 0.10)]), 'xf', 'CIRCULACION', fill=BLACK, z=1.9)
            d.circle(Tp((xs - 0.6, by)), 0.06, 'xf', 'CIRCULACION', fill=BLACK, z=1.9)
            d.text(Tp((xs + 2.05, by)), 'BAJA', 1.5, angle=angle, align='l', halo=True)
    # puerta de la escalera (abre hacia la caja, sentido de evacuación)
    hinge = Tp((-i, 0.50))
    door_leaf(d, hinge, 0.90, rot((0, -1), angle), rot((1, 0), angle))


# ===================================================================== losa de la torre (marco de la planta)
ZONE_STRIPS = {'bosque': 'NSEW', 'lago': 'NSE', 'cumbre': 'NS', 'ph': ''}
SHAPE_RECT = None


def shape_rect(shape):
    O, g = B.O, B.g
    return {'TL': (-O, g, -g, O), 'TR': (g, g, O, O), 'BR': (g, -O, O, -g), 'BL': (-O, -O, -g, -g),
            'LH': (-O, -O, -g, O), 'RH': (g, -O, O, O), 'FULL': (-O, -O, O, O)}[shape]


def strip_rects(zone):
    O, g, R = B.O, B.g, B.R_PAL
    out = {}
    for ch in ZONE_STRIPS[zone]:
        out[ch] = {'N': sbox(-g, R, g, O), 'S': sbox(-g, -O, g, -R), 'E': sbox(R, -g, O, g), 'W': sbox(-O, -g, -R, g)}[ch]
    return out


def unit_envelope(shape):
    return sbox(*shape_rect(shape)).difference(Point(0, 0).buffer(B.R_PAL, 128))


DOOR_ANGLE = {'TL': 135, 'TR': 45, 'BR': -45, 'BL': -135, 'LH': 180, 'RH': 0, 'FULL': 90}
LABEL_POS = {'TL': (-6.4, 8.4), 'TR': (6.4, 8.4), 'BR': (6.4, -5.0), 'BL': (-6.4, -5.0), 'LH': (-6.6, 8.4),
             'RH': (6.6, 8.4), 'FULL': (-6.4, 9.0)}
TYPE_SHEET = {'B1': 'A-401', 'B2': 'A-402', 'L2': 'A-403', 'L3': 'A-404', 'C3': 'A-405', 'PH': 'A-406'}


def facade_glass(pl, n_bays=5):
    """Cerramiento vidriado del cuadrado de fachada (±O) con módulo de parantes y paño ciego en cada eje."""
    O, g = B.O, B.g
    for side in range(4):
        for a, b in ((-O, -g), (g, O)):
            p, q = rot((a, O), side * 90), rot((b, O), side * 90)
            pl.glazing(p, q, 0.10, mull=B.BAY)
        p, q = rot((-g, O), side * 90), rot((g, O), side * 90)
        pl.wall(p, q, 0.25, 'tab', ext=0)


def ring_and_slab(d, plate_frame=True, rail=True, tone=GRAY(0.93), screens=''):
    slab = Polygon(rounded_square(B.A, B.R_SLAB))
    encl = sbox(-B.O, -B.O, B.O, B.O)
    d.geom(slab.difference(encl), 'hv', 'LOSAS', fill=tone, z=0.4)
    if rail:
        rr = slab.buffer(-0.06, join_style=1)
        d.geom(rr, 'xf', 'LOSAS', stroke=True, fill=None, z=0.45)
    for ch in screens:
        p, q = {'N': ((0, B.O), (0, B.A)), 'S': ((0, -B.O), (0, -B.A)), 'E': ((B.O, 0), (B.A, 0)),
                'W': ((-B.O, 0), (-B.A, 0))}[ch]
        d.geom(LineString([p, q]).buffer(0.05, cap_style=2), 'fn', 'MUROS', fill=GRAY(0.5), z=0.5)
    return slab


def draw_plate(d, S, zone, n_ref, labels=True, dims=True, axes=True, core=True, sections=False):
    """Planta tipo de una zona dibujada en su propio marco (las unidades fijas, el núcleo girado)."""
    rot_n = B.ROT[n_ref]
    O, g, R, A = B.O, B.g, B.R_PAL, B.A
    fl = next(f for f in S['floors'] if f['n'] == n_ref)
    strips = strip_rects(zone)
    ring_and_slab(d, screens=ZONE_STRIPS[zone])
    disc = Point(0, 0).buffer(R, 128)
    # áreas comunes: palier y plenos
    d.geom(disc, 'xf', 'SOLADOS', fill=GRAY(0.9), stroke=False, z=0.3)
    pl = Plan(d)
    # muro de unidades hacia el palier (anillo)
    ann = Point(0, 0).buffer(R + B.T_PAL, 128).difference(disc)
    pl.wall_poly(ann, 'mamp')
    # plenos entre unidades
    for ch, r in strips.items():
        x0, y0, x1, y1 = r.bounds
        d.geom(r, 'xf', 'SOLADOS', fill=GRAY(0.86), stroke=False, z=0.3)
        if ch in 'NS':
            pl.wall((-g - B.T_PARTY / 2, y0), (-g - B.T_PARTY / 2, y1), B.T_PARTY, 'mamp', ext=0)
            pl.wall((g + B.T_PARTY / 2, y0), (g + B.T_PARTY / 2, y1), B.T_PARTY, 'mamp', ext=0)
        else:
            pl.wall((x0, -g - B.T_PARTY / 2), (x1, -g - B.T_PARTY / 2), B.T_PARTY, 'mamp', ext=0)
            pl.wall((x0, g + B.T_PARTY / 2), (x1, g + B.T_PARTY / 2), B.T_PARTY, 'mamp', ext=0)
        # acceso al pleno desde el palier
        ang = {'N': 90, 'S': -90, 'E': 0, 'W': 180}[ch]
        cpt = rot((R + B.T_PAL / 2, 0), ang)
        gapr = affinity.rotate(sbox(-0.3, -0.3, 0.3, 0.3), ang, origin=(0, 0))
        pl.cuts.append(affinity.translate(gapr, cpt[0], cpt[1]))
    if zone == 'ph':
        for ang in (90, -90, 0, 180):  # montantes propios del penthouse junto al hall
            r0 = R + B.T_PAL
            rr = affinity.rotate(sbox(r0, -0.45, r0 + 1.1, 0.45), ang, origin=(0, 0))
            d.geom(rr, 'xf', 'SOLADOS', fill=GRAY(0.86), stroke=False, z=0.3)
            pl.wall_poly(rr.buffer(0.10, join_style=2).difference(rr).difference(disc), 'mamp')
    facade_glass(pl)
    # puertas de acceso a cada unidad (abren hacia adentro de la unidad)
    for u in fl['units']:
        ang = DOOR_ANGLE[u['shape']]
        rc = R + B.T_PAL / 2
        cpt = rot((rc, 0), ang)
        gapr = affinity.rotate(sbox(-0.4, -0.475, 0.4, 0.475), ang, origin=(0, 0))
        pl.cuts.append(affinity.translate(gapr, cpt[0], cpt[1]))
        hinge = rot((R + B.T_PAL, -0.475), ang)
        door_leaf(d, hinge, 0.95, rot((0, 1), ang), rot((1, 0), ang), 'fn')
        if labels:
            lp = rot((R - 0.75, 0), ang)
            d.text(lp, u['letter'], 2.6, font='Helvetica-Bold', halo=True)
    pl.draw()
    # columnas inclinadas (giran con la planta)
    for p in B.COLS:
        column(d, p, 'round', B.COL_D)
    if core:
        draw_core(d, 'typ', angle=rot_n)
    if labels:
        T = S['types']
        for u in fl['units']:
            t = T[u['type']]
            x, y = LABEL_POS[u['shape']]
            ids = [f"{n}{u['letter']}" for n in S['zone_floors'][zone]]
            rng = ids[0] if len(ids) == 1 else f'{ids[0]} a {ids[-1]}'
            lines = [(f'UNIDADES {rng}' if len(ids) > 1 else f'UNIDAD {rng}', 3.0, 'Helvetica-Bold'),
                     (f"{t['name']}: {t['rooms_txt']}", 2.4, 'Helvetica'),
                     (f"Cubierta {t['covered']} m² · {t['plan'][0][0].lower()} {t['open']} m² · total {t['covered'] + t['open']} m²", 2.0, 'Helvetica'),
                     (f"Frente al {bearing_info(S, u['bearing'])[0].lower()} en el piso {n_ref}", 2.0, 'Helvetica'),
                     (f"Distribución interior: lámina {TYPE_SHEET[u['type']]}", 2.0, 'Helvetica-Oblique')]
            yy = y
            for s, sz, f in lines:
                d.text((x, yy), s, sz, font=f, halo=True)
                yy -= d.mm(sz * 1.45)
            # flecha hacia el frente principal de la unidad
            b = math.radians(u['local'])
            v = (math.sin(b), math.cos(b))
            if u['shape'] in ('TL', 'TR', 'BR', 'BL'):
                base = (8.6 if x > 0 else -8.6, 9.7 if y > 0 else -9.0)
            elif u['shape'] in ('LH', 'RH'):
                base = (x, -4.0)
            else:
                base = (6.5, 8.8)
            tip = (base[0] + v[0] * 1.6, base[1] + v[1] * 1.6)
            d.line([base, tip], 'th', 'TEXTOS', color=GRAY(0.25), z=4)
            ah = [rot((-0.22, -0.4), -u['local']), rot((0.22, -0.4), -u['local'])]
            d.poly([tip, (tip[0] + ah[0][0], tip[1] + ah[0][1]), (tip[0] + ah[1][0], tip[1] + ah[1][1])], 'xf',
                   'TEXTOS', fill=GRAY(0.25), z=4)
            d.text((base[0] - v[0] * 0.5, base[1] - v[1] * 0.5 - 0.1), 'frente', 1.6, color=GRAY(0.25), halo=True)
        pa = rot((4.45, 0), -112)
        d.text(pa, 'PALIER', 2.0, font='Helvetica-Bold', halo=True)
        d.level_plan(rot((4.45, 0), -68), 'NPT ' + flevel(B.NPT[n_ref]), 1.7)
        for ch, r in strips.items():
            cx, cy = r.centroid.x, r.centroid.y
            if ch in 'NS':
                d.text((cx, 9.5 if cy > 0 else -9.5), 'PLENO', 1.4, angle=90, halo=True)
            else:
                d.text((9.5 if cx > 0 else -9.5, cy), 'PLENO', 1.4, halo=True)
        d.text((0, A - 0.62), 'BALCÓN CORRIDO · BARANDA DE VIDRIO h 1,05', 1.7, color=GRAY(0.2), halo=True)
    s1, s2 = d.mm(9.0), d.mm(17.0)   # cadenas de cotas a 9 y 17 mm del borde de losa
    if axes:
        ext = A + d.mm(26.0)
        for v, lbl in B.GX:
            if abs(v) <= 12:
                d.axis_line((v, -A - d.mm(4)), (v, ext), None, lbl)
        for v, lbl in B.GY:
            if abs(v) <= 12:
                d.axis_line((-ext, v), (A + d.mm(4), v), lbl, None)
    if dims:
        d.chain([(-O, A + s1), (-g, A + s1), (g, A + s1), (O, A + s1)], 0)
        d.chain([(-A, A + s2), (A, A + s2)], 0)
        d.chain([(-A, -A - s1), (-O, -A - s1), (O, -A - s1), (A, -A - s1)], 0)
        d.chain([(-A - s1, -O), (-A - s1, -g), (-A - s1, g), (-A - s1, O)], 0)
        d.chain([(-A - s2, -A), (-A - s2, A)], 0)
    if sections and abs(rot_n) < 1e-9:
        draw_section_marks(d, A + d.mm(36), A + d.mm(24))


def draw_section_marks(d, ext_a, ext_b=None):
    ext_b = ext_b or ext_a
    d.section_mark((-0.925, -ext_b), (-0.925, ext_a), 'A', (-1, 0))
    d.section_mark((-ext_a, -1.85), (ext_b, -1.85), 'B', (0, 1))



# ===================================================================== láminas
class Ctx:
    pass


def keyplan_tower(zone=None, highlight=None, n=None):
    """Plano llave: losa con la zona y la unidad resaltada, más la flecha de norte del piso."""
    def f(c, fr):
        x, y, w, h = fr
        d = Dwg(500)
        slab = Polygon(rounded_square(B.A, B.R_SLAB))
        d.geom(slab, 'fn', 'LOSAS', fill=GRAY(0.95))
        d.geom(sbox(-B.O, -B.O, B.O, B.O), 'th', 'MUROS', fill=WHITE)
        if highlight:
            for sh in highlight:
                d.geom(unit_envelope(sh), 'fn', 'MUROS', fill=GRAY(0.55))
        d.geom(Point(0, 0).buffer(B.R_PAL, 64), 'xf', 'MUROS', fill=GRAY(0.85))
        d.geom(sbox(-B.CORE, -B.CORE, B.CORE, B.CORE), 'xf', 'MUROS', fill=GRAY(0.2))
        rot_n = B.ROT.get(n, 0.0) if n else 0.0
        d.north((B.A + 9.0, B.A - 3.0), -rot_n, 11)
        render(c, d, (x, y, w, h), (4.0, 0), clip=False)
    return f


# ===================================================================== símbolos de equipamiento
def f_rect(d, x0, y0, x1, y1, fill=WHITE, pen='xf', layer='MOBILIARIO', z=1.2, dash=None):
    d.poly(rect(x0, y0, x1, y1), pen, layer, fill=fill, color=GRAY(0.25), z=z, dash=dash)


def f_rot_rect(d, c, w, h, ang, fill=WHITE, pen='xf', layer='MOBILIARIO', z=1.2):
    pts = [rot(p, ang) for p in rect(-w / 2, -h / 2, w / 2, h / 2)]
    d.poly([(c[0] + p[0], c[1] + p[1]) for p in pts], pen, layer, fill=fill, color=GRAY(0.25), z=z)


def f_sofa(d, c, w, dp, ang, layer='MOBILIARIO'):
    """Sofá centrado en c; ang = hacia dónde mira (grados, 0 = +y)."""
    T = lambda pts: [(c[0] + q[0], c[1] + q[1]) for q in (rot(p, ang) for p in pts)]
    d.poly(T(rect(-w / 2, -dp / 2, w / 2, dp / 2)), 'xf', layer, fill=WHITE, color=GRAY(0.25), z=1.2)
    d.poly(T(rect(-w / 2, -dp / 2, w / 2, -dp / 2 + 0.2)), 'xf', layer, fill=GRAY(0.85), color=GRAY(0.25), z=1.25)
    for s in (-1, 1):
        d.poly(T(rect(s * w / 2 - (0.18 if s > 0 else 0), -dp / 2, s * w / 2 + (0 if s > 0 else 0.18), dp / 2)), 'xf', layer,
               fill=GRAY(0.85), color=GRAY(0.25), z=1.25)


def f_table(d, c, w, h, chairs=(0, 0), round_=False, layer='MOBILIARIO'):
    if round_:
        d.circle(c, w / 2, 'xf', layer, fill=WHITE, color=GRAY(0.25), z=1.25)
        n = chairs[0]
        for i in range(n):
            a = 2 * math.pi * i / n
            d.circle((c[0] + math.cos(a) * (w / 2 + 0.3), c[1] + math.sin(a) * (w / 2 + 0.3)), 0.2, 'xf', layer,
                     fill=WHITE, color=GRAY(0.25), z=1.2)
        return
    f_rect(d, c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2, z=1.25)
    nx, ny = chairs
    for i in range(nx):
        x = c[0] - w / 2 + (i + 0.5) * w / nx
        for s in (-1, 1):
            f_rect(d, x - 0.21, c[1] + s * (h / 2 + 0.08) - 0.2 + s * 0.2, x + 0.21, c[1] + s * (h / 2 + 0.08) + 0.2 + s * 0.2, z=1.2)
    for j in range(ny):
        y = c[1] - h / 2 + (j + 0.5) * h / ny
        for s in (-1, 1):
            f_rect(d, c[0] + s * (w / 2 + 0.28) - 0.2, y - 0.21, c[0] + s * (w / 2 + 0.28) + 0.2, y + 0.21, z=1.2)


def f_wc(d, c, ang, layer='MOBILIARIO'):
    T = lambda p: (c[0] + rot(p, ang)[0], c[1] + rot(p, ang)[1])
    d.poly([T(p) for p in rect(-0.2, -0.36, 0.2, -0.18)], 'xf', layer, fill=WHITE, color=GRAY(0.25), z=1.3)
    pts = [T((0.2 * math.cos(t), 0.08 + 0.26 * math.sin(t))) for t in [i * math.pi / 12 for i in range(-12, 13)]]
    d.poly(pts, 'xf', layer, fill=WHITE, color=GRAY(0.25), z=1.3)


def f_sink(d, c, w=0.5, h=0.4, layer='MOBILIARIO'):
    f_rect(d, c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2, z=1.3)
    d.circle(c, min(w, h) * 0.3, 'xf', layer, color=GRAY(0.25), z=1.35)


def f_shower(d, x0, y0, x1, y1, layer='MOBILIARIO'):
    f_rect(d, x0, y0, x1, y1, fill=GRAY(0.94), z=1.1)
    d.line([(x0, y0), (x1, y1)], 'hr', layer, color=GRAY(0.35), z=1.15)
    d.line([(x0, y1), (x1, y0)], 'hr', layer, color=GRAY(0.35), z=1.15)


def f_tree(d, c, r, layer='ENTORNO', z=0.8):
    d.circle(c, r, 'xf', layer, color=GRAY(0.35), z=z)
    d.circle(c, r * 0.12, 'xf', layer, fill=GRAY(0.35), color=GRAY(0.35), z=z)
    for i in range(7):
        a = 2 * math.pi * i / 7 + r
        d.line([(c[0] + math.cos(a) * r * 0.35, c[1] + math.sin(a) * r * 0.35),
                (c[0] + math.cos(a) * r * 0.85, c[1] + math.sin(a) * r * 0.85)], 'hr', layer, color=GRAY(0.5), z=z)


def stair_run(d, x0, y0, x1, y1, n, direction, label=None, cut=None, layer='CIRCULACION'):
    """Tramo recto de n huellas en el rectángulo dado; direction: 'N','S','E','W' (sube hacia)."""
    f_rect(d, x0, y0, x1, y1, fill=WHITE, pen='xf', layer=layer, z=1.4)
    for i in range(1, n):
        if direction in 'NS':
            y = y0 + (y1 - y0) * i / n
            d.line([(x0, y), (x1, y)], 'xf', layer, z=1.45)
        else:
            x = x0 + (x1 - x0) * i / n
            d.line([(x, y0), (x, y1)], 'xf', layer, z=1.45)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    v = {'N': (0, 1), 'S': (0, -1), 'E': (1, 0), 'W': (-1, 0)}[direction]
    L = (y1 - y0) if direction in 'NS' else (x1 - x0)
    a = (cx - v[0] * L * 0.42, cy - v[1] * L * 0.42)
    b = (cx + v[0] * L * 0.42, cy + v[1] * L * 0.42)
    d.line([a, b], 'xf', layer, z=1.5)
    d.circle(a, 0.07, 'xf', layer, fill=BLACK, z=1.5)
    hd = 0.18
    d.poly([b, (b[0] - v[0] * hd * 1.6 - v[1] * hd, b[1] - v[1] * hd * 1.6 + v[0] * hd),
            (b[0] - v[0] * hd * 1.6 + v[1] * hd, b[1] - v[1] * hd * 1.6 - v[0] * hd)], 'xf', layer, fill=BLACK, z=1.5)
    if label:
        d.text((a[0] - v[0] * 0.4, a[1] - v[1] * 0.4), label, 1.6, angle=0, halo=True)


# ===================================================================== basamento: planta baja y primer piso
def podium_facade(level):
    """Tramos de fachada del basamento: (p, q, 'v' vidriado | 'm' macizo)."""
    x0, y0, x1, y1 = B.POD
    if level == 1:
        return [((x0, y1), (x1, y1), 'v'), ((x0, y0), (7.6, y0), 'v'), ((7.6, y0), (x1, y0), 'm'),
                ((x0, y0), (x0, -5.0), 'v'), ((x0, -5.0), (x0, -1.0), 'm'), ((x0, -1.0), (x0, y1), 'v'),
                ((x1, y0), (x1, 4.0), 'm'), ((x1, 4.0), (x1, y1), 'v')]
    return [((x0, y1), (x1, y1), 'v'), ((x0, y0), (-5.6, y0), 'm'), ((-5.6, y0), (3.9, y0), 'v'), ((3.9, y0), (x1, y0), 'm'),
            ((x0, y0), (x0, 2.0), 'm'), ((x0, 2.0), (x0, y1), 'v'), ((x1, y0), (x1, -7.6), 'm'), ((x1, -7.6), (x1, y1), 'v')]


def podium_shell(pl, level):
    """Fachadas del basamento según nivel."""
    for p, q, k in podium_facade(level):
        if k == 'v':
            pl.glazing(p, q, 0.10, 7.6 / 3)
        else:
            pl.wall(p, q, 0.30, 'mamp')


def podium_columns(d):
    for x in (-22.8, -15.2, -7.6, 0.0, 7.6, 15.2, 22.8):
        for y in (-15.2, -7.6, 0.0, 7.6, 15.2):
            if (x, y) == (0.0, 0.0):
                continue
            if (x, y) in [tuple(map(float, p)) for p in B.COLS]:
                continue
            column(d, (x, y), 'sq', 0.5)
    for p in B.COLS:
        column(d, p, 'round', B.COL_D + 0.1)


def podium_axes(d, ext=None, which='top'):
    x0, y0, x1, y1 = B.POD
    e = ext if ext is not None else d.mm(30)
    for v, l in B.GX:
        if which == 'top':
            d.axis_line((v, y0 - d.mm(4)), (v, y1 + e), None, l)
        else:
            d.axis_line((v, y0 - e), (v, y1 + d.mm(4)), l, None)
    for v, l in B.GY:
        d.axis_line((x0 - e, v), (x1 + d.mm(4), v), l, None)


def plan_pb(d, S):
    pl = Plan(d)
    x0, y0, x1, y1 = B.POD
    podium_shell(pl, 1)
    W = lambda a, b, t=0.15: pl.wall(a, b, t, 'mamp')
    # bloque oeste
    W((-7.6, y0), (-7.6, -1.0))
    pl.glazing((-7.6, -1.0), (-7.6, y1), 0.08)
    W((x0, -1.0), (-7.6, -1.0))
    W((-15.2, y0), (-15.2, -1.0))
    W((x0, -5.0), (-15.2, -5.0))
    W((-15.2, -7.0), (-7.6, -7.0))
    W((-20.5, -5.0), (-20.5, -1.0))
    W((-17.8, -5.0), (-17.8, -1.0))
    # bloque este
    W((7.6, y0), (7.6, -7.6))
    W((7.6, -6.1), (7.6, 4.0))
    pl.glazing((7.6, 4.0), (7.6, y1), 0.08)
    W((7.6, 4.0), (x1, 4.0))
    W((7.6, -1.0), (15.2, -1.0))
    W((15.2, -6.1), (15.2, 4.0))
    W((7.6, -6.1), (x1, -6.1))
    W((7.6, -7.6), (x1, -7.6))
    for x in (11.4, 15.2, 19.0):
        W((x, y0), (x, -7.6))
    # cortaviento
    pl.glazing((-2.4, y0), (-2.4, -12.5), 0.08)
    pl.glazing((2.4, y0), (2.4, -12.5), 0.08)
    pl.glazing((-2.4, -12.5), (2.4, -12.5), 0.08)
    # puertas
    pl.door((0, y0), 2.0, False, 1, kind='auto', t=0.3)
    pl.door((0, -12.5), 2.0, False, 1, kind='auto', t=0.3)
    pl.door((-7.6, -11.0), 1.6, True, -1, double=True)
    pl.door((-7.6, -4.0), 0.9, True, -1, hinge=1)
    pl.door((-7.6, 6.0), 1.8, True, -1, double=True, t=0.3)
    pl.door((-11.5, -1.0), 0.9, False, 1)
    for x in (-21.8, -19.15, -16.5):
        pl.door((x, -1.0), 0.9, False, -1, hinge=1)
    pl.door((-15.2, -11.0), 0.9, True, 1)
    pl.door((7.6, 9.5), 1.8, True, 1, double=True, t=0.3)
    pl.door((11.0, 4.0), 0.9, False, -1)
    pl.door((10.0, -6.1), 0.9, False, 1)
    pl.door((19.0, -6.1), 1.2, False, 1)
    for x in (9.5, 13.3, 17.1, 21.0):
        pl.door((x, -7.6), 0.9, False, -1)
    pl.door((x1, -6.85), 1.1, True, 1, hinge=1)
    pl.door((x1, -1.5), 3.6, True, 1, kind='corrediza')
    pl.door((17.1, y0), 1.6, False, -1, double=True)
    pl.door((21.0, y0), 1.4, False, -1, double=True)
    for x in (-13.0, 0.0, 13.0):
        pl.door((x, y1), 2.4, False, 1, kind='corrediza', t=0.3)
    # locales
    R = pl.room
    R('Cortaviento', rect(-2.4, y0, 2.4, -12.5), size=1.8)
    hall = sbox(-7.6, y0, 7.6, 0).difference(sbox(-2.4, y0, 2.4, -12.5)).difference(sbox(-2.8, -2.8, 2.8, 2.8))
    lob = sbox(-7.6, 0, 7.6, y1).difference(sbox(-2.8, -2.8, 2.8, 2.8))
    R('Hall de acceso', list(hall.exterior.coords)[:-1], lpos=(-3.9, -9.0))
    R('Lobby', list(lob.exterior.coords)[:-1], lpos=(0, 11.0), sub='estar con vista al lago')
    R('Fogón', rect(x0, -1.0, -7.6, y1), lpos=(-15.3, 12.4), sub='salón con hogar a leña')
    R('Administración', rect(x0, y0, -15.2, -5.0))
    R('Damas', rect(x0, -5.0, -20.5, -1.0), size=1.6)
    R('Caballeros', rect(-20.5, -5.0, -17.8, -1.0), size=1.6)
    R('Accesible', rect(-17.8, -5.0, -15.2, -1.0), size=1.6)
    R('Paquetería', rect(-15.2, y0, -7.6, -7.0), sub='correspondencia')
    R('Office', rect(-15.2, -7.0, -7.6, -1.0), sub='apoyo del fogón')
    R('SUM', rect(7.6, 4.0, x1, y1), lpos=(15.3, 12.4), sub='salón de usos múltiples')
    R('Sanitarios SUM', rect(7.6, -1.0, 15.2, 4.0), size=1.8)
    R('Vestuario personal', rect(7.6, -6.1, 15.2, -1.0), size=1.8)
    R('Guardería náutica', rect(15.2, -6.1, x1, 4.0), sub='kayaks y bicicletas', size=1.9)
    R('Circulación de servicio', rect(7.6, -7.6, x1, -6.1), area=False, size=1.4)
    R('Medidores', rect(7.6, y0, 11.4, -7.6), size=1.7)
    R('Bombas', rect(11.4, y0, 15.2, -7.6), sub='tanque de bombeo', size=1.7)
    R('Grupo electr.', rect(15.2, y0, 19.0, -7.6), size=1.7)
    R('Residuos', rect(19.0, y0, x1, -7.6), size=1.7)
    pl.draw()
    # equipamiento
    f_rect(d, -6.6, -7.9, -3.6, -7.2, fill=GRAY(0.9))
    d.text((-5.1, -7.55), 'recepción', 1.5, halo=True)
    for c_, a_ in (((-4.2, 8.0), 180), ((-4.2, 5.4), 0), ((4.2, 8.0), 180), ((4.2, 5.4), 0)):
        f_sofa(d, c_, 2.4, 0.9, a_)
    f_table(d, (-4.2, 6.7), 1.2, 0.6)
    f_table(d, (4.2, 6.7), 1.2, 0.6)
    d.circle((-15.3, 7.0), 1.2, 'fn', 'MOBILIARIO', fill=GRAY(0.85), z=1.3)
    d.circle((-15.3, 7.0), 0.55, 'xf', 'MOBILIARIO', fill=WHITE, z=1.35)
    d.text((-15.3, 5.3), 'hogar central', 1.5, halo=True)
    for a_ in (0, 90, 180, 270):
        p_ = rot((0, 3.2), a_)
        f_sofa(d, (-15.3 + p_[0], 7.0 + p_[1]), 2.6, 0.9, a_ + 180)
    f_table(d, (-11.0, 2.2), 2.4, 1.0, (3, 0))
    f_table(d, (-19.5, 2.2), 2.4, 1.0, (3, 0))
    f_table(d, (15.3, 8.0), 4.8, 1.1, (6, 1))
    f_rect(d, 22.3, 4.6, 22.95, 10.4, fill=GRAY(0.9))
    for i in range(5):
        f_rect(d, 16.0, -5.4 + i * 1.7, 22.4, -5.0 + i * 1.7, fill=GRAY(0.92))
    d.text((19.2, 2.9), 'racks', 1.5, halo=True)
    for x, y in ((-22.3, -4.4), (-19.8, -4.4), (-17.1, -4.4)):
        f_wc(d, (x + 0.4, y + 0.1), 0)
    for x in (-22.5, -19.9):
        f_sink(d, (x + 1.3, -1.5))
    # escalera del club (PB -> 1° piso), dos tramos de 15 alzadas
    stair_run(d, 4.2, -11.0, 5.7, -7.08, 14, 'N', 'SUBE')
    f_rect(d, 4.2, -7.08, 7.4, -5.6, fill=WHITE, layer='CIRCULACION', z=1.4)
    stair_run(d, 5.9, -11.0, 7.4, -7.08, 14, 'S')
    d.line([(5.8, -11.0), (5.8, -7.08)], 'fn', 'CIRCULACION', z=1.5)
    d.line([(6.05, -9.6), (7.25, -9.2)], 'fn', 'CIRCULACION', z=1.6)
    draw_core(d, 'pb')
    podium_columns(d)
    d.level_plan((0.0, -5.4), 'NPT ±0,00', 2.0)
    d.level_plan((0.0, 4.4), 'NPT ±0,00', 2.0)
    return pl


def plan_p1(d, S):
    pl = Plan(d)
    x0, y0, x1, y1 = B.POD
    podium_shell(pl, 2)
    W = lambda a, b, t=0.15: pl.wall(a, b, t, 'mamp')
    pl.glazing((-7.6, 2.0), (-7.6, y1), 0.08)
    W((-7.6, -4.5), (-7.6, 2.0))
    W((-7.6, y0), (-7.6, -6.0))
    W((x0, 2.0), (-7.6, 2.0))
    W((-15.4, -4.5), (-15.4, 2.0))
    W((x0, -4.5), (-7.6, -4.5))
    W((x0, -6.0), (-7.6, -6.0))
    W((x0, -10.0), (-16.1, -10.0))
    W((-19.6, -10.0), (-19.6, -6.0))
    W((-16.1, y0), (-16.1, -6.0))
    W((-13.1, y0), (-13.1, -6.0))
    W((-13.1, -10.5), (-7.6, -10.5))
    W((-10.35, -10.5), (-10.35, -6.0))
    W((-5.6, y0), (-5.6, -9.0))
    W((3.9, y0), (3.9, -9.0))
    pl.glazing((-5.6, -9.0), (3.9, -9.0), 0.08)
    pl.glazing((7.6, 2.0), (7.6, y1), 0.08)
    W((7.6, -7.6), (7.6, 2.0))
    W((7.6, 2.0), (x1, 2.0))
    W((7.6, -7.6), (x1, -7.6))
    W((7.6, -9.1), (x1, -9.1))
    W((7.6, y0), (7.6, -9.1))
    for x in (10.8, 14.0, 17.4):
        W((x, y0), (x, -9.1))
    # puertas
    pl.door((-18.5, 2.0), 0.9, False, 1)
    pl.door((-11.0, 2.0), 0.9, False, 1)
    pl.door((-17.6, -4.5), 0.9, False, 1)
    pl.door((-9.6, -4.5), 0.9, False, 1)
    pl.door((-21.4, -6.0), 0.8, False, -1)
    pl.door((-17.9, -6.0), 0.8, False, -1)
    pl.door((-14.6, -6.0), 0.9, False, -1)
    pl.door((-11.7, -6.0), 0.9, False, -1)
    pl.door((-9.0, -6.0), 0.9, False, -1)
    pl.door((-16.1, -12.8), 0.9, True, -1)
    pl.door((-7.6, -13.0), 0.9, True, -1)
    pl.door((-7.6, 4.0), 0.9, True, -1)
    pl.door((-1.0, -9.0), 0.9, False, -1, t=0.3)
    pl.door((7.6, 5.0), 1.8, True, 1, double=True, t=0.3)
    pl.door((7.6, -3.0), 1.6, True, 1, double=True)
    for x in (9.2, 12.4, 15.7, 20.2):
        pl.door((x, -9.1), 0.9, False, -1)
    R = pl.room
    hall = sbox(-7.6, -9.0, 7.6, y1).difference(sbox(-2.8, -2.8, 2.8, 2.8)).difference(sbox(4.2, -12.6, 7.4, -5.6))
    R('Hall del club', list(hall.exterior.coords)[:-1], lpos=(0, 13.9), sub='estar y cafetería')
    R('Natatorio', rect(x0, 2.0, -7.6, y1), lpos=(-15.3, 6.4), sub='pileta climatizada 12,50 x 5,00')
    R('Vestuario damas', rect(x0, -4.5, -15.4, 2.0), size=1.9, lpos=(-19.2, 0.25))
    R('Vestuario caballeros', rect(-15.4, -4.5, -7.6, 2.0), size=1.9, lpos=(-11.5, 0.25))
    R('Circulación spa', rect(x0, -6.0, -7.6, -4.5), area=False, size=1.4)
    R('Sauna', rect(x0, -10.0, -19.6, -6.0), size=1.8)
    R('Vapor', rect(-19.6, -10.0, -16.1, -6.0), size=1.8)
    R('Relax', rect(x0, y0, -16.1, -10.0), size=1.9)
    R('Duchas', rect(-16.1, y0, -13.1, -6.0), size=1.8)
    R('Masajes', rect(-13.1, -10.5, -10.35, -6.0), size=1.6)
    R('Masajes', rect(-10.35, -10.5, -7.6, -6.0), size=1.6)
    R('Máq. pileta', rect(-13.1, y0, -7.6, -10.5), size=1.7)
    R('Paso', rect(-7.6, y0, -5.6, -9.0), area=False, size=1.4, angle=90)
    R('Cowork', rect(-5.6, y0, 3.9, -9.0))
    R('Gimnasio', rect(7.6, 2.0, x1, y1), lpos=(15.3, 12.6))
    R('Sala de clases', rect(7.6, -7.6, x1, 2.0), sub='yoga y funcional')
    R('Circulación', rect(7.6, -9.1, x1, -7.6), area=False, size=1.4)
    R('Damas', rect(7.6, y0, 10.8, -9.1), size=1.7)
    R('Caballeros', rect(10.8, y0, 14.0, -9.1), size=1.7)
    R('Depósito', rect(14.0, y0, 17.4, -9.1), size=1.7)
    R('Climatización', rect(17.4, y0, x1, -9.1), size=1.7, sub='calderas y UTA')
    pl.draw()
    # pileta y equipamiento
    d.poly(rect(-21.6, 8.4, -9.1, 13.4), 'th', 'MOBILIARIO', fill=GRAY(0.88), z=1.2)
    d.poly(rect(-21.45, 8.55, -9.25, 13.25), 'xf', 'MOBILIARIO', z=1.25)
    for k in (1, 2):
        y = 8.4 + 5.0 * k / 3
        d.line([(-21.0, y), (-9.7, y)], 'hr', 'MOBILIARIO', dash='dash', z=1.3)
    for k in range(4):
        f_rect(d, -9.1 - 0.0, 8.6 + k * 0.3, -8.6, 8.9 + k * 0.3, fill=WHITE, z=1.3)
    d.circle((-20.4, 4.8), 1.2, 'fn', 'MOBILIARIO', fill=GRAY(0.88), z=1.2)
    d.text((-20.4, 4.8), 'hidromasaje', 1.4, halo=True)
    for k in range(5):
        f_rot_rect(d, (-16.6 + k * 1.6, 4.2), 0.7, 1.9, 0)
    f_rect(d, -6.4, -7.6, -3.4, -6.9, fill=GRAY(0.9))
    d.text((-4.9, -7.25), 'control', 1.4, halo=True)
    for k in range(3):
        f_table(d, (-3.0 + k * 3.0, 9.0), 1.0, 1.0, (4,), round_=True)
    for i in range(6):
        for j in range(3):
            f_rect(d, 9.0 + i * 2.3, 9.5 + j * 1.9, 10.6 + i * 2.3, 10.4 + j * 1.9, fill=GRAY(0.9))
    for i in range(6):
        f_rect(d, 9.2 + i * 2.3, 3.3, 10.0 + i * 2.3, 5.2, fill=GRAY(0.9))
    for i in range(8):
        for j in range(2):
            f_rect(d, 9.0 + i * 1.75, -6.4 + j * 3.6, 9.65 + i * 1.75, -4.6 + j * 3.6, fill=WHITE)
    for x0_, x1_ in ((-22.9, -15.6), (-15.2, -7.8)):
        f_rect(d, x0_ + 0.2, 1.3, x1_ - 0.2, 1.8, fill=GRAY(0.9))
        f_rect(d, x0_ + 1.0, -1.6, x1_ - 1.0, -1.2, fill=WHITE)
        f_shower(d, x0_ + 0.2, -4.3, x0_ + 1.2, -3.3)
        f_shower(d, x0_ + 1.3, -4.3, x0_ + 2.3, -3.3)
        f_wc(d, (x1_ - 0.6, -3.9), 0)
    for k in range(3):
        f_shower(d, -15.9 + k * 0.0, -15.2 + k * 1.1, -14.9, -14.2 + k * 1.1)
    f_rect(d, -22.9, -9.8, -22.3, -6.2, fill=GRAY(0.9))
    f_rect(d, -19.4, -9.8, -18.8, -6.2, fill=GRAY(0.9))
    for x in (-11.75, -9.0):
        f_rect(d, x - 0.35, -9.6, x + 0.35, -7.7, fill=WHITE)
    for k in range(3):
        f_table(d, (-3.8 + k * 3.4, -12.6), 1.6, 0.8, (2, 0))
    stair_run(d, 4.2, -11.0, 5.7, -7.08, 14, 'N', None)
    f_rect(d, 4.2, -7.08, 7.4, -5.6, fill=WHITE, layer='CIRCULACION', z=1.4)
    stair_run(d, 5.9, -11.0, 7.4, -7.08, 14, 'S', None)
    f_rect(d, 4.2, -12.6, 7.4, -11.0, fill=WHITE, layer='CIRCULACION', z=1.4)
    d.text((6.65, -11.8), 'llega', 1.4, halo=True)
    d.line([(4.1, -12.7), (4.1, -5.5), (7.5, -5.5)], 'th', 'MUROS', z=2.5)
    draw_core(d, 'p1')
    podium_columns(d)
    d.level_plan((0.0, -5.4), 'NPT ' + flevel(B.NPT[2]), 2.0)
    d.level_plan((-15.3, 14.4), 'NPT ' + flevel(B.NPT[2]), 1.8)
    return pl


def podium_dims(d):
    x0, y0, x1, y1 = B.POD
    xs = [x0] + [v for v, _ in B.GX] + [x1]
    s1, s2 = d.mm(9.0), d.mm(17.0)
    d.chain([(v, y0 - s1) for v in [v for v, _ in B.GX]], 0)
    d.chain([(x0, y0 - s2), (x1, y0 - s2)], 0)
    d.chain([(x1 + s1, v) for v in [v for v, _ in B.GY]], 0)
    d.chain([(x1 + s2, y0), (x1 + s2, y1)], 0)


# ===================================================================== implantación y obras exteriores
LOT = (-45.0, -70.0, 45.0, 36.0)   # lote: 90,00 x 106,00 m
SHORE_Y = 53.0                     # línea de ribera (40 m desde la losa del piso 3)
PROMENADE = (36.0, 46.0)


def shore_line(x0, x1, n=60):
    pts = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        pts.append((x, SHORE_Y + 1.6 * math.sin(x / 13.0) + 0.9 * math.sin(x / 5.3 + 1.0)))
    return pts


def parking_spaces():
    out = []
    for i in range(26):
        x = -32.5 + i * 2.5
        out.append(rect(x, -36.0, x + 2.5, -31.0))
        out.append(rect(x, -47.0, x + 2.5, -42.0))
    return out


TREES = [(-38, 27, 3.2), (-30, 26.5, 2.6), (-21, 27.5, 3.0), (11, 28.5, 2.8), (23, 27.5, 3.0), (39, 25.0, 2.6),
         (-40, 14, 3.0), (-38, 2, 2.6), (-40, -10, 3.2), (38, 12, 3.0), (40, -2, 2.6), (38, -14, 3.0), (-28, -20, 2.4),
         (28, -20, 2.4), (-40, -28, 2.8), (40, -28, 2.8), (-40, -52, 3.0), (40, -52, 3.0), (-20, -60, 2.6), (0, -62, 3.0),
         (20, -60, 2.6), (-38, -64, 2.4), (38, -64, 2.4), (-33, 20, 2.2)]


def site_works(d, detail=True):
    """Obras exteriores en el marco del sitio. detail=False para la escala 1:500."""
    lx0, ly0, lx1, ly1 = LOT
    # entorno: lago, ribera, paseo costero, calles
    d.poly(shore_line(-160, 160) + [(160, 120), (-160, 120)], 'fn', 'ENTORNO', fill=GRAY(0.86), z=0.1)
    for k in range(1, 6):
        d.line([(x, y + 3.0 * k) for x, y in shore_line(-160, 160)], 'hr', 'ENTORNO', color=GRAY(0.55), dash='long', z=0.15)
    d.poly(rect(-160, PROMENADE[0], 160, PROMENADE[1]), 'fn', 'ENTORNO', fill=GRAY(0.95), z=0.2)
    d.line([(-160, PROMENADE[0] + 3.0), (160, PROMENADE[0] + 3.0)], 'hr', 'ENTORNO', dash='dash', z=0.25)
    d.poly(rect(-60, -160, lx0, PROMENADE[0]), 'fn', 'ENTORNO', fill=GRAY(0.9), z=0.2)
    d.poly(rect(-160, ly0 - 20, 160, ly0), 'fn', 'ENTORNO', fill=GRAY(0.9), z=0.2)
    d.line([(-52.5, -160), (-52.5, PROMENADE[0])], 'hr', 'ENTORNO', dash='dash', z=0.25)
    d.line([(-160, ly0 - 10), (160, ly0 - 10)], 'hr', 'ENTORNO', dash='dash', z=0.25)
    # lote y retiros
    d.poly(rect(*LOT), 'hv', 'ENTORNO', dash='axis', z=3)
    d.line([(lx0, 16.0), (lx1, 16.0)], 'fn', 'ENTORNO', dash='dash', color=GRAY(0.3), z=2.9)
    for x in (lx0 + 6.0, lx1 - 6.0):
        d.line([(x, ly0), (x, ly1)], 'hr', 'ENTORNO', dash='dash', color=GRAY(0.3), z=2.9)
    # accesos, solados
    d.poly(rect(-60, -40.0, -32.5, -36.0), 'fn', 'ENTORNO', fill=GRAY(0.82), z=0.6)
    drive = [(-45, -40.0), (-45, -36.0), (-33.0, -36.0), (-33.0, -22.0), (-6.0, -22.0), (-6.0, -18.5), (6.0, -18.5),
             (6.0, -22.0), (36.5, -22.0), (36.5, -42.0), (32.5, -42.0), (32.5, -36.0), (-32.5, -36.0), (-32.5, -40.0)]
    d.poly([(-45.0, -40.0), (-32.5, -40.0), (-32.5, -26.0), (32.5, -26.0), (32.5, -42.0), (36.5, -42.0), (36.5, -22.0),
            (-36.5, -22.0), (-36.5, -36.0), (-45.0, -36.0)], 'fn', 'ENTORNO', fill=GRAY(0.82), z=0.6)
    d.poly(rect(-32.5, -42.0, 32.5, -36.0), 'fn', 'ENTORNO', fill=GRAY(0.82), z=0.6)
    for sp in parking_spaces():
        d.poly(sp, 'xf', 'ENTORNO', z=0.7)
    d.poly(rect(-33.0, -47.6, 33.0, -30.4), 'fn', 'ENTORNO', dash='dash', z=0.75)
    # plaza de acceso y dársena
    d.poly(rect(-12.0, -22.0, 12.0, B.POD[1]), 'fn', 'ENTORNO', fill=GRAY(0.93), z=0.5)
    d.poly(rect(-6.0, -26.0, 6.0, -22.0), 'fn', 'ENTORNO', fill=GRAY(0.82), z=0.6)
    # terrazas sobre el lago
    d.poly(rect(-23.1, B.POD[3], 9.0, 24.0), 'fn', 'ENTORNO', fill=GRAY(0.9), z=0.5)
    d.circle((-14.0, 19.5), 1.6, 'fn', 'ENTORNO', fill=GRAY(0.7), z=0.6)
    d.circle((-14.0, 19.5), 3.2, 'xf', 'ENTORNO', z=0.6)
    d.circle((-14.0, 19.5), 3.9, 'xf', 'ENTORNO', z=0.6)
    for k in range(6):
        y = 24.0 + k * 0.32
        d.line([(-6.0, y), (6.0, y)], 'xf', 'ENTORNO', z=0.6)
    d.poly(rect(-2.0, 25.9, 2.0, PROMENADE[0]), 'fn', 'ENTORNO', fill=GRAY(0.93), z=0.5)
    d.poly(rect(-2.0, -70.0, 2.0, -26.0), 'fn', 'ENTORNO', fill=GRAY(0.93), z=0.5)
    # pérgolas del estacionamiento
    for (a, b) in ((-36.0, -31.0), (-47.0, -42.0)):
        for i in range(14):
            x = -32.5 + i * 5.0
            d.line([(x, a), (x, b)], 'hr', 'ENTORNO', color=GRAY(0.45), z=0.8)
    for x, y, r in TREES:
        f_tree(d, (x, y), r)
    for i in range(18):
        x = 50 + (i % 6) * 9.5 + (i // 6) * 3.0
        y = -60 + (i // 6) * 35 + (i % 3) * 6
        f_tree(d, (x, y), 3.0 + (i % 3) * 0.6)
    # basamento y torre
    d.poly(rect(*B.POD), 'hv', 'MUROS', fill=WHITE, z=0.9)
    slab_env = unary_union([Polygon([rot(p, -B.ROT[n]) for p in rounded_square(B.A, B.R_SLAB, 8)]) for n in range(3, 20)])
    d.geom(slab_env, 'fn', 'LOSAS', dash='dash', z=2.5)
    d.poly(rounded_square(B.A, B.R_SLAB, 8), 'fn', 'LOSAS', dash='hidden', z=2.5)
    if detail:
        pass
    return slab_env


def room_schedule_rows(pl, skip=('Circulación', 'Circulación spa', 'Circulación de servicio', 'Paso')):
    rows = []
    for r in pl.rooms:
        if r['name'] in skip or not r['area']:
            continue
        rows.append([r['name'] + ((' · ' + r['sub']) if r['sub'] else ''), fnum(Polygon(r['poly']).area)])
    return rows


def sh_A101(X, c):
    S = X.S
    d = Dwg(200)
    site_works(d)
    pl = plan_pb(d, S)
    podium_axes(d, ext=d.mm(14), which='bottom')
    x0, y0, x1, y1 = B.POD
    lx0, ly0, lx1, ly1 = LOT
    # cotas generales del lote y del basamento
    d.chain([(lx0, 31.0), (x0, 31.0), (x1, 31.0), (lx1, 31.0)], 0)
    d.chain([(lx0 - d.mm(8), ly0), (lx0 - d.mm(8), y0), (lx0 - d.mm(8), y1), (lx0 - d.mm(8), 16.0), (lx0 - d.mm(8), ly1)], 0)
    d.chain([(lx0 - d.mm(16), ly0), (lx0 - d.mm(16), ly1)], 0)
    d.chain([(lx0, ly0 - d.mm(6)), (lx1, ly0 - d.mm(6))], 0)
    draw_section_marks(d, 27.0, 27.5)
    d.text((-15.0, 34.6), 'LÍNEA MUNICIPAL · PASEO COSTERO PÚBLICO', 1.9, color=GRAY(0.2), halo=True)
    d.text((0.0, 17.2), 'línea de retiro costanero (20,00 m)', 1.6, color=GRAY(0.25), halo=True)
    d.text((-14.0, 23.9), 'fogón exterior', 1.6, halo=True)
    d.text((-8.0, 20.5), 'TERRAZA DEL FOGÓN', 2.0, font='Helvetica-Bold', halo=True)
    d.text((0, 27.0), 'escalinata al paseo costero', 1.6, angle=90, halo=True)
    d.text((0, -24.0), 'dársena de ascenso y descenso', 1.6, halo=True)
    d.text((0, -19.0), 'PLAZA DE ACCESO', 2.0, font='Helvetica-Bold', halo=True)
    d.text((0, -39.0), 'ESTACIONAMIENTO SEMICUBIERTO · 52 COCHERAS BAJO PÉRGOLA', 2.0, font='Helvetica-Bold', halo=True)
    d.text((-52.5, -10.0), 'CALLE LOS ÑIRES', 2.6, angle=90, font='Helvetica-Bold', halo=True)
    d.text((-50.0, -38.0), 'acceso vehicular', 1.6, halo=True)
    d.text((0.0, -66.0), 'acceso peatonal', 1.6, angle=90, halo=True)
    d.text((48.0, 0.0), 'RESERVA DE BOSQUE NATIVO (LENGAS)', 2.2, angle=90, font='Helvetica-Bold', halo=True)
    d.text((-9.4, 13.6), 'proyección losa piso 3', 1.5, color=GRAY(0.25), halo=True)
    d.text((14.2, 17.4), 'envolvente de losas giradas (pisos 3 a 18)', 1.5, color=GRAY(0.25), halo=True)
    for p, t in (((0.0, 21.0), '-0,15'), ((-14.0, 15.9), '-0,15'), ((5.0, -20.6), '-0,05'), ((-20.0, -40.0), '+0,30'),
                 ((-40.0, 33.5), '-0,90'), ((30.0, -56.0), '+0,60')):
        d.level_plan(p, flevel(float(t.replace(',', '.'))), 1.7)
    d.north((31.0, 20.0), 0, 16)
    d.text((14.0, -72.6), 'AV. DEL CERRO', 2.2, font='Helvetica-Bold', halo=True)
    render(c, d, (DA[0], DA[1] + 18, DA[2], DA[3] - 18), (-6.0, -18.6))
    caption(c, DA[0] + 6, DA[1] + 9, 1, 'PLANTA BAJA · NIVEL 1 · LOBBY, FOGÓN Y SERVICIOS', 'Esc. 1:200',
            'NPT ±0,00 = 771,50 m s.n.m.')
    return {'A-101_planta_baja': d}


def sh_A102(X, c):
    S = X.S
    d = Dwg(100)
    pl = plan_p1(d, S)
    podium_axes(d)
    podium_dims(d)
    # losa del piso 3 por encima (proyección)
    d.poly(rounded_square(B.A, B.R_SLAB, 8), 'fn', 'LOSAS', dash='hidden', z=2.6)
    d.text((B.A - 3.5, B.A + 0.5), 'proyección losa piso 3', 1.8, color=GRAY(0.25), halo=True)
    d.north((B.POD[2] + 4.0, B.POD[3] + 6.5), 0, 16)
    frame = (DA[0], DA[1] + 170, DA[2], DA[3] - 170)
    render(c, d, frame, (0.6, 1.6))
    caption(c, DA[0] + 6, DA[1] + 162, 1, 'PLANTA PRIMER PISO · NIVEL 2 · CLUB', 'Esc. 1:100',
            f'NPT {flevel(B.NPT[2])}: pileta, spa, gimnasio y cowork')
    rows = room_schedule_rows(pl)
    half = (len(rows) + 1) // 2
    head = ['Local', 'Sup. (m²)']
    ty = DA[1] + 150
    txt(c, DA[0] + 6, ty, 'Planilla de locales del club (superficies a ejes)', 3.0, 'Helvetica-Bold')
    table(c, DA[0] + 6, ty - 4, [92, 24], rows[:half], head=head, size=2.2, rowh=5.0, aligns=['l', 'r'])
    table(c, DA[0] + 128, ty - 4, [92, 24], rows[half:], head=head, size=2.2, rowh=5.0, aligns=['l', 'r'])
    tx = DA[0] + 262
    txt(c, tx, ty, 'Criterios del basamento', 3.0, 'Helvetica-Bold')
    yy = ty - 7
    for ln in [
        'Los dos niveles del basamento son de uso común de los 49 departamentos (club). La pileta climatizada de 12,50 x 5,00 m '
        'y el natatorio miran al lago; el ingreso al agua es por los vestuarios.',
        'La escalera del club une la planta baja con este nivel en dos tramos de 15 alzadas. La escalera presurizada del '
        'núcleo resuelve el basamento con dos vueltas por piso (alturas 4,80 y 4,20 m).',
        'Sala de climatización: calderas de condensación, unidad de tratamiento de aire del natatorio y bombas de la pileta '
        'en la sala de máquinas junto a las duchas.',
        'La losa del piso 3 cubre el centro del basamento; el resto de la cubierta del basamento es cubierta verde no '
        'transitable (ver A-105).',
    ]:
        yy = para(c, tx, yy, ln, 2.3, 112) - 2.0
    return {'A-102_planta_primer_piso': d}


# ===================================================================== vistas y cortes
VIEW = {  # u = coordenada horizontal en el papel, w = profundidad (mayor = más cerca del observador)
    'N': (lambda p: -p[0], lambda p: p[1], 'VISTA NORTE', 'desde el lago'),
    'S': (lambda p: p[0], lambda p: -p[1], 'VISTA SUR', 'desde la avenida del Cerro'),
    'E': (lambda p: p[1], lambda p: p[0], 'VISTA ESTE', 'desde la reserva de lengas'),
    'W': (lambda p: -p[1], lambda p: -p[0], 'VISTA OESTE', 'desde la calle Los Ñires'),
}
ZONE_OF = {}


def floor_zone(S, n):
    if n >= 19:
        return 'ph'
    return next(f['zone'] for f in S['floors'] if f['n'] == n)


def plate_slab(n, half=None):
    return Polygon([rot(p, -B.ROT[n]) for p in rounded_square(half or B.A, B.R_SLAB, 10)])


def facade_points(n):
    """Caras del cerramiento girado del piso n: lista de (p0, p1, normal) y posiciones de parantes."""
    O, g = B.O, B.g
    faces = []
    for side in range(4):
        a = side * 90 - B.ROT[n]
        p0, p1 = rot((-O, O), a), rot((O, O), a)
        nrm = rot((0, 1), a)
        ss = []
        k = -O
        while k < -g + 1e-6:
            ss.append(k)
            k += B.BAY
        ss += [-g, g]
        k = g + B.BAY
        while k < O + 1e-6:
            ss.append(k)
            k += B.BAY
        faces.append((p0, p1, nrm, [rot((s_, O), a) for s_ in ss], (rot((-g, O), a), rot((g, O), a))))
    return faces


def elevation(d, S, view, x0p=0.0):
    U, Wd, title, sub = VIEW[view]
    vdir = {'N': (0, 1), 'S': (0, -1), 'E': (1, 0), 'W': (-1, 0)}[view]  # hacia el observador
    H = lambda u, z: (x0p + u, z)
    glass_fill, slab_fill = GRAY(0.84), WHITE
    # torre: pisos 3 a 18 y losa de cubierta
    for n in range(3, 20):
        z = B.NPT[n]
        top = (B.NPT[n + 1] if n < 19 else z) - B.FIN - B.SLAB
        if n < 19:
            for p0, p1, nrm, mulls, (pa, pb) in facade_points(n):
                vis = nrm[0] * vdir[0] + nrm[1] * vdir[1]
                if vis <= 1e-6:
                    continue
                u0, u1 = sorted((U(p0), U(p1)))
                d.poly([H(u0, z), H(u1, z), H(u1, top), H(u0, top)], 'xf', 'ABERTURAS', fill=glass_fill, z=1.0)
                ua, ub = sorted((U(pa), U(pb)))
                d.poly([H(ua, z), H(ub, z), H(ub, top), H(ua, top)], 'xf', 'MUROS', fill=WHITE, z=1.05)
                for m in mulls:
                    um = U(m)
                    d.line([H(um, z), H(um, top)], 'hr' if vis < 0.35 else 'xf', 'ABERTURAS', z=1.1)
                d.line([H(u0, z + 1.05), H(u1, z + 1.05)], 'hr', 'ABERTURAS', color=GRAY(0.4), z=1.1)
        sl = plate_slab(n)
        us = [U(p) for p in sl.exterior.coords]
        u0, u1 = min(us), max(us)
        d.poly([H(u0, z - B.FIN - B.SLAB), H(u1, z - B.FIN - B.SLAB), H(u1, z), H(u0, z)], 'fn', 'LOSAS', fill=slab_fill, z=1.3)
        rh = 1.05 if n < 19 else 1.10
        d.line([H(u0 + 0.06, z + rh), H(u1 - 0.06, z + rh)], 'fn', 'LOSAS', z=1.35)
    # sala de tanques y salida a azotea sobre el núcleo (fijo)
    us = [U(p) for p in rect(-B.CORE, -B.CORE, B.CORE, B.CORE)]
    u0, u1 = min(us), max(us)
    d.poly([H(u0, B.ROOF), H(u1, B.ROOF), H(u1, B.TOP), H(u0, B.TOP)], 'fn', 'MUROS', fill=WHITE, z=1.2)
    d.line([H(u0, B.TOP - 0.4), H(u1, B.TOP - 0.4)], 'xf', 'MUROS', z=1.25)
    # basamento
    for lev, z0, z1 in ((1, 0.0, B.NPT[2] - B.FIN - B.SLAB), (2, B.NPT[2], B.NPT[3] - B.FIN - B.SLAB)):
        segs = [(p, q, k) for p, q, k in podium_facade(lev)]
        for p, q, k in segs:
            mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            nrm = (0, 1) if abs(my - B.POD[3]) < 0.01 and p[1] == q[1] else (0, -1) if abs(my - B.POD[1]) < 0.01 and p[1] == q[1] else \
                (1, 0) if abs(mx - B.POD[2]) < 0.01 else (-1, 0)
            if nrm[0] * vdir[0] + nrm[1] * vdir[1] <= 0:
                continue
            ua, ub = sorted((U(p), U(q)))
            if k == 'v':
                d.poly([H(ua, z0), H(ub, z0), H(ub, z1), H(ua, z1)], 'fn', 'ABERTURAS', fill=glass_fill, z=2.0)
                n_m = max(1, int(round((ub - ua) / (7.6 / 3))))
                for i in range(n_m + 1):
                    um = ua + (ub - ua) * i / n_m
                    d.line([H(um, z0), H(um, z1)], 'xf', 'ABERTURAS', z=2.05)
                d.line([H(ua, z0 + 2.4), H(ub, z0 + 2.4)], 'hr', 'ABERTURAS', z=2.05)
            else:
                d.poly([H(ua, z0), H(ub, z0), H(ub, z1), H(ua, z1)], 'fn', 'MUROS', fill=WHITE,
                       hatch=(0, 1.2, 'hr', GRAY(0.6)), z=2.0)
    xs = [U(p) for p in rect(*B.POD)]
    pu0, pu1 = min(xs), max(xs)
    for zz in (B.NPT[2], B.NPT[3]):
        d.poly([H(pu0, zz - B.FIN - B.SLAB), H(pu1, zz - B.FIN - B.SLAB), H(pu1, zz), H(pu0, zz)], 'fn', 'LOSAS', fill=WHITE, z=2.1)
    d.poly([H(pu0, B.NPT[3]), H(pu1, B.NPT[3]), H(pu1, B.NPT[3] + 0.60), H(pu0, B.NPT[3] + 0.60)], 'fn', 'LOSAS',
           fill=WHITE, z=2.1)
    # terreno
    d.line([H(pu0 - 9, 0), H(pu1 + 9, 0)], 'hv', 'ENTORNO', z=3)
    d.poly([H(pu0 - 9, 0), H(pu1 + 9, 0), H(pu1 + 9, -1.2), H(pu0 - 9, -1.2)], 'xf', 'ENTORNO', stroke=False,
           hatch=(45, 1.4, 'hr', GRAY(0.4)), z=2.9)
    for k, (u, h, r) in enumerate(((pu0 + 3.0, 6.0, 2.4), (pu1 - 3.0, 5.6, 2.2))):
        pts = [H(u + r * math.cos(t) * (1 + 0.08 * math.sin(5 * t)), h - r * 1.1 + r * 1.25 * math.sin(t)) for t in
               [i * math.pi / 18 for i in range(37)]]
        d.poly(pts, 'xf', 'ENTORNO', fill=WHITE, color=GRAY(0.4), z=3.1)
        d.line([H(u, 0), H(u, h - r * 2.0)], 'fn', 'ENTORNO', color=GRAY(0.4), z=3.1)
    return pu0, pu1


def level_marks(d, S, xr, xl=None, names=True):
    """Niveles a la derecha (xr) y nombres de piso a la izquierda (xl)."""
    marks = [(0.0, 'NPT ±0,00 planta baja')] + [(B.NPT[n], f'NPT {flevel(B.NPT[n])}') for n in range(2, 19)] + \
            [(B.ROOF, f'{flevel(B.ROOF)} azotea'), (B.TOP, f'{flevel(B.TOP)} sala de tanques')]
    for z, t in marks:
        d.level_section((xr, z), t, 1.9)
    if xl is not None and names:
        for n in range(1, 19):
            z = B.NPT[n]
            h = (B.NPT[n + 1] - z) if n < 18 else B.FTF
            lbl = 'PB' if n == 1 else f'{n}'
            d.text((xl, z + h / 2), lbl, 2.2, font='Helvetica-Bold', align='r')
        zones = [('club', 1, 2), ('bosque', 3, 8), ('lago', 9, 14), ('cumbre', 15, 17), ('ph', 18, 18)]
        for zk, a, b in zones:
            za, zb = B.NPT[a], (B.NPT[b + 1] if b < 18 else B.ROOF)
            xx = xl - d.mm(9)
            d.line([(xx, za + 0.15), (xx, zb - 0.15)], 'fn', 'TEXTOS', z=4)
            for zz in (za + 0.15, zb - 0.15):
                d.line([(xx, zz), (xx + d.mm(1.5), zz)], 'fn', 'TEXTOS', z=4)
            d.text((xx - d.mm(2.5), (za + zb) / 2), S['zones'][zk]['name'].upper(), 2.0, angle=90, font='Helvetica-Bold')


def sh_elev(X, c, views):
    S = X.S
    out = {}
    fw = DA[2] / 2
    for i, v in enumerate(views):
        d = Dwg(200)
        pu0, pu1 = elevation(d, S, v)
        level_marks(d, S, pu1 + 2.0, pu0 - 2.5)
        d.chain([(pu0 - d.mm(30), 0.0), (pu0 - d.mm(30), B.NPT[3]), (pu0 - d.mm(30), B.NPT[18]),
                 (pu0 - d.mm(30), B.ROOF), (pu0 - d.mm(30), B.TOP)], 0)
        d.chain([(pu0, -d.mm(9)), (pu1, -d.mm(9))], 0)
        frame = (DA[0] + i * fw, DA[1] + 24, fw, DA[3] - 26)
        render(c, d, frame, ((pu0 + pu1) / 2 + 2.0, B.TOP / 2 + 0.2))
        U, Wd, title, sub = VIEW[v]
        caption(c, frame[0] + 10, DA[1] + 14, i + 1, title, 'Esc. 1:200', sub + ' · giro de cada losa según A-106')
        out[f"{X.sheet.code}_{title.lower().replace(' ', '_')}"] = d
    return out


def sh_A201(X, c):
    return sh_elev(X, c, ('N', 'E'))


def sh_A202(X, c):
    return sh_elev(X, c, ('S', 'W'))


def zone_cut_walls(zone):
    """Muros de unidad hacia el palier y hacia los plenos, en el marco de la planta."""
    O, g, R = B.O, B.g, B.R_PAL
    parts = [Point(0, 0).buffer(R + B.T_PAL, 96).difference(Point(0, 0).buffer(R, 96))]
    for ch in ZONE_STRIPS[zone]:
        a = {'N': 0, 'W': 90, 'S': 180, 'E': 270}[ch]
        for xa, xb in ((-g - B.T_PARTY, -g), (g, g + B.T_PARTY)):
            parts.append(affinity.rotate(sbox(xa, R, xb, O), a, origin=(0, 0)))
    return unary_union(parts)


def cut_intervals(geom, line, U):
    out = []
    inter = geom.intersection(line)
    for gg in getattr(inter, 'geoms', [inter]):
        if gg.is_empty or gg.geom_type != 'LineString':
            continue
        us = sorted(U(p) for p in gg.coords)
        out.append((us[0], us[-1]))
    return out


def section(d, S, which):
    """Corte A-A: plano x = -0,925 mirando al oeste (u = y). Corte B-B: plano y = -1,85 mirando al norte (u = x)."""
    if which == 'A':
        c0 = -0.925
        U = lambda p: p[1]
        line = LineString([(c0, -200), (c0, 200)])
        beyond = sbox(-200, -200, c0, 200)
    else:
        c0 = -1.85
        U = lambda p: p[0]
        line = LineString([(-200, c0), (200, c0)])
        beyond = sbox(-200, c0, 200, 200)
    H = lambda u, z: (u, z)
    CUT = GRAY(0.05)
    # torre
    for n in range(3, 20):
        z = B.NPT[n]
        zs0, zs1 = z - B.FIN - B.SLAB, z - B.FIN
        ztop = (B.NPT[n + 1] if n < 19 else z) - B.FIN - B.SLAB
        sl = plate_slab(n)
        for u0, u1 in cut_intervals(sl, line, U):
            d.poly([H(u0, zs0), H(u1, zs0), H(u1, zs1), H(u0, zs1)], 'fn', 'LOSAS', fill=CUT, z=2.5)
            d.poly([H(u0 + 0.0, zs1), H(u1, zs1), H(u1, z), H(u0, z)], 'xf', 'LOSAS', fill=WHITE, z=2.4)
            rh = 1.05 if n < 19 else 1.10
            for uu in (u0 + 0.06, u1 - 0.06):
                d.line([H(uu, z), H(uu, z + rh)], 'fn', 'ABERTURAS', z=2.6)
        # proyección de la losa más allá del plano
        bh = sl.intersection(beyond)
        if not bh.is_empty:
            us = [U(p) for p in bh.exterior.coords]
            d.poly([H(min(us), zs0), H(max(us), zs0), H(max(us), z), H(min(us), z)], 'xf', 'LOSAS', color=GRAY(0.35), z=1.0)
        if n == 19:
            continue
        enc = Polygon([rot(p, -B.ROT[n]) for p in rect(-B.O, -B.O, B.O, B.O)])
        for u0, u1 in cut_intervals(enc, line, U):
            for uu in (u0, u1):
                d.poly([H(uu - 0.05, z), H(uu + 0.05, z), H(uu + 0.05, ztop), H(uu - 0.05, ztop)], 'xf', 'ABERTURAS', fill=WHITE, z=2.6)
                d.line([H(uu, z), H(uu, ztop)], 'hr', 'ABERTURAS', z=2.65)
        be = enc.intersection(beyond)
        if not be.is_empty:
            us = [U(p) for p in be.exterior.coords]
            for uu in (min(us), max(us)):
                d.line([H(uu, z), H(uu, ztop)], 'xf', 'ABERTURAS', color=GRAY(0.35), z=1.0)
        zone = floor_zone(S, n)
        walls = affinity.rotate(zone_cut_walls(zone), -B.ROT[n], origin=(0, 0))
        for u0, u1 in cut_intervals(walls, line, U):
            d.poly([H(u0, z), H(u1, z), H(u1, ztop), H(u0, ztop)], 'fn', 'MUROS', fill=WHITE,
                   hatch=(45, 0.9, 'hr', GRAY(0.2)), z=2.6)
        # cielorraso suspendido
        for u0, u1 in cut_intervals(enc, line, U):
            d.line([H(u0, z + B.H), H(u1, z + B.H)], 'hr', 'LOSAS', dash='dash', z=1.2)
        # columnas inclinadas cortadas
        for p in B.COLS:
            q = rot(p, -B.ROT[n])
            dist = abs(q[0] - c0) if which == 'A' else abs(q[1] - c0)
            if dist < B.COL_D / 2:
                u = U(q)
                d.poly([H(u - 0.25, z), H(u + 0.25, z), H(u + 0.25, ztop), H(u - 0.25, ztop)], 'fn', 'ESTRUCTURA', fill=CUT, z=2.7)
    # basamento: losas, fachadas y muros cortados
    pod = sbox(*B.POD)
    for zz in (B.NPT[2], B.NPT[3]):
        for u0, u1 in cut_intervals(pod, line, U):
            d.poly([H(u0, zz - B.FIN - B.SLAB), H(u1, zz - B.FIN - B.SLAB), H(u1, zz - B.FIN), H(u0, zz - B.FIN)], 'fn',
                   'LOSAS', fill=CUT, z=2.5)
    green = pod.difference(Polygon(rounded_square(B.A, B.R_SLAB, 10)))
    for u0, u1 in cut_intervals(green, line, U):
        d.poly([H(u0, B.NPT[3]), H(u1, B.NPT[3]), H(u1, B.NPT[3] + 0.45), H(u0, B.NPT[3] + 0.45)], 'fn', 'LOSAS',
               fill=WHITE, hatch=(45, 0.8, 'hr', GRAY(0.4)), z=2.4)
    for u0, u1 in cut_intervals(pod, line, U):
        for uu in (u0, u1):
            d.poly([H(uu - 0.15, B.NPT[3]), H(uu + 0.15, B.NPT[3]), H(uu + 0.15, B.NPT[3] + 0.60), H(uu - 0.15, B.NPT[3] + 0.60)],
                   'fn', 'LOSAS', fill=CUT, z=2.5)
        d.poly([H(u0, -2.10), H(u1, -2.10), H(u1, -0.60), H(u0, -0.60)], 'fn', 'ESTRUCTURA', fill=CUT, z=2.5)
        d.poly([H(u0, -0.60), H(u1, -0.60), H(u1, 0.0), H(u0, 0.0)], 'xf', 'LOSAS', fill=WHITE, hatch=(45, 1.4, 'hr', GRAY(0.4)), z=2.4)
        d.text(((u0 + u1) / 2 + 9.0, -1.35), 'platea de fundación H°A° e = 1,50', 1.8, color=WHITE, z=6)
    for lev, z0, z1 in ((1, 0.0, B.NPT[2] - B.FIN - B.SLAB), (2, B.NPT[2], B.NPT[3] - B.FIN - B.SLAB)):
        dd = Dwg(200)
        pl = plan_pb(dd, S) if lev == 1 else plan_p1(dd, S)
        groups = unary_union([g for g, k in pl.walls])
        cut = unary_union(pl.cuts) if pl.cuts else None
        if cut is not None:
            groups = groups.difference(cut)
        for u0, u1 in cut_intervals(groups, line, U):
            d.poly([H(u0, z0), H(u1, z0), H(u1, z1), H(u0, z1)], 'fn', 'MUROS', fill=WHITE, hatch=(45, 0.9, 'hr', GRAY(0.2)), z=2.6)
        for p, q, gw, _ in pl.glass:
            gl = LineString([p, q]).buffer(0.06, cap_style=2)
            for u0, u1 in cut_intervals(gl, line, U):
                uu = (u0 + u1) / 2
                d.poly([H(uu - 0.05, z0), H(uu + 0.05, z0), H(uu + 0.05, z1), H(uu - 0.05, z1)], 'xf', 'ABERTURAS', fill=WHITE, z=2.6)
    # núcleo fijo
    core = core_parts()
    for u0, u1 in cut_intervals(core, line, U):
        d.poly([H(u0, -1.40), H(u1, -1.40), H(u1, B.TOP), H(u0, B.TOP)], 'fn', 'MUROS', fill=CUT, z=2.8)
    if which == 'A':
        # pasadizo del ascensor A, puertas de piso y fosa
        d.poly([H(0.75, -1.40), H(2.55, -1.40), H(2.55, B.ROOF + 3.4), H(0.75, B.ROOF + 3.4)], 'xf', 'CIRCULACION', z=1.5)
        for n in range(1, 19):
            z = B.NPT[n]
            d.poly([H(2.55, z + 2.10), H(2.80, z + 2.10), H(2.80, (B.NPT[n + 1] if n < 18 else B.ROOF) - B.FIN), H(2.55, (B.NPT[n + 1] if n < 18 else B.ROOF) - B.FIN)],
                   'fn', 'MUROS', fill=CUT, z=2.9)
            d.poly([H(2.55, z), H(2.80, z), H(2.80, z + 2.10), H(2.55, z + 2.10)], 'fn', 'ABERTURAS', fill=WHITE, z=2.9)
        zc = B.NPT[12]
        d.poly([H(0.95, zc), H(2.35, zc), H(2.35, zc + 2.30), H(0.95, zc + 2.30)], 'fn', 'CIRCULACION', fill=WHITE, z=2.9)
        d.text((1.65, zc + 1.15), 'cabina', 1.6, angle=90, z=6)
        d.text((1.65, B.ROOF + 1.6), 'sobrerrecorrido', 1.5, angle=90, z=6)
        d.text((1.65, -0.75), 'fosa', 1.5, z=6)
        # escalera cortada transversalmente: tramos S y N de cada piso
        for n in range(1, 19):
            z = B.NPT[n]
            h = (B.NPT[n + 1] if n < 18 else B.ROOF) - z
            if n <= 2:
                parts = [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]
                ys = [(-2.55, -1.15), (-0.85, 0.55), (-2.55, -1.15), (-0.85, 0.55)]
                for (f0, f1), (ya, yb) in zip(parts, ys):
                    zz = z + h * (f0 + 0.04)
                    d.poly([H(ya, zz - 0.18), H(yb, zz - 0.18), H(yb, zz), H(ya, zz)], 'fn', 'CIRCULACION', fill=CUT, z=2.7)
            else:
                zz = z + 0.33
                d.poly([H(-2.55, zz - 0.18), H(-1.15, zz - 0.18), H(-1.15, zz), H(-2.55, zz)], 'fn', 'CIRCULACION', fill=CUT, z=2.7)
                zz = z + h - 0.22
                d.poly([H(-0.85, zz - 0.18), H(0.55, zz - 0.18), H(0.55, zz), H(-0.85, zz)], 'fn', 'CIRCULACION', fill=CUT, z=2.7)
    else:
        # escalera en perfil (tramo S cortado, tramo N en vista)
        for n in range(1, 19):
            z = B.NPT[n]
            h = (B.NPT[n + 1] if n < 18 else B.ROOF) - z
            if n > 2:
                r = h / 20
                pts = [H(-1.30, z)]
                for k in range(10):
                    pts += [H(-1.30 + k * 0.28, z + (k + 1) * r), H(-1.30 + (k + 1) * 0.28, z + (k + 1) * r)]
                pts[-1] = H(1.22, z + 10 * r)
                pts += [H(2.55, z + 10 * r), H(2.55, z + 10 * r - 0.20), H(1.22, z + 10 * r - 0.20), H(-1.30, z - 0.20)]
                d.poly(pts, 'fn', 'CIRCULACION', fill=CUT, z=2.7)
                d.line([H(1.22, z + 10 * r), H(-1.30, z + h)], 'xf', 'CIRCULACION', color=GRAY(0.35), z=1.5)
                d.line([H(-2.55, z), H(-1.30, z)], 'fn', 'CIRCULACION', z=2.7)
                d.line([H(-1.30, z + 0.9), H(1.22, z + 10 * r + 0.9)], 'xf', 'CIRCULACION', z=2.7)
            else:
                quarter = h / 4
                for k in range(4):
                    za = z + k * quarter
                    if k % 2 == 0:
                        d.poly([H(-1.30, za - 0.18), H(1.22, za + quarter - 0.18), H(1.22, za + quarter), H(-1.30, za)], 'fn',
                               'CIRCULACION', fill=CUT, z=2.7)
                    else:
                        d.line([H(1.22, za), H(-1.30, za + quarter)], 'xf', 'CIRCULACION', color=GRAY(0.35), z=1.5)
    # tanques sobre el núcleo
    d.poly([H(-2.2, B.ROOF + 0.3), H(-0.15, B.ROOF + 0.3), H(-0.15, B.TOP - 0.7), H(-2.2, B.TOP - 0.7)], 'xf', 'MUROS', z=2.0)
    d.poly([H(0.15, B.ROOF + 0.3), H(2.2, B.ROOF + 0.3), H(2.2, B.TOP - 0.7), H(0.15, B.TOP - 0.7)], 'xf', 'MUROS', z=2.0)
    d.text((-1.18, B.ROOF + 1.9), 'TR 15.000 l', 1.5, angle=90, z=6)
    d.text((1.18, B.ROOF + 1.9), 'TR 15.000 l', 1.5, angle=90, z=6)
    d.poly([H(-B.CORE, B.TOP - 0.3), H(B.CORE, B.TOP - 0.3), H(B.CORE, B.TOP), H(-B.CORE, B.TOP)], 'fn', 'LOSAS', fill=CUT, z=2.9)
    return U


def terrain_A(d):
    """Perfil del terreno en el corte A-A (u = y)."""
    prof = [(-60, 0.55), (-47.6, 0.30), (-30.4, 0.30), (-26.0, 0.05), (-15.5, 0.0), (15.5, -0.15), (24.0, -0.15),
            (25.9, -0.15), (30.0, -0.55), (36.0, -0.90), (46.0, -0.90), (50.0, -2.2), (SHORE_Y, -3.30), (62.0, -3.6)]
    pts = [(u, z) for u, z in prof]
    d.line(pts[:5], 'hv', 'ENTORNO', z=3)
    d.line(pts[5:], 'hv', 'ENTORNO', z=3)
    d.poly(pts[:5] + [(-15.5, -2.4), (-60, -2.4)], 'xf', 'ENTORNO', stroke=False, hatch=(45, 1.4, 'hr', GRAY(0.45)), z=0.5)
    d.poly(pts[5:] + [(62.0, -4.6), (15.5, -2.4)], 'xf', 'ENTORNO', stroke=False, hatch=(45, 1.4, 'hr', GRAY(0.45)), z=0.5)
    d.poly([(SHORE_Y - 1.0, -3.30), (64.0, -3.30), (64.0, -4.6), (SHORE_Y + 2.0, -4.6)], 'xf', 'ENTORNO', fill=GRAY(0.85), z=0.6)
    d.line([(SHORE_Y - 1.0, -3.30), (64.0, -3.30)], 'fn', 'ENTORNO', z=3)
    for u, h, r in ((-36.0, 7.0, 2.8), (-22.0, 8.0, 3.2), (28.0, 7.5, 3.0), (40.5, 6.5, 2.6)):
        z0 = next(z for (a, z), (b, z2) in zip(prof, prof[1:]) if a <= u <= b)
        pts = [(u + r * math.cos(t), z0 + h - r * 1.1 + r * 1.25 * math.sin(t)) for t in [i * math.pi / 18 for i in range(37)]]
        d.poly(pts, 'xf', 'ENTORNO', fill=WHITE, color=GRAY(0.4), z=3.1)
        d.line([(u, z0), (u, z0 + h - r * 2.0)], 'fn', 'ENTORNO', color=GRAY(0.4), z=3.1)
    for a, b in ((-47.0, -42.0), (-36.0, -31.0)):
        d.line([(a, 0.30 + 2.6), (b, 0.30 + 2.6)], 'th', 'ENTORNO', z=3)
        for u in (a, b):
            d.line([(u, 0.30), (u, 0.30 + 2.6)], 'fn', 'ENTORNO', z=3)
    d.text((-39.0, 3.6), 'pérgola del estacionamiento', 1.7, z=6)
    d.text((41.0, 0.2), 'PASEO COSTERO', 1.9, font='Helvetica-Bold', z=6)
    d.text((58.0, -2.6), 'LAGO ILÉN', 2.2, font='Helvetica-Bold', z=6)
    d.text((58.0, -4.2), 'nivel medio 768,20 m s.n.m. = -3,30', 1.6, z=6)
    d.line([(36.0, -0.9), (36.0, 1.6)], 'fn', 'ENTORNO', dash='axis', z=3)
    d.text((36.0, 2.2), 'L.M.', 1.6, z=6)
    d.line([(SHORE_Y, -3.3), (SHORE_Y, 1.6)], 'fn', 'ENTORNO', dash='axis', z=3)
    d.text((SHORE_Y, 2.2), 'línea de ribera', 1.6, z=6)
    d.dim((13.0, 3.4), (SHORE_Y, 3.4), 0, text=f'{fnum(SHORE_Y - 13.0)} a la orilla')


def sh_A301(X, c):
    S = X.S
    d = Dwg(200)
    section(d, S, 'A')
    terrain_A(d)
    level_marks(d, S, 22.0, -20.0)
    d.chain([(-27.0, -2.10), (-27.0, 0.0), (-27.0, B.NPT[2]), (-27.0, B.NPT[3]), (-27.0, B.NPT[18]), (-27.0, B.ROOF),
             (-27.0, B.TOP)], 0)
    frame = (DA[0], DA[1] + 24, DA[2], DA[3] - 26)
    render(c, d, frame, (2.0, 31.5))
    caption(c, DA[0] + 8, DA[1] + 14, 1, 'CORTE A-A · POR NÚCLEO (ASCENSOR) Y PALIER', 'Esc. 1:200',
            'plano x = -0,925 m, mirando al oeste · losas giradas según A-106')
    return {'A-301_corte_AA': d}


def sh_A302(X, c):
    S = X.S
    d = Dwg(200)
    section(d, S, 'B')
    d.line([(-45.0, 0.0), (45.0, 0.0)], 'hv', 'ENTORNO', z=3)
    d.poly([(-45.0, 0.0), (45.0, 0.0), (45.0, -2.4), (-45.0, -2.4)], 'xf', 'ENTORNO', stroke=False,
           hatch=(45, 1.4, 'hr', GRAY(0.45)), z=0.5)
    level_marks(d, S, 26.0, -26.0)
    frame = (DA[0], DA[1] + 24, DA[2], DA[3] - 26)
    render(c, d, frame, (-2.0, 31.5))
    caption(c, DA[0] + 8, DA[1] + 14, 1, 'CORTE B-B · POR ESCALERA PRESURIZADA', 'Esc. 1:200',
            'plano y = -1,85 m, mirando al norte · losas giradas según A-106')
    return {'A-302_corte_BB': d}


# ===================================================================== tipologías (port de js/plan.js)
EPS = 0.01


def pj_shared(a, b):
    """Segmento compartido entre dos ambientes (igual que shared() de plan.js)."""
    _, ax, ay, aw, ah, _k = a
    _, bx, by, bw, bh, _k2 = b
    ov = lambda a0, a1, b0, b1: (max(a0, b0), min(a1, b1))
    if abs(ax + aw - bx) < EPS or abs(bx + bw - ax) < EPS:
        x = ax + aw if abs(ax + aw - bx) < EPS else ax
        s, e = ov(ay, ay + ah, by, by + bh)
        if e - s > 0.85:
            return dict(v=True, x=x, s=s, e=e)
    if abs(ay + ah - by) < EPS or abs(by + bh - ay) < EPS:
        y = ay + ah if abs(ay + ah - by) < EPS else ay
        s, e = ov(ax, ax + aw, bx, bx + bw)
        if e - s > 0.85:
            return dict(v=False, y=y, s=s, e=e)
    return None


def pj_layout(t):
    """Aberturas según drawPlan() de plan.js: puertas (con barrido), vanos y acceso."""
    rooms = t['plan']
    cov = [r for r in rooms if r[5] != 'balcony']
    W = max(r[1] + r[3] for r in cov)
    D = max(r[2] + r[4] for r in cov)
    is_liv = lambda r: r[5] == 'living'
    is_hall = lambda r: r[5] == 'hall' and r[0] == 'Paso'
    doors, opens = [], []
    for r in cov:
        if is_liv(r) or is_hall(r):
            continue
        name = r[0].lower()
        if name.startswith('cocina'):
            prefs = [s for s in cov if is_liv(s)]
        elif name == 'vestidor' or (name == 'baño' and any(s[0] == 'Suite' and pj_shared(r, s) for s in cov)):
            prefs = [s for s in cov if s[0] in ('Suite', 'Vestidor')]
        else:
            prefs = [s for s in cov if is_hall(s)] + [s for s in cov if is_liv(s)] + \
                    [s for s in cov if s[0] in ('Cocina y comedor', 'Estudio')]
        for s in prefs:
            if s is r:
                continue
            seg = pj_shared(r, s)
            if not seg:
                continue
            if name.startswith('cocina') and is_liv(s):
                opens.append(seg)
            else:
                doors.append((seg, r, 0.85))
            break
    for a in cov:
        for b in cov:
            if a is not b and is_liv(a) and is_liv(b) and a[0] < b[0]:
                seg = pj_shared(a, b)
                if seg:
                    opens.append(seg)
    entry = None
    for r in [s for s in cov if is_hall(s)] + [s for s in cov if is_liv(s)]:
        _, x, y, w, h, _k = r
        if abs(y + h - D) < EPS:
            entry = dict(r=r, side='b', c=x + w / 2)
            break
        if abs(x + w - W) < EPS:
            entry = dict(r=r, side='r', c=y + h / 2)
            break
        if abs(x) < EPS:
            entry = dict(r=r, side='l', c=y + h / 2)
            break
    return dict(W=W, D=D, cov=cov, doors=doors, opens=opens, entry=entry)


class Flip:
    """Dibuja en coordenadas de plan.js (y hacia abajo, balcón con y < 0) sobre un Dwg con y hacia arriba."""

    def __init__(self, d, ox=0.0, oy=0.0):
        self.d, self.ox, self.oy = d, ox, oy

    def P(self, x, y):
        return (self.ox + x, self.oy - y)

    def rect(self, x, y, w, h, fill=WHITE, pen='xf', layer='MOBILIARIO', color=GRAY(0.25), z=1.2, hatch=None):
        self.d.poly([self.P(x, y), self.P(x + w, y), self.P(x + w, y + h), self.P(x, y + h)], pen, layer, fill=fill,
                    color=color, z=z, hatch=hatch)

    def circle(self, cx, cy, r, fill=WHITE, pen='xf', layer='MOBILIARIO', color=GRAY(0.25), z=1.25):
        self.d.circle(self.P(cx, cy), r, pen, layer, fill=fill, color=color, z=z)

    def ellipse(self, cx, cy, rx, ry, fill=WHITE, layer='MOBILIARIO', z=1.25):
        pts = [self.P(cx + rx * math.cos(2 * math.pi * i / 32), cy + ry * math.sin(2 * math.pi * i / 32)) for i in range(32)]
        self.d.poly(pts, 'xf', layer, fill=fill, color=GRAY(0.25), z=z)

    def line(self, x1, y1, x2, y2, pen='xf', layer='MOBILIARIO', color=GRAY(0.25), z=1.25, dash=None):
        self.d.line([self.P(x1, y1), self.P(x2, y2)], pen, layer, color=color, z=z, dash=dash)


FX, DK, CT, SH = WHITE, GRAY(0.84), GRAY(0.93), GRAY(0.9)


def pj_furniture(F, r):
    """Equipamiento de un ambiente: misma lógica que furniture() de plan.js."""
    name, x, y, w, h, kind = r
    n = name.lower()
    if kind == 'balcony':
        for i in range(int(math.floor(w / 3.2))):
            cx = x + 1.6 + i * 3.2
            F.circle(cx, y + h / 2, 0.35)
            F.rect(cx - 1.05, y + h / 2 - 0.3, 0.55, 0.6)
            F.rect(cx + 0.5, y + h / 2 - 0.3, 0.55, 0.6)
        return
    if n.startswith('estar') or n == 'comedor' or n.startswith('cocina y'):
        dining = 'comedor' in n or n.startswith('cocina y')
        sofa_only = n == 'estar' or not dining
        if not n.startswith('cocina') and n != 'comedor':
            sw, sx = min(3.2, w * 0.45), x + 0.5
            F.rect(sx, y + h - 1.15, sw, 0.9)
            F.rect(sx, y + h - 0.45, sw, 0.2, fill=DK)
            F.rect(sx + sw * 0.2, y + h - 2.4, sw * 0.6, 0.8)
            F.rect(sx - 0.1, y + 0.6, sw + 0.2, 0.12, fill=DK)
        if (dining and not sofa_only) or n == 'comedor' or n.startswith('cocina y'):
            tx = x + w / 2 if (n == 'comedor' or n.startswith('cocina y')) else x + w - 2.2
            ty = y + h / 2 + 0.3
            F.rect(tx - 0.9, ty - 0.5, 1.8, 1.0)
            for dx in (-0.5, 0.5):
                for dy in (-0.85, 0.85):
                    F.circle(tx + dx, ty + dy, 0.22)
        if n.startswith('cocina y'):
            F.rect(x + 0.15, y + 0.15, w - 0.3, 0.6, fill=CT)
            F.circle(x + 1.2, y + 0.45, 0.16)
            F.circle(x + 1.7, y + 0.45, 0.16)
        return
    if kind == 'bed' and ('dormitorio' in n or 'suite' in n):
        dbl = 'suite' in n or w > 3.6
        bw = 0.9 if w < 3 else (1.6 if dbl else 1.4)
        bl = 2.0
        bx, by = x + w / 2 - bw / 2, y + h - 0.15 - bl
        F.rect(bx, by, bw, bl)
        F.rect(bx + 0.1, by + bl - 0.55, bw / 2 - 0.15, 0.4, fill=DK)
        F.rect(bx + bw / 2 + 0.05, by + bl - 0.55, bw / 2 - 0.15, 0.4, fill=DK)
        F.line(bx, by + 0.6, bx + bw, by + 0.6)
        if w > bw + 1.2:
            F.rect(bx - 0.55, y + h - 0.6, 0.45, 0.45)
            F.rect(bx + bw + 0.1, y + h - 0.6, 0.45, 0.45)
        F.rect(x + 0.12, y + 0.4, 0.6, max(1.2, h - bl - 1.2), fill=CT)
        return
    if n in ('estudio', 'biblioteca'):
        F.rect(x + 0.2, y + 0.2, min(2.0, w - 0.4), 0.7)
        F.circle(x + 1.0, y + 1.3, 0.28)
        F.rect(x + w - 0.5, y + 0.3, 0.35, h - 0.6, fill=CT)
        return
    if n == 'cocina':
        F.rect(x + 0.12, y + 0.12, w - 0.24, 0.62, fill=CT)
        F.rect(x + 0.12, y + 0.74, 0.62, max(0.6, h - 1.6), fill=CT)
        F.circle(x + w - 1.1, y + 0.43, 0.15)
        F.circle(x + w - 0.65, y + 0.43, 0.15)
        F.rect(x + 1.2, y + 0.24, 0.7, 0.4, fill=DK)
        if w > 4.3 and h > 3.5:
            F.rect(x + w / 2 - 0.9, y + h / 2 + 0.1, 1.8, 0.9, fill=CT)
        return
    if n in ('baño', 'toilette'):
        vert = h > w
        tx, ty = x + (w / 2 if vert else 0.55), y + (h - 0.55 if vert else h / 2)
        F.ellipse(tx, ty, 0.22, 0.3)
        sx, sy = x + (w / 2 if vert else w - 0.7), y + (0.45 if vert else 0.4)
        F.rect(sx - 0.35, sy - 0.25, 0.7, 0.5)
        F.circle(sx, sy, 0.13)
        if n == 'baño' and w * h > 3.6:
            shw = min(1.1, (w if vert else h) - 0.3)
            px = x + 0.15 if vert else x + w / 2 - shw / 2 - 0.2
            py = y + h / 2 - shw / 2 - 0.2 if vert else y + 0.15
            F.rect(px, py, shw, shw, fill=SH)
            F.line(px, py, px + shw, py + shw)
        return
    if n == 'lavadero':
        F.rect(x + 0.15, y + 0.15, 0.65, 0.65)
        F.circle(x + 0.475, y + 0.475, 0.22)
        F.rect(x + 0.9, y + 0.15, 0.65, 0.65)
        F.circle(x + 1.225, y + 0.475, 0.22)
        return
    if n in ('vestidor', 'despensa'):
        F.rect(x + 0.1, y + 0.1, w - 0.2, 0.5, fill=CT)
        F.rect(x + 0.1, y + 0.6, 0.5, max(0.3, h - 0.8), fill=CT)


FINISH = {
    'living': ('Entablonado de madera miel', 'Yeso, látex', 'Placa de yeso susp.'),
    'bed': ('Entablonado de madera miel', 'Yeso, látex', 'Placa de yeso susp.'),
    'hall': ('Entablonado de madera miel', 'Yeso, látex', 'Placa de yeso susp.'),
    'wet': ('Porcellanato 60 x 60', 'Porcellanato h 2,40', 'Placa de yeso verde'),
    'balcony': ('Deck de lenga termotr.', 'Baranda vidrio 5+5', 'Losa vista, borde GRC'),
}


def unit_drawing(d, S, D, key, ox=0.0, oy=0.0, model=False, extra=None):
    """Planta de tipología a 1:50. Para L2 se usan muros, aberturas y equipamiento de tools/depto.py."""
    t = S['types'][key]
    L = pj_layout(t)
    W, Dp = L['W'], L['D']
    F = Flip(d, ox, oy)
    bal = next(r for r in t['plan'] if r[5] == 'balcony')
    # solados: baldosas en locales húmedos, deck en el balcón
    for r in t['plan']:
        name, x, y, w, h, kind = r
        if kind == 'wet' and not (key == 'L2' and name.startswith('Cocina')):
            F.rect(x, y, w, h, fill=None, pen='hr', layer='SOLADOS', color=GRAY(0.7), z=0.3)
            k = x + 0.6
            while k < x + w - 0.05:
                F.line(k, y, k, y + h, 'hr', 'SOLADOS', GRAY(0.78), 0.3)
                k += 0.6
            k = y + 0.6
            while k < y + h - 0.05:
                F.line(x, k, x + w, k, 'hr', 'SOLADOS', GRAY(0.78), 0.3)
                k += 0.6
        if kind == 'balcony':
            k = x + 0.14
            while k < x + w:
                F.line(k, y + 0.06, k, y + h, 'hr', 'SOLADOS', GRAY(0.72), 0.3)
                k += 0.14
    pl = Plan(d)
    te, ti = 0.25, 0.12
    P = F.P
    if key == 'L2':
        dep = depto_geometry(D)
        for wl in dep['walls']:
            (ax, ay), (bx, by) = wl['a'], wl['b']
            pl.wall(P(ax, -ay), P(bx, -by), wl['t'], 'mamp' if wl['t'] > 0.2 else 'tab')
            for (s0, s1, top, sill) in wl['open']:
                horiz = abs(ay - by) < 1e-9
                ln = math.hypot(bx - ax, by - ay)
                ux, uy = (bx - ax) / ln, (by - ay) / ln
                m = ((s0 + s1) / 2)
                cx, cy = ax + ux * m, ay + uy * m
                pl.gap(P(cx, -cy), s1 - s0, not horiz, t=wl['t'] + 0.1)
        for win in dep['windows']:
            (ax, ay), (bx, by) = win['a'], win['b']
            pl.glazing(P(ax, -ay), P(bx, -by), 0.10, abs((bx - ax) + (by - ay)) / win['mull'])
        for (x0_, y0_, x1_, y1_) in dep['cols']:
            d.poly([P(x0_, -y0_), P(x1_, -y0_), P(x1_, -y1_), P(x0_, -y1_)], 'md', 'ESTRUCTURA', fill=GRAY(0.12), z=2.6)
        # puertas: hojas según el modelo; las que el modelo no tiene se dibujan con su barrido
        for (hinge, along, into, w_) in dep['door_leaves']:
            door_leaf(d, P(*hinge), w_, (along[0], -along[1]), (into[0], -into[1]), 'fn')
        # acceso (el modelo 3D no lo tiene: se ubica en el muro oeste del estar, libre de equipamiento)
        ent = dep['entry']
        pl.gap(P(0, ent), 0.95, True, t=0.4)
        door_leaf(d, P(0, ent - 0.475), 0.95, (0, -1), (1, 0), 'fn')
        ex, ey = P(-0.25, ent)
        d.line([(ex - 0.6, ey), (ex, ey)], 'th', 'TEXTOS', z=4)
        d.line([(ex - 0.25, ey + 0.2), (ex, ey), (ex - 0.25, ey - 0.2)], 'th', 'TEXTOS', z=4)
        d.text((ex - 0.35, ey + 0.32), 'ACCESO', 1.9, font='Helvetica-Bold', align='c')
        depto_furniture(d, D, F, model=model)
    else:
        # muro perimetral (fondo y laterales) y frente vidriado continuo
        pl.wall(P(0, Dp), P(W, Dp), te, 'mamp')
        pl.wall(P(0, 0), P(0, Dp), te, 'mamp')
        pl.wall(P(W, 0), P(W, Dp), te, 'mamp')
        nb = max(2, int(round(W / 2.6)))
        pl.glazing(P(0.2, 0), P(W - 0.2, 0), 0.10, (W - 0.4) / nb)
        for xx in (0.0, W):
            d.poly([P(xx - 0.2, -0.05), P(xx + 0.2, -0.05), P(xx + 0.2, 0.2), P(xx - 0.2, 0.2)], 'md', 'ESTRUCTURA',
                   fill=GRAY(0.12), z=2.6)
        # tabiques: bordes interiores de los ambientes cubiertos
        segs = set()
        for _, x, y, w, h, _k in L['cov']:
            for (p, q) in (((x, y), (x + w, y)), ((x, y + h), (x + w, y + h)), ((x, y), (x, y + h)), ((x + w, y), (x + w, y + h))):
                if p[1] == q[1] and (abs(p[1]) < EPS or abs(p[1] - Dp) < EPS):
                    continue
                if p[0] == q[0] and (abs(p[0]) < EPS or abs(p[0] - W) < EPS):
                    continue
                segs.add((round(p[0], 3), round(p[1], 3), round(q[0], 3), round(q[1], 3)))
        for (x1, y1, x2, y2) in segs:
            pl.wall(P(x1, y1), P(x2, y2), ti, 'tab')
        for seg, room, w_ in L['doors']:
            mid = (seg['s'] + seg['e']) / 2
            a = mid - w_ / 2
            _, rx, ry, rw, rh, _k = room
            if seg['v']:
                pl.gap(P(seg['x'], mid), w_, True, t=0.3)
                inward = 1 if rx + rw / 2 > seg['x'] else -1
                door_leaf(d, P(seg['x'], a), w_, (0, -1), (inward, 0), 'fn')
            else:
                pl.gap(P(mid, seg['y']), w_, False, t=0.3)
                inward = 1 if ry + rh / 2 > seg['y'] else -1
                door_leaf(d, P(a, seg['y']), w_, (1, 0), (0, -inward), 'fn')
        for seg in L['opens']:
            ln = min(seg['e'] - seg['s'] - 0.4, 2.4)
            mid = (seg['s'] + seg['e']) / 2
            if seg['v']:
                pl.gap(P(seg['x'], mid), ln, True, t=0.3)
            else:
                pl.gap(P(mid, seg['y']), ln, False, t=0.3)
        e = L['entry']
        if e:
            r = e['r']
            c0 = e['c']
            if e['side'] == 'b':
                pl.gap(P(c0, Dp), 0.95, False, t=0.4)
                door_leaf(d, P(c0 - 0.475, Dp), 0.95, (1, 0), (0, 1), 'fn')
                ex, ey = P(c0, Dp + 0.25)
                d.line([(ex, ey - 0.6), (ex, ey)], 'th', 'TEXTOS', z=4)
                d.line([(ex - 0.2, ey - 0.25), (ex, ey), (ex + 0.2, ey - 0.25)], 'th', 'TEXTOS', z=4)
                d.text((ex + 0.3, ey - 0.42), 'ACCESO', 1.9, font='Helvetica-Bold', align='l')
            else:
                xw = W if e['side'] == 'r' else 0
                k = 1 if e['side'] == 'r' else -1
                pl.gap(P(xw, c0), 0.95, True, t=0.4)
                door_leaf(d, P(xw, c0 - 0.475), 0.95, (0, -1), (-k, 0), 'fn')
                ex, ey = P(xw + k * 0.25, c0)
                d.line([(ex + k * 0.6, ey), (ex, ey)], 'th', 'TEXTOS', z=4)
                d.line([(ex + k * 0.25, ey + 0.2), (ex, ey), (ex + k * 0.25, ey - 0.2)], 'th', 'TEXTOS', z=4)
                d.text((ex + k * 0.35, ey + 0.32), 'ACCESO', 1.9, font='Helvetica-Bold', align='c')
        for r in t['plan']:
            pj_furniture(F, r)
    pl.draw(labels=False)
    # balcón: canto de losa y baranda
    bx, by, bw, bh = bal[1], bal[2], bal[3], bal[4]
    if key == 'L2':
        F.rect(-0.2, -2.4, 13.4, 2.4, fill=None, pen='md', layer='LOSAS', color=BLACK, z=0.5)
        F.line(-0.1, -2.34, 13.1, -2.34, 'fn', 'LOSAS', BLACK, 0.6)
    else:
        F.rect(bx, by, bw, bh, fill=None, pen='md', layer='LOSAS', color=BLACK, z=0.5)
        F.line(bx, by + 0.05, bx + bw, by + 0.05, 'fn', 'LOSAS', BLACK, 0.6)
    if extra:
        extra(d)
    # rótulos de locales: se busca dentro de cada local la posición que menos pisa el equipamiento
    obst = []
    for it in d.items:
        if it['layer'] not in ('MOBILIARIO', 'ESTRUCTURA', 'CIRCULACION'):
            continue
        try:
            if it['k'] == 'poly':
                obst.append(Polygon(it['rings'][0]).buffer(0))
            elif it['k'] == 'circle':
                obst.append(Point(it['c']).buffer(it['r'], 12))
            elif it['k'] == 'line':
                obst.append(LineString(it['pts']).buffer(d.mm(0.3)))
        except Exception:
            pass
    obst = unary_union(obst) if obst else Polygon()
    for i, r in enumerate(t['plan']):
        name, x, y, w, h, kind = r
        big = w >= 1.7 and h >= 1.5
        sz = 2.6 if big else 2.0
        ang = 90 if (w < 1.7 and h > w) else 0
        lbl = f'{i + 1:02d}  {name.upper()}'
        tw = d.mm(max(stringWidth(lbl, 'Helvetica-Bold', sz), stringWidth(f'{fnum(w)} x {fnum(h)}', 'Helvetica', sz * 0.72)) + 1.5)
        th = d.mm(sz * 3.4)
        if ang:
            tw, th = th, tw
        best = None
        mx, my = min(0.35, w * 0.2), min(0.3, h * 0.15)
        for i_ in range(9):
            for j_ in range(9):
                cx = x + mx + tw / 2 + (w - 2 * mx - tw) * i_ / 8 if w - 2 * mx > tw else x + w / 2
                cy = y + my + (h - 2 * my - th) * j_ / 8 if h - 2 * my > th else y + h / 2 - th / 2
                P0 = F.P(cx, cy)
                if ang:
                    bx = sbox(P0[0] - d.mm(sz * 2.9), P0[1] - tw / 2 + 0.0 - th / 2, P0[0] + d.mm(sz * 0.6), P0[1] + th / 2) if False else                         sbox(P0[0] - tw + d.mm(sz * 0.5), P0[1] - th / 2, P0[0] + d.mm(sz * 0.5), P0[1] + th / 2)
                else:
                    bx = sbox(P0[0] - tw / 2, P0[1] - th + d.mm(sz * 0.6), P0[0] + tw / 2, P0[1] + d.mm(sz * 0.6))
                score = bx.intersection(obst).area / max(bx.area, 1e-9)
                dist = math.hypot(cx - (x + w / 2), cy - (y + h / 2 - th / 2)) / max(w, h)
                cand = (round(score, 3) + 0.08 * dist, cx, cy)
                if best is None or cand < best:
                    best = cand
        _, cx, cy = best
        p = F.P(cx, cy)
        d.text(p, lbl, sz, font='Helvetica-Bold', angle=ang, halo=True, z=5.2)
        o = rot((0, -d.mm(sz * 1.35)), ang)
        d.text((p[0] + o[0], p[1] + o[1]), farea(w * h), sz * 0.85, angle=ang, halo=True, z=5.2)
        o2 = rot((0, -d.mm(sz * 2.55)), ang)
        d.text((p[0] + o2[0], p[1] + o2[1]), f'{fnum(w)} x {fnum(h)}', sz * 0.72, angle=ang, halo=True,
               color=GRAY(0.3), z=5.2)
    # cotas
    s1, s2, s3 = d.mm(10), d.mm(18), d.mm(26)
    top = [r for r in L['cov'] if abs(r[2]) < EPS]
    xs = sorted({0.0, W} | {r[1] for r in top} | {r[1] + r[3] for r in top})
    bot = [r for r in L['cov'] if abs(r[2] + r[4] - Dp) < EPS]
    xb = sorted({0.0, W} | {r[1] for r in bot} | {r[1] + r[3] for r in bot})
    lef = [r for r in L['cov'] if abs(r[1]) < EPS]
    yl = sorted({0.0, Dp} | {r[2] for r in lef} | {r[2] + r[4] for r in lef})
    rig = [r for r in L['cov'] if abs(r[1] + r[3] - W) < EPS]
    yr = sorted({0.0, Dp} | {r[2] for r in rig} | {r[2] + r[4] for r in rig})
    ytop = bal[2]
    sl = s1 + (d.mm(12) if ((L['entry'] and L['entry']['side'] == 'l') or key == 'L2') else 0)
    sr = s1 + (d.mm(12) if (L['entry'] and L['entry']['side'] == 'r') else 0)
    sb = s1 + (d.mm(12) if (L['entry'] and L['entry']['side'] == 'b') else 0)
    d.chain([P(x_, ytop) for x_ in xs], s1)
    d.chain([P(0, ytop), P(W, ytop)], s2)
    d.chain([P(x_, Dp) for x_ in reversed(xb)], sb)
    d.chain([P(0, y_) for y_ in sorted(set([ytop] + yl), reverse=True)], sl)
    d.chain([P(0, Dp), P(0, ytop)], sl + (s2 - s1))
    d.chain([P(W, y_) for y_ in sorted(set([ytop] + yr))], sr)
    return L


def depto_geometry(D):
    """Muros, ventanas, columnas y puertas del departamento modelo, leídos de tools/depto.py."""
    out = dict(walls=[], windows=[], cols=[], door_leaves=[])
    for cl in dcalls(D, 'wall'):
        nm, a, b, t = cl['args'][:4]
        opens = cl['args'][4] if len(cl['args']) > 4 and cl['args'][4] else []
        out['walls'].append(dict(name=nm, a=a, b=b, t=t, open=opens))
    for cl in dcalls(D, 'window'):
        nm, a, b = cl['args'][:3]
        out['windows'].append(dict(name=nm, a=a, b=b, mull=cl['kw'].get('mullions', D['defaults']['window']['mullions']),
                                   open=cl['kw'].get('open', [])))
    for cl in dcalls(D, 'box', 'Columna fachada'):
        _, x0, y0, z0, x1, y1, z1 = cl['args'][:7]
        out['cols'].append((x0, y0, x1, y1))
    # hojas de puerta: las dos modeladas (abiertas) y las del resto de los vanos de 2,20 m
    leaves = []
    for cl in dcalls(D, 'box', 'Puerta'):
        _, x0, y0, z0, x1, y1, z1 = cl['args'][:7]
        leaves.append((x0, -y0, x1, -y1))
    walls = {w['name']: w for w in out['walls']}

    def opening_mid(wn, i):
        w = walls[wn]
        (ax, ay), (bx, by) = w['a'], w['b']
        s0, s1 = w['open'][i][:2]
        ln = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / ln, (by - ay) / ln
        return (ax + ux * s0, -(ay + uy * s0)), (ax + ux * s1, -(ay + uy * s1)), s1 - s0
    # suite: la hoja modelada está contra el tabique, del lado del estar; bisagra en la jamba oeste
    p0, p1, w_ = opening_mid('Tabique estar', 0)
    out['door_leaves'].append((p0, (1, 0), (0, -1), w_))
    # segunda suite: hoja abierta 90° hacia la suite, bisagra en la jamba oeste
    p0, p1, w_ = opening_mid('Tabique estar', 1)
    out['door_leaves'].append((p0, (1, 0), (0, 1), w_))
    # baño en suite (abre hacia el baño), vestidor (abre hacia la suite), baño 2 (abre hacia el baño)
    p0, p1, w_ = opening_mid('Tabique suite', 0)
    out['door_leaves'].append((p0, (0, 1), (1, 0), w_))
    p0, p1, w_ = opening_mid('Tabique suite', 1)
    out['door_leaves'].append((p1, (0, -1), (-1, 0), w_))
    p0, p1, w_ = opening_mid('Tabique suite 2', 0)
    out['door_leaves'].append((p0, (0, 1), (-1, 0), w_))
    out['leaves_model'] = leaves
    out['entry'] = 4.60
    return out


def depto_furniture(d, D, F, model=False):
    """Equipamiento del departamento modelo con las posiciones de tools/depto.py (y del plano = -y del modelo)."""
    G = GRAY(0.25)

    def box_(x0, y0, x1, y1, fill=WHITE, pen='xf', z=1.25, hatch=None):
        F.rect(min(x0, x1), min(-y0, -y1), abs(x1 - x0), abs(y1 - y0), fill=fill, pen=pen, z=z, hatch=hatch)

    def grp(x, y, ang, pts_list, fill=WHITE, z=1.25):
        for pts, fl in pts_list:
            q = [rot(p, ang) for p in pts]
            d.poly([F.P(x + p[0], -(y + p[1])) for p in q], 'xf', 'MOBILIARIO', fill=fl if fl is not None else fill, color=G, z=z)
    # aparador, sofá, mesa ratona, alfombras
    for cl in dcalls(D, 'rug'):
        x, y, w, dd = cl['args'][:4]
        box_(x - w / 2, y - dd / 2, x + w / 2, y + dd / 2, fill=GRAY(0.96), z=1.0)
        box_(x - w / 2 + 0.08, y - dd / 2 + 0.08, x + w / 2 - 0.08, y + dd / 2 - 0.08, fill=None, z=1.0)
    for cl in dcalls(D, 'sofa'):
        x, y, r_ = cl['args'][:3]
        w = cl['kw'].get('w', 2.8)
        dd = cl['kw'].get('d', 1.02)
        hw, hd = w / 2, dd / 2
        grp(x, y, r_, [(rect(-hw, -hd, hw, hd), WHITE), (rect(-hw, hd - 0.2, hw, hd), DK), (rect(-hw, -hd, -hw + 0.2, hd), DK),
                       (rect(hw - 0.2, -hd, hw, hd), DK)])
    for cl in dcalls(D, 'coffee_table'):
        x, y = cl['args'][:2]
        box_(x - 0.68, y - 0.38, x + 0.68, y + 0.38, fill=CT)
    for cl in dcalls(D, 'credenza'):
        x, y = cl['args'][:2]
        r_ = cl['kw'].get('rot', 0)
        grp(x, y, r_, [(rect(-1.2, -0.225, 1.2, 0.225), CT)])
    for cl in dcalls(D, 'side_table'):
        x, y = cl['args'][:2]
        F.circle(x, -y, 0.22)
    for cl in dcalls(D, 'floor_lamp'):
        x, y = cl['args'][:2]
        F.circle(x, -y, 0.21, fill=None)
        F.circle(x, -y, 0.05, fill=G)
    # piezas del catálogo de ambientación (interiorismo/catalogo.json), con su huella real
    cat_f = ROOT / 'interiorismo' / 'catalogo.json'
    cat = json.loads(cat_f.read_text(encoding='utf-8'))['slots'] if cat_f.exists() else {}
    for cl in dcalls(D, 'mueble'):
        slot, x, y = cl['args'][:3]
        if slot not in cat or cl['kw'].get('colgar') or cl['kw'].get('z'):
            continue  # lo que cuelga o va arriba de otro mueble no se dibuja en planta
        s = cat[slot]
        c = next(k for k in s['candidates'] if k['id'] == (cl['kw'].get('pick') or s['pick']))
        w0, d0 = c['dims_m'][:2]
        k = (cl['kw']['w'] / w0) if cl['kw'].get('w') else 1.0
        w_, d_ = w0 * k, d0 * k
        ang = 180 - (cl['kw'].get('rot', cl['args'][3] if len(cl['args']) > 3 else 0) or 0)
        hw, hd = w_ / 2, d_ / 2
        if any(t in slot for t in ('sofa', 'armchair', 'chair', 'stool', 'lounge')):
            grp(x, y, ang, [(rect(-hw, -hd, hw, hd), WHITE), (rect(-hw, hd - min(0.18, d_ * 0.25), hw, hd), DK)])
        elif 'plant' in slot or 'lamp' in slot:
            d.circle(F.P(x, -y), max(hw, hd), 'xf', 'MOBILIARIO', color=G, z=1.3)
        else:
            grp(x, y, ang, [(rect(-hw, -hd, hw, hd), CT)])
    for cl in dcalls(D, 'ph_model'):
        asset, x, y = cl['args'][:3]
        ang = cl['kw'].get('rot', 0)
        if 'chair' in asset and 'table' not in asset:
            grp(x, y, ang, [(rect(-0.36, -0.38, 0.36, 0.38), WHITE), (rect(-0.36, 0.22, 0.36, 0.38), DK)])
        elif 'table_chair' in asset:
            F.circle(x, -y, 0.38)
            for a in (0, 120, 240):
                q = rot((0, 0.62), a + ang)
                F.circle(x + q[0], -(y + q[1]), 0.2)
        elif 'plant' in asset or 'planter' in asset:
            if 'planter' in asset:
                box_(x - 0.45, y - 0.2, x + 0.45, y + 0.2, fill=GRAY(0.9))
            else:
                r = 0.18 + 0.12 * (cl['kw'].get('height', 0.6) or 0.6)
                d.circle(F.P(x, -y), r, 'xf', 'MOBILIARIO', color=G, z=1.3)
                d.circle(F.P(x, -y), r * 0.45, 'xf', 'MOBILIARIO', color=G, z=1.3)
    # cocina e isla
    for cl in D['calls']:
        if cl['fn'] != 'box' or not cl['args'] or cl['args'][0] is None:
            continue
        nm = cl['args'][0]
        x0, y0, z0, x1, y1, z1 = cl['args'][1:7]
        if nm in ('Columna', 'Bajo mesada', 'Isla tapa', 'Vanitory tapa', 'Vanitory 2', 'Banco', 'Cómoda', 'Banco ducha',
                  'Banco hogar', 'Hogar'):
            box_(x0, y0, x1, y1, fill=CT if nm not in ('Columna',) else DK)
        elif nm in ('Mesada',):
            box_(x0, y0, x1, y1, fill=None, pen='hr')
        elif nm in ('Anafe',):
            box_(x0, y0, x1, y1, fill=GRAY(0.75))
            for (cx, cy) in ((0.3, 0.25), (0.3, -0.12), (-0.15, 0.1)):
                pass
        elif nm in ('Bacha',):
            box_(x0, y0, x1, y1, fill=GRAY(0.85))
        elif nm == 'Receptáculo':
            box_(x0, y0, x1, y1, fill=SH)
            F.line(x0, -y0, x1, -y1)
        elif nm == 'Mampara':
            box_(x0, y0, x1 + 0.02, y1, fill=BLACK, pen='xf')
        elif nm == 'Toallero':
            box_(x0, y0, x1, y1, fill=BLACK)
        elif nm == 'Zócalo' and abs(y0 + 5.542) < 0.01:
            pass
    for cl in dcalls(D, 'stool'):
        x, y = cl['args'][:2]
        F.circle(x, -y, 0.19)
    for cl in dcalls(D, 'dining'):
        x, y = cl['args'][:2]
        ang = cl['kw'].get('rot', 0)
        w = cl['kw'].get('w', 2.2)
        dd = cl['kw'].get('d', 1.0)
        n = cl['kw'].get('chairs', 3)
        parts = [(rect(-w / 2, -dd / 2, w / 2, dd / 2), WHITE)]
        for i in range(n):
            cx = -w / 2 + (i + 0.5) * w / n
            for side in (-1, 1):
                cy = side * (dd / 2 + 0.12)
                parts.append((rect(cx - 0.23, cy - 0.22, cx + 0.23, cy + 0.22), WHITE))
        grp(x, y, ang, parts[1:], z=1.2)
        grp(x, y, ang, parts[:1], z=1.3)
    for cl in dcalls(D, 'wardrobe'):
        x0, y0, x1, y1 = cl['args'][:4]
        box_(x0, y0, x1, y1, fill=CT)
        box_(x0, y0, x1, y1, fill=None, hatch=None)
    for cl in dcalls(D, 'bed'):
        x, y = cl['args'][:2]
        w = cl['kw'].get('w', 1.8)
        l = 2.1
        hw = (w + 1.0) / 2
        # la cama arma hacia -y local; en depto.py va girada 180° (cabecera contra el muro del fondo)
        yy = y
        parts = [(rect(-hw, -0.06, hw, 0.0), DK), (rect(-w / 2, -l, w / 2, -0.06), WHITE),
                 (rect(-w / 2 - 0.02, -l - 0.02, w / 2 + 0.02, -0.55), CT)]
        for s in (-1, 1):
            parts.append((rect(s * w / 4 - 0.34, -0.5, s * w / 4 + 0.34, -0.1), DK))
            parts.append((rect(s * (w / 2 + 0.3) - 0.25, -0.46, s * (w / 2 + 0.3) + 0.25, -0.08), CT))
        grp(x, yy, 180, parts, z=1.3)
        for s in (-1, 1):
            F.circle(x + s * (w / 2 + 0.3), -(yy + 0.27), 0.15, fill=None, z=1.35)
    for cl in dcalls(D, 'curtain'):
        nm, a, b = cl['args'][:3]
        (ax, ay), (bx, by) = a, b
        n = 14
        pts = []
        for i in range(n + 1):
            tt = i / n
            px, py = ax + (bx - ax) * tt, ay + (by - ay) * tt
            ln = math.hypot(bx - ax, by - ay)
            nx, ny = -(by - ay) / ln, (bx - ax) / ln
            off = 0.035 * math.sin(tt * math.pi * 8)
            pts.append(F.P(px + nx * off, -(py + ny * off)))
        d.line(pts, 'xf', 'MOBILIARIO', color=GRAY(0.35), z=1.3)
    for cl in D['calls']:
        if cl['fn'] == 'box' and cl['args'] and cl['args'][0] in ('Vanitory',):
            pass
    # bachas del vanitory del baño en suite
    for xx in (5.75, 6.75):
        F.circle(xx, 7.94 - 0.27, 0.2)
    if model:
        for cl in dcalls(D, 'clad'):
            nm, a, b = cl['args'][:3]
            d.line([F.P(a[0], -a[1]), F.P(b[0], -b[1])], 'fn', 'MUROS', color=GRAY(0.3), z=2.45)


def type_units(S, key):
    return [(f, u) for f in S['floors'] for u in f['units'] if u['type'] == key]


def unit_frame_info(S, key):
    t = S['types'][key]
    L = pj_layout(t)
    bal = next(r for r in t['plan'] if r[5] == 'balcony')
    W, Dp = L['W'], L['D']
    return t, L, bal, W, Dp


def plate_location(S, key):
    """Planta de la zona a 1:200 con las unidades de la tipología resaltadas."""
    units = type_units(S, key)
    f0 = units[0][0]
    zone = f0['zone']
    d = Dwg(200)
    ring_and_slab(d, screens=ZONE_STRIPS[zone])
    for u in f0['units']:
        env = unit_envelope(u['shape'])
        hl = u['type'] == key
        d.geom(env, 'th', 'MUROS', fill=GRAY(0.72) if hl else WHITE, z=1)
        x, y = LABEL_POS[u['shape']]
        ids = [f"{n}{u['letter']}" for n in S['zone_floors'][zone]]
        rng = ids[0] if len(ids) == 1 else f'{ids[0]} a {ids[-1]}'
        d.text((x, y - 1.5), rng, 2.6, font='Helvetica-Bold', halo=True)
        d.text((x, y - 3.0), u['type'], 2.2, halo=True)
    for ch, r in strip_rects(zone).items():
        d.geom(r, 'xf', 'MUROS', fill=GRAY(0.86), z=1.1)
    d.geom(Point(0, 0).buffer(B.R_PAL, 64), 'fn', 'MUROS', fill=GRAY(0.9), z=1.2)
    draw_core(d, 'typ', angle=B.ROT[f0['n']], detail=False)
    d.north((B.A + 2.0, B.A + 3.5), -B.ROT[f0['n']], 10)
    return d, zone, f0


def sh_unit(X, c, key, model=False, extra=None, north=None):
    S, D = X.S, X.D
    t, L, bal, W, Dp = unit_frame_info(S, key)
    d = Dwg(50)
    unit_drawing(d, S, D, key, model=model, extra=extra)
    units = type_units(S, key)
    f0, u0 = units[0]
    zone = f0['zone']
    x0m, x1m = -d.mm(40), W + d.mm(30)
    y0m, y1m = -(Dp + d.mm(30)), -bal[2] + d.mm(30)
    pw, ph = (x1m - x0m) * 20, (y1m - y0m) * 20
    fx, fy = DA[0] + 2, DA[1] + DA[3] - ph - 2
    if north is None:
        d.north((x1m - d.mm(12), y1m - d.mm(13)), -u0['bearing'], 15)
        d.text((x1m - d.mm(12), y1m - d.mm(26)), f"norte para la unidad {u0['id']}", 1.8, color=GRAY(0.3))
    else:
        d.north((x1m - d.mm(12), y1m - d.mm(13)), north[0], 15)
        d.text((x1m - d.mm(12), y1m - d.mm(26)), north[1], 1.8, color=GRAY(0.3))
    render(c, d, (fx, fy, pw, ph), ((x0m + x1m) / 2, (y0m + y1m) / 2))
    title = f"TIPOLOGÍA {key} · {t['rooms_txt'].upper()}" if not model else 'DEPARTAMENTO MODELO · TIPOLOGÍA L2 · 2 SUITES'
    caption(c, fx + 6, fy - 4, 1, title, 'Esc. 1:50',
            f"{len(units)} unidades · {t['name']}" if not model else 'tal como se presenta en el recorrido virtual')
    right_w = DA[0] + DA[2] - (fx + pw) - 8
    rows = []
    for i, r in enumerate(t['plan']):
        fin = FINISH[r[5]]
        if key == 'L2' and r[0].startswith('Cocina'):
            fin = ('Entablonado de madera miel', 'Piedra caliza s/ mesada de granito', 'Placa de yeso susp.')
        if key == 'L2' and r[0] == 'Baño':
            fin = ('Piedra gris', 'Piedra caliza crema', 'Placa de yeso verde')
        rows.append([f'{i + 1:02d}', r[0], f'{fnum(r[3])} x {fnum(r[4])}', fnum(r[3] * r[4]), fin[0], fin[2]])
    covx, opx = t['covered_exact'], t['open_exact']
    oname = bal[0].lower()
    srows = [['Superficie cubierta propia', fnum(covx), f"{t['covered']}"],
             [f'Superficie de {oname} (descubierta)', fnum(opx), f"{t['open']}"],
             ['Total de la unidad', fnum(covx + opx), f"{t['covered'] + t['open']}"]]
    urows = []
    for f, u in units:
        dirn, view = bearing_info(S, u['bearing'])
        urows.append([u['id'], str(f['n']), flevel(B.NPT[f['n']]), f"{fnum(u['bearing'] % 360, 0)}°", dirn, view])
    ucols = [13, 9, 15, 13, 20, 70]
    uhead = ['Unidad', 'Piso', 'NPT', 'Rumbo', 'Frente', 'Vista']

    def schedule(tx, ty):
        txt(c, tx, ty, 'Planilla de locales', 3.2, 'Helvetica-Bold')
        ty = table(c, tx, ty - 3, [8, 32, 23, 15, 37, 33], rows,
                   head=['N°', 'Local', 'Medidas (m)', 'Sup. (m²)', 'Solado', 'Cielorraso'],
                   size=2.05, rowh=4.6, aligns=['c', 'l', 'c', 'r', 'l', 'l'])
        txt(c, tx, ty - 3.2, 'Medidas y superficies a ejes de muros; incluyen la mitad de los muros perimetrales.', 1.8,
            color=GRAY(0.3))
        ty = table(c, tx, ty - 7, [80, 33, 35], srows, head=['Superficies', 'Planilla (m²)', 'Ficha comercial (m²)'],
                   size=2.2, rowh=5.0, aligns=['l', 'r', 'r'], bold_last=True)
        return ty

    def unitlist(tx, ty):
        txt(c, tx, ty, f'Unidades {key} ({len(units)})', 3.2, 'Helvetica-Bold')
        return table(c, tx, ty - 3, ucols, urows, head=uhead, size=2.0, rowh=4.3, aligns=['c', 'c', 'r', 'r', 'l', 'l'])
    if model:
        schedule(fx + pw + 8, DA[1] + DA[3] - 6)
    elif right_w >= 175:
        ty = schedule(fx + pw + 8, DA[1] + DA[3] - 6)
        uy = unitlist(DA[0] + 6, fy - 22)
        sec = unit_section(S, key)
        sw = (Dp - bal[2] + 4.6) * 20
        sx = DA[0] + 160
        render(c, sec, (sx, fy - 156, min(sw, DA[0] + DA[2] - sx), 132), ((bal[2] + Dp + 2.6) / 2, 1.45))
        caption(c, sx + 4, fy - 162, 2, 'CORTE TRANSVERSAL POR EL ESTAR', 'Esc. 1:50', 'piso a piso 3,30 m')
    else:
        schedule(DA[0] + 6, fy - 20)
        unitlist(DA[0] + 6 + 172, fy - 20)
    X.sheet.keyplan = keyplan_tower(zone, [u['shape'] for u in f0['units'] if u['type'] == key], f0['n'])
    return d


def unit_section(S, key):
    """Corte transversal de la tipología por el eje del estar (1:50): u = profundidad desde el frente, z = altura."""
    t = S['types'][key]
    L = pj_layout(t)
    D_ = L['D']
    bal = next(r for r in t['plan'] if r[5] == 'balcony')
    liv = next(r for r in L['cov'] if r[5] == 'living')
    xc = liv[1] + liv[3] / 2
    d = Dwg(50)
    CUT = GRAY(0.05)
    FTF, SL, FIN, H = B.FTF, B.SLAB, B.FIN, B.H
    by = bal[2]
    H_ = lambda u, z: (u, z)
    for zb in (0.0, FTF):
        d.poly([H_(by, zb - FIN - SL), H_(D_ + 0.6, zb - FIN - SL), H_(D_ + 0.6, zb - FIN), H_(by, zb - FIN)], 'fn', 'LOSAS', fill=CUT, z=2)
        d.poly([H_(0.0, zb - FIN), H_(D_ + 0.6, zb - FIN), H_(D_ + 0.6, zb), H_(0.0, zb)], 'xf', 'LOSAS', fill=WHITE,
               hatch=(45, 0.8, 'hr', GRAY(0.45)), z=2)
        d.line([H_(by + 0.02, zb - FIN + 0.06), H_(-0.05, zb - FIN + 0.06)], 'fn', 'LOSAS', z=2.1)
        rh = 1.05
        d.poly([H_(by + 0.03, zb - FIN + 0.06), H_(by + 0.07, zb - FIN + 0.06), H_(by + 0.07, zb + rh), H_(by + 0.03, zb + rh)],
               'fn', 'ABERTURAS', fill=WHITE, z=2.2)
        d.line([H_(by + 0.01, zb + rh), H_(by + 0.09, zb + rh)], 'th', 'ABERTURAS', z=2.2)
    zt = FTF - FIN - SL
    d.line([H_(0.12, H), H_(D_ - 0.13, H)], 'fn', 'LOSAS', z=2)
    d.line([H_(0.12, H + 0.02), H_(D_ - 0.13, H + 0.02)], 'hr', 'LOSAS', z=2)
    # carpintería del frente y muro del fondo
    d.poly([H_(-0.05, 0.0), H_(0.05, 0.0), H_(0.05, zt), H_(-0.05, zt)], 'fn', 'ABERTURAS', fill=WHITE, z=2.3)
    d.line([H_(0.0, 0.0), H_(0.0, zt)], 'hr', 'ABERTURAS', z=2.35)
    for zz in (0.0, zt - 0.06):
        d.poly([H_(-0.06, zz), H_(0.06, zz), H_(0.06, zz + 0.06), H_(-0.06, zz + 0.06)], 'xf', 'ABERTURAS', fill=BLACK, z=2.4)
    d.poly([H_(D_ - 0.125, 0.0), H_(D_ + 0.125, 0.0), H_(D_ + 0.125, zt), H_(D_ - 0.125, zt)], 'md', 'MUROS', fill=WHITE,
           hatch=(45, 0.9, 'hr', GRAY(0.2)), z=2.3)
    # tabiques cortados por el plano x = eje del estar
    rooms = sorted([r for r in L['cov'] if r[1] - 1e-6 <= xc <= r[1] + r[3] + 1e-6], key=lambda r: r[2])
    cuts = []
    for a, b in zip(rooms, rooms[1:]):
        y = a[2] + a[4]
        op = None
        for seg in L['opens']:
            if not seg['v'] and abs(seg['y'] - y) < 1e-6:
                ln = min(seg['e'] - seg['s'] - 0.4, 2.4)
                m = (seg['s'] + seg['e']) / 2
                if m - ln / 2 <= xc <= m + ln / 2:
                    op = 'vano'
        for seg, rm, w_ in L['doors']:
            if not seg['v'] and abs(seg['y'] - y) < 1e-6:
                m = (seg['s'] + seg['e']) / 2
                if m - w_ / 2 <= xc <= m + w_ / 2:
                    op = 'puerta'
        cuts.append((y, op))
    for y, op in cuts:
        z0 = 2.10 if op else 0.0
        d.poly([H_(y - 0.06, z0), H_(y + 0.06, z0), H_(y + 0.06, zt), H_(y - 0.06, zt)], 'th', 'MUROS', fill=GRAY(0.62), z=2.3)
        if op == 'puerta':
            d.line([H_(y, 0.0), H_(y, 2.10)], 'hr', 'ABERTURAS', dash='hidden', z=2.3)
    bounds = [0.0] + [y for y, _ in cuts] + [D_]
    for r, (a, b) in zip(rooms, zip(bounds, bounds[1:])):
        d.text(((a + b) / 2, 1.45), r[0].upper(), 2.0, font='Helvetica-Bold')
    d.text((by / 2, 1.45), bal[0].upper(), 2.0, font='Helvetica-Bold')
    # niveles y cotas
    xr = D_ + 1.4
    for z, tx_ in ((0.0, 'NPT ±0,00'), (H, f'cielorraso +{fnum(H)}'), (FTF, f'NPT piso superior +{fnum(FTF)}')):
        d.level_section((xr, z), tx_, 1.9)
    d.chain([(D_ + 0.9, -FIN - SL), (D_ + 0.9, -FIN), (D_ + 0.9, 0.0), (D_ + 0.9, H), (D_ + 0.9, FTF - FIN - SL),
             (D_ + 0.9, FTF - FIN), (D_ + 0.9, FTF)][::-1], 0)
    d.chain([(by, -0.95), (0.0, -0.95)] + [(y, -0.95) for y, _ in cuts] + [(D_, -0.95)], 0)
    return d


TYPE_NOTES = {
    'B1': [], 'B2': [], 'L3': [], 'C3': ['La galería se extiende sobre el frente principal (18,00 x 3,00 m).'],
    'PH': ['Terraza de 22,00 x 4,00 m sobre el frente principal; el resto del perímetro es balcón corrido de servicio.'],
    'L2': ['Muros, aberturas y equipamiento según el departamento modelo (A-501). El acceso se ubica en el '
           'muro oeste del estar, entre el muro del hogar y la suite.'],
}


def mk_unit_sheet(key):
    def fn(X, c):
        d = sh_unit(X, c, key)
        return {f'{X.sheet.code}_tipologia_{key}': d}
    return fn


def sh_A501(X, c):
    S, D = X.S, X.D
    V = D['VIEWS']
    order = ['living', 'kitchen', 'balcony', 'suite', 'bedroom', 'bath']

    def points(d):
        # puntos del recorrido 360° y trayectos (tools/depto.py: VIEWS y LINKS); el marco del modelo es el del plano
        for (a, b), mids in D['LINKS'].items():
            pts = [V[a][0]] + list(mids) + [V[b][0]]
            d.line([(x, y) for x, y in pts], 'fn', 'CIRCULACION', dash='dash', color=GRAY(0.3), z=4.5)
        for i, k in enumerate(order):
            (x, y), yaw = V[k]
            v = (math.sin(math.radians(yaw)), math.cos(math.radians(yaw)))
            for s_ in (-1, 1):
                q = rot(v, -s_ * D.get('MOVE_FOV', 96) / 2)
                d.line([(x, y), (x + q[0] * 0.9, y + q[1] * 0.9)], 'fn', 'CIRCULACION', z=4.6)
            d.circle((x, y), 0.26, 'fn', 'CIRCULACION', fill=BLACK, z=4.7)
            d.text((x, y), str(i + 1), 2.2, font='Helvetica-Bold', color=WHITE, z=4.8)
    d = sh_unit(X, c, 'L2', model=True, extra=points, north=(0.0, 'norte del modelo 3D (balcón al norte)'))
    # planta de cielorrasos e iluminación 1:100
    r = Dwg(100)
    dep = depto_geometry(D)
    walls = []
    for wl in dep['walls']:
        (ax, ay), (bx, by) = wl['a'], wl['b']
        walls.append(LineString([(ax, ay), (bx, by)]).buffer(wl['t'] / 2, cap_style=2))
    r.geom(unary_union(walls), 'md', 'MUROS', fill=GRAY(0.25))
    for win in dep['windows']:
        r.line([win['a'], win['b']], 'fn', 'ABERTURAS')
    r.poly(rect(-0.25, -10.25, 13.25, 0.0), 'xf', 'LOSAS', dash='hidden')
    for cl in dcalls(D, 'downlight'):
        x, y = cl['args'][:2]
        r.circle((x, y), 0.09, 'xf', 'MOBILIARIO', fill=WHITE)
        r.line([(x - 0.15, y), (x + 0.15, y)], 'hr', 'MOBILIARIO')
        r.line([(x, y - 0.15), (x, y + 0.15)], 'hr', 'MOBILIARIO')
    for cl in dcalls(D, 'pendant'):
        x, y = cl['args'][:2]
        r.circle((x, y), 0.13, 'fn', 'MOBILIARIO', fill=GRAY(0.6))
    for cl in D['calls']:
        if cl['fn'] == 'box' and cl['args'] and cl['args'][0] in ('Tira LED', 'Luz espejo'):
            x0, y0, z0, x1, y1, z1 = cl['args'][1:7]
            r.poly(rect(x0, y0 - 0.03, x1, y1 + 0.03), 'fn', 'MOBILIARIO', fill=GRAY(0.4))
    for cl in dcalls(D, 'curtain'):
        a, b = cl['args'][1:3]
        r.line([a, b], 'th', 'MOBILIARIO', dash='dot', color=GRAY(0.3))
    for p, t_ in (((2.5, -2.6), 'h 2,75'), ((10.5, -2.6), 'h 2,75'), ((2.5, -8.0), 'h 2,75'), ((11.0, -8.0), 'h 2,75'),
                  ((6.2, -6.9), 'h 2,45')):
        r.level_plan(p, t_, 1.6)
    # baño en suite y vestidor a 1:25 (mismo modelo, recortado)
    b25 = Dwg(25)
    unit_drawing(b25, S, D, 'L2', model=True)
    bx, by = DA[0] + 6, DA[1] + 122
    render(c, b25, (bx, by, 150, 116), (6.2, -7.75))
    c.setLineWidth(0.25)
    c.rect(bx, by, 150, 116, stroke=1, fill=0)
    caption(c, bx + 4, by - 5, 3, 'BAÑO EN SUITE Y VESTIDOR', 'Esc. 1:25', 'receptáculo de cemento alisado, mampara fija, vanitory doble')
    rx, ry = DA[0] + DA[2] - 196, DA[1] + 128
    render(c, r, (rx, ry, 190, 140), (6.5, -5.0))
    caption(c, rx + 4, ry - 4, 2, 'CIELORRASOS E ILUMINACIÓN', 'Esc. 1:100', 'losa a +2,75; baños con cielorraso bajo a 2,45')
    # tablas del modelo
    tx, ty = DA[0] + 6, DA[1] + 98
    txt(c, tx, ty, 'Puntos del recorrido 360°', 3.2, 'Helvetica-Bold')
    rows = []
    for i, k in enumerate(order):
        (x, y), yaw = V[k]
        links = ', '.join(sorted(D['LABELS'][b if a == k else a] for (a, b) in D['LINKS'] if k in (a, b)))
        rows.append([str(i + 1), D['LABELS'][k], f'{fnum(x)} / {fnum(-y)}', f'{fnum(yaw, 0)}°', links])
    ty = table(c, tx, ty - 3, [8, 34, 30, 18, 104], rows,
               head=['N°', 'Ambiente', 'x / y (m)', 'Mira a', 'Trayectos a'], size=2.0, rowh=4.4,
               aligns=['c', 'l', 'c', 'r', 'l'])
    txt(c, tx, ty - 3.4, f"Altura de cámara {fnum(D['EYE'])} m; ángulo desde el norte, horario. Trayectos en línea de trazos.",
        1.8, color=GRAY(0.3))
    tx2 = tx + 206
    ty2 = DA[1] + 98
    txt(c, tx2, ty2, 'Terminaciones del modelo', 3.2, 'Helvetica-Bold')
    fin = [['Piso estar, cocina y suites', 'Entablonado de madera miel'], ['Muro del hogar (estar)', 'Piedra laja apilada'],
           ['Banco del hogar, mesada e isla', 'Granito negro apomazado'], ['Bajo mesada', 'Laca mate verde bosque'],
           ['Columna, isla y estante', 'Madera miel'], ['Salpicadero', 'Piedra caliza crema'],
           ['Respaldo suite principal', 'Listones de madera miel'], ['Respaldo segunda suite', 'Pintura verde bosque'],
           ['Piso y mesada del baño', 'Piedra gris'], ['Paredes del baño', 'Piedra caliza crema en placas'], ['Balcón', 'Deck de madera'],
           ['Carpinterías y griferías', 'Metal negro'], ['Paredes', 'Enlucido de yeso blanco cálido']]
    table(c, tx2, ty2 - 3, [62, 52], fin, head=['Ubicación', 'Material'], size=2.0, rowh=4.4)
    return {'A-501_departamento_modelo_L2': d, 'A-501_cielorrasos_L2': r}


# ===================================================================== techos, giro, implantación, carátula
def sh_A105(X, c):
    S = X.S
    d = Dwg(100)
    x0, y0, x1, y1 = B.POD
    pod = sbox(*B.POD)
    s3 = Polygon(rounded_square(B.A, B.R_SLAB, 10))
    green = pod.difference(s3)
    d.geom(green, 'md', 'LOSAS', fill=WHITE, hatch=(45, 2.2, 'hr', GRAY(0.55)), z=0.5)
    d.geom(pod.buffer(-0.30, join_style=2).difference(s3), 'xf', 'LOSAS', z=0.6)
    for p_ in ((x0 + 1.0, y0 + 1.0), (x1 - 1.0, y0 + 1.0), (x0 + 1.0, y1 - 1.0), (x1 - 1.0, y1 - 1.0)):
        d.circle(p_, 0.25, 'fn', 'LOSAS', fill=WHITE, z=0.7)
        d.text((p_[0] + (1.5 if p_[0] < 0 else -1.5), p_[1]), 'BLL', 1.6, z=6)
    d.text(((x0 - B.A) / 2 + 1.0, 0.0), 'CUBIERTA VERDE EXTENSIVA', 2.2, font='Helvetica-Bold', halo=True)
    d.text(((x0 - B.A) / 2 + 1.0, -1.4), 'no transitable · sobre losa del piso 3', 1.8, halo=True)
    d.text(((x1 + B.A) / 2 - 1.0, 0.0), 'CUBIERTA VERDE EXTENSIVA', 2.2, font='Helvetica-Bold', halo=True)
    d.level_plan(((x0 - B.A) / 2 + 1.0, -3.0), '+9,00 / parapeto +9,60', 1.7)
    # losas de los pisos inferiores y losa de cubierta (giro 64°)
    env = unary_union([plate_slab(n) for n in range(3, 19)])
    d.geom(env, 'xf', 'LOSAS', dash='hidden', z=0.8)
    roof = plate_slab(19)
    d.geom(roof, 'hv', 'LOSAS', fill=WHITE, z=1.0)
    d.geom(roof.buffer(-0.08, join_style=1), 'xf', 'LOSAS', z=1.05)
    # pendientes hacia cuatro embudos y paneles fotovoltaicos
    for k in range(4):
        q = rot((7.5, 7.5), -B.ROT[19] + k * 90)
        d.circle(q, 0.22, 'fn', 'LOSAS', fill=WHITE, z=1.2)
        for a_ in (0, 90):
            p0 = rot((7.5 - (2.6 if a_ == 0 else 0), 7.5 - (2.6 if a_ else 0)), -B.ROT[19] + k * 90)
            d.line([p0, q], 'xf', 'LOSAS', z=1.2)
            v = (q[0] - p0[0], q[1] - p0[1])
            Lv = math.hypot(*v)
            u = (v[0] / Lv, v[1] / Lv)
            d.poly([q, (q[0] - u[0] * 0.5 - u[1] * 0.18, q[1] - u[1] * 0.5 + u[0] * 0.18),
                    (q[0] - u[0] * 0.5 + u[1] * 0.18, q[1] - u[1] * 0.5 - u[0] * 0.18)], 'xf', 'LOSAS', fill=BLACK, z=1.2)
            mid = ((p0[0] + q[0]) / 2, (p0[1] + q[1]) / 2)
            d.text((mid[0], mid[1] + 0.5), '2%', 1.5, z=6, halo=True)
    for i in range(4):
        for j in range(3):
            cx, cy = -6.0 + i * 3.2, 5.0 + j * 1.9
            pts = [rot((cx + a_, cy + b_), -B.ROT[19]) for a_, b_ in ((-1.4, -0.75), (1.4, -0.75), (1.4, 0.75), (-1.4, 0.75))]
            d.poly(pts, 'xf', 'MOBILIARIO', fill=GRAY(0.88), z=1.3)
    d.text(rot((-1.2, 10.2), -B.ROT[19]), 'paneles fotovoltaicos (12 u.)', 1.7, angle=-B.ROT[19], halo=True)
    for i in range(3):
        q = rot((-6.0 + i * 2.4, -7.0), -B.ROT[19])
        pts = [(q[0] + a_, q[1] + b_) for a_, b_ in rect(-0.8, -0.5, 0.8, 0.5)]
        d.poly(pts, 'xf', 'MOBILIARIO', fill=WHITE, z=1.3)
        d.circle(q, 0.35, 'xf', 'MOBILIARIO', z=1.35)
    d.text(rot((-3.6, -8.6), -B.ROT[19]), 'condensadoras', 1.7, angle=-B.ROT[19], halo=True)
    # núcleo (fijo): sala de tanques y salida de escalera
    d.poly(rect(-B.CORE, -B.CORE, B.CORE, B.CORE), 'hv', 'MUROS', fill=GRAY(0.9), z=1.5)
    d.line([(-B.CORE, -B.CORE), (B.CORE, B.CORE)], 'hr', 'MUROS', z=1.55)
    d.line([(-B.CORE, B.CORE), (B.CORE, -B.CORE)], 'hr', 'MUROS', z=1.55)
    d.text((0, 0.6), 'SALA DE TANQUES', 1.8, font='Helvetica-Bold', halo=True)
    d.text((0, -0.5), 'TR 2 x 15.000 l', 1.6, halo=True)
    d.level_plan((0, -1.7), flevel(B.TOP), 1.6)
    d.circle((B.CORE - 0.5, B.CORE - 0.5), 0.12, 'fn', 'MUROS', fill=BLACK, z=1.6)
    d.text((B.CORE + 1.6, B.CORE + 0.4), 'pararrayos', 1.5, halo=True)
    door_leaf(d, (-B.CORE, 0.50), 0.90, (0, -1), (-1, 0))
    d.text((-B.CORE - 1.9, -0.6), 'salida a azotea', 1.5, halo=True)
    d.level_plan(rot((6.5, -2.0), -B.ROT[19]), flevel(B.ROOF), 1.7)
    d.text(rot((0, -11.4), -B.ROT[19]), 'AZOTEA TÉCNICA · BARANDA DE VIDRIO h 1,10', 1.8, angle=-B.ROT[19], halo=True)
    podium_axes(d)
    podium_dims(d)
    d.north((x1 + 4.5, y1 + 5.0), 0, 16)
    frame = (DA[0], DA[1] + 24, DA[2], DA[3] - 26)
    render(c, d, frame, (0.6, 0.8))
    caption(c, DA[0] + 8, DA[1] + 14, 1, 'PLANTA DE TECHOS', 'Esc. 1:100',
            f'cubierta del basamento +9,00 · azotea {flevel(B.ROOF)} (losa girada {fnum(B.ROT[19], 0)}°) · tanques {flevel(B.TOP)}')
    return {'A-105_planta_de_techos': d}


def sh_A106(X, c):
    S = X.S
    d = Dwg(200)
    for n in range(3, 20):
        sl = plate_slab(n)
        heavy = n in (3, 9, 15, 18)
        d.geom(sl, 'md' if heavy else 'hr', 'LOSAS', color=BLACK if heavy else GRAY(0.45), z=1)
        if n < 19:
            q = rot((0, B.A + 0.9), -B.ROT[n])
            if heavy or n % 2 == 1:
                d.text(q, str(n), 1.7, font='Helvetica-Bold' if heavy else 'Helvetica', angle=-B.ROT[n], halo=True)
    d.geom(Point(0, 0).buffer(B.R_PAL, 96), 'fn', 'MUROS', dash='dash', z=1.5)
    d.geom(Point(0, 0).buffer(math.hypot(B.CORE, B.CORE), 96), 'xf', 'MUROS', dash='dot', z=1.5)
    d.geom(core_parts(), 'fn', 'MUROS', fill=GRAY(0.15), z=2)
    for n in (3, 18):
        for u_ in next(f for f in S['floors'] if f['n'] == n)['units']:
            b = math.radians(u_['bearing'])
            v = (math.sin(b), math.cos(b))
            p0 = (v[0] * 18.6, v[1] * 18.6)
            p1 = (v[0] * 21.0, v[1] * 21.0)
            d.line([p0, p1], 'fn', 'TEXTOS', z=3)
            d.text((v[0] * 22.4, v[1] * 22.4), u_['id'], 1.8, font='Helvetica-Bold', halo=True)
    for k, (dirn, view) in enumerate(S['bearings']):
        a = math.radians(k * 45)
        v = (math.sin(a), math.cos(a))
        d.line([(v[0] * 24.5, v[1] * 24.5), (v[0] * 26.0, v[1] * 26.0)], 'th', 'TEXTOS', z=3)
        d.text((v[0] * 27.6, v[1] * 27.6), dirn.upper(), 1.9, font='Helvetica-Bold', halo=True)
        d.text((v[0] * 27.6, v[1] * 27.6 - 1.0), view, 1.5, halo=True)
    d.circle((0, 0), 24.5, 'xf', 'TEXTOS', z=0.5)
    d.north((-23.5, 23.5), 0, 12)
    render(c, d, (DA[0], DA[1] + DA[3] - 300, 300, 296), (0, 0))
    caption(c, DA[0] + 8, DA[1] + DA[3] - 306, 1, 'LOSAS DE LOS PISOS 3 A 18 Y CUBIERTA', 'Esc. 1:200',
            'núcleo fijo, palier circular; rumbos de las unidades de los pisos 3 y 18')
    tx = DA[0] + 308
    ty = DA[1] + DA[3] - 128
    txt(c, tx, ty, 'Regla de orientación', 3.2, 'Helvetica-Bold')
    ty -= 6
    for ln in [
        f"Rumbo de cada unidad = rumbo de su frente en el piso 3 + giro del piso (rumbo local + giro del piso). Orientación y vista "
        "según los ocho sectores de 45° de bearingInfo().",
        f"Giro por piso: {fnum(B.TW, 0)}° horario. Los pisos 1 y 2 (club) no giran; la cubierta continúa la regla ({fnum(B.ROT[19], 0)}°).",
        f"Separación mínima entre el núcleo fijo ({fnum(2 * B.CORE)} x {fnum(2 * B.CORE)} m) y el palier: {fnum(B.CLEAR)} m con "
        "cualquier giro (diagonal del núcleo dentro de un círculo de Ø " + fnum(2 * B.R_PAL) + ").",
    ]:
        ty = para(c, tx, ty, ln, 2.3, 300) - 2.0
    rows = []
    for f in S['floors']:
        for u in f['units']:
            dirn, view = bearing_info(S, u['bearing'])
            rows.append([u['id'], str(f['n']), u['type'], fnum(f['rot'], 0) + '°', fnum(u['bearing'] % 360, 0) + '°', dirn, view])
    half = (len(rows) + 1) // 2
    cols = [13, 9, 13, 12, 13, 20, 54]
    head = ['Unidad', 'Piso', 'Tipo', 'Giro', 'Rumbo', 'Frente', 'Vista']
    al = ['c', 'c', 'c', 'r', 'r', 'l', 'l']
    table(c, DA[0] + 308, DA[1] + DA[3] - 4, cols, rows[:half], head=head, size=1.95, rowh=4.15, aligns=al)
    table(c, DA[0] + 308 + 142, DA[1] + DA[3] - 4, cols, rows[half:], head=head, size=1.95, rowh=4.15, aligns=al)
    floors = (3, 6, 9, 12, 15, 17, 18)
    w = DA[2] / len(floors)
    for i, n in enumerate(floors):
        m = Dwg(500)
        mini_plate(m, S, n)
        render(c, m, (DA[0] + i * w, DA[1] + 22, w, 96), (0, 0), clip=False)
        f = next(x for x in S['floors'] if x['n'] == n)
        txt(c, DA[0] + i * w + w / 2, DA[1] + 14, f"Piso {n} · giro {fnum(f['rot'], 0)}° · frente {bearing_info(S, f['rot'])[0].lower()}",
            2.2, 'Helvetica-Bold', 'c')
    caption(c, DA[0] + 8, DA[1] + 128, 2, 'PLANTAS EN EL MARCO DEL SITIO (NORTE ARRIBA)', 'Esc. 1:500', 'unidades y núcleo fijo')
    return {'A-106_esquema_de_giro': d}


def mini_plate(d, S, n):
    f = next(x for x in S['floors'] if x['n'] == n)
    th = -B.ROT[n]
    R_ = lambda g_: affinity.rotate(g_, th, origin=(0, 0))
    d.geom(R_(Polygon(rounded_square(B.A, B.R_SLAB, 8))), 'fn', 'LOSAS', fill=GRAY(0.93))
    for u in f['units']:
        d.geom(R_(unit_envelope(u['shape'])), 'fn', 'MUROS', fill=WHITE)
        x, y = LABEL_POS[u['shape']]
        q = rot((x, y - 2.0), th)
        d.text(q, u['id'], 2.0, font='Helvetica-Bold')
    d.geom(Point(0, 0).buffer(B.R_PAL, 48), 'xf', 'MUROS', fill=GRAY(0.85))
    d.geom(sbox(-B.CORE, -B.CORE, B.CORE, B.CORE), 'xf', 'MUROS', fill=GRAY(0.2))
    d.north((15.0, 15.0), 0, 7)


def town_map(d):
    """Plano de ubicación esquemático (escala 1:5000): lago, pueblo, ruta al cerro y el lote."""
    shore = [(x, 120 + 40 * math.sin(x / 260.0) + 18 * math.sin(x / 90.0)) for x in range(-900, 901, 30)]
    d.poly(shore + [(900, 700), (-900, 700)], 'fn', 'ENTORNO', fill=GRAY(0.86), z=0.1)
    d.line(shore, 'fn', 'ENTORNO', z=0.2)
    for i in range(-6, 3):
        for j in range(-4, 2):
            x, y = -700 + i * 0 + (i + 6) * 70, -380 + (j + 4) * 70
            if x > -150:
                continue
            d.poly(rect(x, y, x + 55, y + 55), 'xf', 'ENTORNO', fill=GRAY(0.95), z=0.3)
    d.line([(-150, 60), (-150, -520)], 'fn', 'ENTORNO', z=0.4)
    d.line([(-900, 40), (900, 40)], 'th', 'ENTORNO', z=0.4)
    d.line([(-60, 40), (200, -200), (520, -520)], 'th', 'ENTORNO', dash='dash', z=0.4)
    d.poly([(-520, 112), (-505, 112), (-505, 200), (-520, 200)], 'fn', 'ENTORNO', fill=WHITE, z=0.5)
    d.text((-512, 222), 'MUELLE', 2.0, font='Helvetica-Bold', halo=True)
    d.text((-430, -150), 'PUERTO ILÉN', 3.0, font='Helvetica-Bold', halo=True)
    d.text((0, 420), 'LAGO ILÉN', 3.6, font='Helvetica-Bold', halo=True)
    d.text((420, -380), 'al cerro Ilén y las pistas', 2.0, angle=-45, halo=True)
    d.text((600, 20), 'Av. Costanera del Ilén', 1.8, halo=True)
    for i in range(30):
        x = 120 + (i % 6) * 110 + (i // 6) * 17
        y = -100 - (i // 6) * 70
        f_tree(d, (x, y), 22)
    d.poly(rect(*LOT), 'th', 'ENTORNO', fill=BLACK, z=1)
    d.circle(((LOT[0] + LOT[2]) / 2, (LOT[1] + LOT[3]) / 2), 95, 'fn', 'ENTORNO', z=1)
    d.text((0, 160), 'LENGA', 2.4, font='Helvetica-Bold', halo=True)
    d.north((780, 560), 0, 12)


def sh_A100(X, c):
    S = X.S
    d = Dwg(500)
    site_works(d, detail=False)
    lx0, ly0, lx1, ly1 = LOT
    d.text((0, 85.0), 'LAGO ILÉN', 4.0, font='Helvetica-Bold', halo=True)
    d.text((0, 78.0), 'nivel medio 768,20 m s.n.m. (-3,30)', 2.0, halo=True)
    d.text((62.0, 41.0), 'PASEO COSTERO PÚBLICO (ciclovía y senda peatonal)', 2.0, halo=True)
    d.text((-120.0, 57.5), 'línea de ribera', 1.8, halo=True)
    d.text((-52.5, -110.0), 'CALLE LOS ÑIRES', 2.4, angle=90, font='Helvetica-Bold', halo=True)
    d.text((40.0, -80.0), 'AV. DEL CERRO', 2.4, font='Helvetica-Bold', halo=True)
    d.text((74.0, -60.0), 'RESERVA DE BOSQUE NATIVO', 2.4, font='Helvetica-Bold', halo=True)
    d.text((74.0, -66.0), 'bosque de lengas', 2.0, halo=True)
    d.text((-110.0, -30.0), 'PUEBLO', 2.4, font='Helvetica-Bold', halo=True)
    d.text((-110.0, -36.0), 'al muelle, 800 m', 2.0, halo=True)
    for i in range(4):
        for j in range(5):
            x, y = -150 + i * 22, -150 + j * 30
            if y + 24 > -94 and y < -68:
                continue
            d.poly(rect(x, y, x + 17, y + 24), 'xf', 'ENTORNO', fill=GRAY(0.95), z=0.3)
    d.text((0, 2.0), 'TORRE', 2.2, font='Helvetica-Bold', halo=True)
    d.text((0, -2.6), '18 niveles', 1.8, halo=True)
    # cotas del lote, retiros y distancia a la orilla
    d.chain([(lx0, ly0 - d.mm(10)), (lx1, ly0 - d.mm(10))], 0)
    d.chain([(lx1 + d.mm(10), ly0), (lx1 + d.mm(10), ly1)], 0)
    d.chain([(lx0, ly1 - 4.0), (B.POD[0], ly1 - 4.0), (B.POD[2], ly1 - 4.0), (lx1, ly1 - 4.0)], 0)
    d.chain([(lx0 - d.mm(10), B.POD[3]), (lx0 - d.mm(10), 16.0), (lx0 - d.mm(10), ly1), (lx0 - d.mm(10), PROMENADE[1]),
             (lx0 - d.mm(10), SHORE_Y)], 0)
    d.dim((30.0, 13.0), (30.0, SHORE_Y), 0, text='40,00 a la orilla')
    d.north((85.0, 70.0), 0, 18)
    frame = (DA[0], DA[1] + 24, 400, DA[3] - 26)
    render(c, d, frame, (0.0, -15.0))
    caption(c, DA[0] + 8, DA[1] + 14, 1, 'IMPLANTACIÓN', 'Esc. 1:500', 'lote 90,00 x 106,00 m frente al paseo costero')
    m = Dwg(5000)
    town_map(m)
    render(c, m, (DA[0] + 408, DA[1] + DA[3] - 200, 215, 196), (0, 0))
    caption(c, DA[0] + 412, DA[1] + DA[3] - 206, 2, 'PLANO DE UBICACIÓN', 'Esc. 1:5000 (esquema)', 'Puerto Ilén')
    tx, ty = DA[0] + 412, DA[1] + DA[3] - 226
    txt(c, tx, ty, 'Indicadores urbanísticos', 3.2, 'Helvetica-Bold')
    pod_a = (B.POD[2] - B.POD[0]) * (B.POD[3] - B.POD[1])
    lot_a = (lx1 - lx0) * (ly1 - ly0)
    tower = 16 * (2 * B.O) ** 2
    tot = 2 * pod_a + tower
    rows = [['Superficie del terreno', f'{fnum(lot_a)} m²', ''],
            ['FOS (ocupación del suelo)', fnum(pod_a / lot_a, 2), 'máx. 0,30'],
            ['FOT (ocupación total)', fnum(tot / lot_a, 2), 'máx. 1,50'],
            ['Altura máxima', f'{fnum(B.TOP)} m', 'máx. 66,00 m'],
            ['Retiro costanero', '20,50 m', 'mín. 20,00 m'],
            ['Retiros laterales', '21,90 m', 'mín. 6,00 m'],
            ['Distancia de la torre a la orilla', f'{fnum(SHORE_Y - B.A)} m', ''],
            ['Cocheras', '52', '1 por unidad + 3'],
            ['Unidades funcionales', str(sum(len(f['units']) for f in S['floors'])), '']]
    ty = table(c, tx, ty - 3, [92, 52, 60], rows, head=['Indicador', 'Proyecto', 'Norma (distrito costero R3)'],
               size=2.2, rowh=5.0, aligns=['l', 'r', 'r'])
    txt(c, tx, ty - 4, 'Código de planeamiento de Puerto Ilén: ficticio, como la locación.', 1.9, color=GRAY(0.3))
    return {'A-100_implantacion': d}


# ===================================================================== verificaciones contra las fuentes
def verify(S, D):
    """Controles cruzados: superficies y cantidades contra js/data.js; tipo L2 contra tools/depto.py."""
    out = []
    T = S['types']
    cnt = {}
    for f in S['floors']:
        for u in f['units']:
            cnt[u['type']] = cnt.get(u['type'], 0) + 1
    for k, t in T.items():
        rooms = t['plan']
        cov = [r for r in rooms if r[5] != 'balcony']
        W = max(r[1] + r[3] for r in cov)
        Dp = max(r[2] + r[4] for r in cov)
        tiles = abs(sum(r[3] * r[4] for r in cov) - W * Dp) < 1e-6
        out.append(f"{k}: {cnt.get(k, 0)} unidades; cubierta {fnum(t['covered_exact'])} m² ({t['covered']} en el sitio); "
                   f"{rooms[0][0].lower()} {fnum(t['open_exact'])} m² ({t['open']}); ambientes cubren {fnum(W)} x {fnum(Dp)}: "
                   f"{'sí' if tiles else 'NO'}")
    out.append(f"Total: {sum(cnt.values())} unidades en {len([f for f in S['floors'] if f['units']])} pisos")
    # L2 contra depto.py: cada tabique del modelo coincide con un borde de ambiente de plan.js (y invertida)
    t = T['L2']
    edges_x = {round(r[1], 3) for r in t['plan'] if r[5] != 'balcony'} | {round(r[1] + r[3], 3) for r in t['plan'] if r[5] != 'balcony'}
    edges_y = {round(r[2], 3) for r in t['plan'] if r[5] != 'balcony'} | {round(r[2] + r[4], 3) for r in t['plan'] if r[5] != 'balcony'}
    bad = []
    for cl in dcalls(D, 'wall'):
        nm, (ax, ay), (bx, by) = cl['args'][0], cl['args'][1], cl['args'][2]
        if abs(ay - by) < 1e-9:
            if round(-ay, 3) not in edges_y:
                bad.append(nm)
        elif round(ax, 3) not in edges_x:
            bad.append(nm)
    out.append('L2 vs tools/depto.py: ' + ('todos los muros coinciden con los ambientes de js/data.js'
                                         if not bad else 'muros sin correspondencia: ' + ', '.join(bad)))
    beds = dcalls(D, 'bed')
    behind = [c_ for c_ in beds if (c_['args'][2] if len(c_['args']) > 2 else 0) == 0 and c_['args'][1] - 2.1 < -10.0]
    if behind:
        out.append(f'Aviso: {len(behind)} camas de tools/depto.py quedan detrás del muro del fondo (y < -10); se dibujan giradas 180°.')
    return out


def zone_title(S, zone):
    fl = S['zone_floors'][zone]
    return f"PISOS {fl[0]} A {fl[-1]} · {S['zones'][zone]['name'].upper()}" if len(fl) > 1 else f"PISO {fl[0]} · {S['zones'][zone]['name'].upper()}"


def sh_A103(X, c):
    S = X.S
    out = {}
    fw = DA[2] / 3
    top = DA[1] + DA[3]
    for i, zone in enumerate(('bosque', 'lago', 'cumbre')):
        n0 = S['zone_floors'][zone][0]
        d = Dwg(200)
        draw_plate(d, S, zone, n0)
        d.north((B.A + 4.6, B.A + 5.0), -B.ROT[n0], 11)
        frame = (DA[0] + i * fw, top - 214, fw, 210)
        render(c, d, frame, (0, 0.8))
        fl = S['zone_floors'][zone]
        rots = f"giro {fnum(B.ROT[fl[0]], 0)}° a {fnum(B.ROT[fl[-1]], 0)}° respecto del piso 3 (dibujado: piso {n0})"
        caption(c, frame[0] + 8, frame[1] - 6, i + 1, zone_title(S, zone), 'Esc. 1:200', rots)
        out[f'A-103_planta_{zone}'] = d
    # regla de giro
    d = Dwg(200)
    for n in range(3, 19):
        pts = [rot(p, -B.ROT[n]) for p in rounded_square(B.A, B.R_SLAB, 6)]
        heavy = n in (3, 9, 15, 18)
        d.poly(pts, 'md' if heavy else 'hr', 'LOSAS', color=BLACK if heavy else GRAY(0.45), z=1)
    d.geom(Point(0, 0).buffer(B.R_PAL, 64), 'fn', 'MUROS', dash='dash', z=1.5)
    d.geom(Point(0, 0).buffer(math.hypot(B.CORE, B.CORE), 64), 'xf', 'MUROS', dash='dot', z=1.5)
    d.geom(core_parts(), 'fn', 'MUROS', fill=GRAY(0.15), z=2)
    for n in (3, 9, 15, 18):
        q = rot((0, B.A + 1.9), -B.ROT[n])
        d.text(q, f'piso {n}', 2.4, font='Helvetica-Bold', halo=True)
    d.text((0, -B.R_PAL - 0.8), f'palier Ø {fnum(2 * B.R_PAL)}', 2.0, halo=True)
    d.north((-B.A - 2, B.A + 4), 0, 12)
    yb = DA[1] + 18
    render(c, d, (DA[0], yb, 205, 315), (0, 0), clip=False)
    caption(c, DA[0] + 8, yb - 4, 4, 'REGLA DE GIRO · LOSAS DE LOS PISOS 3 A 18', 'Esc. 1:200', 'núcleo fijo, planta girada')
    tx = DA[0] + 214
    ty = yb + 298
    txt(c, tx, ty, 'Cómo gira la torre', 3.6, 'Helvetica-Bold')
    ty -= 7
    lines = [
        f"Cada planta desde el piso 3 gira {fnum(B.TW, 0)}° en sentido horario (visto desde arriba) respecto de la planta "
        f"inferior: el piso n gira (n - 3) x {fnum(B.TW, 0)}°. El piso 3 tiene giro 0° y el piso 18, {fnum(B.ROT[18], 0)}°.",
        "Giran juntas la losa, el cerramiento, las columnas y las unidades. Por eso cada tipología es igual en todos los pisos "
        "de su zona y solo cambia hacia dónde mira (orientación de cada unidad en A-106).",
        f"El núcleo (ascensores, escalera presurizada y montantes) es vertical y no gira. Se aloja en un palier circular de "
        f"Ø {fnum(2 * B.R_PAL)} m: el núcleo de {fnum(2 * B.CORE)} x {fnum(2 * B.CORE)} m (diagonal {fnum(2 * math.hypot(B.CORE, B.CORE))} m) "
        f"deja siempre al menos {fnum(B.CLEAR)} m de paso, con cualquier giro.",
        "Las ocho columnas de la torre van en los plenos entre unidades y acompañan el giro: son inclinadas y en cada nivel "
        "ocupan el mismo lugar de la planta (ver cortes A-301 y A-302).",
        "Las plantas 1 a 3 se dibujan en su propio marco (unidades fijas en el papel); la flecha de norte y el "
        "núcleo están girados según el piso indicado en cada título.",
    ]
    for ln in lines:
        ty = para(c, tx, ty, ln, 2.4, 160) - 2.4
    rows = []
    for n in range(3, 19):
        f = next(x for x in S['floors'] if x['n'] == n)
        rows.append([str(n), S['zones'][f['zone']]['name'], flevel(B.NPT[n]), fnum(f['rot'], 0) + '°',
                     bearing_info(S, f['rot'])[0], '  '.join(u['id'] + ' ' + u['type'] for u in f['units'])])
    table(c, DA[0] + 384, yb + 302, [10, 21, 17, 12, 21, 154], rows,
          head=['Piso', 'Zona', 'NPT', 'Giro', 'Frente', 'Unidades y tipologías (ver orientaciones en A-106)'],
          size=2.1, rowh=5.2, aligns=['c', 'l', 'r', 'r', 'l', 'l'])
    return out


def sh_A104(X, c):
    S = X.S
    d = Dwg(100)
    draw_plate(d, S, 'ph', 18)
    d.north((B.A + 3.5, B.A + 8.0), -B.ROT[18], 16)
    frame = (DA[0] + 4, DA[1] + 16, 420, DA[3] - 22)
    render(c, d, frame, (0, 0.5))
    caption(c, frame[0] + 4, DA[1] + 10, 1, 'PLANTA PISO 18 · PENTHOUSE (UNIDAD 18A)', 'Esc. 1:100',
            f"giro {fnum(B.ROT[18], 0)}° · NPT {flevel(B.NPT[18])}")
    t = S['types']['PH']
    tx, ty = frame[0] + frame[2] + 8, DA[1] + DA[3] - 8
    txt(c, tx, ty, 'Penthouse 18A', 4.2, 'Helvetica-Bold')
    ty -= 6
    ty = para(c, tx, ty, f"{t['name']}: {t['rooms_txt']}. Única unidad del piso; el palier circular funciona como hall "
              "privado y los ascensores llegan directo a él.", 2.4, 180) - 3
    rows = [[r[0], f"{fnum(r[3])} x {fnum(r[4])}", fnum(r[3] * r[4])] for r in t['plan']]
    ty = table(c, tx, ty, [70, 50, 40], rows, head=['Local', 'Medidas (m)', 'Sup. (m²)'], size=2.2, rowh=5.0,
               aligns=['l', 'c', 'r'])
    ty = table(c, tx, ty - 4, [120, 40], [['Superficie cubierta propia', f"{fnum(t['covered_exact'])}"],
                                         ['Terraza', f"{fnum(t['open_exact'])}"],
                                         ['Total', f"{fnum(t['covered_exact'] + t['open_exact'])}"]],
               size=2.4, rowh=5.4, aligns=['l', 'r'], bold_last=True)
    para(c, tx, ty - 6, 'La distribución interior completa, con amoblamiento y planilla de locales, está en la lámina A-406.',
         2.3, 160)
    return {'A-104_planta_piso18': d}


def sh_A000(X, c):
    S = X.S
    x0, y0, w, h = DA
    top = y0 + h
    txt(c, x0 + 6, top - 26, PROJECT, 30.0, 'Helvetica-Bold')
    txt(c, x0 + 7, top - 38, PROJECT_SUB, 8.0)
    txt(c, x0 + 7, top - 47, f'{PROJECT_KIND} · {sum(len(f["units"]) for f in S["floors"])} unidades · club en basamento', 3.6)
    txt(c, x0 + 7, top - 54, ADDRESS, 3.0)
    txt(c, x0 + 7, top - 62, f'LEGAJO DE PLANOS · REVISIÓN {REV} · {REV_DATE}', 3.4, 'Helvetica-Bold')
    # imagen del proyecto
    try:
        from PIL import Image
        import io
        src = ROOT / 'img' / 'torre.webp'
        if not src.exists():
            src = ROOT / 'img' / 'originales' / 'torre-16x9.jpg'
        im = Image.open(src).convert('RGB')
        im.thumbnail((1700, 1000))
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=80, optimize=True)
        buf.seek(0)
        iw = 380.0
        ih = iw * im.height / im.width
        c.drawImage(ImageReader(buf), x0 + 6, top - 72 - ih, iw, ih)
        c.setLineWidth(0.35)
        c.rect(x0 + 6, top - 72 - ih, iw, ih, stroke=1, fill=0)
        txt(c, x0 + 6, top - 76 - ih, 'Imagen ilustrativa del proyecto (render). Vista desde el lago Ilén, al atardecer.', 2.2,
            color=GRAY(0.3))
        img_bottom = top - 80 - ih
    except Exception as e:  # sin Pillow la carátula sale sin imagen
        print('  ! carátula sin imagen:', e, file=sys.stderr)
        img_bottom = top - 80
    # índice de planos
    tx = x0 + 400
    txt(c, tx, top - 8, 'Índice de planos', 3.6, 'Helvetica-Bold')
    rows = [[code, title, scale, REV] for code, title, scale, notes, fn in SHEETS]
    ty = table(c, tx, top - 12, [18, 160 - 18 + 6, 22, 11], rows, head=['Lámina', 'Título', 'Escala', 'Rev.'],
               size=2.25, rowh=5.2, aligns=['l', 'l', 'c', 'c'])
    # superficies por tipología
    T = S['types']
    cnt = {}
    for f in S['floors']:
        for u in f['units']:
            cnt[u['type']] = cnt.get(u['type'], 0) + 1
    rows = []
    tc = to = tu = 0
    for k in ('B1', 'B2', 'L2', 'L3', 'C3', 'PH'):
        t = T[k]
        n = cnt.get(k, 0)
        rows.append([k, t['rooms_txt'], str(n), str(t['covered']), str(t['open']), str(t['covered'] + t['open']),
                     fnum(n * t['covered'], 0), fnum(n * t['open'], 0)])
        tc += n * t['covered']
        to += n * t['open']
        tu += n
    rows.append(['Total', '', str(tu), '', '', '', fnum(tc, 0), fnum(to, 0)])
    txt(c, tx, ty - 9, 'Unidades por tipología (m²)', 3.2, 'Helvetica-Bold')
    ty = table(c, tx, ty - 13, [12, 70, 12, 17, 17, 17, 22, 20], rows,
               head=['Tipo', 'Programa', 'Cant.', 'Cub.', 'Desc.', 'Total', 'Σ cub.', 'Σ desc.'],
               size=2.2, rowh=5.0, aligns=['c', 'l', 'c', 'r', 'r', 'r', 'r', 'r'], bold_last=True)
    # datos del proyecto
    lx0, ly0, lx1, ly1 = LOT
    pod_a = (B.POD[2] - B.POD[0]) * (B.POD[3] - B.POD[1])
    tower = 16 * (2 * B.O) ** 2
    data = [['Comitente', CLIENT], ['Proyecto y dirección', f'{STUDIO.title()} · proyecto N° {PROJ_NO}'],
            ['Ubicación', 'Av. Costanera del Ilén s/n°, Puerto Ilén'], ['Nomenclatura catastral', CATASTRO],
            ['Terreno', f'{fnum((lx1 - lx0) * (ly1 - ly0))} m² (90,00 x 106,00 m)'],
            ['Superficie cubierta total', f'{fnum(2 * pod_a + tower, 0)} m² (basamento {fnum(2 * pod_a, 0)} + torre {fnum(tower, 0)})'],
            ['Niveles', 'planta baja + 17 pisos (club en niveles 1 y 2) + azotea'],
            ['Altura', f'{fnum(B.ROOF)} m a azotea; {fnum(B.TOP)} m a sala de tanques'],
            ['Giro de plantas', f'{fnum(B.TW, 0)}° por piso desde el piso 3 (piso 18: {fnum(B.ROT[18], 0)}°)'],
            ['Cocheras', '52 semicubiertas'], ['Estructura', 'H°A°: núcleo fijo, columnas inclinadas, losas postesadas']]
    txt(c, x0 + 6, img_bottom - 6, 'Datos del proyecto', 3.6, 'Helvetica-Bold')
    table(c, x0 + 6, img_bottom - 10, [56, 160], data, size=2.3, rowh=5.2)
    tx2 = x0 + 232
    txt(c, tx2, img_bottom - 6, 'Convenciones', 3.6, 'Helvetica-Bold')
    yy = img_bottom - 14
    conv = [('ha', 'Hormigón armado cortado'), ('mamp', 'Mampostería / muro cortado'), ('tab', 'Tabique interior (placa o ladrillo 12)'),
            ('glass', 'Carpintería vidriada'), ('axis', 'Eje estructural'), ('hidden', 'Proyección / oculto')]
    for k, lbl in conv:
        if k == 'ha':
            c.setFillColorRGB(0.12, 0.12, 0.12)
            c.rect(tx2, yy - 1.2, 14, 3.6, stroke=1, fill=1)
        elif k == 'mamp':
            c.setLineWidth(0.35)
            c.rect(tx2, yy - 1.2, 14, 3.6, stroke=1, fill=0)
            c.saveState()
            pa = c.beginPath()
            pa.rect(tx2, yy - 1.2, 14, 3.6)
            c.clipPath(pa, stroke=0, fill=0)
            c.setLineWidth(0.09)
            for i in range(-4, 20):
                c.line(tx2 + i * 0.9, yy - 1.2, tx2 + i * 0.9 + 3.6, yy + 2.4)
            c.restoreState()
        elif k == 'tab':
            c.setFillColorRGB(0.62, 0.62, 0.62)
            c.setLineWidth(0.25)
            c.rect(tx2, yy - 0.3, 14, 1.8, stroke=1, fill=1)
        elif k == 'glass':
            c.setLineWidth(0.18)
            c.rect(tx2, yy - 0.0, 14, 1.2, stroke=1, fill=0)
            c.line(tx2, yy + 0.6, tx2 + 14, yy + 0.6)
        else:
            c.setLineWidth(0.25)
            c.setDash(list(DASH[k]), 0)
            c.line(tx2, yy + 0.6, tx2 + 14, yy + 0.6)
            c.setDash([], 0)
        txt(c, tx2 + 18, yy, lbl, 2.3)
        yy -= 6.2
    txt(c, tx2, yy - 3, 'Escalas: 1:500 · 1:200 · 1:100 · 1:50. Cotas en metros.', 2.3)
    txt(c, tx2, yy - 8, 'Niveles: ±0,00 = 771,50 m s.n.m.', 2.3)
    # vista norte reducida y memoria
    e = Dwg(500)
    pu0, pu1 = elevation(e, S, 'N')
    render(c, e, (tx, y0 + 216, 110, ty - 22 - (y0 + 216)), ((pu0 + pu1) / 2, B.TOP / 2), clip=False)
    txt(c, tx + 55, y0 + 210, 'Vista norte · esc. 1:500', 2.2, align='c')
    mx = tx + 116
    my = ty - 18
    txt(c, mx, my, 'Memoria (síntesis)', 3.6, 'Helvetica-Bold')
    my -= 7
    for ln in [
        'Torre de 18 niveles sobre el paseo costero del lago Ilén. Un basamento de dos niveles aloja el club '
        '(lobby, fogón, pileta climatizada, spa y gimnasio) y sobre él se apilan 16 plantas de viviendas.',
        f'Cada planta gira {fnum(B.TW, 0)}° respecto de la inferior. El giro reparte las vistas: el piso 3 mira al norte '
        f'y el piso 18, {fnum(B.ROT[18], 0)}° más al este. El núcleo de ascensores y escalera es fijo y se aloja en un '
        'palier circular.',
        'Zonas: Bosque (pisos 3 a 8, cuatro unidades), Lago (9 a 14, tres), Cumbre (15 a 17, dos) y Penthouse (18).',
        'Estructura de hormigón armado con columnas inclinadas en los plenos entre unidades; cerramiento de piso a '
        'techo con carpintería de aluminio y DVH; balcón corrido con baranda de vidrio.',
    ]:
        my = para(c, mx, my, ln, 2.35, 104) - 2.2
    para(c, x0 + 6, y0 + 8, FICTION + ' Las superficies y la numeración de unidades coinciden con la ficha comercial '
         'del proyecto.', 2.2, 380, color=GRAY(0.3))
    return {}


SHEETS = [
    ('A-000', 'Carátula e índice de planos', 'S/E', [], sh_A000),
    ('A-100', 'Implantación y plano de ubicación', '1:500 / 1:5000', ['Lote sobre el paseo costero público; la torre queda a 40 m de la línea de ribera.'], sh_A100),
    ('A-101', 'Planta baja (nivel 1) y obras exteriores', '1:200', ['Cocheras: 52 (49 unidades y 3 de cortesía), 2,50 x 5,00 m bajo pérgola de acero y madera de lenga.'], sh_A101),
    ('A-102', 'Planta primer piso (nivel 2): club', '1:100', ['Superficies de locales medidas a ejes de muros.'], sh_A102),
    ('A-103', 'Plantas tipo: pisos 3 a 17 (Bosque, Lago y Cumbre)', '1:200',
     ['Envolventes de unidades funcionales según la subdivisión comercial. La distribución interior de cada '
      'tipología se desarrolla en las láminas A-401 a A-406.'], sh_A103),
    ('A-104', 'Planta piso 18: penthouse', '1:100', ['Envolvente de la unidad funcional; distribución interior en A-406.'], sh_A104),
    ('A-105', 'Planta de techos', '1:100', ['Cubierta verde extensiva del basamento: no transitable, acceso solo para mantenimiento.'], sh_A105),
    ('A-106', 'Esquema de giro de plantas y orientación de unidades', '1:200 / 1:500', ['Rumbos y vistas: rumbo local de la unidad + giro acumulado del piso.'], sh_A106),
    ('A-201', 'Vistas Norte y Este', '1:200', ['Losas de H°A° con canto revestido en GRC blanco. Barandas de vidrio laminado 5+5 h 1,05 m.', 'Carpintería de aluminio con RPT y DVH 6/12/6 de piso a techo; paños ciegos en los ejes (columnas).'], sh_A201),
    ('A-202', 'Vistas Sur y Oeste', '1:200', ['Losas de H°A° con canto revestido en GRC blanco. Barandas de vidrio laminado 5+5 h 1,05 m.', 'Basamento: muro cortina con parantes cada 2,53 m; tramos ciegos revestidos en piedra local.'], sh_A202),
    ('A-301', 'Corte A-A', '1:200', ['Piso a piso típico 3,30 m = losa 0,30 + contrapiso y solado 0,10 + pleno de cielorraso 0,15 + altura libre 2,75.'], sh_A301),
    ('A-302', 'Corte B-B', '1:200', ['Escalera presurizada: alzada 0,165 m, huella 0,28 m (2a + h = 0,61). En el basamento resuelve cada piso con dos vueltas.'], sh_A302),
    ('A-401', 'Tipología B1: 2 dormitorios', '1:50', TYPE_NOTES['B1'], mk_unit_sheet('B1')),
    ('A-402', 'Tipología B2: 2 dormitorios y estudio', '1:50', TYPE_NOTES['B2'], mk_unit_sheet('B2')),
    ('A-403', 'Tipología L2: 2 suites', '1:50', TYPE_NOTES['L2'], mk_unit_sheet('L2')),
    ('A-404', 'Tipología L3: 3 dormitorios', '1:50', TYPE_NOTES['L3'], mk_unit_sheet('L3')),
    ('A-405', 'Tipología C3: 3 dormitorios y estudio', '1:50', TYPE_NOTES['C3'], mk_unit_sheet('C3')),
    ('A-406', 'Tipología PH: penthouse', '1:50', TYPE_NOTES['PH'], mk_unit_sheet('PH')),
    ('A-501', 'Departamento modelo L2 (recorrido 360°)', '1:50 · 1:100 · 1:25',
     ['Unidad amoblada para el recorrido virtual: muros, aberturas, equipamiento, luminarias y puntos de vista.',
      'Camas con la cabecera contra el muro del fondo; banco al pie de la cama principal.'], sh_A501),
]


def build(only=None, png=None, png_dir=None):
    S = load_site()
    D = load_depto()
    setup(S, D)
    X = Ctx()
    X.S, X.D = S, D
    (OUT / 'pdf').mkdir(parents=True, exist_ok=True)
    (OUT / 'dxf').mkdir(parents=True, exist_ok=True)
    total = len(SHEETS)
    pdfs, dxfs = [], []
    for idx, (code, title, scale, notes, fn) in enumerate(SHEETS, 1):
        if only and code not in only:
            continue
        sh = Sheet(code, title, scale, notes)
        X.sheet = sh
        X.idx = idx
        path = OUT / 'pdf' / f'{code}.pdf'
        c = rl_canvas.Canvas(str(path), pagesize=(PAGE[0] * MM, PAGE[1] * MM), pageCompression=1)
        c.setTitle(f'{PROJECT} · {code} {title}')
        c.setAuthor(STUDIO + ' (ficticio)')
        c.setSubject(f'{PROJECT} - {PROJECT_SUB}. Proyecto {PROJ_NO}. {FICTION}')
        c.setCreator('planos/fuente/generar.py')
        c.scale(MM, MM)
        drawings = fn(X, c) or {}
        sh.frame(c, idx, total)
        c.showPage()
        c.save()
        pdfs.append(path)
        for name, d in drawings.items():
            dp = OUT / 'dxf' / f'{name}.dxf'
            if write_dxf(d, str(dp), f'{PROJECT} {name}'):
                dxfs.append(dp)
        print(f'{code}  {title}')
        if png:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(path))
            img = pdf[0].render(scale=png / 72.0).to_pil()
            img.save(pathlib.Path(png_dir) / f'{code}.png')
            pdf.close()
    for ln in verify(S, D):
        print('  control:', ln)
    if not only:
        from pypdf import PdfWriter, PdfReader
        wr = PdfWriter()
        for (code, title, scale, notes, fn), pth in zip(SHEETS, pdfs):
            rd = PdfReader(str(pth))
            wr.add_page(rd.pages[0])
            wr.add_outline_item(f'{code}  {title}', len(wr.pages) - 1)
        wr.add_metadata({'/Title': f'{PROJECT} - {PROJECT_SUB}: legajo de planos (Rev. {REV})',
                         '/Author': STUDIO + ' (ficticio)', '/Subject': FICTION, '/Creator': 'planos/fuente/generar.py'})
        wr.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        with open(OUT / f'{PROJECT.capitalize()} - Legajo de planos.pdf', 'wb') as fh:
            wr.write(fh)
        print('PDF combinado:', OUT / f'{PROJECT.capitalize()} - Legajo de planos.pdf')
    return pdfs, dxfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--png', help='carpeta para vistas previas PNG')
    ap.add_argument('--dpi', type=int, default=110)
    ap.add_argument('--only', nargs='*')
    a = ap.parse_args()
    if a.png:
        pathlib.Path(a.png).mkdir(parents=True, exist_ok=True)
    build(a.only, a.dpi if a.png else None, a.png)


if __name__ == '__main__':
    main()
