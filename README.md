# SnakeBot

Bot competitivo de Snake desarrollado para un proyecto universitario. Este
repositorio conserva la evolución Gemini → ChatGPT Plus y una copia operativa
de **ChatGPT Plus V8.0 (`botv8.0_v5.py`)**.

## Estructura

```text
versions/
  gemini/{v1,v2,v3,v3.1,v5,v5.5}/
  chatgpt/{v7.6,modular,v8.0}/
src/bot_final/       # V8 y sus dependencias de ejecución
tests/              # Pruebas existentes adaptadas a la ubicación de V8
docs/evolucion.md
unclassified/       # Versiones adicionales sin etapa asignada
.github/workflows/ci.yml
arena.py            # Simulador y visor local, conservado sin cambios
requirements.txt
requirements-dev.txt
pytest.ini
```

Los archivos históricos mantienen sus bytes originales. La copia de V8 en
`src/bot_final/` coincide con `versions/chatgpt/v8.0/`. El runtime y el visualizador
incluidos junto a V7.6 y V8 proceden de R4, sin cambios: no se encontraron copias
independientes en las carpetas originales de esas versiones.

La cronología y las diferencias observables están en [docs/evolucion.md](docs/evolucion.md).
Los commits incorporan archivos históricos en el presente; no recrean fechas de
trabajo ni certifican la autoría de un modelo por el contenido del código.

## Instalación

Se utiliza Python 3.12.

```sh
python -m venv .venv
```

Activar con `.venv\Scripts\Activate.ps1` en PowerShell, o
`source .venv/bin/activate` en Linux/macOS.

```sh
python -m pip install -r requirements.txt
```

## Ejecución

```sh
python src/bot_final/botv8.0_v5.py TU_TOKEN
```

El runtime abre la conexión WebSocket y el visualizador Pygame. Se necesita un
entorno gráfico para jugar con el visor. Los mensajes de ayuda internos conservan
el nombre de V7.6 porque no se modificó código existente.

Para enfrentamientos locales y el visor de la arena:

```sh
python arena.py
```

La arena descubre bots por sus archivos; las copias histórica y operativa de V8
pueden aparecer por separado. `R`/Enter reinicia, `N` cambia la semilla y `Tab`
intercambia los lados. Los resultados se guardan localmente en `arena_results/`.
`start.sh` no se utiliza y queda excluido de Git.

## Tests y cobertura

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

La configuración ejecuta las pruebas de reglas, simulación, estrategia, runtime,
visualizador, regresiones, equivalencia y los cinco escenarios de arena existentes.
Los tests apuntan a `src/bot_final/`. El snapshot histórico se conserva como oráculo,
no como bot desplegable. Un adaptador permite que pytest recoja los chequeos que
antes se ejecutaban solo como scripts. Sus escenarios y aserciones se conservan.

La cobertura de líneas se mide sobre **los tres archivos de `src/bot_final/`**,
incluidos runtime y visualizador, con umbral obligatorio del 90 %. Los bots
históricos y el simulador auxiliar `arena.py` no integran ese denominador.
No se excluyen funciones del bot para elevar el porcentaje. El reporte local
`coverage.xml` no se publica. El porcentaje mide ejecución de líneas, no fuerza
competitiva ni funcionamiento real de la red o pantalla.

## Integración continua y Git

GitHub Actions ejecuta instalación, comprobación de sintaxis y `python -m pytest`
en cada push y pull request. La prueba falla si la cobertura queda por debajo del
90 %. Flujo: `development` → verificación → merge a `main`.

Configuración basada en la documentación de
[GitHub Actions para Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
y [pytest-cov](https://pytest-cov.readthedocs.io/en/stable/config.html).

Los entornos, cachés, resultados, reportes generados y respaldos permanecen fuera
del historial. La reorganización no introduce optimizaciones ni correcciones en
los bots existentes.
