# Casos de estado, respawn y memoria del v4

> **Nota (reorganización 2026-09-30):** documento rescatado de la antigua carpeta `competitive_audit/`. Analiza el bot modular R4 (`botv7.6_v4.py`), hoy en `versions/chatgpt/modular/`. Las rutas `BOT CHATGPT PLUS/...` y `BOT GEMINI PRO/...` son las ubicaciones de esa época; los scripts y resultados crudos (`results/`, `*.json`) no se conservaron en el repositorio.

Objetivo exclusivo: `BOT CHATGPT PLUS/SNAKE_V76_MODULAR_R4/botv7.6_v4.py`.
No se modificó ese archivo ni otro archivo existente. El script comprueba SHA-256 antes y después.
Los números y fixtures completos están en `results.json`.

Reproducción desde la raíz:

```powershell
.\.venv\Scripts\python.exe -B competitive_audit/state_audit/audit_state.py
```

## 1. Reconstrucción con snapshots perdidos: bug reproducible

La historia inicial corresponde a A `[(2,3),(2,2),(2,1)]`, cabeza primero.
Se ejecutan cuatro movimientos propios válidos `DOWN, LEFT, UP, UP`, intercalados
con movimientos válidos del rival, sin entregar los snapshots intermedios a `get_bodies`.

| Estado después de los movimientos | Cuerpo de A, cabeza primero |
|---|---|
| Motor real | `[(1,2),(2,2),(3,2)]` |
| Reconstrucción con historial antiguo | `[(1,2),(2,3),(2,2)]` |

Ambas longitudes son 3. La reconstrucción conserva una celda vacía y trata el cuello
real `(2,2)` como cola. `get_legal_moves_raw` incorpora `DOWN`, una jugada contra cuerpo
propio; el motor real confirma la colisión al ejecutarla.

Causa: `_resync_path_if_short` solo reconstruye si `len(path) < cell_count` (v4:424);
`get_bodies` añade una sola cabeza y recorta por longitud sin comprobar ocupación ni
continuidad (v4:452). `_legal_destination` permite entrar en la cola recibida (v4:501).

**Impacto demostrado:** cuerpo incorrecto y candidato ilegal aceptado por la interfaz
interna. **Impacto competitivo todavía no demostrado:** las ocho decisiones auxiliares
con/sin historial, `remaining_moves` 1/10/60/300 y búsqueda determinista
`search_mode="nodes", node_budget=100` eligieron jugadas legales; no hubo derrota de v4
observada por este fallo. Sus tiempos no son muestras de rendimiento del modo normal.

La secuencia es válida en la arena, pero no demuestra que la misma serpiente pueda
avanzar cuatro veces mientras este cliente está desconectado. En un flujo alternado
normal, cada cliente observa un movimiento propio entre turnos. La semántica remota
de recuperación, jugadores duplicados y acciones durante la ausencia no está
disponible para verificarla aquí. No se atribuye frecuencia real a este caso.

## 2. Comida nueva: simplificación reproducible, frecuencia competitiva desconocida

Se compararon `make_move` (v4:712) y el motor real `SnakeArenaEngine.step` (arena:418)
sobre estados conocidos, con semillas fijas y acciones iguales.

### Cadena de aciertos v3

Fixture 12x12: A empieza en `(5,2)`, con los dígitos 1..5 consecutivos en `(5,3)`..`(5,7)`.
A come los cinco, mientras B se desplaza sin comer.

| Aciertos de A | Objetivo del motor | Objetivo del simulador |
|---|---|---|
| 1 | 2 | 2 |
| 2 | 3 | 3 |
| 3 | 4 | 4 |
| 4 | 5 | 5 |
| 5 | 6, en posición sorteada | Ninguno |

Los objetivos siguientes al primer acierto **no son todos desconocidos**: 2..5 ya estaban
visibles. Este detalle reduce el alcance de la afirmación anterior sobre respawn.
No significa que toda la simulación sea exacta hasta el quinto acierto: desde el primer
acierto aparece un 6 nuevo, que todavía es incorrecto y podría penalizar una trayectoria
que la simulación cree vacía. Después de cinco aciertos, también falta el objetivo activo.
El ejemplo requiere nueve plies porque B no come; con ambos actores consumiendo puede
agotarse la comida visible antes, según la posición.

### Un dígito incorrecto adelanta la divergencia

Si A come primero el 2 incorrecto y después el 1 correcto, el motor respawnea el 2 y
lo conserva como siguiente objetivo. El simulador elimina el 2 y, tras el 1, considera
que debe perseguir el 3. El test confirma `real_target='2'`, `sim_target='3'`.

Causa: `_refresh_food_after_move` (v4:707) vuelve a inferir el objetivo del tablero
simulado, pero `make_move` nunca crea comida nueva; el motor sí crea un dígito tras cada
consumo, correcto o incorrecto (`arena.py:371`, especialmente 393-400).

**Clasificación:** divergencia del modelo demostrada con casos concretos; no se ha
medido una frecuencia apreciable de decisiones estratégicamente malas por ella.
Los fixtures usan acciones prefijadas y no demuestran que v4 escogería esas acciones.
Agregar aleatoriedad, rollout de respawn o un bonus nuevo todavía carece de evidencia
de mejora de win-rate. Haría falta comparar decisiones en posiciones realmente perdidas
y evaluar continuaciones sobre semillas de respawn independientes.

## 3. Memoria de `bot_histories`: crecimiento medido

Se utilizó `tracemalloc` con el `get_bodies` real y `_update_anti_cycle_history`, sin
ejecutar búsquedas. Cada partida tiene dos cuerpos de longitud 3 y el historial
anticiclo lleno con 32 cabezas; IDs y cabezas recientes son sintéticos.

| Partidas retenidas | Memoria Python retenida | Bytes por partida |
|---:|---:|---:|
| 100 | 0,449 MiB | 4713 |
| 1000 | 4,476 MiB | 4693 |
| 10000 | 44,689 MiB | 4686 |

Al vaciar únicamente el diccionario auxiliar del experimento quedaron unos 2,9 KB de
asignaciones instrumentadas. No se modificó la limpieza del bot real.

`my_path`/`en_path` se recortan al tamaño del cuerpo (v4:463-464), y `ac_recent_heads`
usa `deque(maxlen=AC_HISTORY_SIZE)` (v4:1942, constante en 130). Por eso no hay un
historial de movimientos ilimitado **dentro** de una partida; el crecimiento viene
del número de `game_id` conservados. No hay eliminación en v4; `game_over` del runtime
solo actualiza el visor (`snake_runtime.py:61`).

**Impacto práctico:** en cientos o unos miles de partidas, este diccionario por sí solo
consume una cantidad moderada de memoria bajo el fixture; no se demostró ralentización
de decisiones ni pérdida de partidas. En procesos de muy larga duración, el crecimiento
lineal sí justifica limpieza de estado terminado. Los cuerpos largos aumentan estos
valores; no se presenta el fixture de longitud 3 como cota superior. Son asignaciones
Python retenidas, no RSS del proceso, y no incluyen la retención del visualizador.

## Prioridad resultante

- Validar/reconstruir un historial incongruente es una mejora de robustez defendible,
  pero su aumento de win-rate real aún no se midió.
- Limpiar historias finalizadas es mantenimiento de sesiones largas, con evidencia
  de crecimiento pero sin beneficio competitivo inmediato demostrado.
- Respawn merece un experimento específico si los replays de derrotas lo señalan;
  los casos existentes no justifican introducir un modelo aleatorio ahora.
