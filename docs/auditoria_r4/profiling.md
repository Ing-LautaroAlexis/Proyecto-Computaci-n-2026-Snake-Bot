# Perfil competitivo del v4 sin modificar

> **Nota (reorganización 2026-09-30):** documento rescatado de la antigua carpeta `competitive_audit/`. Analiza el bot modular R4 (`botv7.6_v4.py`), hoy en `versions/chatgpt/modular/`. Las rutas `BOT CHATGPT PLUS/...` y `BOT GEMINI PRO/...` son las ubicaciones de esa época; los scripts y resultados crudos (`results/`, `*.json`) no se conservaron en el repositorio.

Mediciones locales; el percentil no es una garantía de tiempo máximo. Los casos fueron seleccionados deliberadamente para estrés, no representan una distribución de partidas.

Se restaura una copia del historial previo antes de cada repetición. Las reconstrucciones frías modelan falta de historial; las cálidas reciben el cuerpo ordenado. Las serpentinas son posiciones sintéticas válidas y no se afirma que el servidor las genere.

## Tiempo real sin instrumentación (modo time predeterminado)

| Fuente | n | Media ms | p95 ms | p99 ms | Máximo ms | >80 ms |
|---|---:|---:|---:|---:|---:|---:|
| benchmark | 36 | 52.364 | 68.475 | 69.779 | 69.779 | 0 |
| existing_legacy_regression | 12 | 59.466 | 68.637 | 68.637 | 68.637 | 0 |
| synthetic_reconstruction_search | 12 | 3.273 | 8.511 | 8.511 | 8.511 | 0 |
| synthetic_stress | 18 | 60.195 | 63.214 | 63.214 | 63.214 | 0 |

## Atribución exclusiva instrumentada por decisión

Cada muestra suma todas las invocaciones del componente dentro de UNA decisión. Se excluye el tiempo de funciones hijas ya atribuido a otros componentes: no hay doble conteo. La instrumentación añade coste y cambia la profundidad alcanzada por el deadline; esta tabla identifica dónde se trabaja, no estima directamente latencia sin instrumentar.

| Componente | Media ms | p95 ms | p99 ms | Máximo ms |
|---|---:|---:|---:|---:|
| topology_territory | 41.381 | 87.198 | 93.608 | 93.608 |
| parsing_control | 17.211 | 27.663 | 41.440 | 41.440 |
| body_reconstruction | 4.225 | 16.336 | 75.810 | 75.810 |
| move_generation | 1.455 | 4.125 | 5.044 | 5.044 |
| move_simulation_undo | 1.206 | 4.428 | 5.694 | 5.694 |
| future_escape | 0.954 | 1.558 | 1.696 | 1.696 |
| tactical_traps | 0.668 | 3.287 | 5.420 | 5.420 |
| food | 0.293 | 0.762 | 0.844 | 0.844 |
| anti_cycle | 0.240 | 0.618 | 3.029 | 3.029 |
| forced_trap | 0.209 | 0.520 | 0.730 | 0.730 |
| alpha_beta_search | 0.123 | 0.008 | 3.166 | 3.166 |
| banking_strategy | 0.100 | 0.142 | 1.523 | 1.523 |
| fallback_safety | 0.063 | 0.103 | 1.033 | 1.033 |

## Control de perturbación

Se repiten posiciones con presupuesto fijo de nodos. El modo nodes también sustituye los límites temporales de capas por límites de nodos, por lo que NO corresponde a la configuración competitiva. Su única finalidad es medir el coste del profiler sobre trabajo equivalente.

| Caso | Base ms | Perfil ms | Cociente | Nodos iguales | Dirección igual |
|---|---:|---:|---:|---|---|
| game_0_move_0 | 297.914 | 4107.783 | 13.79 | True | True |
| synthetic_12x12_len24_cold | 150.037 | 1990.456 | 13.27 | True | True |
| synthetic_12x12_len24_warm | 161.345 | 2038.982 | 12.64 | True | True |

## Funciones con mayor tiempo propio instrumentado

| Función | Media acumulada por decisión ms | Llamadas totales |
|---|---:|---:|
| _flood_cell_allowed | 15.4221 | 180976 |
| is_pos_inside | 13.5762 | 265862 |
| _flood_distances | 11.3596 | 216 |
| bfs_distances | 6.6302 | 72 |
| _bfs_can_enter | 5.1944 | 61168 |
| is_open_cell | 2.6088 | 79091 |
| _bfs_neighbors | 2.4615 | 76475 |
| _is_unvisited_body_cell | 1.8044 | 15840 |
| _trace_candidates | 0.8603 | 1491 |
| _legal_destination | 0.7216 | 6256 |
| _body_candidate_degree | 0.6477 | 2469 |
| _state_snapshot | 0.5565 | 324 |
| get_legal_moves_raw | 0.4774 | 1564 |
| make_move | 0.4272 | 1413 |
| is_food_symbol | 0.4003 | 16309 |
| _trace_dfs | 0.3057 | 1539 |
| unmake_move | 0.2932 | 1413 |
| _trace_full_snake | 0.2824 | 48 |
| <genexpr> | 0.2365 | 7032 |
| _tactical_order_moves | 0.1722 | 204 |
| _force_target_death | 0.1453 | 230 |
| analyze_topology_consolidated | 0.1253 | 216 |
| _build_turn_context | 0.1186 | 78 |
| _count_target_cells | 0.1126 | 156 |
| _is_open_exit | 0.1006 | 864 |

## Peores observaciones sin instrumentar

- game_2_move_82: 69.779 ms; nodos 21; {'rows': 17, 'cols': 15, 'own_length': 8, 'combined_length': 13, 'remaining': 218, 'side': 'A'}.
- regression_thiago_cold: 68.637 ms; nodos 14; {'rows': 15, 'cols': 17, 'own_length': 15, 'combined_length': 29, 'remaining': 44, 'side': 'A'}.
- game_4_move_298: 68.475 ms; nodos 61; {'rows': 17, 'cols': 15, 'own_length': 14, 'combined_length': 23, 'remaining': 2, 'side': 'A'}.
- regression_thiago_warm: 65.305 ms; nodos 11; {'rows': 15, 'cols': 17, 'own_length': 15, 'combined_length': 29, 'remaining': 44, 'side': 'A'}.
- game_0_move_0: 63.909 ms; nodos 18; {'rows': 17, 'cols': 15, 'own_length': 3, 'combined_length': 6, 'remaining': 300, 'side': 'A'}.
- game_0_move_298: 63.824 ms; nodos 47; {'rows': 17, 'cols': 15, 'own_length': 12, 'combined_length': 21, 'remaining': 2, 'side': 'A'}.
- game_0_move_296: 63.370 ms; nodos 18; {'rows': 17, 'cols': 15, 'own_length': 12, 'combined_length': 21, 'remaining': 4, 'side': 'A'}.
- synthetic_20x20_len80_warm: 63.214 ms; nodos 11; {'rows': 20, 'cols': 20, 'own_length': 80, 'combined_length': 160, 'remaining': 40, 'side': 'A'}.
- game_0_move_242: 62.978 ms; nodos 14; {'rows': 17, 'cols': 15, 'own_length': 11, 'combined_length': 19, 'remaining': 58, 'side': 'A'}.
- regression_candela_cold: 62.953 ms; nodos 26; {'rows': 12, 'cols': 15, 'own_length': 7, 'combined_length': 14, 'remaining': 214, 'side': 'A'}.

La tabla y los datos crudos se generan con profile_v4.py; profile.json incluye entorno, hash SHA-256 del archivo objetivo, selección, estadísticas por decisión, llamadas y observaciones completas.
