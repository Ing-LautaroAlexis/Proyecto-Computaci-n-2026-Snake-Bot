# Requisitos del bot y tests

Esta carpeta junta **todo lo que el bot tiene que cumplir**. Cada requisito tiene
un test que lo verifica automáticamente contra el bot operativo
`src/bot_final/bot_3.9.3.py` (más `snake_runtime.py` y `snake_visualizer.py`).

## Cómo correrlos

Desde la raíz del proyecto, con el entorno activado:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

En Windows también sirve doble clic en `RUN_TESTS.bat`.

La corrida falla si **cualquier test falla** o si la **cobertura baja del 90 %**
(configurado en `pytest.ini`). GitHub Actions corre lo mismo en cada push.

## Qué tiene que cumplir el bot

### 1. Reglas del juego (v3) — `test_v3_rules.py` · 13 tests

- Lee bien tableros rectangulares (12×20, 20×12) y el tamaño aunque falten metadatos.
- Los dígitos `1` y `2` del tablero son comida, no cabezas de serpiente.
- Identifica el dígito correcto a comer (incluye el salto 9 → 1).
- Los dígitos incorrectos son celdas pisables.
- Comer el dígito correcto suma `dígito × 100` y hace crecer; el incorrecto
  penaliza sin crecer, y la simulación se puede deshacer.
- La comida clásica `*` sigue funcionando igual.
- `choose_direction` devuelve un movimiento válido en tableros numerados rectangulares.

### 1b. Reglas de octubre (v7 a v10) — `test_v7_v10_rules.py` · 8 tests

- Las casillas al alcance de una bomba (💣 a 2, 🧨 a 1, con diagonales) se tratan como muro, y el bot no se mete en ellas.
- Las `*` de los disparos no esconden los dígitos.
- `Ⓐ`/`Ⓑ` y `⭐` se pueden pisar; un símbolo desconocido se trata como muro.
- Se ignora el selector de variante de los emojis al leer el tablero.
- Con invencibilidad (cabeza en minúscula) el bot encuentra igual su cabeza.
- En un tablero de 30×30 decide en menos de 200 ms.

### 2. Estrategia y caminos internos — `test_quality_paths.py` · 41 tests

Recorre cada capa de decisión para que no rompa en casos borde: parsing,
historial de cuerpos, topología y cuellos de botella, simulación reversible,
Future Escape (FE), carrera por comida, Apple Freeze / Endgame Bank, territorio,
búsqueda alfa-beta con tabla de transposición, fallback de emergencia,
anti-ciclo, trampas tácticas y comida segura.

### 3. Errores vistos en partidas reales — `test_real_match_regressions.py` · 5 tests

Situaciones que hicieron perder partidas y no se pueden repetir:

- La distancia al borde usa los bordes reales del tablero rectangular.
- La comida pegada al borde no se considera "segura" (partida vs. Candela).
- El Endgame Bank posterga la comida cuando conviene (partida vs. Thiago)
  y deja de postergar en los últimos 8 movimientos.
- La penalización del bank escala con el valor del dígito.

### 4. Auditoría histórica — `test_historical_regression.py` · 21 chequeos

Ejecuta la auditoría de corrección guardada en
`REFERENCE_DO_NOT_DEPLOY.snapshot` (versión congelada V6/V7.5) contra el bot
actual: make/unmake reversible, tabla de transposición, Future Escape,
anti-ciclo, controlador de estrategia, trampas forzadas, cierre de partida por
puntaje exacto, etc. Corre al importarse, así que si falla aparece como
error de colección de pytest.

### 5. Misma decisión que la versión de referencia — `test_refactor_equivalence.py` · 100 escenarios

En 100 tableros aleatorios fijos (semilla constante, presupuesto de 24 nodos)
el bot actual tiene que elegir **exactamente el mismo movimiento** que el
snapshot de referencia. Sirve para detectar cambios de comportamiento no buscados.
> Si a propósito cambiás la estrategia (por ejemplo, al pasar a V8.1), este test
> va a fallar y hay que actualizar la referencia conscientemente.

### 6. Partidas de humo — `v3_arena_smoke.py` · 5 partidas

Dos copias del bot juegan 24 turnos en tableros 12×20, 20×12, 12×12, 20×20 y
17×14. El bot nunca puede devolver un movimiento inválido.

### 7. Conexión y visor — `test_runtime_ui.py` · 11 tests

El runtime WebSocket (turnos, puntajes, ganador, fin de partida, token, hilos)
y el visualizador Pygame (colores, layout, HUD) funcionan con dobles de prueba,
sin servidor ni pantalla reales.

### 8. Estrategia nueva (3.9.2 en adelante) — `test_strategy_392.py` · 6 tests, `test_strategy_393.py` · 4 tests

- No se come un número si eso le regala al rival el siguiente y el rival vale más (3.9.2).
- La X vale más que un número chico al principio de la partida (3.9.2).
- El bot ve las X hasta 40 casillas y va a buscarlas; con la vista de 8 de la 3.9.2 no iba (3.9.3).
- Una X a la que el rival llega apenas antes también se pelea (3.9.3).

## Archivos de apoyo

| Archivo | Para qué está |
| --- | --- |
| `test_existing_scripts.py` | Hace que pytest ejecute los puntos 5 y 6, que originalmente eran scripts sueltos. |
| `REFERENCE_DO_NOT_DEPLOY.snapshot` | Bot congelado que sirve de "oráculo" para los puntos 4 y 5. **No borrar ni jugar con él.** |
| `quality_check.py` | Mide complejidad ciclomática (nota A–F por función). No corre con pytest: `python tests/quality_check.py`. Hoy V8.0 tiene algunas funciones fuera de nota A. |
| `RUN_TESTS.bat` | Atajo de Windows para correr `python -m pytest` desde la raíz. |
| `__init__.py` | Marca la carpeta como paquete de Python. |

## Si cambiás el bot operativo

Todos los tests cargan `src/bot_final/bot_3.9.3.py` por nombre. Si el bot
principal pasa a ser otro archivo, hay que actualizar la ruta `BOT` / `CURRENT`
al principio de cada test.
