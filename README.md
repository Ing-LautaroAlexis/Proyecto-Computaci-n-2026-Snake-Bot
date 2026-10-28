# SnakeBot

Bot competitivo de Snake para el code challenge de la universidad. El bot que
juega hoy es la **3.10.1** (`src/bot_final/bot_3.10.1.py`), adaptada a las reglas
hasta la v10 (estrella e invencibilidad, 28/10). El resto del repositorio guarda la evolución
Gemini → ChatGPT y las herramientas para probarlo.

## Cómo se numeran las versiones

`bot_INCREMENTO.REGLAS.VERSION.py`, por ejemplo `bot_3.9.1.py`:

1. **Incremento** de la materia en el que se hizo (septiembre = 2, octubre = 3).
2. **Reglas** del challenge que soporta (v9 = disparos).
3. **Versión** desarrollada dentro de ese incremento y esas reglas.

| Versión | Antes se llamaba | Reglas | Dónde está |
| --- | --- | --- | --- |
| 2.3.1 | ChatGPT V7.6 (`botv7.6_v3.py`) | hasta v3 | `versions/chatgpt/v7.6/` |
| 2.3.2 | Modularización R4 (`botv7.6_v4.py`) | hasta v3 | `versions/chatgpt/modular/` |
| 2.3.3 | ChatGPT V8.0 (`botv8.0_v5.py`) | hasta v3 | `versions/chatgpt/v8.0/` |
| 2.6.1 | v6actualizado / "V8.1" (`v6.py`) | hasta v6 | `versions/chatgpt/v6actualizado/` |
| 3.9.1 | — | hasta v9 | `versions/Claude/3.9.1/` |
| 3.9.2 | — | hasta v9: no regala el número que viene y valora más las X | `versions/Claude/3.9.2/` |
| 3.9.3 | — | hasta v9: ve y pelea las X aunque estén lejos | `versions/Claude/3.9.3/` |
| 3.9.4 | — | hasta v9: no se mete en un pasillo sin salida para comer | `versions/Claude/3.9.4/` |
| **3.10.1** | — | hasta v10: estrella e invencibilidad; todo en complejidad A | `src/bot_final/` (la que juega) |

## Estructura

```text
src/bot_final/          El bot que juega (3.10.1) + snake_runtime.py (conexión) + snake_visualizer.py (visor)
tests/                  Todo lo que el bot tiene que cumplir  →  ver tests/README.md
docs/                   Documentación                         →  ver docs/README.md
  evolucion.md            Historia de versiones
  auditoria_r4/           Análisis de rendimiento y parámetros del bot R4
versions/               Versiones anteriores (solo historial, no se tocan)
  gemini/                 v1, v2, v3, v3.1, v5, v5.5
  chatgpt/                v7.6, modular (R4), v8.0, v6actualizado (en desarrollo)
  Claude/                 3.9.1, 3.9.2, 3.9.3, 3.9.4
simulador/              Simulador con las reglas hasta la v10 → ver simulador/LEEME.txt
arena.py                Simulador local para enfrentar bots entre sí
.github/workflows/      CI: tests, cobertura y complejidad (xenon) en cada push
.coveragerc             Qué mide la cobertura (solo src/bot_final, sin los tests)
.local_backup/          Respaldo local de los archivos originales (no se sube a Git)
requirements.txt        Dependencias para jugar
requirements-dev.txt    Dependencias para testear
pytest.ini              Configuración de tests y cobertura
```

Regla práctica: **se trabaja en `src/bot_final/`**. Cuando una versión nueva
queda estable, se guarda una copia en `versions/` como historial.

## Instalación

Python 3.12.

```sh
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell
source .venv/bin/activate           # Linux/macOS
python -m pip install -r requirements.txt
```

## Jugar

```sh
python src/bot_final/bot_3.10.1.py TU_TOKEN
```

Abre la conexión WebSocket y el visor Pygame (necesita entorno gráfico).

## Enfrentar bots localmente

```sh
python arena.py
```

La arena encuentra sola cualquier `.py` que tenga `def choose_direction` (ignora
`tests/`, `.venv/` y cachés). `R`/Enter reinicia, `N` cambia la semilla y `Tab`
intercambia lados. Los resultados se guardan en `arena_results/` (local, no se
sube a Git).

## Tests y cobertura

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

108 tests sobre reglas (v3 y v7–v10), estrategia, regresiones de partidas reales, equivalencia
con la versión de referencia, partidas de humo, runtime y visor. La cobertura se
mide sobre los tres archivos de `src/bot_final/` y tiene que ser **≥ 90 %** o la
corrida falla. El detalle de qué verifica cada test está en
[tests/README.md](tests/README.md).

La cobertura mide líneas ejecutadas, no fuerza competitiva.

## Complejidad (Incremento 3)

Todo el código propio tiene que dar nota **A** con xenon (cada función, cada
módulo y el promedio). Para revisarlo en la compu:

```sh
python -m pip install -r requirements-dev.txt
xenon --max-absolute A --max-modules A --max-average A --exclude "arena.py" --ignore ".venv,versions,.git" .
```

Si no imprime nada, está todo en A. `versions/` (historial) y `arena.py`
(herramienta personal) quedan afuera del control.

## Integración continua y Git

GitHub Actions instala dependencias, compila todo, corre xenon (falla si algo
no da A) y corre `python -m pytest` (falla si la cobertura baja del 90 %) en
cada push y pull request. Flujo: `development` → verificación → merge a `main`.

No se suben a Git: `.venv/`, cachés (`__pycache__/`, `.pytest_cache/`),
`coverage.xml`, `arena_results/` ni `.local_backup/`.
