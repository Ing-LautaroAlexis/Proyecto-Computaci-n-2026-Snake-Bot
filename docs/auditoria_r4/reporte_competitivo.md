# Auditoría competitiva del bot modular R4

> **Nota (reorganización 2026-09-30):** documento rescatado de la antigua carpeta `competitive_audit/`. Analiza el bot modular R4 (`botv7.6_v4.py`), hoy en `versions/chatgpt/modular/`. Las rutas `BOT CHATGPT PLUS/...` y `BOT GEMINI PRO/...` son las ubicaciones de esa época; los scripts y resultados crudos (`results/`, `*.json`) no se conservaron en el repositorio.

**No se modificó la estrategia.** Hash SHA-256 al cierre: `85f74cfd69d8133e07ce181fc3a90906e672b280a5a1c2436a27250622f7b24a`.

Se completaron **117 partidas**: 81 con configuración base y el resto con overrides en memoria. Las partidas fallidas están registradas aparte; no se cuentan como victorias.

## Qué demuestra y qué no demuestra esta muestra

Frente a las dos estrategias rivales v3 distintas, la base obtuvo 9 victorias, 11 derrotas y 0 empates en 20 partidas.
La referencia Gemini `botv7.6.py` tiene el mismo AST estratégico que R4 y se utiliza como control de self-play. Las victorias rápidas contra versiones legacy no son evidencia sólida de fuerza bajo v3.
Las variantes se evaluaron en dos semillas, tres referencias y ambos lados: doce partidas por configuración. Es exploración, no validación independiente de una mejora pequeña. La carga de Windows produjo variabilidad temporal importante; el bot usa deadline de reloj y eso también cambia cuánto busca.

## Baseline por rival

Reglas v3, máximo 300 movimientos, dimensiones sorteadas por semilla, inicios estándar del motor. W/L/D desde el punto de vista del v4. Δscore es descriptivo: morir puede perder aun con más puntos.
Semillas utilizadas: 970001, 970002, 970003, 970011 y 970012. Los tamaños sorteados fueron 13×14, 14×12, 17×13 y 17×15. El estrés sintético del perfil añade, entre otros, 12×12 y 20×20. Los resultados no cubren todas las dimensiones ni posiciones iniciales posibles.

| Rival | Partidas | W | L | D | Δscore medio | Duración media s | Juegos técnicos |
|---|---:|---:|---:|---:|---:|---:|---:|
| BOT CHATGPT PLUS/Botv7.6/botv7.6_v3.py | 10 | 5 | 5 | 0 | -139.40 | 19.34 | 0 |
| BOT GEMINI PRO/botv7.6_v3.py | 10 | 4 | 6 | 0 | -1129.20 | 20.69 | 0 |
| BOT GEMINI PRO/botv7.6.py | 10 | 5 | 5 | 0 | 129.90 | 18.05 | 0 |
| BOT GEMINI PRO/botv6.1.py | 1 | 1 | 0 | 0 | 3594.00 | 21.16 | 1 |
| BOT GEMINI PRO/snakechatgpt.py | 2 | 2 | 0 | 0 | 1500.50 | 0.77 | 0 |
| BOT GEMINI PRO/BOT9de10PruebaLocal.py | 2 | 2 | 0 | 0 | 1500.50 | 0.83 | 0 |
| BOT GEMINI PRO/BotV2.5.py | 2 | 2 | 0 | 0 | 1500.50 | 0.93 | 0 |
| BOT GEMINI PRO/BotV2.py | 2 | 2 | 0 | 0 | 1500.50 | 0.91 | 0 |
| BOT GEMINI PRO/botV2_vs_2.1.py | 2 | 2 | 0 | 0 | 1500.50 | 0.73 | 0 |
| BOT GEMINI PRO/BotV2conCiclomatica2.py | 2 | 2 | 0 | 0 | 1500.50 | 0.88 | 0 |
| BOT GEMINI PRO/BotV2sinCliclomatica.py | 2 | 2 | 0 | 0 | 1500.50 | 1.11 | 0 |
| BOT GEMINI PRO/botV3.1new.py | 2 | 2 | 0 | 0 | 1500.50 | 2.19 | 0 |
| BOT GEMINI PRO/botV3.py | 2 | 2 | 0 | 0 | 1500.50 | 1.30 | 0 |
| BOT GEMINI PRO/botv5-opti.py | 2 | 2 | 0 | 0 | 1500.50 | 1.27 | 0 |
| BOT GEMINI PRO/botv5.1.opt.fe.fr.ac.py | 2 | 2 | 0 | 0 | 1500.50 | 1.15 | 1 |
| BOT GEMINI PRO/botv5.1.opt.fe.py | 2 | 2 | 0 | 0 | 1500.50 | 1.33 | 1 |
| BOT GEMINI PRO/botv5.2.3.py | 2 | 2 | 0 | 0 | 1500.50 | 1.79 | 1 |
| BOT GEMINI PRO/botV5.5.py | 2 | 2 | 0 | 0 | 1500.50 | 1.65 | 0 |
| BOT GEMINI PRO/botv5.opt.fe.fr.py | 2 | 2 | 0 | 0 | 1500.50 | 1.00 | 1 |
| BOT GEMINI PRO/botV5.py | 2 | 2 | 0 | 0 | 1500.50 | 0.99 | 0 |
| BOT GEMINI PRO/botv6.py | 2 | 2 | 0 | 0 | 1500.50 | 1.65 | 1 |
| BOT GEMINI PRO/snake1.1.py | 2 | 2 | 0 | 0 | 2746.00 | 4.19 | 0 |
| BOT GEMINI PRO/snake1.py | 2 | 2 | 0 | 0 | 2897.00 | 4.51 | 0 |
| BOT GEMINI PRO/snake2.0.py | 2 | 2 | 0 | 0 | 2547.50 | 2.91 | 0 |
| BOT GEMINI PRO/snake2.1.py | 2 | 2 | 0 | 0 | 2547.50 | 2.82 | 0 |
| BOT GEMINI PRO/snake3.0.py | 2 | 2 | 0 | 0 | 2547.50 | 2.82 | 0 |
| BOT GEMINI PRO/snakeagresiva.py | 2 | 2 | 0 | 0 | 1500.50 | 0.66 | 0 |
| BOT GEMINI PRO/snakebera.py | 2 | 2 | 0 | 0 | 1500.50 | 0.74 | 0 |
| BOT GEMINI PRO/SnakeV2alpha.py | 2 | 2 | 0 | 0 | 1649.50 | 1.51 | 1 |

