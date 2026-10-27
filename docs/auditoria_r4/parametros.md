# Parámetros y entrenamiento del bot modular R4

> **Nota (reorganización 2026-09-30):** documento rescatado de la antigua carpeta `competitive_audit/`. Analiza el bot modular R4 (`botv7.6_v4.py`), hoy en `versions/chatgpt/modular/`. Las rutas `BOT CHATGPT PLUS/...` y `BOT GEMINI PRO/...` son las ubicaciones de esa época; los scripts y resultados crudos (`results/`, `*.json`) no se conservaron en el repositorio.

Fecha: 2026-09-09. Alcance: inspección estática de `BOT CHATGPT PLUS/SNAKE_V76_MODULAR_R4/botv7.6_v4.py`, sus puntos de entrada y auxiliares de entrenamiento. No se modificó código del bot ni se ejecutó entrenamiento. Este documento es un artefacto de auditoría separado.

## Lectura de la evidencia

Los nombres, valores, condiciones y funciones de las tablas se verificaron leyendo el código y su AST. **La sensibilidad y el riesgo son estimaciones técnicas; no son resultados de torneos.** Una diferencia sintáctica pequeña puede cambiar muchas jugadas y requiere medir victorias, muertes, decisiones y tiempo. Las reglas del motor y las constantes del protocolo se separan de los pesos que tendría sentido optimizar.

Fuentes principales:

- [Bot R4](../../versions/chatgpt/modular/botv7.6_v4.py), constantes en líneas 10–151 y `choose_direction` en 3034.
- [Runtime modular](../../versions/chatgpt/modular/snake_runtime.py), `_play_turn` en 87 y `run_client` en 163.
- Entrenador evolutivo antiguo *(archivo que ya no está en el proyecto)*, `FastBoard` en 48 y `run_evolution` en 345.
- Cliente que consume los pesos antiguos *(archivo que ya no está en el proyecto)*, evaluador en 131 y `choose_direction` en 175.
- [Arena raíz](../../arena.py), motor en 220, semilla en 234 y torneo con lados alternados en 808.

## Conclusiones que condicionan la optimización

1. R4 ya permite comparar variantes en módulos aislados en memoria. La estrategia se importa sin iniciar Pygame, WebSocket ni partidas remotas. Los parámetros deben aplicarse al módulo de cada jugador y registrarse junto al resultado.
2. Los `USE_*_DEFAULT` se capturan al definir `choose_direction`. Asignar después `module.USE_APPLE_FREEZE_DEFAULT=False` no modifica el argumento predeterminado ya capturado: hay que pasar `use_apple_freeze=False`. Lo mismo ocurre con `use_fe` y `use_ac`.
3. `FE_HORIZON` y `FORCED_TRAP_MAX_ROUNDS` también quedan capturados en argumentos predeterminados de funciones internas; una asignación tardía al nombre global no basta para variar el camino de `choose_direction`. No los incluyo en la primera búsqueda.
4. `USE_ADAPTIVE_TERRITORY_V6` sí se consulta durante cada evaluación. Está desactivado y puede activarse mediante asignación al módulo aislado. Los parámetros territoriales carecen de efecto por esa ruta mientras siga desactivado.
5. En v3, `find_food()` devuelve solamente el objetivo correcto actual. Por ello `FOOD_RACE_SECONDARY_WEIGHT` y la rama histórica Apple Freeze que requiere dos objetivos no influyen normalmente en v3. La capa **Endgame Bank sí está activa en v3** y comparte `use_apple_freeze`.
6. No todos los límites son parámetros efectivos con el resto de valores de fábrica: el cap Endgame de 500000 por escala nunca limita su base de 420000; el cap Apple Freeze de 440000 supera su máximo aritmético actual de 380000; el cap territorial de 3500 supera el máximo actual de 650. No gastar evaluaciones variándolos en rangos donde siguen sin activarse.
7. Las recompensas de comida escalan con el dígito. Safe Food y varios umbrales de ventaja de puntos son fijos; sus efectos relativos pueden cambiar mucho entre un objetivo 1 y uno 9. Esa interacción merece estratificar resultados por fase y dígito, no asumir un único efecto constante.

## Inventario de constantes estratégicas nombradas

Cada nombre de las siguientes tablas aparece en el archivo principal. Los valores son los del código inspeccionado. Agrupo únicamente parámetros con el mismo propósito; los nombres y valores se enumeran completos.

### Búsqueda, presupuestos y seguridad

