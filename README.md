# Lenga — Residencias sobre el lago Ilén

Sitio conceptual de un desarrollo inmobiliario (locación y marca ficticias), hecho para portfolio.

- **Inicio por scroll:** la cámara baja sobre un mapa topográfico 3D del lago y la torre se arma piso a piso (Three.js).
- **Final por scroll: el edificio.** Render fotorrealista con zonas calibradas por piso, ascensor para elegir altura y el piso elegido "saliendo" de la fachada.
- **Planta del piso** que gira según la rotación de cada planta, con unidades por estado.
- **Ficha de unidad** con plano de arquitecto (SVG generado desde los datos) y render 3D de la tipología.
- **Recorrido en primera persona** por ambientes, con mini plano de ubicación.

## Correrlo

Es estático, sin build. Cualquier servidor local sirve:

```bash
python -m http.server 5173
```

y abrir http://localhost:5173.

## Estructura

- `js/data.js` pisos, tipologías y unidades
- `js/scene.js` escena 3D del inicio
- `js/building.js` edificio, planta y ficha
- `js/tour.js` recorrido interior
- `js/plan.js` dibujo de planos y plantas
- `js/zones.js` contorno de cada piso sobre el render (generado con `tools/track.py` + `tools/fit.py`)
- `shots.html` vistas limpias que se usaron como referencia para generar los renders

Si se cambia `img/torre.webp`, hay que regenerar `js/zones.js` con los scripts de `tools/`.

## Créditos

Renders del edificio, tipologías e interiores generados con ChatGPT a partir de la maqueta y los planos del proyecto. Librerías: Three.js, GSAP + ScrollTrigger, Lenis.
