# Revisión del departamento completo (19-nov-2026)

Estado de los seis 360° y del caminar libre que muestra el sitio. El criterio es el de `referencias/hiperrealismo-metodo.md`, en la carpeta del manual. La primera revisión (doce defectos, hojas en `3d/out/revision/`) quedó resuelta en las pasadas de abajo.

## Estado (19-nov-2026, segunda pasada)

El método ya se aplica al departamento entero: `depto.build()` llama a `habitacion.departamento()`, así los 360° y el recorrido horneado salen de la misma escena.

**Resuelto, con la causa confirmada:**

| # | Defecto | Causa | Arreglo |
|---|---|---|---|
| 4 y 6 | Vidrios negros | Reflexión total en la cara de salida | Reflejo solo en la cara de entrada |
| 8 | Rendija de luz | Hoja de la puerta al ras del vano | La hoja entra 2 cm en el muro |
| 11 | Raya blanca en el baño | Piedra pulida que reflejaba la tira del espejo | Piedra apomazada |
| 10 | Cuarto negro | Baño 2 sin luz | Luz propia en el baño 2 |

**Resuelto, a la vista en las pruebas:**
- 1: aparador, cerámicas y foto en la pared del living.
- 2: el hogar, apagado. Ni quemada ni anaranjada la llama aguantó de cerca.
- Nuevo: el contorno brillante de la puerta de entrada (2 cm de luz con el marco hacia el cielo). La hoja ahora entra en el muro.
- 3: mesada de una pieza.
- 5: jardineras con tierra, pasto y arbusto.
- 7: la suite trabajada y el punto de vista movido a la esquina de la puerta.
- 9: la cama del dormitorio 2 rehecha y vestida.
- 12: bachas de cerámica, toalla simulada y nicho con fondo y luz.

**Recorrido horneado (caminar libre):**
- Bachas negras por fuera: la pared de la cavidad asomaba por fuera de la de afuera. Ahora el fondo se cierra al 85 %; confirmado con un rayo.
- El GLB pasó de 12,9 a 22,2 MB por las telas y el respaldo. El decimado ahora agrupa las piezas armadas por nombre y ambiente; el peso final está en «Peso del recorrido», abajo.
- El grano de las telas en `3d/out/bake-check/` es de la hoja de control (Cycles sin mipmaps). En el visor no aparece.

## Tercera pasada: auditoría objeto por objeto (19-nov-2026)

Cada objeto contra las tablas de síntomas de las áreas del método. Lo medible lo mide `tools/render/auditoria.py` (informe en `3d/out/auditoria/informe.json`); cada marca se confirmó con rayos antes de arreglarla. Lo demás se miró en los seis 360°, en seis vistas cada uno.

**Fallaban y se arreglaron:**

| Objeto | Lección | Se veía | Arreglo |
|---|---|---|---|
| Piso y maderas miel | Barniz | Raya blanca en el piso del living (la tira LED de la cocina) y puntitos bajo los spots | Barniz satinado: rugosidad de capa 0,3 |
| Veladores del dormitorio 2 | Contacto | A 1,4 cm de la mesa de luz | `apoyar()` |
| Jarrón de la mesa del comedor | Contacto | A 7,7 cm de la mesa | `apoyar()` |
| Cama de la suite | Contacto | La base a 6 cm del piso, sin nada abajo | Zócalo hundido en sombra |
| Banco de la ducha | Modelo pobre | Una caja de roble | Taburete plegable de Poly Haven (CC0) |
| Respaldo (recorrido) | Decimado | Canales retorcidos | Vértices soldados |
| Juntas del placard (recorrido) | Texel | Una junta blanca | Densidad ×4 en tiras finas |

**Cumplen:** luces (veladores a 10 W, una luz en cada ambiente), vidrios (reflejo solo en la cara de entrada), bachas, nicho, toalla, almohadas y frazada apoyadas, hogar apagado, jardineras, puertas metidas en el muro, ropa de cama dentro de su rango (picos de 0,92 a 0,95; el vivo de una europea llega a 0,99, un tubo de 9 mm).

**Falsos positivos de la auditoría:** lo que cuelga (cuadros, manijas, rieles, horno en su columna, bacha de la cocina), las almohadas inclinadas (su caja no toca), frazadas que cuelgan, juntas sobre los frentes y las caras al revés de leños, puerta y zócalos, que `enderezar()` corrige en el horneado.

## Cuarta pasada: la suite, lo que marcó el humano (20-nov-2026)

Cada falla se midió con rayos (`asentar()` imprime cuánto bajó cada pieza) y con el perfil del acolchado antes de darla por resuelta.

| Se veía | Causa | Arreglo |
|---|---|---|
| Acolchado levantado junto a las almohadas | Cabecera fija 4 cm en el aire: subía hasta 8,6 cm | Cabecera doblada hacia los pies; fijo solo lo que apoya en el colchón |
| Esquinas del acolchado paradas | La franja fija cruzaba también lo que cuelga | Fija solo sobre la parte plana |
| Almohadas flotando | Infladas contra el respaldo, el roce las sostenía: europeas a 3,7 cm, de dormir a 5, lumbar a 7 | `asentar()` |
| Almohadones como piedras | Cuero arrugado y brillante; escocés parado en una punta | Un solo lumbar de lino terracota |
| Cortinas de chapa | Onda perfecta de dos filas de vértices, voile liso | Lino con caída, ruedo y cabezal, en riel de techo (las seis del departamento) |
| Sillón junto a la ventana | Pedido del humano | Se sacó con su manta; su crédito de ABO también |
| Piso como una sola superficie | Foto de tablas de 9 cm con juntas tenues | Tablas de 18,5 × 190 cm con junta, bisel y tono propio (todo el departamento) |
| Alfombra como placa gris | Bereber lisa de 1,4 cm con canto recto | Lana tejida en canasta, 1 cm, canto redondeado y ribete (las tres) |
| Asiento del banco como papel arrugado | Relieve del cuero a fuerza 1 | 0,35 |

**Regla corregida:** los 360° quedan a 1,55 m, a la altura del caminar libre (área 2 del método).

**Peso del recorrido** (20-nov-2026): GLB de 17,8 MB, 586.000 triángulos. Antes del método eran 12,9 MB, con las telas sin agrupar llegó a 22,2 y el 19-nov quedó en 16,5; las cortinas con caída y el acolchado doblado suman 1,3 MB. Los créditos de ABO quedaron iguales a los 22 modelos que hay en la escena.

**Abierto:**
- La foto del lago (ventanas y cuadros) puede ser de IA `[verificar]`: si lo es, rompe la regla 1. Entra con el trabajo del exterior.
- Los colgantes de la cocina se ven muy brillantes de abajo, aunque menos que antes.
- Las juntas finas del baño: líneas negras de un píxel, sin profundidad.
- La vista por la ventana sigue lavada.