| Nombre y valor | Función / evidencia en código | Sensibilidad esperada y riesgo de variarlo |
|---|---|---|
| `DEADLINE_TIMEOUT=0.080` | `_decision_deadline` (2722); nominal de 80 ms en comentario, no verificación del contrato remoto | Alta para tiempo y profundidad; no optimizar como peso |
| `DEADLINE_MARGIN_SECONDS=0.020` | Se resta al timeout: presupuesto interno nominal 60 ms desde antes del parseo | Alta; bajar el margen puede ganar profundidad y aumentar excesos externos |
| `INF=10**9` | Inalcanzable en BFS y límites alfa-beta | Infraestructura; no ajustar sin revisar rangos de todas las puntuaciones |
| `TERMINAL_WIN_SCORE=900000000` | `_score_terminal_by_points`, `_exact_terminal_result`, `_no_moves_terminal_score` | Escala decisiva; fijar, no entrenar |
| `USE_FUTURE_ESCAPE_DEFAULT=True` | `choose_direction`, `_future_escape_layer`, `_forced_trap_layer` | Ablación amplia: desactiva tanto FE como Forced Trap; riesgo alto |
| `FE_HORIZON=2` | `compute_future_escape_penalties(horizon=FE_HORIZON)`, respuesta rival y nuestra siguiente jugada tras raíz | Alta para seguridad/coste; default capturado al importar |
| `FE_TIME_BUDGET=0.008` | Deadline local FE, 8 ms dentro del total | Alta: si aborta, se ponen a cero todas las penalizaciones FE |
| `FE_NODE_BUDGET=450` | `_fe_budget_reached` | Alta; también rige FE determinista y puede anular toda la capa |
| `FE_FATAL_RISK=450000` | `_future_escape_state_risk`, `_scaled_fe_risk` y otros filtros | Alta; cambia castigo y umbral de clasificación conjuntamente |
| `FE_POCKET_RISK=180000` | `_fe_exit_risk`, `_future_escape_state_risk` | Alta en encierros; requiere casos geométricos y supervivencia |
| `FE_TIGHT_RISK=90000` | `_fe_tail_space_risk` | Media/alta en espacio reducido sin cola alcanzable |
| `FE_SINGLE_EXIT_RISK=20000` | `_fe_exit_risk` | Media; corredor útil y peligroso pueden compartir señal |
| `FE_SAFETY_GATE_MIN_LENGTH=10` | `strengthen_root_fe_penalties` | Alta en serpientes largas; gate solo con alguna alternativa FE=0 |
| `FE_SAFETY_GATE_SCALE_LONG=4` | `_fe_gate_scale` | Alta; aumenta riesgo no fatal, con techo fatal |
| `FE_SAFETY_GATE_SCALE_VERY_LONG=5` | `_fe_gate_scale`, longitud ≥14 | Alta; interacciona con fase y diferencia de puntos |
| `FORCED_TRAP_MAX_ROUNDS=4` | `compute_forced_trap_penalties(max_rounds=...)` | Alta en persecuciones con única respuesta; default capturado |
| `FORCED_TRAP_FATAL_PENALTY=FE_FATAL_RISK`, valor inicial `450000` | `_forced_trap_candidate_penalty` | Alta; es una asignación inicial, no alias dinámico de FE_FATAL_RISK |
| `TACTICAL_SOLVER_MAX_PLIES=14` | `_run_tactical_defense` | Alta en profundidad/coste; mantener para primera optimización |
| `TACTICAL_SOLVER_TIME_BUDGET=0.007` | `_tactical_local_deadline`, 7 ms | Alta; defensa y ofensiva comparten la ventana |
| `TACTICAL_OFFENSE_MAX_PLIES=10` | `_run_tactical_offense_candidate` | Media/alta para ataques y consumo |
| `TACTICAL_OFFENSE_TIME_BUDGET=0.0025` | `_tactical_offense_deadline`, hasta 2.5 ms dentro de deadline anterior | Media/alta; no añade 2.5 ms independientes tras los 7 ms |
| `TACTICAL_SOLVER_NODE_BUDGET=3500` | `_tactical_budget_exhausted` | Alta; se comparte entre candidatos, defensa y ofensiva |
| `TACTICAL_ACTIVE_REMAINING=50` | `_tactical_late_large`, con longitud combinada ≥24 | Media/alta; solo uno de varios disparadores |
| `TACTICAL_HEAD_DISTANCE=4` | `_tactical_close_contact` y `_tactical_edge_pressure` | Media/alta; el disparador de borde usa además `max(6, ...)` |
| `TACTICAL_FORCED_LOSS_PENALTY=850000000` | `_run_tactical_defense`, ajuste raíz | Escala decisiva; no entrenar |
| `TACTICAL_FORCED_WIN_BONUS=850000000` | `_run_tactical_offense_candidate`, ajuste raíz | Escala decisiva; no entrenar |

### Carrera de comida y oportunidad segura

