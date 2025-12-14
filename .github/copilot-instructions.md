## Resumen rápido para agentes AI

Este repositorio analiza bibliotecas Plex, consulta OMDb/Wikipedia, decide KEEP/MAYBE/DELETE y genera reportes (CSV/HTML) y un dashboard Streamlit.

Objetivo del archivo: dar instrucciones claras y prácticas a agentes AI (Copilot, Codegen, etc.) para modificar, mejorar y mantener el código sin romper la funcionalidad.

## Estructura y puntos clave
- `analiza_plex.py`: runner principal que produce `report_all.csv`, `report_filtered.csv` y el HTML.
- `backend/`: lógica de negocio (conexión a Plex, OMDb, scoring y generación de CSV/HTML).
  - `omdb_client.py`: caché local `omdb_cache.json`, manejo de rate-limit y funciones de búsqueda.
  - `plex_client.py`: utilidades para extraer `imdb_id`, ruta de archivo y título más fiable desde objetos de Plex.
  - `analyzer.py`: orquesta la fila final por película (uniendo Plex, OMDb y Wiki).
  - `reporting.py`: escribe `report_all.csv`, `report_filtered.csv` y `report_filtered.html`.
  - `scoring.py` y `decision_logic.py`: reglas y umbrales para KEEP/MAYBE/DELETE.
- `frontend/`: dashboard Streamlit (`dashboard.py`, `frontend/components.py`).

## Flujo de datos importante
1. `plex_client` extrae metadatos y posible `imdb_id` de objetos Plex.
2. `omdb_client` consulta OMDb (cache + reintentos); si OMDb falla usa sólo caché.
3. `wiki_client` enriquece datos cuando procede.
4. `scoring` / `decision_logic` determinan KEEP/MAYBE/DELETE.
5. `reporting` genera CSV/HTML y `frontend` muestra dashboard (Streamlit).

## Convenciones y variables de entorno
- Configuración via `.env` (leída en `backend/config.py`). Variables críticas:
  - `BASEURL`, `PLEX_TOKEN`, `OMDB_API_KEY`, `OUTPUT_PREFIX`, `SILENT_MODE`.
- Logging: los módulos deben respetar `SILENT_MODE`. Utilizar el logger central (`backend/logger.py`) si existe.
- Caché OMDb: `omdb_cache.json` es la única fuente persistente de OMDb; el cliente normaliza formatos antiguos.

## Reglas para modificar el código
1. Mantener la API pública de funciones y módulos (nombres y firmas públicas usadas por `analiza_plex.py` y `frontend`). Evitar renombrados sin actualizar todos los usos.
2. Evitar imprimir directamente; usar el logger central o funciones `_log`/`_log_always` respetando `SILENT_MODE`.
3. Para cambios en caché (`omdb_cache.json`, `wiki_cache.json`): escribir de forma atómica (tempfile + os.replace) y mantener compatibilidad con versiones antiguas del formato.
4. Las llamadas a OMDb deben usar `requests.Session` con reintentos exponenciales y backoff; detectar el texto "Request limit reached!" y pausar según `OMDB_RATE_LIMIT_WAIT_SECONDS`.
5. Al modificar plantillas HTML/JS internas (por ejemplo en `reporting.py`), no usar f-strings que generen conflicto con llaves `{}` en JavaScript; usar placeholders y `.replace()` o un motor de plantillas seguro.

## Calidad y pruebas
- Añadir tests unitarios con `pytest` para funciones críticas (OMDb parsing, `plex_client.get_imdb_id_from_movie`, scoring/decision logic, `reporting.write_interactive_html`).
- Antes de abrir PRs grandes, ejecutar:

```bash
python -m venv venv && source venv/bin/activate
pip install -e .
pytest -q
```

## Patrones a favor
- Uso de cachés locales para evitar llamadas repetidas a OMDb/Wiki.
- Separación clara entre extracción (plex_client), enriquecimiento (omdb_client/wiki_client), scoring (scoring.py) y reporting.

## Riesgos y puntos a vigilar
- OMDb rate limits — si la API falla, la lógica debe degradar a usar solo caché.
- No asumir que `movie.guids` existe o que `guids` tenga formato consistente; usar utilidades en `plex_client`.
- Evitar incluir grandes bloques de HTML/JS sin pruebas; pueden introducir errores de sintaxis si se editan en Python con f-strings.

## Qué pedirle al agente AI (ejemplos de prompts eficaces)
- "Corrige/añade manejo de excepciones en `backend/omdb_client.py` para HTTP 5xx y registra el código de estado." (indicar función/fila si es posible).
- "Añade tests unitarios para `plex_client.get_imdb_id_from_plex_guid` y `omdb_client.normalize_imdb_votes` usando pytest." (indicar carpeta `tests/`).
- "Reescribe `backend/reporting.py` para que la plantilla HTML se genere sin romper la sintaxis del módulo y añada una función mínima `write_interactive_html` para tests." 

## Checklist rápido antes de PR
- ¿Modificaste firmas públicas? Actualiza `analiza_plex.py` y `frontend` si corresponde.
- ¿Añadiste tests para la funcionalidad nueva? ¿Pasaron en CI local?
- ¿Respetaste `SILENT_MODE` y la política de logging?
- ¿Hiciste escrituras atómicas para cachés y archivos de salida?

