# Auditoría competitiva del Snake modular R4

> **Nota (reorganización 2026-09-30):** documento rescatado de la antigua carpeta `competitive_audit/`. Analiza el bot modular R4 (`botv7.6_v4.py`), hoy en `versions/chatgpt/modular/`. Las rutas `BOT CHATGPT PLUS/...` y `BOT GEMINI PRO/...` son las ubicaciones de esa época; los scripts y resultados crudos (`results/`, `*.json`) no se conservaron en el repositorio.

Objetivo: `BOT CHATGPT PLUS/SNAKE_V76_MODULAR_R4/botv7.6_v4.py`.
El archivo de estrategia permanece sin cambios. Todos los programas, registros
y documentos de esta auditoría están bajo `competitive_audit/`.

## Reproducir los ensayos

Desde la raíz del repositorio, usando el entorno existente:

```powershell
.\.venv\Scripts\python.exe -B competitive_audit/benchmark.py inventory
.\.venv\Scripts\python.exe -B competitive_audit/benchmark.py run --suite screen
.\.venv\Scripts\python.exe -B competitive_audit/benchmark.py run --suite core
.\.venv\Scripts\python.exe -B competitive_audit/benchmark.py run --suite variants
.\.venv\Scripts\python.exe -B competitive_audit/summarize.py
.\.venv\Scripts\python.exe -B competitive_audit/trajectory_audit.py
.\.venv\Scripts\python.exe -B competitive_audit/profiling/profile_v4.py
.\.venv\Scripts\python.exe -B competitive_audit/profiling/profile_boundaries.py
.\.venv\Scripts\python.exe -B competitive_audit/profiling/fe_budget_probe.py
.\.venv\Scripts\python.exe -B competitive_audit/state_audit/audit_state.py
.\.venv\Scripts\python.exe -B competitive_audit/build_report.py
```

Las suites omiten las partidas que ya constan como completas en `results/games.jsonl`.
No ejecutar en paralelo torneos ni perfiles: distorsionaría el presupuesto temporal.
Los fallos de workers se registran aparte y no se convierten en victorias.

## Método y límites

- Motor existente `arena.SnakeArenaEngine`, reglas v3, máximo 300 movimientos.
- Tableros de 12..20 por dimensión, generados por semilla; posiciones iniciales
  estándar del motor en esquinas opuestas. No se alteraron los puntos de inicio.
- Parejas A/B con la misma semilla. El sorteo inicial es idéntico; los respawns
  posteriores pueden diferir porque las estrategias recorren caminos distintos.
- Estrategia v4 con modo `time` y parámetros actuales. No se reduce el presupuesto
  ni se sustituye la búsqueda por otro algoritmo para acelerar los torneos.
- Cada partida se ejecuta en un proceso nuevo y serial, con módulos independientes
  para candidato y rival. Se conservan hash de fuentes, reglas, plan y overrides.
- Las variantes se asignan al módulo importado en memoria; no se escribe el bot.
- Se mide la llamada completa a `choose_direction`. La carga del módulo se incluye
  en duración de partida, pero no en tiempo de decisión. Las nuevas muestras también
  incluyen tiempo de CPU del proceso; Windows puede tener resolución limitada.
- La arena contabiliza excesos de 80 ms sin adjudicar derrota por tiempo. El valor
  procede del código del proyecto; el contrato remoto exacto no se certificó.
- Una misma configuración temporal puede elegir distinto bajo distinta carga de
  máquina. Semillas y hashes hacen repetible el experimento, no garantizan una
  secuencia idéntica de decisiones en modo temporal.
- `screen` es un filtro amplio de compatibilidad: una pareja por rival ejecutable.
  Ganar a bots legacy que interpretan mal dígitos no demuestra mayor fuerza v3.
- `core` amplía tres referencias con soporte explícito v3 y dos semillas nuevas.
  La lógica estratégica de `BOT GEMINI PRO/botv7.6.py` coincide exactamente en AST
  con el candidato hasta `choose_direction`: es un control de self-play con otro
  archivo, no una tercera estrategia independiente.
- `variants` compara base, territorio ON, cobro final a 12 y bonus de camino a 30000,
  en tres referencias, dos semillas nuevas y ambos lados. Se rota orden de ejecución.
- Son experimentos exploratorios pequeños, no una optimización de pesos. Las
  parejas de una semilla están correlacionadas; no afirmar significancia a partir
  de un porcentaje sobre doce partidas. El Wilson incluido en JSON es descriptivo
  de victorias individuales, no un intervalo ajustado por dependencia entre parejas.

## Evidencia conservada

- `results/inventory.json`: bots encontrados, hash, exclusiones y prueba de entrada.
- `results/manifest_*.json`: configuración y partidas previstas.
- `results/games.jsonl`: tableros, movimientos, tiempos, diagnósticos y resultados.
- `results/failures.jsonl`: ensayos que no llegaron a resultado completo.
- `results/summary.json` y `baseline.csv`: agregados y derrotas observables.
- `results/trajectory_audit.json`: reconstrucción normal y divergencias del modelo
  de respawn en continuaciones realmente jugadas; no atribuye causalidad a derrotas.
- `profiling/profile.json` y `profile.md`: estrés, tiempos sin instrumentación y
  perfil detallado. `sys.setprofile` tiene sobrecoste importante, explicitado por
  controles de trabajo fijo; sus tiempos no son latencia de producción.
- `profiling/boundaries.json`: instrumentación alternativa de menor coste en
  límites de componentes, con tiempos exclusivos e inclusivos diferenciados.
- `profiling/fe_budget_probe.json`: activación FE con 8/12/16 ms sobre posiciones
  guardadas; no es una comparación de win-rate.
- `state_audit/REPORT.md`: fixtures reproducibles de estado/respawn y memoria.
- `parameters_training/README.md`: inventario de parámetros y diseño de entrenamiento.

No se iniciaron conexiones de juego ni se usaron tokens de los bots antiguos.
Las propuestas del informe requieren aprobación antes de incorporarse al v4.