| Nombre y valor | Función / evidencia | Sensibilidad esperada y riesgo |
|---|---|---|
| `FOOD_RACE_MAX_DISTANCE=12` | `_food_race_value`; satura distancia, también define margen para rival inalcanzable | Media; efecto múltiple, no solo radio de búsqueda |
| `FOOD_RACE_BASE=1400` | Valor por ventaja de acceso | Media; favorece reclamar objetivos |
| `FOOD_RACE_DISTANCE_WEIGHT=150` | Bonifica cercanía al objetivo | Media; trayectoria directa frente a movilidad |
| `FOOD_RACE_MARGIN_WEIGHT=320` | Bonifica ventaja de distancia al rival | Media; compite con otros bonos de comida |
| `FOOD_RACE_NEAR_BONUS=900` | Distancia propia ≤2 | Media y localizada |
| `FOOD_RACE_SOLO_REACHABLE_BONUS=700` | Rival sin ruta BFS al objetivo | Media; BFS estático no equivale a posesión garantizada |
| `FOOD_RACE_SECONDARY_WEIGHT=0.35` | `_weighted_top_two` | Nula en v3 normal, donde solo existe un target estratégico |
| `FOOD_RACE_CAP=7500` | `compute_food_race_bonus`, cap multiplicado por escala de dígito 1..9 | Media si se alcanza; hasta 67500 antes de factores del evaluador |
| `SAFE_FOOD_MAX_STEPS=3` | `_safe_food_tuple`, distancia tras raíz ≤2; también fórmula de bonus | Media/alta: cambia horizonte elegible y magnitud a la vez |
| `SAFE_FOOD_IMMEDIATE_BONUS=75000` | `_safe_food_candidate_adjustment` | Media/alta; fijo para todos los dígitos, sujeto a filtros FE/tácticos |
| `SAFE_FOOD_PATH_BONUS=45000` | `_safe_food_path_adjustment` | Media; buen primer peso aislado a comparar |
| `SAFE_FOOD_STEP_BONUS=10000` | Bonus por cercanía tras raíz | Media; con valores base, ruta tras raíz a distancia 1 vale 65000 y a 2 vale 55000 |

### Control de fase y almacenamiento de comida

| Nombre y valor | Función / evidencia | Sensibilidad esperada y riesgo |
|---|---|---|
| `STRATEGY_ACTIVE_REMAINING=120` | `_strategy_mode`; antes de ese umbral usa NORMAL | Media/alta; activa varios comportamientos a la vez |
| `STRATEGY_LOCK_REMAINING=70` | `_leading_strategy_mode`, `_losing_strategy_mode` | Media/alta; afecta LOCK y urgencia DESPERATE |
| `STRATEGY_DESPERATE_NET_APPLES=3` | `_losing_strategy_mode` | Media; número estimado de comidas netas al reward actual |
| `USE_APPLE_FREEZE_DEFAULT=True` | `_apple_freeze_layer` | Ablación amplia: desactiva Apple Freeze histórico y Endgame Bank |
| `APPLE_FREEZE_MAX_REMAINING=70` | `_apple_freeze_inactive` | Bajo/nulo en rama histórica v3, ya que exige ≥2 targets |
| `APPLE_BANK_CASHOUT_REMAINING=8` | `_apple_freeze_inactive` y `_safe_food_lock_window` | Mixto: rama histórica y bloqueo del bonus inmediato Safe Food en LOCK |
| `APPLE_FREEZE_MIN_ENEMY_DISTANCE=5` | `_freeze_candidate_eligible` | Bajo/nulo en rama histórica v3 |
| `APPLE_FREEZE_BASE_PENALTY=320000` | `_freeze_penalty_value` | Alto en legacy; rama histórica no se activa normalmente en v3 |
| `APPLE_FREEZE_EXTRA_BANKED=30000` | Suma por ≥2 comidas bancables y por ≥3 concedibles | Igual limitación v3 |
| `APPLE_FREEZE_CAP=440000` | `_freeze_penalty_value` | Sin efecto con base actual: máximo de la suma =380000 |
| `ENDGAME_BANK_MAX_REMAINING=60` | `_bank_time_window_open` | Media/alta en finales v3 |
| `ENDGAME_BANK_CASHOUT_REMAINING=8` | Banca solo cuando remaining >8 | Media/alta; candidato pequeño: probar 12 conservando el resto |
| `ENDGAME_BANK_MAX_MY_DISTANCE=2` | `_strongly_bankable_food` | Alta; afecta si se considera controlable la comida |
| `ENDGAME_BANK_MIN_ENEMY_MARGIN=6` | Exige rival a distancia ≥propia+6, o inalcanzable | Media/alta; mayor margen hace la banca menos frecuente |
| `ENDGAME_BANK_MAX_REQUIRED_NET=2` | `_deferred_catchup_bank_allowed` | Condicionado por otra restricción: no admite margen menor que `-food_swing` |
| `ENDGAME_BANK_BASE_PENALTY=420000` | `_bank_penalty_for_reward`, multiplicado por dígito | Alta; rango actual 420000..3780000 |
| `ENDGAME_BANK_CAP_PER_REWARD_SCALE=500000` | Cap por dígito sobre base de 420000 | Sin efecto con base actual; no entrenarlo solo |
| `TRAILING_EAT_BONUS=12000` | `compute_strategy_root_adjustments` | Media; compensa heurísticamente respawn ausente en búsqueda |
| `DESPERATE_EAT_BONUS=28000` | Misma función, modo DESPERATE | Media; fijo para todos los dígitos |

