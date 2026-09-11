# Evolución de SnakeBot

Secuencia solicitada: Gemini V1 → V2 → V3 → V3.1 → V5 → V5.5 →
ChatGPT Plus V7.6 → Modularización R4 → ChatGPT Plus V8.0.

Las etiquetas Gemini y ChatGPT provienen de la clasificación del proyecto.
Los objetivos de abajo se infieren de funciones observables, no de métricas de
victorias. Los números de versión no prueban una mejora de rendimiento.

| Etapa | Archivos principales | Objetivo y diferencias observables |
| --- | --- | --- |
| Gemini V1 | `snake1.py`, `snake1.1.py` | Movimiento seguro, espacio disponible y distancia a comida; V1.1 separa una función `evaluate_move`. |
| Gemini V2 | `snake2.0.py`, `snake2.1.py` | Añade evaluación territorial Voronoi, longitudes y espacio disponible del adversario. |
| Gemini V3 | `snake3.0.py`, `botV3.py` | Se preservan dos implementaciones diferentes: la primera conserva evaluación territorial; `botV3.py` incorpora reconstrucción de cuerpos, simulación reversible, BFS espacio-temporal y búsqueda alfa-beta. |
| Gemini V3.1 | `botV3.1.py`, `botV3.1new.py` | Expone movimientos legales, análisis de topología/corredores y alternativa de emergencia. La variante `new` organiza ventanas de partida por separado. |
| Gemini V5 | `botV5.py` y variantes | Usa distancias BFS y evaluación V5. `botv5-opti.py` añade `TopologyInfo` y análisis consolidado; las variantes FE, FR y AC incluyen escape futuro, carrera por comida y penalizaciones anticiclo. `botv5.2.3.py` añade territorio adaptativo y penalizaciones de trampas forzadas. Son variantes preservadas, no una clasificación por fuerza. |
| Gemini V5.5 | `botV5.5.py` | Contiene `get_strict_legal_moves`, seguimiento en `update_and_get_state` y funciones de evaluación llamadas V6. Ese nombre interno no cambia su clasificación solicitada como V5.5. |
| ChatGPT Plus V7.6 | `botv7.6_v3.py` | Motor de decisiones separado del runtime; parsing de dimensiones, comida numerada, historial de cuerpos, búsqueda y capas tácticas. Esta separación ya existía en el archivo recibido. |
| Modularización R4 | `botv7.6_v4.py`, `snake_runtime.py`, `snake_visualizer.py` | Paquete recibido con estrategia, conexión y visor separados. Frente al archivo V7.6 recibido añade 15 funciones auxiliares y cambia cinco funciones existentes, principalmente congelación/comida segura. No se presenta como una refactorización puramente estructural. |
| ChatGPT Plus V8.0 | `botv8.0_v5.py` | Añade `_fast_bfs_distances`, con índices enteros y buffers planos. `bfs_distances` y `_flood_distances` delegan en ese núcleo. Las restantes funciones conservan su AST respecto de R4. |

## Integridad y dependencias

Los bots se movieron sin modificar contenido. Se verificaron hashes SHA-256
antes y después de cada traslado/copia. `.gitattributes` evita conversiones de
finales de línea en los fuentes históricos. El respaldo original queda fuera de Git.

Las carpetas originales V7.6 y V8 no contenían `snake_runtime.py` ni
`snake_visualizer.py`. Se incluyeron copias exactas de R4 para completar las
importaciones; esto se documenta como asociación actual, no como recuperación de
archivos originales ausentes. `src/bot_final/` contiene únicamente V8 y estas dos
dependencias. Su duplicación con el archivo histórico es deliberada para distinguir
la versión operativa del archivo de evolución solicitado.

Los tests recibidos con R4 se trasladaron a `tests/`; únicamente se adaptaron sus
rutas y el lanzador. El adaptador pytest invoca los escenarios de equivalencia y
arena ya existentes. El snapshot `REFERENCE_DO_NOT_DEPLOY.snapshot` se conserva
intacto y participa como oráculo de regresión.

`LEEME.txt` de R4 se conserva como documento histórico; sus instrucciones de tests
reflejan la ubicación antigua. Para el uso actual corresponde el README raíz.

## Alcance de la validación

La inspección previa comprobó igualdad R4/V8 en 1.000 mapas BFS rectangulares
aleatorios y 100 decisiones con presupuesto fijo de 24 nodos. Es evidencia limitada
de equivalencia; no demuestra equivalencia universal, mejora de tiempos ni victorias.
La suite automatizada contrasta además V8 con el snapshot histórico recibido.

No se reescribió la historia Git existente. Los nuevos commits documentan la
incorporación ordenada de las versiones, con fechas reales de incorporación.

## Archivos adicionales

`botv6.py` y `botv6.1.py` permanecen en `unclassified/` porque no corresponden a
una etapa pedida. Los archivos sin clasificar que contienen credenciales se
conservan solo localmente y se excluyen de Git. Los scripts y reportes de
`competitive_audit/` permanecen locales: no forman parte de esta publicación del
bot. No se eliminan resultados de partidas ni el entorno Python.
