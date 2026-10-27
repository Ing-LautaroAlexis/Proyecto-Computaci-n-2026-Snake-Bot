# Documentación

| Documento | Qué contiene |
| --- | --- |
| [evolucion.md](evolucion.md) | Historia de las versiones (Gemini V1 → ChatGPT V8.0 → 3.9.1) y qué cambió en cada una. |
| [../tests/README.md](../tests/README.md) | Requisitos que tiene que cumplir el bot y qué test verifica cada uno. |
| [auditoria_r4/reporte_competitivo.md](auditoria_r4/reporte_competitivo.md) | Resultados de 117 partidas del bot R4 contra las versiones anteriores. |
| [auditoria_r4/parametros.md](auditoria_r4/parametros.md) | Inventario de constantes/pesos de la estrategia y cuáles conviene ajustar. **Útil para mejorar el bot.** |
| [auditoria_r4/auditoria_estado.md](auditoria_r4/auditoria_estado.md) | Casos de estado, respawn y memoria: cómo reconstruye cuerpos e historial entre turnos. |
| [auditoria_r4/profiling.md](auditoria_r4/profiling.md) | Cuánto tarda cada decisión (media, p95, casos que pasan de 80 ms). |
| [auditoria_r4/metodo.md](auditoria_r4/metodo.md) | Cómo se hizo la auditoría (los scripts originales ya no están). |

La auditoría R4 analiza `versions/chatgpt/modular/botv7.6_v4.py`. V8.0 comparte casi
todo ese código (solo cambia el BFS), así que sus conclusiones siguen siendo válidas
en su mayoría para el bot operativo.