La banca admite `base_margin>=0` en su ventana sin exigir modo LOCK; también admite determinadas situaciones de desventaja. Una alternativa FE=0 y ForcedTrap=0 es una señal geométrica utilizada por el código; no es una demostración universal de supervivencia futura.

### Territorio adaptativo (actualmente apagado)

| Nombre y valor | Función / evidencia | Sensibilidad esperada y riesgo |
|---|---|---|
| `USE_ADAPTIVE_TERRITORY_V6=False` | `_territory_eval_bonus` | Probar activación aislada; coste adicional de recorrer celdas en cada evaluación |
| `TERRITORY_EARLY_REMAINING=210` | `_territory_base_weight` | Sin efecto mientras esté apagado; luego media/baja |
| `TERRITORY_LATE_REMAINING=80` | Misma función | Igual |
| `TERRITORY_BASE_EARLY=0` | Peso inicial con remaining>210 | No garantiza bonus cero: la ventaja de puntos puede sumar 4 |
| `TERRITORY_BASE_MID=5` | Peso en fase intermedia | Bajo frente a score/seguridad; puede desempatar |
| `TERRITORY_BASE_LATE=9` | Peso tardío | Bajo frente a score/seguridad |
| `TERRITORY_WIN_BONUS=4` | `_territory_score_weight`, score_diff≥100 | Interacciona con fase, comida y modo |
| `TERRITORY_LOSE_REDUCTION=5` | score_diff≤-100, con suelo 0 | Igual |
| `TERRITORY_FOOD_SUPPRESS=0.25` | `_territory_food_weight` | Reduce territorio si hay comida accionable |
| `TERRITORY_CAP=3500` | `compute_adaptive_territory_bonus` | Sin efecto con máximos actuales: delta≤50 y peso≤13 →650 |
| `TERRITORY_MIN_COMBINED_LENGTH=14` | `_territory_eval_bonus` | Determina cuándo se paga el coste y aparece el bonus |

### Anticiclo

| Nombre y valor | Función / evidencia | Sensibilidad esperada y riesgo |
|---|---|---|
| `USE_ANTI_CYCLE_DEFAULT=True` | `_build_turn_context`, `_adjust_root_score` | Ablación media/alta; afecta progreso y supervivencia en rutas repetidas |
| `AC_HISTORY_SIZE=32` | `_anti_cycle_recent` crea deque acotado | Media; cambiar después de crear un historial no cambia su `maxlen` |
| `AC_MAX_PERIOD=8` | `_anti_cycle_penalty_for_candidate` | Media; patrones más largos requieren más historial y crecimiento detenido |
| `AC_MIN_REPEATS=2` | `_cycle_period_penalty` | Media; controla falsos positivos y demora de detección |
| `AC_MIN_NO_GROWTH_TURNS=8` | `_anti_cycle_penalty_for_candidate` | Media; cuenta turnos propios nuevos, no todos los plies |
| `AC_BASE_PENALTY=9000` | `_cycle_period_penalty` | Media; valor raíz, no repetido por hoja |
| `AC_REPEAT_PENALTY=3500` | Penalización por repeticiones adicionales | Media |
| `AC_SHORT_PERIOD_BONUS=1200` | Bonificación de penalización por ciclo corto | Media |
| `AC_PENALTY_CAP=30000` | Cap base y techo adicional de estrategia DESPERATE | Media; el ajuste estratégico puede alcanzar 45000 |

## Parámetros numéricos estratégicos escritos dentro de funciones

Estos valores también forman parte de la estrategia aunque no tengan un nombre global. Inventariarlos evita reducir una optimización a las constantes de la cabecera. Los índices 0/1 de coordenadas, incrementos de bucles y valores booleanos no se consideran pesos.