A/B y tiempos crudos por rival están en `results/summary.json`; la tabla exportable está en `results/baseline.csv`.

### Fuera del benchmark completo

- `BOT CHATGPT PLUS/SNAKE_V76_MODULAR_R4/botv7.6_v4.py`: Candidate itself.
- `BOT CHATGPT PLUS/SNAKE_V76_R4_JUGAR/botv7.6_v4.py`: Same executable AST as candidate.
- `BOT GEMINI PRO/botevolution.py`: {'ok': False, 'exception': '10s preflight timeout'}.
- `BOT GEMINI PRO/botV2_vs_botV3PRUEBAFALLIDA.py`: {'ok': False, 'exception': 'IndexError'}.
- `BOT GEMINI PRO/Botv2conCiclomatica vs BotV2.5.py`: No top-level choose_direction function.
- `BOT GEMINI PRO/botV3.1.py`: {'ok': False, 'exception': 'NameError'}.
- `BOT GEMINI PRO/import asyncio.py`: No top-level choose_direction function.
- `BOT GEMINI PRO/snakeclaude.py`: Requires additional argument; no strategy/UI adapter introduced.

Un ensayo `screen` contra `botv6.1.py` como A superó el límite auxiliar de 100 segundos. No se adjudica ganador ni se identifica sin más al responsable del bloqueo.

## Rendimiento real

| Muestra sin profiler | n | Media ms | p95 ms | p99 ms | Máximo ms | >80 ms |
|---|---:|---:|---:|---:|---:|---:|
| Baseline completa | 4850 | 68.15 | 98.65 | 232.83 | 1381.55 | 360 |
| Baseline: referencias v3 | 4099 | 68.49 | 98.65 | 234.76 | 1381.55 | 305 |
| Repetición de estrés controlada | 78 | 47.71 | 65.31 | 69.78 | 69.78 | 0 |

En 3390 decisiones base con CPU registrada, la media de reloj fue 67.54 ms y la de CPU 44.46 ms. Hay muestras extremas con muy poca CPU contabilizada: los excesos no se pueden atribuir enteramente a cálculos del bot. El contador de CPU de Windows tiene resolución limitada.
No hubo concurrencia entre partidas de esta auditoría. Eso no garantiza CPU exclusiva de la máquina. Los 80 ms son el nominal del código; la arena no aplica derrota automática por excederlos. No se puede certificar aquí que producción siempre cumpla ese límite.

### Tiempo por componente con instrumentación acotada

Wrappers en límites de funciones, asignación **exclusiva por decisión**. Los valores incluyen coste de instrumentación; se acompañan de control de trabajo fijo y latencia sin instrumentar. La búsqueda inclusiva contiene evaluación/BFS y no debe sumarse a los componentes exclusivos.