---
Si quieres, puedo:
- Reforzar un módulo concreto (ej: `backend/omdb_client.py`) con manejo de errores y tests.
- Añadir o mejorar tests `pytest` y ejecutar la suite aquí.

Indica qué prefieres que haga a continuación.
## Resumen rápido para agentes AI

Este repo analiza bibliotecas Plex, consulta OMDb/Wikipedia, decide KEEP/MAYBE/DELETE y genera reportes (CSV/HTML) y un dashboard Streamlit.

## Estructura y componentes clave
- `analiza_plex.py` : runner principal que produce `report_all.csv`, `report_filtered.csv` y el HTML.
- `backend/` : lógica de negocio (conexión a Plex, OMDb, scoring y generación de CSV).
  - `omdb_client.py` : caché local `omdb_cache.json`, manejo de rate-limit y funciones de búsqueda (por `imdb_id`, `title+year` y candidatos).
  - `plex_client.py` : utilidades para extraer `imdb_id`, ruta de archivo y título más fiable desde objetos de Plex.
  - `analyzer.py` : orquesta la fila final por película (uniendo Plex, OMDb y Wiki).
  - `reporting.py` : escribe `report_all.csv`, `report_filtered.csv` y `report_filtered.html` (plantilla JS + DataTables).
- `frontend/` : dashboard Streamlit. `frontend/components.py` usa `st_aggrid` y `streamlit` para mostrar filas y detalle.

## Flujo de datos importante (por orden)
1. `plex_client` extrae metadatos y posible `imdb_id` de objetos Plex.
2. `omdb_client` consulta OMDb (cache + reintentos); si OMDb falla usa sólo caché.
3. `wiki_client` enriquece datos cuando procede.
4. `scoring` / `decision_logic` determinan KEEP/MAYBE/DELETE.
5. `reporting` genera CSV/HTML y `frontend` muestra dashboard (Streamlit).

## Convenciones de proyecto útiles para el agente
- Configuración via `.env` (leída en `backend/config.py`). Variables críticas: `BASEURL`, `PLEX_TOKEN`, `OMDB_API_KEY`, `OUTPUT_PREFIX`, `SILENT_MODE`.
- Logging: respetar `SILENT_MODE` (módulos usan `_log` y `_log_always`). Evitar imprimir si `SILENT_MODE=true`.
- Caché OMDb: `omdb_cache.json` es la única fuente persistente de OMDb; `omdb_client` normaliza formatos antiguos.
- Umbrales y comportamiento configurable en `backend/config.py` (ej: `IMDB_KEEP_MIN_RATING`, `OMDB_RATE_LIMIT_WAIT_SECONDS`, `OMDB_RETRY_EMPTY_CACHE`).

## Comandos de desarrollador y flujo de ejecución
- Crear entorno y ejecutar (recomendado):
  - `python3 -m venv venv && source venv/bin/activate`
  - `pip install -e .` (instala el paquete y dependencias declaradas en `setup.py`).
- Ejecutar el analizador en local: `python analiza_plex.py` (genera CSV/HTML en el cwd).
- Dashboard: `streamlit run dashboard.py` → por defecto en `http://localhost:8501`.

## Patrones y puntos críticos a evitar/considerar
- OMDb puede devolver `"Request limit reached!"`. `omdb_client` muestra un aviso una única vez y espera `OMDB_RATE_LIMIT_WAIT_SECONDS`. Si se agotan reintentos, OMDb se marca como desactivado para la ejecución y se usa sólo la caché.
- No asumir que `movie.guids` existe o tiene formato consistente: usar las utilidades en `plex_client.get_imdb_id_from_movie`.
- Cuando se modifican thresholds en `.env`, reejecutar para recalcular scoring; `backend/stats.py` y `config.py` contienen lógica de umbrales automáticos.

## Ejemplos concretos que el agente puede usar
- Para obtener ratings normalizados desde OMDb: ver `backend/omdb_client.extract_ratings_from_omdb`.
- Para construir la fila CSV final: ver `backend/analyzer.analyze_single_movie`.
- Para escribir el HTML interactivo con DataTables + Chart.js: `backend/reporting.write_interactive_html`.

## Integraciones externas
- Plex: `plexapi` (usa `PlexServer` con `BASEURL` y `PLEX_TOKEN`).
- OMDb: accesos HTTP directos (`requests`) y cacheado en `omdb_cache.json`.
- Streamlit + st_aggrid para UI.

## Qué pedirle al agente AI (ejemplos de prompts eficaces)
- "Corrige/añade manejo de excepciones en `backend/omdb_client.py` para HTTP 5xx y registra el código de estado." (mencionar fila/función concreta).
- "Añade tests unitarios para `plex_client.get_imdb_id_from_plex_guid` y `omdb_client.normalize_imdb_votes` usando pytest." (indicar carpeta `tests/`).

Si algo no es claro o quieres más detalle (ej: ejemplos de `.env`, tests o ampliación de la sección de thresholds), dime qué sección prefieres que expanda.