| Ubicación | Valores y uso exacto | Sensibilidad / riesgo esperado |
|---|---|---|
| `_trace_full_snake` (399) | DFS de reconstrucción hasta 50000 nodos por intento, luego greedy | Alto para coste y exactitud; no entrenar por win rate |
| `analyze_topology` (535), `analyze_topology_consolidated` (651) | Pocket cuando espacio≤longitud+1 y cola no alcanzable | Alto: definición de riesgo compartida |
| `_find_reachable_chokepoint` (565) | Conexiones exteriores≥2; llegar al menos tan pronto como rival | Alto en trampas; desigualdad de empate es una decisión estratégica |
| `_enemy_region_is_compressed` (574) | Salidas≤2 y espacio<mitad del área del tablero | Medio/alto; activa bonus de estrangulamiento |
| `_fe_exit_risk` (770) | 0 salidas→fatal/pocket; 1 salida→single exit | Alto; clasificación geométrica |
| `_fe_tail_space_risk` (779) | Sin cola alcanzable: margen≤1→FE_TIGHT_RISK+50000; ≤3→FE_TIGHT_RISK; ≤6→35000 | Alto; umbrales y offsets no parametrizados |
| `_future_escape_state_risk` (791) | Pocket suma `max(0,2-margen)*10000` a FE_POCKET_RISK | Alto en espacios muy pequeños |
| `_food_race_value` (1006) | Ventaja finita saturada a 6; rival inalcanzable usa 12; bono cercano a distancia≤2 | Medio; distinto régimen para inaccesible |
| `_leading_strategy_mode` (1075) | LOCK exige al menos 2 comidas concedibles | Medio/alto |
| `_losing_strategy_mode` (1080) | En ventana tardía, 2 comidas requeridas bastan para DESPERATE | Medio/alto |
| `_strategy_adjust_anti_cycle_penalties` (1115) | LOCK×0.20; LEADING×0.70; DESPERATE×1.35 y cap×1.5 | Medio; modular por fase sin rehacer detector |
| `_is_bankable_food` (1160) | Distancia propia≤2 y rival≥propia+3, o inalcanzable | Histórico legacy; no confundir con margen endgame de 6 |
| `_is_enemy_urgent_food` (1164) | Rival≤2 y llega antes que nosotros | Histórico legacy |
| `_apple_freeze_inactive` (1136) | Requiere al menos 2 objetivos | Hace inactiva esa rama en v3 normal |
| `_freeze_strength_ok` (1241) | ≥2 bancables y ≥2 concedibles, o ≥3 concedibles; además concedibles≥urgentes+1 | Histórico legacy |
| `_freeze_penalty_value` (1257) | Suma extra por ≥2 bancables y por ≥3 concedibles | Dos extras como máximo |
| `_deferred_catchup_bank_allowed` (1187) | Margen no negativo basta; perdiendo, margen≥-food_swing y required≤2 | Alto en finales ajustados |
| `_territory_score_weight` (1392) | Ventaja/desventaja de 100 puntos cambia peso | Solo con territorio ON; umbral fijo pese a dígito variable |
| `_territory_food_weight` (1400) | Distancia≤5 y abs(food_race_bonus)≥1800 activa supresión | Solo con territorio ON |
| `_territory_mode_weight` (1411) | DESPERATE×0; TRAILING×0.35; LOCK×0.50 | Solo con territorio ON |
| `compute_adaptive_territory_bonus` (1419) | Delta territorial acotado a [-50,50] | Cap efectivo de magnitud, antes de TERRITORY_CAP |
| `_pocket_terminal_value` (1461) | Nuestro pocket: -500000+espacio×100; rival: +500000-espacio×100 | Alto: retorno temprano omite score y demás evaluación; es heurística, no final autoritativo |
| `_choke_bonus` (1469) | Puerta a distancia 0:350000; otra alcanzable:150000-distancia×3000 | Alto frente a comida y movilidad |
| `_food_distance_contribution` (1483) | Llegamos primero:400-md×12; rival primero:-(250-ed×8); empate finito:100-md×8 | Medio; componente asimétrico |
| `_food_tempo` (1493) | Extra por comida cercana:200-distancia_mínima×10 | Medio; todo tempo se multiplica por dígito |
| `_final_evaluation_value` (1541) | Restantes<30 y sin ventaja:tempo×4+carrera×2; score_diff<-150:tempo×3+carrera×1.5; normal:tempo×2+carrera×1 | Alto en cambio de fase; umbral de puntos fijo |
| `_late_leading_value` (1553), `_combine_evaluation` (1560) | Restantes<30 y ventaja:espacio×50+salidas×250; omite tempo/carrera | Alto para defensa de ventaja |
| `evaluate_state_v5` (1573) | Score diferencial×500 si restantes>100, luego ×2500; movilidad=salidas×120+min(espacio,40)×8 | Alto; salto de ponderación ×5 al cruzar 100 |
| `_cut_priority` (1634) | Prioridad de ordenación puerta=100000 | Medio por búsqueda interrumpida; no es puntaje final |
| `_food_priority` (1638) | Comida correcta=20000×dígito | Medio, mismo matiz de ordenación |
| `_move_priority_score` (1645) | Número incorrecto=-250000; acercarse por Manhattan=5000; resto=0 | Medio/alto bajo presupuesto; orden determina trabajo antes de corte |
| `_exact_terminal_result` (1701), `_no_moves_terminal_score` (1740) | Suma/resta max(0,remaining) a ±TERMINAL_WIN_SCORE en muerte | Prefiere victoria más temprana y muerte más tardía en esa escala; no entrenar |
| `_fallback_candidate_score` (1908) | Espacio×15+salidas×60+cola alcanzable×1500-trampa×10000-número incorrecto×200000 | Alto cuando se usa emergencia |
| `_fallback_food_bonus` (1903) | Comida accesible:200-distancia×5 | Bajo/moderado en emergencia |
| `_anti_cycle_penalty_for_candidate` (2004) | Períodos desde 2 hasta AC_MAX_PERIOD | Medio; no considera período1 |
| `_fe_gate_scale` (2049) | Muy larga desde14; restantes≤100 suma1; perdiendo≥300 resta1 con mínimo3 | Alto: refuerza prudencia y la reduce al perder |
| Forced Trap (2086–2180) | Sigue solo con 0/1 respuesta propia; deja de forzar al recuperar ≥2 | Alto; alcance deliberadamente selectivo |
| `_tactical_critical_mobility` (2207) | Cualquiera con ≤1 jugada | Alto para disparo táctico |
| `_tactical_late_large` (2211) | Longitud combinada≥24 | Medio |
| `_tactical_any_compressed` (2215) | Cualquiera con ≤2 jugadas | Medio |
| `_tactical_close_contact` (2219) | Longitud combinada≥14, distancia≤TACTICAL_HEAD_DISTANCE y compresión | Medio/alto |
| `_tactical_edge_pressure` (2227) | Borde≤1, distancia≤max(6,TACTICAL_HEAD_DISTANCE), longitud combinada≥16 y compresión | Medio/alto |
| `_tactical_offense_promising` (2429) | Rival≤2 jugadas o cabezas a distancia≤4 | Medio; este 4 no usa TACTICAL_HEAD_DISTANCE |
| `_safe_food_tuple` (2609) | Distancia tras raíz≤SAFE_FOOD_MAX_STEPS-1; llegar estrictamente antes que rival | Medio/alto |
| `_same_real_edge_lane` (2588), `_short_shadowable_race` (2594) | Ambas posiciones a borde0; distancia propia≤3 y rival≤distancia+3 descartan bonus | Alto para regresión de persecución por borde |
| `_safe_food_lock_window` (2685) | LOCK y restantes>APPLE_BANK_CASHOUT_REMAINING bloquea bonus inmediato | Medio; no bloquea por sí mismo toda comida |
| `_decision_deadline` (2722) | Presupuesto interno mínimo0.001 s | Infraestructura, no peso |
| `_build_turn_context` (2749) | remaining_moves ausente→300; scores ausentes→0 | Compatibilidad de payload, no entrenar |
| `_iterative_root_search` (2987) | Profundidades desde1; máximo12 en time/nodes | Alto en coste/visión; fixed_depth configura otro máximo |
| `_prefer_root_move` (2963) | Empate favorece dirección actual; si persiste, conserva orden de candidatos | Medio en decisiones empatadas; registrar orden para reproducibilidad |
| `choose_direction` (3034) | `search_mode="time"`, `node_budget=12000`, `fixed_depth=6` | Cambian presupuesto, no son pesos: nodes y fixed_depth no tienen deadline de reloj |