| Componente | Media ms | p95 ms | p99 ms | Máximo ms |
|---|---:|---:|---:|---:|
| topology_bfs | 38.60 | 60.90 | 63.36 | 63.36 |
| tactical_traps | 9.30 | 17.51 | 29.25 | 29.25 |
| safe_food | 4.08 | 6.58 | 8.00 | 8.00 |
| alpha_beta_search | 1.30 | 2.42 | 4.56 | 4.56 |
| future_escape | 0.67 | 1.07 | 6.03 | 6.03 |
| body_reconstruction | 0.49 | 2.31 | 4.16 | 4.16 |
| move_generation | 0.41 | 1.07 | 1.11 | 1.11 |
| forced_trap | 0.30 | 0.69 | 1.70 | 1.70 |
| other_control | 0.29 | 0.45 | 0.56 | 0.56 |
| food_target | 0.23 | 0.86 | 1.23 | 1.23 |
| food_scoring | 0.18 | 0.45 | 0.70 | 0.70 |
| anti_cycle | 0.05 | 0.09 | 0.11 | 0.11 |
| banking | 0.04 | 0.13 | 0.18 | 0.18 |
| adaptive_territory | 0.01 | 0.03 | 0.04 | 0.04 |

La búsqueda inclusiva promedió 26.68 ms. Topología/BFS supone aproximadamente 68.98% del tiempo instrumentado acotado de esta selección, no de todas las partidas.

Cocientes perfil/base con trabajo fijo: 0.84×, 0.95×, 1.25×. El profiler exhaustivo por función tuvo perturbación mucho mayor (~13×); se conserva para localizar funciones calientes, no para afirmar que esos milisegundos son latencia normal.

## Derrotas: observación frente a causalidad

- puntos al agotar movimientos: 12 derrotas base frente a referencias v3.
- sin salida inmediata legal: 4 derrotas base frente a referencias v3.

No se etiquetó automáticamente como “mala territorialidad”, “agresividad” o “horizonte insuficiente” una derrota por puntos. Esas causas requieren repetir desde la posición con alternativas controladas. Las posiciones y diagnósticos finales están en `results/trajectory_audit.json` y los movimientos completos en `games.jsonl`.

## Experimentos controlados

| Configuración | W | L | D | Variación neta de puntos de torneo contra base emparejada |
|---|---:|---:|---:|---:|
| baseline | 5 | 7 | 0 | +0.0 |
| territory_on | 5 | 7 | 0 | +0.0 |
| bank_cashout_12 | 5 | 7 | 0 | +0.0 |
| safe_path_30000 | 5 | 7 | 0 | +0.0 |

Cambios: `territory_on` activa `USE_ADAPTIVE_TERRITORY_V6`; `bank_cashout_12` cambia `ENDGAME_BANK_CASHOUT_REMAINING` de 8 a 12; `safe_path_30000` baja `SAFE_FOOD_PATH_BONUS` de 45000 a 30000.

| Configuración | Decisiones con banca activa | Banca activa con restantes 9..12 | Camino Safe Food disponible |
|---|---:|---:|---:|
| baseline | 4 | 0 | 195 |
| territory_on | 11 | 1 | 227 |
| bank_cashout_12 | 8 | 0 | 208 |
| safe_path_30000 | 7 | 2 | 207 |

Diferencias de resultado sin activación relevante del parámetro no demuestran su efecto: la ejecución temporal puede divergir por carga incluso con comportamiento parametrizado idéntico en los estados visitados.

### Escape Futuro: disponibilidad efectiva de la capa

En la base se registraron 4539 abortos FE en 4850 decisiones. `_finalize_fe_penalties` devuelve penalizaciones cero cuando FE aborta. Esto demuestra que una capa existente rara vez termina en estas condiciones; no demuestra que causó las cuatro muertes.
Se probaron 8/12/16 ms de presupuesto FE, sin editar el archivo y conservando el deadline total. Son 12 posiciones guardadas por dos repeticiones, no partidas nuevas:

| Presupuesto FE ms | Evaluaciones | Finalizadas/aplicadas | Media total ms | Máximo ms | >80 ms |
|---|---:|---:|---:|---:|---:|
| 8 | 24 | 0 | 59.39 | 192.26 | 2 |
| 12 | 24 | 1 | 60.11 | 354.75 | 1 |
| 16 | 24 | 4 | 50.53 | 71.75 | 0 |

Subir el presupuesto a 16 ms solo completó 4/24 evaluaciones. No basta para recomendarlo ni prueba mejores tiempos: la muestra también tiene variabilidad del sistema. La prioridad es investigar el coste de la capa y sus recorridos, no añadirle tiempo indiscriminadamente.

## Reconstrucción, respawn y memoria

