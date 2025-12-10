# 🎬 Plex Movies Cleaner  
### Automatiza la limpieza, análisis y auditoría de tus bibliotecas Plex

Plex Movies Cleaner es una herramienta modular que analiza películas en Plex usando datos de OMDb, decide automáticamente si deben conservarse o eliminarse, detecta errores de metadata, genera informes interactivos y ofrece un dashboard avanzado para inspección manual y borrado seguro.

---

## 🚀 Funcionalidades principales

### 🔍 Análisis automático de películas
- Conexión a Plex vía API.
- Extracción de rating IMDb, votos y score RottenTomatoes.
- Scoring detallado (KEEP / DELETE / MAYBE / UNKNOWN).
- Columna adicional `scoring_rule` para depurar qué regla se aplicó.

### 🧠 Detección de metadata incorrecta
- Comparación Plex vs OMDb.
- Identificación de discrepancias severas (título, año).
- Sugerencias automáticas:
  - `"Fix title"`
  - `"Fix year"`
  - `"Fix title & year"`

### 📊 Informes generados automáticamente
- `report_all.csv` (todas las películas)
- `report_filtered.csv` (DELETE y MAYBE)
- `report_filtered.html` (informe interactivo autónomo)
- `metadata_fix_suggestions.csv`
- `metadata_fix_log.txt`

### 🧼 Borrado controlado de archivos
- Basado en `report_filtered.csv`
- Con confirmación opcional
- Opción `DELETE_DRY_RUN` para revisión segura

### 🖥️ Dashboard interactivo (Streamlit)
Incluye:
- Vista completa
- Candidatas DELETE/MAYBE
- Búsqueda avanzada
- Gráficos Altair (incluido scoring_rule)
- Corrección de metadata

---

## 📁 Arquitectura del proyecto

```
backend/
    config.py
    plex_client.py
    omdb_client.py
    analyzer.py
    scoring.py
    decision_logic.py
    metadata_fix.py
    delete_logic.py
    reporting.py
    summary.py
    report_loader.py

frontend/
    data_utils.py
    components.py
    tabs/
        all_movies.py
        candidates.py
        advanced.py
        delete.py
        charts.py
        metadata.py

dashboard.py
analiza_plex.py
```

---

## ⚙️ Configuración

Crear archivo `.env`:

```env
PLEX_BASEURL=http://192.168.X.X:32400
PLEX_TOKEN=TU_TOKEN
OMDB_API_KEY=TU_API

OUTPUT_PREFIX=report
METADATA_OUTPUT_PREFIX=metadata_fix

DELETE_DRY_RUN=true
DELETE_REQUIRE_CONFIRM=true
SILENT_MODE=false
```

Opcionales:
- `EXCLUDE_LIBRARIES`
- `OMDB_RATE_LIMIT_WAIT_SECONDS`
- `OMDB_RATE_LIMIT_MAX_RETRIES`
- `OMDB_RETRY_EMPTY_CACHE`

---

## 🏃 Instalación

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ▶️ Ejecución

### 1. Analizar biblioteca Plex

```bash
python analiza_plex.py
```

Genera todos los CSV y el informe HTML.

### 2. Abrir dashboard web

```bash
streamlit run dashboard.py
```

---

## 📊 Ejemplo de scoring_rule

Cada película queda clasificada según regla de decisión:

| scoring_rule         | Significado |
|----------------------|-------------|
| KEEP_IMDB            | Rating y votos IMDb altos |
| KEEP_RT_IMDB         | Rating IMDb + buen RT score |
| DELETE_IMDB          | Rating bajo + pocos votos |
| DELETE_IMDB_NO_RT    | Versión “sin RT” del caso anterior |
| FALLBACK_MAYBE       | No se cumple KEEP ni DELETE |
| NO_DATA              | Falta info de OMDb |

Esto permite auditar rápidamente si el modelo de scoring está funcionando como deseas.

---

## 📄 Informes generados

### `report_all.csv`
Incluye:
- ratings IMDb/RT
- decisión final
- scoring_rule
- misidentified_hint
- metadata básica
- omdb_json en bruto

### `report_filtered.html`
HTML autónomo con:
- tabla interactiva
- gráficos de decisión
- top de bibliotecas
- filtros dinámicos

Ideal para compartir sin necesidad de Streamlit.

---

## ⚠️ Advertencias

- El borrado físico debe usarse con precaución.
- OMDb puede aplicar límites de uso; la aplicación detecta esto y utiliza caché.
- Plex puede tardar unos segundos en procesar cambios de metadata.

---

## 📜 Licencia

Ver archivo `LICENSE`.

---

## 🤝 Contribuciones

Se acepta código estructurado, modular y respetando el diseño actual del backend y frontend.
