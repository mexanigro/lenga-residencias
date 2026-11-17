# Lenga — Residencias sobre el lago Ilén

Sitio conceptual de un desarrollo inmobiliario (locación y marca ficticias), hecho para portfolio.

- **Carga:** placeholder borroso embebido del primer cuadro del vuelo y progreso real de los cuadros necesarios para empezar.
- **Inicio por scroll: una sola toma.** Un vuelo de dron continuo desde lo alto del lago hasta la torre (240 cuadros dibujados en un canvas, con fundido entre cuadros vecinos). No hay cambios de escena: el último cuadro es la misma foto en la que se calibraron los pisos.
- **Final del scroll: el edificio.** Cada piso se puede tocar sobre la foto o con el ascensor.
- **Planta del piso:** render cenital de cada planta, girado según la rotación del piso, con las unidades por estado.
- **Ficha de unidad:** maqueta 3D de la tipología con puntos por ambiente y plano de arquitecto (SVG generado desde los datos).
- **Recorrido interior en 360°:** el departamento modelo (tipo L2) armado en 3D y renderizado con luz física. Cada ambiente es un panorama real; al tocar un punto de paso, la vista gira hacia la puerta y se reproduce el trayecto caminando hasta el otro ambiente, que empieza y termina en el mismo encuadre que los panoramas.
- Navegación por niveles con URL propia (`#/piso/10/10C/living`), migas, Escape para subir y botón atrás del navegador.

## Correrlo

Es estático, sin build:

```bash
python -m http.server 5173
```

y abrir http://localhost:5173.

## Estructura

- `js/main.js` carga, scroll (Lenis) y textos del recorrido
- `js/flight.js` vuelo por scroll (secuencia de cuadros en canvas)
- `js/building.js` edificio, ascensor, planta, ficha y router de niveles
- `js/pano.js` visor 360° y trayectos entre ambientes (Three.js, se carga solo al entrar a un ambiente)
- `js/depto.js` ambientes, puntos de paso y trayectos del departamento modelo (generado por `tools/depto.py`)
- `js/plan.js` dibujo de planos; `js/data.js` pisos, tipologías y unidades
- `js/zones.js` contorno de cada piso sobre la foto final (generado por `tools/zonas.py`)
- `js/assets.js` cajas de las plantas y placeholder del loader (generado por `tools/assets.py`)

### Herramientas

- `tools/vuelo.py` arma el vuelo a partir de los clips de video (los reparte por cantidad de movimiento para que el scroll avance parejo)
- `tools/zonas.py` detecta las losas en la foto final y genera los polígonos de cada piso
- `tools/depto.py` arma el departamento en Blender 4.5 (`blender -b --factory-startup -P tools/depto.py -- --pano all --move all`)
- `tools/polyhaven.py` baja las texturas y modelos CC0 que usa el departamento (fuera del repo, en `%LOCALAPPDATA%/lenga3d`)
- `tools/assets.py` convierte originales y renders a los `.webp`/`.mp4` del sitio

Los originales (`img/originales/`) y los renders crudos (`3d/out/`) no se versionan.

## Créditos

Vuelo y fotos de la torre generados con Google Flow (Veo y Omni) a partir del render del proyecto. Departamento modelado y renderizado en Blender con texturas y modelos CC0 de Poly Haven. Plantas y maquetas generadas con ChatGPT. Librerías: Three.js y Lenis.
