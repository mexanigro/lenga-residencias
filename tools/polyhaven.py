"""Baja texturas y modelos CC0 de Poly Haven a %LOCALAPPDATA%/lenga3d/assets (fuera del repo: rutas cortas).
Uso: python -I tools/polyhaven.py"""
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(os.environ.get('LENGA3D', pathlib.Path(os.environ.get('LOCALAPPDATA', '~')) / 'lenga3d')).expanduser() / 'assets'
UA = {'User-Agent': 'lenga-portfolio-build/1.0'}

TEXTURES = ['laminate_floor_02', 'white_oak_veneer', 'marble_01', 'long_white_tiles', 'wood_floor_deck',
            'poly_wool_herringbone', 'rough_linen', 'white_plaster_02', 'smooth_concrete_floor', 'terrazzo_tiles']
MODELS = ['mid_century_lounge_chair', 'modern_arm_chair_01', 'potted_plant_04', 'potted_plant_01', 'potted_plant_02',
          'outdoor_table_chair_set_01', 'decorative_book_set_01', 'ceramic_vase_02', 'ceramic_vase_03',
          'wooden_bowl_01', 'side_table_01', 'throw_pillows_01', 'standing_picture_frame_01', 'planter_box_01',
          'grass_medium_01', 'shrub_04',  # pasto y arbusto para las jardineras del balcón
          'folding_wooden_stool']  # banco de la ducha: la caja de roble no aguantaba la mirada
MAPS = ['Diffuse', 'Rough', 'nor_gl', 'arm']


def get(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        dest.write_bytes(r.read())


def files(asset):
    with urllib.request.urlopen(urllib.request.Request(f'https://api.polyhaven.com/files/{asset}', headers=UA)) as r:
        return json.load(r)


for t in TEXTURES:
    f = files(t)
    for m in MAPS:
        if m in f:
            get(f[m]['2k']['jpg']['url'], OUT / 'tex' / t / f'{m}.jpg')
    print('tex', t)

for m in MODELS:
    b = files(m)['blend']['2k']['blend']
    get(b['url'], OUT / 'models' / m / f'{m}.blend')
    for path, inc in b.get('include', {}).items():
        get(inc['url'], OUT / 'models' / m / path)
    print('model', m)
