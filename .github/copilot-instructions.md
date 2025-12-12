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
- Configuración via `.env` (leída en `backend/config.py`). Variables críticas: `PLEX_BASEURL`, `PLEX_TOKEN`, `OMDB_API_KEY`, `OUTPUT_PREFIX`, `SILENT_MODE`.
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
- Plex: `plexapi` (usa `PlexServer` con `PLEX_BASEURL` y `PLEX_TOKEN`).
- OMDb: accesos HTTP directos (`requests`) y cacheado en `omdb_cache.json`.
- Streamlit + st_aggrid para UI.

## Qué pedirle al agente AI (ejemplos de prompts eficaces)
- "Corrige/añade manejo de excepciones en `backend/omdb_client.py` para HTTP 5xx y registra el código de estado." (mencionar fila/función concreta).
- "Añade tests unitarios para `plex_client.get_imdb_id_from_plex_guid` y `omdb_client.normalize_imdb_votes` usando pytest." (indicar carpeta `tests/`).

Si algo no es claro o quieres más detalle (ej: ejemplos de `.env`, tests o ampliación de la sección de thresholds), dime qué sección prefieres que expanda.