La rama `remaining<30 and score_diff>0` de `_final_evaluation_value` queda interceptada antes por `_combine_evaluation`; el comportamiento efectivo es `_late_leading_value` y sus pesos 50/250.

### Valores de reglas y soporte que deben permanecer fijos

| Constante / comportamiento | Valor observado | Motivo para excluir de optimización |
|---|---|---|
| Movimiento normal en `_score_move_result` | +1 | Regla simulada, no preferencia |
| Comida legacy | +100 total por movimiento que come | Regla simulada |
| Dígito correcto | dígito×100; escala 1..9 | Regla v3 simulada |
| Dígito incorrecto | -500 y no crecimiento | Regla v3 simulada |
| Secuencia `FOOD_DIGITS` | `123456789`, ciclo9→1 | Protocolo/reglas |
| `DIRECTIONS` | UP(-1,0), DOWN(1,0), LEFT(0,-1), RIGHT(0,1), en ese orden | Vectores de movimiento; el orden sí influye en desempates |
| `TT_EXACT=0`, `TT_LOWER=1`, `TT_UPPER=2` | Etiquetas de tabla de transposición | No son pesos |
| `WINDOW_WIDTH=1280`, `WINDOW_HEIGHT=800`, `GLOBAL_HUD_HEIGHT=50`, `FPS=30` | Constantes de interfaz conservadas en archivo | No intervienen en estrategia |
| `bot_histories`, `TT`, `SEARCH_ABORTED`, `SEARCH_NODES`, `SEARCH_NODE_BUDGET`, `SEARCH_MODE`, `LAST_FE_STATS`, `LAST_AC_STATS`, `LAST_STRATEGY_STATS` | Estado y telemetría mutables | No son genes; requieren aislamiento entre módulos/partidas |

## Espacio pequeño de optimización propuesto

Primera etapa: **cuatro configuraciones totales**, una base y tres variantes que cambian una sola cosa cada una. Esto identifica dirección de efecto antes de mezclar parámetros. No se afirma que ninguna variante mejore todavía.

