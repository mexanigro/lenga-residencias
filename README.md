# Lenga — Residencias sobre el lago Ilén

Sitio conceptual de un desarrollo inmobiliario (locación y marca ficticias), hecho para portfolio.

- **Carga:** placeholder borroso embebido de la primera toma, contador real de las imágenes críticas y entrada orquestada.
- **Inicio por scroll, todo fotográfico:** dos tomas aéreas del lago con zoom hacia el lote, el lote vacío alineado al render y la torre que sube piso a piso recortando el render real.
- **Final por scroll: el edificio.** Render fotorrealista con zonas calibradas por piso y ascensor para elegir altura.
- **Planta del piso:** render cenital de cada planta, girado según la rotación del piso, con las unidades marcadas por estado.
- **Ficha de unidad:** maqueta 3D de la tipología con puntos por ambiente, y plano de arquitecto (SVG generado desde los datos).
- **Vistas 360°** de cada ambiente (living, cocina, balcón, dormitorios y baño), con saltos entre ambientes y mini plano con la dirección de la mirada.
- Navegación por niveles con URL propia (`#/piso/10/10C/living`), migas, Escape para subir y botón atrás del navegador.

## Correrlo

Es estático, sin build. Cualquier servidor local sirve:

```bash
python -m http.server 5173
```

y abrir http://localhost:5173.

## Estructura

- `js/main.js` carga, scroll (Lenis) y secuencia de tomas
- `js/building.js` edificio, ascensor, planta, ficha y router de niveles
- `js/pano.js` visor 360° (Three.js, se carga solo al entrar a un ambiente)
- `js/plan.js` dibujo de planos
- `js/data.js` pisos, tipologías y unidades
- `js/zones.js` contorno de cada piso sobre el render (generado con `tools/track.py` + `tools/fit.py`)
- `js/assets.js` cajas de las plantas y placeholder del loader (generado con `tools/assets.py`)
- `tools/assets.py` procesa los originales de `img/originales/` (no versionados) a los `.webp` del sitio: plantas con fondo transparente, panoramas con la costura fundida
- `tools/align.py` alinea la toma del lote al render de la torre
- `shots.html` vistas limpias que se usaron como referencia para generar los renders

Si se cambia `img/torre.webp`, hay que regenerar `js/zones.js` con los scripts de `tools/`.

## Créditos

Tomas aéreas, renders del edificio, plantas, tipologías y panoramas 360° generados con ChatGPT a partir de la maqueta y los planos del proyecto. Librerías: Three.js y Lenis.
