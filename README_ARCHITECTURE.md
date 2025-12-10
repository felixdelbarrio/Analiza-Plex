# 🧩 Plex Movies Cleaner — Arquitectura técnica (README EXTRA)

Este documento está pensado **para desarrolladores** que quieran entender cómo está organizado el proyecto, cómo fluyen los datos entre backend y frontend, y qué módulos dependen de cuáles.

No sustituyen al `README.md` principal: lo complementa a nivel de arquitectura.

---

## 1. Visión general

El sistema se divide en dos capas:

- **backend/** → lógica de negocio pura:
  - Conexión a Plex
  - Llamadas a OMDb + caché
  - Scoring (KEEP/DELETE/MAYBE/UNKNOWN)
  - Detección de misidentificaciones
  - Generación de informes (CSV + HTML)
  - Borrado físico de archivos

- **frontend/** → visualización y control manual:
  - Dashboard en Streamlit (`dashboard.py`)
  - Componentes reutilizables (AgGrid, tarjetas de detalle)
  - Pestañas modulares
  - Gráficos (Altair)
  - Interacción de usuario para borrados, filtros, etc.

El **flujo típico** es:

1. `analiza_plex.py` recorre Plex y genera los CSV.
2. `dashboard.py` carga esos CSV ya preparados y los muestra organizados en pestañas.

---

## 2. Módulos backend y responsabilidades

### 2.1. `backend/config.py`

- Lee variables de entorno (`.env`).
- Expone constantes y parámetros:
  - Conexión a Plex (`PLEX_BASEURL`, `PLEX_TOKEN`).
  - Clave OMDb (`OMDB_API_KEY`).
  - Prefijos de salida (`OUTPUT_PREFIX`, `METADATA_OUTPUT_PREFIX`).
  - Flags de comportamiento (`SILENT_MODE`, `DELETE_DRY_RUN`, etc.).
  - Umbrales de scoring IMDb/RT (por ejemplo `IMDB_KEEP_MIN_RATING`, `RT_KEEP_MIN_SCORE`, etc.).

👉 Todos los módulos que necesitan opciones externas las obtienen aquí.

---

### 2.2. `backend/plex_client.py`

Responsable de todo lo relacionado con Plex:

- Conexión (`connect_plex()`).
- Obtención de secciones (bibliotecas) y filtrado por tipo (`movie`) y exclusiones (`EXCLUDE_LIBRARIES`).
- Extracción de la información de fichero por película (`get_movie_file_info()`).
- Extracción de `imdb_id` a partir del `guid` de Plex (`get_imdb_id_from_plex_guid()`).
- Obtención del mejor título de búsqueda para OMDb (`get_best_search_title()`).

👉 No tiene lógica de scoring ni reporting: solo *habla con Plex* y devuelve datos.

---

### 2.3. `backend/omdb_client.py`

Capa de acceso a OMDb con buena higiene:

- `search_omdb_by_imdb_id(imdb_id)`
- `search_omdb_with_candidates(título, año)`
- `extract_ratings_from_omdb(omdb_json) -> (imdb_rating, imdb_votes, rt_score)`
- Gestión de:
  - Caché local (`omdb_cache.json`).
  - Límite de peticiones (`Request limit reached!`).
  - Reintentos con espera (`OMDB_RATE_LIMIT_WAIT_SECONDS`, `OMDB_RATE_LIMIT_MAX_RETRIES`).
  - Flag `OMDB_RETRY_EMPTY_CACHE` para rellenar huecos en llamadas previas.

👉 El resto del backend asume que esta capa ya entrega datos estables (o `None`).

---

### 2.4. `backend/scoring.py`

Encapsula la **lógica de scoring puro**:

- `compute_scoring(imdb_rating, imdb_votes, rt_score) -> dict`
  - Devuelve un objeto enriquecido:

    ```python
    {
        "decision": "KEEP" | "DELETE" | "MAYBE" | "UNKNOWN",
        "reason": "explicación humana",
        "rule": "KEEP_IMDB" | "DELETE_IMDB" | "FALLBACK_MAYBE" | ...,
        "inputs": {...}
    }
    ```

- `decide_action(imdb_rating, imdb_votes, rt_score) -> (decision, reason)`
  - Wrapper histórico para mantener compatibilidad.
  - Internamente llama a `compute_scoring`.

👉 Todos los umbrales y “reglas” se definen aquí. Si algún día cambias la política de limpieza, este es el módulo clave.

---

### 2.5. `backend/decision_logic.py`

Agrupa la lógica de *interpretación* y ordenación:

- `detect_misidentified(...) -> str`
  - Usa título/año Plex vs OMDb.
  - Añade pistas si:
    - Títulos difieren notablemente.
    - Años se alejan más de 1 año.
    - Rating muy bajo con muchos votos.
    - RT extremadamente bajo.

- `sort_filtered_rows(rows) -> rows_ordenadas`
  - Ordena películas DELETE/MAYBE para el CSV filtrado:
    1. DELETE → MAYBE → KEEP → UNKNOWN
    2. Más votos IMDb.
    3. Mayor rating IMDb.
    4. Mayor tamaño de fichero.

👉 No decide por sí mismo KEEP/DELETE: solo ordena y detecta “huele mal”.

---

### 2.6. `backend/metadata_fix.py`

- Compara metadata de Plex con OMDb y genera sugerencias estructuradas:
  - Posibles cambios de título/año.
  - Campo `action` sugerido: `"Fix title"`, `"Fix year"`, `"Fix title & year"`, etc.
  - JSON de detalle (`suggestions_json`).

- Soporta modos:
  - `METADATA_DRY_RUN` → solo sugerencias.
  - `METADATA_APPLY_CHANGES` → (si implementado) aplicación real de cambios en Plex.

- Devuelve:
  - Filas orientadas a CSV (`metadata_fix_suggestions.csv`).
  - Mensajes de log (`metadata_fix_log.txt`).

---

### 2.7. `backend/delete_logic.py`

- `delete_files_from_rows(df, delete_dry_run) -> (ok, error, logs)`
- Encapsula el borrado de archivos de disco:
  - Comprueba existencia del archivo.
  - Respeta `DELETE_DRY_RUN`.
  - No tiene ninguna dependencia de Streamlit.

👉 Se separa explícitamente del frontend. El tab de borrado solo prepara los datos y llama a esta función.

---

### 2.8. `backend/reporting.py`

- Escribe CSVs:
  - `write_all_csv(path, rows)`
  - `write_filtered_csv(path, rows)`
  - `write_suggestions_csv(path, rows)`

- Genera el HTML autónomo:
  - `report_filtered.html` a partir de `report_filtered.csv`.

👉 Genera artefactos que otros componentes pueden usar sin depender de Python (por ejemplo, enviar el HTML por correo).

---

### 2.9. `backend/summary.py`

- `compute_summary(df_all) -> dict`:

  ```python
  {
      "total_count": ...,
      "total_size_gb": ...,
      "keep_count": ...,
      "keep_size_gb": ...,
      "dm_count": ...,
      "dm_size_gb": ...
  }
  ```

- Resumen global usado por el dashboard (`metric` de Streamlit).

---

### 2.10. `backend/report_loader.py`

- `load_reports(all_csv_path, filtered_csv_path) -> (df_all, df_filtered)`
  - Lee `report_all.csv` y `report_filtered.csv`.
  - Castea columnas texto (poster_url, trailer_url, omdb_json).
  - Añade columnas derivadas (GB, década, etc.) usando `frontend.data_utils.add_derived_columns`.
  - Limpia columnas no necesarias para el dashboard (como `thumb`).

👉 Es el “adaptador” entre reporting y visualización.

---

### 2.11. `analiza_plex.py`

Script principal de análisis:

1. Conecta a Plex.
2. Recorre las bibliotecas de tipo `movie`.
3. Para cada película:
   - Obtiene información de fichero.
   - Llama a OMDb (o usa caché).
   - Calcula scoring (`compute_scoring`).
   - Detecta misidentificaciones.
   - Genera sugerencias de metadata.
4. Agrega resultados y llama a:
   - `write_all_csv`
   - `write_filtered_csv`
   - `write_suggestions_csv`
5. Genera el log de metadata.

---

## 3. Módulos frontend y responsabilidades

### 3.1. `dashboard.py`

- Punto de entrada de la UI (Streamlit).
- Hace:
  - Carga de `.env`.
  - `load_reports(...)` (backend).
  - `compute_summary(...)` (backend).
  - Configuración visual (ocultar header, layout wide).
  - Gestión de estado del “modal” de detalle.
  - Definición de pestañas y delegación a `frontend.tabs.*`.

👉 No contiene lógica de negocio pesada: solo orquesta.

---

### 3.2. `frontend/components.py`

Componentes reutilizables de UI:

- `aggrid_with_row_click(df, key_suffix) -> dict | None`
  - Pinta AgGrid con selección por fila.
  - Devuelve la fila seleccionada como dict.
  - Oculta columnas técnicas (omdb_json, file, etc.).

- `render_detail_card(row, show_modal_button=True)`
  - Muestra la ficha lateral tipo Plex:
    - Poster
    - Ratings
    - Info OMDb
    - Archivo y tamaño
    - Enlaces a IMDb y Plex Web

- `render_modal()`
  - Implementa la vista “ampliada” reutilizando `render_detail_card`.

---

### 3.3. `frontend/data_utils.py`

Funciones de ayuda de datos usadas por el frontend:

- `add_derived_columns(df)`
  - Convierte numéricos (ratings, votos, año, file_size).
  - Calcula `file_size_gb`.
  - Calcula `decade` y `decade_label`.

- `explode_genres_from_omdb_json(df)`
  - Lee `omdb_json` por fila.
  - Explota una fila por género (`genre`).

- `build_word_counts(df, decisions)`
  - Construye tabla de palabras frecuentes en títulos.

- `decision_color(field="decision")`
  - Define paleta de colores fija para Altair por decisión.

- `safe_json_loads_single(x)`
  - Parseo defensivo de JSON usado en detalle y gráficos.

---

### 3.4. `frontend/tabs/*`

Cada pestaña del dashboard está encapsulada en un módulo:

- `tabs/all_movies.py`
  - Pestaña “📚 Todas”.
  - Muestra todas las películas, grid + detalle.

- `tabs/candidates.py`
  - Pestaña “⚠️ Candidatas”.
  - Solo DELETE/MAYBE.

- `tabs/advanced.py`
  - Pestaña “🔎 Búsqueda avanzada”.
  - Filtros por biblioteca, decisión, rating mínimo IMDb, votos mínimos.

- `tabs/delete.py`
  - Pestaña “🧹 Borrado”.
  - Filtros por biblioteca/decisión.
  - Selección múltiple en AgGrid.
  - Llamada a `backend.delete_logic.delete_files_from_rows`.

- `tabs/charts.py`
  - Pestaña “📊 Gráficos”.
  - Distintas vistas:
    - Distribución por decisión
    - IMDb vs RT
    - Décadas
    - Bibliotecas
    - Géneros (OMDb)
    - Espacio en disco por biblioteca/decisión
    - Boxplot IMDb por biblioteca
    - Ranking de directores
    - Palabras frecuentes
    - **Distribución por `scoring_rule`**

- `tabs/metadata.py`
  - Pestaña “🧠 Metadata”.
  - Carga `metadata_fix_suggestions.csv`.
  - Permite filtrar por biblioteca y acción.
  - Permite exportar CSV filtrado.

---

## 4. Diagrama ASCII de flujo backend → frontend

```text
                 ┌──────────────────────────────┐
                 │          analiza_plex.py     │
                 └──────────────┬───────────────┘
                                │
                                │ usa
                                ▼
         ┌─────────────────────────────────────────────┐
         │                 backend/                    │
         │                                             │
         │  config.py          plex_client.py          │
         │      ▲                      ▲               │
         │      │                      │               │
         │  scoring.py         omdb_client.py          │
         │      ▲                      ▲               │
         │      │                      │               │
         │ decision_logic.py    metadata_fix.py        │
         │      ▲                      ▲               │
         │      └─────────── analyzer / loop ─────────┘
         │                      │
         │                      ▼
         │          reporting.py (CSV + HTML)          │
         └──────────────────────┬──────────────────────┘
                                │
                                │ genera
                                ▼
                 ┌──────────────────────────────────┐
                 │     report_all.csv, ...          │
                 └──────────────────────────────────┘
                                │
                                │ lee
                                ▼
          ┌────────────────────────────────────────┐
          │               dashboard.py             │
          │          (Streamlit frontend)          │
          └────────────────┬───────────────────────┘
                           │
                           │ usa
                           ▼
      ┌───────────────────────────────────────────────────┐
      │                    frontend/                      │
      │                                                   │
      │  report_loader.py  → df_all / df_filtered         │
      │  components.py     → grids, detalles, modal       │
      │  data_utils.py     → derivadas para gráficos      │
      │  tabs/*.py         → pestañas de Streamlit        │
      └───────────────────────────────────────────────────┘
```

---

## 5. Diagrama ASCII de dependencias principales

> Nota: no es exhaustivo al detalle de cada función, pero sí a nivel de módulo.

```text
[config]
   ▲
   │
   ├──> [plex_client]
   ├──> [omdb_client]
   ├──> [scoring]
   ├──> [metadata_fix]
   ├──> [delete_logic]
   └──> [reporting]

[omdb_client]
   ▲
   │
   └──> usado por [analyzer / analiza_plex.py]

[plex_client]
   ▲
   │
   └──> usado por [analyzer / analiza_plex.py]

[scoring]
   ▲
   │
   └──> [decision_logic] (reexporta decide_action)
              ▲
              │
              └──> usado por [analyzer]

[metadata_fix]
   ▲
   │
   └──> usado por [analyzer]

[delete_logic]
   ▲
   │
   └──> usado por [frontend.tabs.delete]

[reporting]
   ▲
   │
   └──> usado por [analyzer] para CSV/HTML

[summary]
   ▲
   │
   └──> usado por [dashboard.py]

[report_loader]
   ▲
   │
   └──> usado por [dashboard.py]
             ▲
             │
             ├──> usa [frontend.data_utils.add_derived_columns]
             └──> alimenta [frontend.tabs.*]

[frontend.components]
   ▲
   │
   └──> usado por [frontend.tabs.all_movies],
                    [frontend.tabs.candidates],
                    [frontend.tabs.advanced],
                    [frontend.tabs.metadata],
                    [render_modal en dashboard/components]

[frontend.tabs.*]
   ▲
   │
   └──> llamados desde [dashboard.py]
```

---

## 6. Puntos de extensión recomendados

- **Nuevas reglas de scoring**: `backend/scoring.py`
  - Añadir nuevas reglas o cambiar umbrales sin tocar el resto del sistema.
- **Nuevos gráficos / análisis**: `frontend/tabs/charts.py`
  - Reutilizar `frontend.data_utils` para nuevas métricas.
- **Nuevas vistas de detalle**: `frontend/components.py`
  - Ampliar la tarjeta de detalle con más campos de `omdb_json`.
- **Integraciones externas (ej. enviar informes)**:
  - Colgarse de los ficheros ya generados en `reporting.py`.

---

## 7. Resumen para desarrolladores

- El **backend** se encarga de:
  - Hablar con Plex y OMDb.
  - Aplicar reglas y generar artefactos (CSV/HTML).
- El **frontend**:
  - No hace lógica de negocio.
  - Solo presenta, filtra, grafica y llama a funciones backend bien encapsuladas.

Si mantienes esta separación (todo lo que toque Plex/OMDb/disco en backend, todo lo que sea UI en frontend), el proyecto seguirá siendo fácil de extender y refactorizar sin sorpresas.