| Configuración | Cambio en memoria sobre base intacta | Hipótesis y riesgo |
|---|---|---|
| Base | Todos los parámetros originales | Referencia obligatoria |
| Territorio ON | `USE_ADAPTIVE_TERRITORY_V6=True` | Puede desempatar hacia control; coste extra por evaluación puede reducir profundidad en modo tiempo |
| Cobro endgame 12 | `ENDGAME_BANK_CASHOUT_REMAINING=12` (antes8) | Acorta ventana de retención del objetivo y permite buscar cobro antes; puede conceder antes un respawn al rival |
| Ruta comida 30000 | `SAFE_FOOD_PATH_BONUS=30000` (antes45000) | Reduce atracción a comida futura manteniendo bonus inmediato75000 y filtros de seguridad; puede perder carreras aprovechables |

Los dos últimos cambios no añaden BFS, búsquedas o módulos. El cambio de cobro solo afecta Endgame Bank; `APPLE_BANK_CASHOUT_REMAINING` queda en8, por lo que Safe Food en modo LOCK mantiene su ventana propia. Esto debe registrarse como alcance exacto de la variante.

Solo después de encontrar una señal repetible, ampliar de forma secuencial a `ENDGAME_BANK_CASHOUT_REMAINING ∈ {8,10,12}` y `SAFE_FOOD_PATH_BONUS ∈ {30000,45000,60000}`. No ejecutar de entrada el producto cartesiano. Si la muestra no contiene activaciones de una capa, informar que esa muestra no mide el parámetro; no declarar equivalencia general.

Como ablaciones posteriores útiles: pasar explícitamente `use_apple_freeze=False` o `use_ac=False`. `use_fe=False` es una ablación amplia de seguridad y no una primera candidata de mejora. Los modos `nodes` y `fixed_depth` sirven para diagnosticar decisiones reproducibles, pero no validan cumplimiento de 80 ms ni son intercambiables con producción.

### Protocolo de evaluación que tendría sentido implementar después

1. Cargar una instancia distinta del módulo R4 por jugador; limpiar/cambiar instancia por partida para impedir contaminación de `bot_histories`, TT y telemetría. Aplicar overrides antes de crear historiales.
2. Usar el motor v3 de la arena raíz, con semilla explícita, tamaño explícito, mismo conjunto de semillas entre variantes y lados A/B intercambiados por pareja. Misma semilla garantiza mismo arranque/RNG inicial, no idéntica ubicación de cada spawn tras trayectorias divergentes.
3. Separar semillas para desarrollo, selección y evaluación final. No seleccionar y proclamar mejora en las mismas semillas. Registrar el hash del bot, overrides, reglas, límites, rival, tamaño y lado.
4. Medir resultado autoritativo de cada partida: victoria/empate/derrota, muerte, derrota técnica, comida correcta/incorrecta, puntos y movimientos. El promedio de puntos no sustituye al ganador cuando hay muerte.
5. Registrar por decisión tiempo total externo, p50/p95/p99/máximo y cantidad >80 ms; además nodos, FE abortada, disparo táctico y activaciones de banca/Safe Food. La arena actual contabiliza tiempo después de la llamada y no detiene un bot bloqueado.
6. Filtro funcional primero con presupuesto determinista; verificación temporal después usando `search_mode="time"`, de forma secuencial o con CPU controlada. El modo nodes limita alfa-beta, mientras FE y táctico mantienen sus presupuestos propios; no interpretarlo como límite total idéntico de trabajo.
7. Para una futura búsqueda de pesos, fitness primario `victorias + 0.5*empates` por partida, reportado también por lado, tamaño y rival; mortalidad y tiempo son restricciones/diagnósticos. No añadir puntos sin acotar hasta que puedan anular el resultado primario. Evaluar sobre varios rivales, no solo self-play.
8. Reportar tamaño de muestra e incertidumbre. Las dos partidas de una semilla forman una pareja; analizar diferencias por pareja o intervalos remuestreados por semilla. Una muestra pequeña detecta fallos y cambios grandes, no certifica pequeñas mejoras.

## Qué rescatar de `botautodi.py` y `botevolution.py`

### Infraestructura observada

`botautodi.py` contiene un algoritmo genético autónomo. Usa población24, generaciones1000, seis partidas por individuo, mutación por gen de probabilidad0.25 y escala gaussiana0.35; cruza cada gen entre dos progenitores con probabilidad0.5, conserva los mejores3 y elige padres entre los primeros10. Abre un pool de `mp.cpu_count()` trabajadores, enfrenta cada candidato a GREEDY, SURVIVAL y cuatro genomas de población, y escribe `best_weights.json` relativo al directorio de trabajo.

El número nominal es 144 partidas por generación y hasta144000 en toda la configuración predeterminada. Cada partida usa hasta300 movimientos, con otro evaluador de una sola jugada. Ese coste no permite inferir el coste de entrenar R4 con su búsqueda.

`botevolution.py` es el cliente que carga ese JSON y ejecuta el evaluador de una jugada; no entrena. Su `DEFAULT_GENOME` contiene estos once genes:

