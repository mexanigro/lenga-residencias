# Revisión del departamento completo (19-nov-2026)

Revisión de los seis 360° que muestra el sitio (`img/depto3d/pano-*.webp`). Cada uno se miró en seis vistas de 75°, como las vería alguien parado en el punto (`tools/render/vistas.py`). Las hojas están en `3d/out/revision/`; `hallazgos.jpg` junta los doce defectos más claros.

El criterio es el de `referencias/hiperrealismo-metodo.md`, en la carpeta del manual. Las causas marcadas «a confirmar» son probables; se confirman con `bmcp.py rayo` antes de arreglarlas.

## Lo que pesa más: el resto del departamento todavía no tiene el método

Todo lo que se corrigió en la suite vive en `tools/habitacion.py`, que trabaja la suite sola. El resto del departamento, sus 360° y el recorrido 3D horneado siguen con los valores viejos de `tools/depto.py`:

- **Sol a 11° con ángulo de 0,8°:** deja franjas largas y duras en pisos y muebles.
- **Paredes con albedo 0,86 y lisas:** el cuarto queda chato.
- **Lámparas a 30 W.**
- **Telas teñidas a ojo:** quedan grises.

El 360° de la suite que ve el visitante es el viejo: la cama de catálogo con la ropa de cama fundida.

**Arreglo:**
1. Llevar a `depto.py` lo que ya está probado (sol suave, cielo de relleno, albedos, variación de paredes y listones, lámparas a 10 W).
2. Rehacer los seis 360°.
3. Volver a hornear el recorrido.

Un solo cambio mejora todos los ambientes a la vez.

## Defectos por ambiente

| # | Ambiente | Se ve | Causa | Arreglo |
|---|---|---|---|---|
| 1 | Living | Pared enorme, vacía y lisa (la del pasillo a la suite) | Nada la ocupa; pintura sin variación | Obra o estante con objetos; pintura con variación y piel de naranja (`superficies()`) |
| 2 | Living | El fuego del hogar parece dibujado: picos blancos | Emisión de ruido estirado (`fire_mat`) que se quema a blanco | Llama más baja y anaranjada, sin pasar a blanco, con brasas; o hogar apagado con leños, que en una foto de día es lo normal |
| 3 | Cocina | Los colgantes de cobre tienen un disco blanco quemado abajo | Emisor plano y muy fuerte a la vista | Difusor que no se vea de frente, o bajar la potencia a la de una lámpara real |
| 3 | Cocina | La mesada negra de la isla está partida en baldosas | Textura de piedra con juntas | Piedra de una sola pieza, sin juntas, con el reflejo suave de una mesada pulida |
| 4 | Balcón | La baranda de vidrio se ve como una placa negra (o blanca) con un borde curvo | A confirmar: el vidrio refleja algo oscuro en ángulo rasante; la curva es el límite del Fresnel | Vidrio que refleje cielo y lago (que el fondo sea visible en reflejos) y con un tinte verdoso en el canto |
| 5 | Balcón | Jardineras de madera vacías, negras por dentro | Faltan tierra y plantas | Tierra y plantas de Poly Haven (CC0), o sacarlas |
| 6 | Living y cocina | El vidrio de la puerta corrediza es un espejo negro | La misma causa que el 4 | Lo mismo que el 4 |
| 6 | Living y cocina | Puntos blancos en el vidrio y el piso (reflejos de los spots del techo) | Spots chicos y piso con barniz | Spots más grandes (radio) o más bajos; menos barniz en el piso, como en los listones |
| 7 | Suite | El 360° es el viejo, y el punto mira medio cuarto de placard y paredes | El 360° es anterior al trabajo de la suite | Rehacer el 360° con `habitacion.py` y elegir puntos de vista como en `camara()`. Pendiente la idea de puntos fijos de 360° más videos de Cycles entre puntos |
| 8 | Dormitorio 2 | Una rendija de luz vertical en la pared | A confirmar: una junta entre dos piezas de muro deja pasar el sol | Solapar los muros o cerrar la junta |
| 9 | Dormitorio 2 | La cama es un bloque blanco, con almohadas simples y un almohadón naranja con pompones | Cama de catálogo con la ropa de cama fundida | `ropa()` de la suite: acolchado simulado, almohadas que caen, frazada |
| 9 | Dormitorio 2 | Oscuro y plano; los veladores dejan halos en la pared verde | Poca luz de ventana y lámparas sin control | Sol y cielo como en la suite; veladores a 10 W |
| 10 | Dormitorio 2 | La puerta da a un cuarto negro | El cuarto de atrás no tiene luz ni está en el recorte | Luz en ese cuarto, o la puerta entornada |
| 11 | Baño | Una raya blanca fina cruza las paredes | A confirmar: reflejo de la tira de luz del espejo en la piedra brillante | Piedra más mate (honed) o una tira de luz más ancha y suave |
| 11 | Baño | Las juntas de las placas son líneas negras de un píxel, cortadas | Juntas dibujadas en la textura, sin profundidad | Juntas de 2–3 mm como geometría o relieve, con un color de pastina |
| 11 | Baño | El nicho de la ducha es un rectángulo negro plano | El nicho no tiene fondo ni luz | Nicho con profundidad, la misma piedra adentro y algo de luz |
| 12 | Baño | Piletas de plástico blanco puro; la toalla es una caja | Albedo 1 sin variación; la toalla no tiene simulación | Cerámica de albedo ~0,8 con reflejo, toalla simulada colgando de la barra; un par de objetos (jabón, plantita) |
| — | Baño | Oscuro, sin luz de ventana | No tiene ventana | Spots más cálidos y, si el baño tiene una, luz de afuera |

## Orden propuesto

1. Llevar el método a `depto.py` (sol, cielo, albedos, paredes, lámparas, vidrios) y rehacer los 360°. Arregla el 1, el 4, el 6, el 7 y buena parte del 9 y del 11.
2. Defectos puntuales: rendija (8), cuarto negro (10), fuego (2), colgantes (3), mesada (3), jardineras (5), baño (11 y 12).
3. Ambientación: la pared vacía del living y la cama del dormitorio 2 con `ropa()`.
4. Cada ambiente pasa por la lupa del método antes de reemplazar su 360° en el sitio.
