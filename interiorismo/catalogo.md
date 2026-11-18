# Catálogo de ambientación · L2

Detalle completo (medidas, tris, peso, licencia, crédito) en `catalogo.json`. Archivos en `%LOCALAPPDATA%\lenga3d\assets\` (`abo/<id>.glb`, `models/<nombre>/`, `tex/<nombre>/`). Las hojas de contacto por slot están en el scratchpad de la sesión (`catalogo/<slot>.jpg`) y se regeneran desde los IDs.

Fuentes: solo Poly Haven y ambientCG (CC0) y Amazon Berkeley Objects (CC BY 4.0, crédito "Amazon.com" en la página de créditos del sitio, con link a la licencia y aclarando que se modificaron). En Blender todos los GLB de ABO miran a −Y, con Z arriba.

## Living
- **sofa_3**: ABO `B07B4MD59G` (Stone & Beam Andover, 2,40 m, brazos rectos, patas de madera). La tela viene greige: subile el valor o teñila hacia Lana. Alternativa: `B07HZ5PF5S` (Calhoun, ya viene crudo, más relajado).
- **armchair_leather ×2**: `B075X2WN27` (Rivet Aiden, cuero coñac con brazos rectos). Alternativa: `B071J7Q9WN` (coñac con trineo de hierro negro).
- **coffee_table**: `B07QF9Y71V` (1,35 × 0,75, tablones de madera sobre marcos de hierro negro). Alternativa: `B07K8F2WHK` (haya maciza).
- **side_table ×2**: `B07B7H9VMM` (bloque facetado de abeto recuperado, tiene 20 tris). Alternativa: `B072ZLCB3M` (nogal con borde natural y hierro).
- **console_table**: `B075ZF4SF1` (caballete de madera recuperada, 1,80 m). Alternativa: `B07TQ8WK61` (roble envejecido con hierro, 1,80 × 0,39).
- **floor_lamp**: `B073755HVS` (arco negro con pantalla tambor). Alternativa: `B073P484RR` (trípode negro con pantalla de lino).
- **table_lamp ×2**: `B075X1T517` (base cerámica gris con textura de piedra, pantalla de lino). Alternativa: `B07QJLF9XP` (cerámica crema).
- **throw_blanket**: no hay modelo libre, la tenés que modelar (plegada o con cloth sim). Materiales listos: `knit_rust` (Otoño) y `plaid_green` (Bosque).
- **cushions**: `B07JLGCKPV` (cuero coñac), `B07JM1VM9Q` (lino con banda verde), `B07JLZC7FK` (terracota) y `B07BMTXJ1V` (piel sintética crema). `throw_pillows_01` es demasiado étnico: usalo solo retexturizado. El toque Lago sale de retexturizar uno con `rough_linen`.
- **firewood**: no hay modelo de pila. Va el material `firewood_logs` (ambientCG Logs001) en una caja dentro del nicho; si no, cortás `dead_tree_trunk` en troncos de 40 cm.
- **big_plant**: solo existe `potted_plant_01` (1,35 m, ya estaba bajada). Escalala ×1,15 y cambiá la maceta a cerámica Lana o Piedra. Alternativa: `potted_plant_02` sobre un banquito. No hay planta de interior de 1,5–1,9 m.
- **decor**: `wicker_basket_02`, `wooden_bowl_02`, `ceramic_vase_04`, `B07B8PXTSY` (vaso esmaltado óxido), `B07QHL8W81` (par crema y azul pizarra), `B078JMXRGC` (bandeja de pizarra y abedul), `B07HSPJ11F` (faroles de gres), `B07QFB5MW6` (vasija gris de 50 cm) y `decorative_book_set_01`.

## Comedor y cocina
- **dining_table**: `B07KV3HBMR` (madera maciza de 2,00 × 1,00, patas en X de hierro negro). Alternativa: `B075Z9QB8P` (abeto de 2,20 m con caballetes de hierro).
- **dining_chair ×6**: `B0857JQ3BZ` (marco de nogal con asiento de cuerda tejida; tiene 161k tris, hay que decimarla para la web). Alternativa: `B07B83KVGK` (roble miel, liviana).
- **pendant_dining**: `B07HK85JV8` (soga natural, 0,64 m). Alternativa: `B082JH9VVD` (globo de mimbre, dos en línea).
- **bar_stool ×3**: `B07QFRRLG1` (asiento de cuero coñac con patas de madera). Es de altura bar: escalala en Z ×0,86 para la isla. Alternativa: `B0857JWWWS` (wishbone de altura mostrador, pesada).

## Suite principal
- **bed_king**: `B075QBL1V8` (Clifton, king tapizada crema con respaldo de alas). La cama existe, solo falta modelar la ropa de cama. Alternativa: `B07HSL882C` (plataforma de acacia).
- **nightstand ×2**: `B082JH6LSF` (pino miel, dos cajones). Alternativa: `B072ZLCB32` (nogal con hierro).
- **bed_bench**: `B07K7NQR23` (roble con asiento de cuero, 1,20 m). Alternativa: `B07B4SC9RP` (lino sobre hierro negro, 1,49 m).
- **reading_chair**: `B082QDSXMN` (Rivet Spear, marfil con brazos de nogal). Alternativa: `B07B4MTFRH`.
- **sheepskin**: no hay modelo. Usá el material `sheepskin_teddy` sobre una piel modelada, con pelo de Blender si hay primer plano.

## Segunda suite, baño y balcón
- **nightstand_suite2**: `B072ZLCB32`. Alternativa: `B07RMZ83ZY`.
- **desk_or_dresser**: `B07HSNQW37` (cómoda de acacia de 6 cajones). Alternativa: `B071P9WJBT`.
- **wall_art**: `B073P5V2LX` (lago y cerros nevados sobre madera; escalala a ~1,1 m sobre el hogar). Alternativa: `B073P1RD5Z` (muelle en el lago, 1,15 m).
- **bath_accessories**: `B07HSMVFKY` (cestos de yute), `B078JMXRGC` como jabonera de piedra y `potted_plant_04`. Las toallas hay que modelarlas, con el material `terry_towel`.
- **outdoor_lounge_chair ×2**: no hay sillón bajo de teca libre. Provisoriamente va `B07B4M6B3B` (Alderman, marco de madera) con el marco teñido teca y almohadones en lona Lana. Mejor: modelar un sillón bajo de listones de teca.

## Materiales (`tex/<nombre>/`: Diffuse, Rough, nor_gl, arm, disp)
- **floor_wood_honey**: Poly Haven oak_wood_planks, 4K, 1,2 m. Alternativa: `floor_wood_plank_alt` (ambientCG WoodFloor051).
- **stone_ledge**: castle_wall_slates, 4K, 2,5 m, laja gris cálida apilada. Alternativa: `stone_ledge_alt` (stacked_stone_wall, más óxido).
- **granite_dark**: granite_tile, 4K, carbón apomazado. Tiene juntas cada ~1,15 m.
- **tile_backsplash**: ambientCG Tiles139, 4K, piedra caliza crema. No hay zellige en estas fuentes.
- **oak_slats**: oak_veneer_01, 4K.
- **wool_cream**: Fabric019, 4K, teñila Lana. Ojo: el "wool_boucle" de Poly Haven en realidad es un príncipe de Gales gris y óxido.
- **linen_natural**: Fabric036, 4K.
- **plaid_green**: curly_teddy_checkered, 4K.
- **knit_rust**: Fabric085, 4K.
- **leather_cognac**: fabric_leather_02, 4K.
- **rug_berber**: Carpet016, 4K.
- **sheepskin_teddy**: curly_teddy_natural, 4K.
- **black_metal**: Metal046A, 2K.
- **bath_stone**: large_grey_tiles, 4K.
- **firewood_logs**: Logs001, 2K.
- **terry_towel**: terry_cloth, 2K.
- Los tamaños de baldosa se agregaron a `tex/dims.json`.