| Gen | Rango inicial en entrenador | Predeterminado cliente | Uso observado |
|---|---:|---:|---|
| `w_food_dist` | 5..30 | 14 | Pendiente de distancia |
| `w_food_lead` | 100..600 | 380 | Llegar primero |
| `w_food_gradient` | 10..50 | 25 | Progreso hacia comida |
| `w_space` | 5..40 | 18 | Espacio propio |
| `w_exits` | 20..150 | 60 | Salidas propias |
| `w_tail_reach` | 50..300 | 150 | **No leído por el evaluador** |
| `w_pocket_trap` | 200000..800000 | 600000 | Retorno temprano de trampa |
| `w_territory` | 5..40 | 20 | Celdas a las que llegamos primero, no delta simétrico |
| `w_choke_bonus` | 50000..300000 | 120000 | **No leído por el evaluador** |
| `w_score_diff` | 500..5000 | 2500 | Puntaje diferencial; constante entre jugadas evaluadas normalmente, porque la simulación no actualiza scores |
| `w_option_delta` | 10..60 | 25 | Diferencial de salidas |

La mutación impone suelo0.1 pero no conserva los rangos superiores iniciales. Los nombres de genes no corresponden a una interfaz de parámetros R4: no se puede volcar ese JSON en R4 y esperar una estrategia entrenada equivalente.

### Problemas concretos antes de reutilizar el entrenamiento

| Evidencia estática | Consecuencia práctica |
|---|---|
| `FastBoard` fija 15×15, tres `*`, cuerpos iniciales fijos y sin números | No representa las reglas v3 ni la distribución variable de tamaños |
| `FastBoard.step`, líneas114–121, añade +100 y después +1 al comer | Entrena con +101; no coincide con +100 total del simulador R4 ni de arena raíz legacy |
| `play_match`, líneas300–324, siempre sitúa al candidato como A y empieza con A | Sesgo de lado no medido |
| `random` global sin semilla por partida/tarea; `random.choice(population)` por candidato | Evaluaciones no emparejadas y no reproducibles a partir de un ID de partida; rivales distintos por candidato |
| Cambian rivales y azar entre generaciones y `best_overall_fitness` conserva solo el máximo histórico | El récord puede reflejar muestra más fácil/afortunada y no fuerza superior |
| Fitness por muerte propia `-1000+score_A`, por muerte rival `1500+score_A` | Recompensa puntos incluso al morir; no garantiza ordenar toda victoria por encima de toda derrota |
| Final por límite: `(1000 si gana, -500 si no)+(score_A-score_B)*2+score_A` | Empate se agrupa con derrota; score puede dominar comparación con desenlaces por muerte |
| Simulación de candidatos en `decide_genome_move` no actualiza puntuaciones ni consume/refresca `food_list` antes de evaluar | Señales para entrenar no equivalen al estado que se ejecutará; `w_score_diff` no distingue normales por comida inmediata |
| Trampas retornan antes de score en evaluador | `w_score_diff` no es literalmente muerto: puede cambiar el contraste entre candidato normal y pocket; su influencia es indirecta, no la pretendida actualización de comida |
| `w_tail_reach` y `w_choke_bonus` solo están en catálogo/rangos/defaults | Se desperdician dimensiones de búsqueda sin efecto estratégico |
| `botevolution` busca cabezas entre A/1 y B/2; legalidad/BFS solo permiten espacio o `*` | Dígitos v3 pueden confundirse con cabezas y se consideran obstáculos; incompatible como rival v3 representativo |
| `botevolution` importa Pygame/WebSocket y lee JSON al importar; `choose_direction` vuelve a leerlo | Mezcla estrategia y runtime, añade I/O y cambios potenciales durante una partida |
| JSON sin esquema/versionado y ruta relativa al cwd | Pesos incompletos pueden fallar; directorio de lanzamiento decide qué archivo se lee |
| `mp.Pool(mp.cpu_count())` sin reservar capacidad ni presupuestar por decisión | Puede saturar la máquina y sesgar evaluación de tiempos de R4 |

**Rescatable:** el esquema conceptual de genoma, mutación/cruce, elitismo, checkpoints y ejecución de tareas independientes. **Requiere rediseño para R4:** simulador v3, adapter de parámetros, RNG con semillas por tarea, emparejamiento de lados, fitness centrado en resultado, rivales fijos de referencia, validación separada, límite de CPU y metadatos reproducibles. No recomiendo copiar su evaluador, pesos ni runtime en el bot modular.

La vía más pequeña es un evaluador externo que importe R4 y arena v3, aplique los tres overrides propuestos y guarde resultados. El algoritmo genético solo tendría sentido más tarde, una vez que ese evaluador mida algo confiable y existan parámetros con sensibilidad demostrada.

## Límites de este documento

No se ejecutaron entrenamientos ni se validó una mejora competitiva en este subanálisis. No se abrieron conexiones remotas, no se usaron credenciales y no se cambiaron parámetros persistentes. Las propuestas requieren autorización antes de incorporarse al bot. Los experimentos independientes que pueda incluir el informe general deben leerse con su propio tamaño de muestra, presupuesto y metodología.
