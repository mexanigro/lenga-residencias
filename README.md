# Lenga — Residencias sobre el lago Ilén

Sitio conceptual de un desarrollo inmobiliario (locación y marca ficticias), hecho para portfolio.

- **Carga:** placeholder borroso embebido del primer cuadro del vuelo y progreso real de los cuadros necesarios para empezar.
- **Inicio por scroll: vuelo y obra.** Un vuelo de dron continuo desde lo alto del lago hasta el lote vacío (168 cuadros en 1080p dibujados en un canvas). Al llegar, la torre se construye con el scroll sobre la misma toma: hormigonado del basamento, la estructura piso por piso con la grúa, el cerramiento y el edificio terminado. Las cuatro etapas de obra son fotos alineadas al píxel con la final, así que no hay cortes de escena.
- **Final del scroll: el edificio.** La última etapa es la misma foto en la que se calibraron los pisos: cada piso se puede tocar sobre la foto o con el ascensor.
- **Planta del piso:** render cenital de cada planta, girado según la rotación del piso, con las unidades por estado.
- **Ficha de unidad:** maqueta 3D de la tipología con puntos por ambiente y plano de arquitecto (SVG generado desde los datos).
- **Recorrido interior en 3D, en tiempo real:** el departamento modelo (tipo L2) armado en Blender con la luz de Cycles horneada en texturas, así se ve igual que un render desde cualquier punto. Se camina libre como en un juego (W A S D o flechas, arrastrar para mirar), tocando el piso (camina hasta ahí esquivando paredes y muebles) o eligiendo un ambiente (camina hasta él pasando por las puertas). El mini mapa sigue la posición y la mirada.
- Navegación por niveles con URL propia (`#/piso/10/10C/living`), migas, Escape para subir y botón atrás del navegador.

## Correrlo

Es estático, sin build:

```bash
python -m http.server 5173
```

y abrir http://localhost:5173.

## Estructura

- `js/main.js` carga, scroll (Lenis) y textos del recorrido
- `js/flight.js` vuelo por scroll (secuencia de cuadros en canvas) y obra piso por piso (etapas recortadas con los contornos de `js/zones.js`)
- `js/building.js` edificio, ascensor, planta, ficha y router de niveles
- `js/pano.js` recorrido 3D: caminar, colisiones y caminos entre ambientes (Three.js, se carga solo al entrar)
- `js/depto3d.js` zonas, ambientes y cajas de colisión del modelo horneado (generado por `tools/hornear.py`)
- `js/depto.js` ambientes del departamento modelo para el mini mapa (generado por `tools/depto.py`)
- `js/plan.js` dibujo de planos; `js/data.js` pisos, tipologías y unidades
- `js/zones.js` contorno de cada piso sobre la foto final (generado por `tools/zonas.py`)
- `js/assets.js` cajas de las plantas y placeholder del loader (generado por `tools/assets.py`)
- `js/vendor/` Three.js 0.170 (con GLTFLoader) y Lenis 1.1.20, alojados en el repo para no depender de un CDN
- `planos/` legajo de planos de arquitectura del proyecto (19 láminas A1 en PDF y DXF, ver `planos/README.md`)

### Herramientas

- `tools/vuelo.py` arma el vuelo a partir del video de acercamiento (reparte los cuadros por cantidad de movimiento para que el scroll avance parejo)
- `tools/obra.py` prepara las etapas de obra (`img/obra/`): usa cada etapa solo donde difiere de la foto final y le iguala el color
- `tools/zonas.py` sigue cada losa sobre la foto final y genera los polígonos de cada piso (deja un control en `img/originales/zonas-control.jpg`)
- `tools/depto.py` arma el departamento en Blender 4.5
- `tools/hornear.py` hornea la luz del departamento en Cycles y exporta el modelo del recorrido (`blender -b --factory-startup -P tools/hornear.py --`; con `--zonas suite2` rehornea solo esa zona)
- `tools/polyhaven.py` baja las texturas y modelos CC0 que usa el departamento (fuera del repo, en `%LOCALAPPDATA%/lenga3d`)
- `tools/assets.py` convierte los originales a los `.webp` del sitio y arma `img/og.jpg`

Los originales (`img/originales/`) y los renders crudos (`3d/out/`) no se versionan.

## Créditos

Vuelo, fotos de la torre y etapas de obra generados con Google Flow (Veo 3.1 y Nano Banana) a partir del render del proyecto. Departamento modelado en Blender, con la luz horneada en Cycles, y texturas y modelos CC0 de Poly Haven. Plantas y maquetas generadas con ChatGPT. Librerías: Three.js y Lenis (en `js/vendor`).
