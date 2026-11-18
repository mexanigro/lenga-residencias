# Lenga · Legajo de planos

**Ilén Sur Arquitectos** · Proyecto N° 2026-014 · Revisión C · 28/09/2026
Comitente: Lenga Desarrollos S.A.

> Proyecto de portfolio: la locación (Puerto Ilén, lago Ilén), la marca, el comitente y el estudio son ficticios.

## Nota de envío

Equipo del sitio de Lenga:

Les mandamos el legajo de planos de Lenga en su revisión C, la emisión para comercialización. Son 19 láminas A1 apaisadas: implantación, basamento, plantas tipo, penthouse, techos, vistas, cortes, las seis tipologías a 1:50 y el departamento modelo L2. El modelo es el mismo que muestra el recorrido 360°.

La numeración de pisos y unidades, los programas y las superficies son los de la planilla de comercialización que nos pasaron:

- 49 unidades en total.
- 6.551 m² cubiertos propios y 1.540 m² de balcones, galerías y terraza.

La regla de giro es de 4° por piso desde el piso 3. El núcleo de ascensores y escalera no gira: queda fijo dentro de un palier circular de Ø 10,40 m.

Les pasamos cada lámina en PDF, el juego completo en un solo PDF con marcadores y los dibujos en DXF:

- Unidades en metros.
- Capas MUROS, ABERTURAS, COTAS, TEXTOS, EJES y MOBILIARIO, más LOSAS, ESTRUCTURA, SOLADOS, RAYADOS, ENTORNO y CIRCULACION.

Cotas en metros. Niveles referidos a ±0,00 = NPT de planta baja = 771,50 m s.n.m.

Saludos,
Ilén Sur Arquitectos

## Índice de láminas

| Lámina | Título | Escala | Contenido |
|---|---|---|---|
| A-000 | Carátula e índice de planos | S/E | Datos del proyecto, índice, unidades por tipología, convenciones, vista norte reducida y memoria. |
| A-100 | Implantación y plano de ubicación | 1:500 / 1:5000 | Lote de 90 x 106 m sobre el paseo costero, retiros, 40 m a la orilla, indicadores urbanísticos. |
| A-101 | Planta baja (nivel 1) y obras exteriores | 1:200 | Lobby, fogón, SUM, servicios, plaza de acceso, terraza al lago y 52 cocheras bajo pérgola. |
| A-102 | Planta primer piso (nivel 2): club | 1:100 | Natatorio con pileta de 12,50 x 5,00 m, spa, vestuarios, gimnasio, cowork y planilla de locales. |
| A-103 | Plantas tipo: pisos 3 a 17 | 1:200 | Plantas Bosque, Lago y Cumbre con unidades, núcleo, plenos y columnas; regla de giro y tabla por piso. |
| A-104 | Planta piso 18: penthouse | 1:100 | Unidad 18A con hall privado en el palier y planilla de superficies. |
| A-105 | Planta de techos | 1:100 | Cubierta verde del basamento, azotea técnica girada 64°, paneles, sala de tanques. |
| A-106 | Esquema de giro y orientación de unidades | 1:200 / 1:500 | Losas de los pisos 3 a 18 superpuestas, rumbo, frente y vista de las 49 unidades. |
| A-201 | Vistas Norte y Este | 1:200 | Fachadas con el giro de cada losa, niveles y zonas. |
| A-202 | Vistas Sur y Oeste | 1:200 | Fachadas con el giro de cada losa, niveles y zonas. |
| A-301 | Corte A-A | 1:200 | Corte norte-sur por el ascensor y el palier, con el terreno hasta el lago. |
| A-302 | Corte B-B | 1:200 | Corte este-oeste por la escalera presurizada. |
| A-401 | Tipología B1: 2 dormitorios | 1:50 | Planta amoblada, cotas, planilla de locales, superficies, unidades 3B a 8D y corte. |
| A-402 | Tipología B2: 2 dormitorios y estudio | 1:50 | Ídem para las unidades 3A a 8C. |
| A-403 | Tipología L2: 2 suites | 1:50 | Ídem para las unidades 9B a 14C, con la geometría del departamento modelo. |
| A-404 | Tipología L3: 3 dormitorios | 1:50 | Ídem para las unidades 9A a 14A. |
| A-405 | Tipología C3: 3 dormitorios y estudio | 1:50 | Ídem para las unidades 15A a 17B. |
| A-406 | Tipología PH: penthouse | 1:50 | Ídem para la unidad 18A. |
| A-501 | Departamento modelo L2 (recorrido 360°) | 1:50 / 1:100 / 1:25 | Unidad amoblada del recorrido virtual, con puntos de vista, cielorrasos e iluminación, baño en suite y terminaciones. |

## Archivos

- `Lenga - Legajo de planos.pdf`: juego completo, una lámina por página, con marcadores.
- `pdf/A-xxx.pdf`: cada lámina por separado.
- `dxf/`: plantas, vistas y cortes de cada lámina, en metros. La implantación y las plantas del basamento están en el marco del sitio (x este, y norte, origen en el eje del núcleo). Las plantas tipo están en el marco de la planta y las tipologías en el de la unidad.
- `fuente/generar.py`: el generador de todo el legajo.

## Regenerar

Desde la raíz del repositorio:

```
python -I planos/fuente/generar.py                 # PDF por lámina, PDF combinado y DXF
python -I planos/fuente/generar.py --png carpeta   # además, vistas previas PNG
```

El generador lee `js/data.js`, `js/building.js` y `tools/depto.py` (este último con `ast`, sin Blender) e imprime los controles cruzados. Necesita reportlab, pypdf y shapely. Usa ezdxf para los DXF y pypdfium2 para las vistas previas.