Se comprobaron 4099 observaciones normales: 0 discrepancias del cuerpo propio y 0 del rival respecto al motor real.
El fixture con cuatro posiciones propias omitidas sí reproduce una cola falsa y una dirección ilegal admitida. Las ocho decisiones de prueba no eligieron esa dirección. Es un bug de robustez demostrado, sin pérdida competitiva demostrada ni confirmación de que el servidor haga avanzar nuestra serpiente durante una ausencia.

Exposición del modelo de comida en continuaciones realmente jugadas de hasta doce plies:

```json
{
  "candidate_windows": 4099,
  "full_12_ply_windows": 3934,
  "no_observed_disagreement": 4084,
  "next_target_disagreement": 15
}
```

Estas ventanas se solapan y no son muestras independientes. Una discrepancia indica que la simplificación puede importar en esa continuación; no demuestra que causó la elección inicial. No se evaluó un nuevo algoritmo de respawn ni se demostró aumento de victorias al introducirlo.
Después de un acierto, los cuatro objetivos siguientes ya están visibles; el problema no es que toda comida futura sea desconocida. Sí faltan los nuevos dígitos que aparecen, y comer un dígito incorrecto puede adelantar la divergencia del objetivo. Fixtures: `state_audit/REPORT.md`.
Memoria medida: 0,449 MiB/100 historiales; 4,476 MiB/1000; 44,689 MiB/10000, con cuerpos de longitud 3 e historial anticiclo lleno. No es una prioridad de win-rate para sesiones ordinarias.

## Parámetros y entrenamiento

El inventario completo de nombres, valores, funciones, sensibilidad esperada y riesgo está en [parameters_training/README.md](parametros.md). Sensibilidad estimada no equivale a sensibilidad medida.
Espacio pequeño propuesto, solo si se confirma activación/efecto: cobro endgame {8,10,12}; bonus de camino {30000,45000,60000}; territorio como ablación booleana. No variar caps que no se activan ni constantes de reglas. Los flags capturados como defaults requieren kwargs explícitos, no solo asignar globals.
Del entrenador antiguo rescataría la organización de candidatos, mutación, elitismo y checkpoints. No reutilizaría su motor: 15×15/asteriscos, candidato siempre A, semillas no emparejadas, fitness que mezcla puntos con victoria y genes sin uso. Para R4: motor v3 existente, módulos aislados, parejas A/B, varios rivales, semillas separadas para ajuste y validación, restricciones de tiempo/mortalidad, registro de hashes y CPU controlada.

## Candidatas de mejora; no son mejoras demostradas

| Prioridad | Modificación candidata | Beneficio esperado y evidencia | Riesgo / dificultad / tiempo |
|---|---|---|---|
| 1 | Reducir trabajo redundante y coste de recorridos BFS/topología conservando su resultado | ~69% del perfil acotado y FE abortada en 4539/4850 decisiones; podría permitir completar FE y dejar más presupuesto a búsqueda | Riesgo medio; dificultad media; debería reducir CPU. Exigir equivalencia determinista y nuevo torneo |
| 2 | Calibrar banca solo en posiciones donde realmente se activa | Peso puede ser alto y escala por dígito; los resultados exploratorios no bastan para elegir 12 | Riesgo medio; dificultad baja; mismo coste asintótico |
| 3 | Calibrar Safe Food sobre regresiones y partidas nuevas | Se ejercitó el bonus de camino; comparar la tabla antes de promover cualquier valor | Riesgo medio; dificultad baja; sin búsqueda adicional |
| 4 | Validar continuidad/ocupación del historial antes de confiar en la cola | El fixture prueba un candidato ilegal; mejora robustez, sin win-rate demostrado en flujo normal | Riesgo medio por ambigüedad del cuerpo sin historial; dificultad media; coste pequeño salvo reconstrucción |

No se propone activar territorio ni incorporar simulación estocástica como mejora por defecto: su beneficio competitivo todavía no está validado. No hace falta completar cinco propuestas sin evidencia.

## Si solo se pudiera realizar una modificación

**Elegiría una optimización localizada del cálculo de topología/BFS que mantenga exactamente sus resultados.** La razón es liberar tiempo para las capas que el v4 ya tiene, sin agregar una heurística nueva ni cambiar las reglas, especialmente porque Escape Futuro aborta con mucha frecuencia. El perfil ofrece evidencia de coste, no una garantía de más victorias: antes de incorporarla exigiría equivalencia con presupuesto fijo, regresiones y un benchmark separado bajo carga controlada. Los resultados actuales no justifican prometer una mejora de win-rate para ningún cambio.

La estrategia no fue editada; cualquier implementación necesita aprobación. Los comandos para repetir y los límites metodológicos completos están en [README.md](metodo.md).
