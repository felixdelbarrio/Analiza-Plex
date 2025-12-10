# 📘 Plex Movies Cleaner — Analizador Inteligente de Películas para Plex

Este proyecto permite:

- Conectarse a tu servidor **Plex**
- Analizar todas las bibliotecas de películas (excepto las que excluyas)
- Consultar puntuaciones de **IMDb** y **Rotten Tomatoes** vía OMDb  
- Clasificar las películas como `KEEP`, `MAYBE`, `DELETE`, `UNKNOWN`
- Generar **dos CSV**:
  - `*_all.csv` → todas tus películas analizadas  
  - `*_filtered.csv` → solo las películas “prescindibles” ordenadas de peor a menos mala
- Evitar bloqueos de OMDb usando:
  - ⏱ Delay
  - 💾 Cache local
  - 🛑 Sistema de espera + reintento + parada limpia  
- Integración con **Streamlit** para un dashboard gráfico
- Sistema de **borrado seguro** de archivos desde la interfaz

---

# 📄 Índice

- [⚙️ Características](#⚙️-características)
- [🧩 Requisitos](#🧩-requisitos)
- [🛠 Instalación en macOS](#🛠-instalación-en-macos)
- [🐧 Instalación en Raspbian / Raspberry Pi OS](#🐧-instalación-en-raspbian--raspberry-pi-os)
- [🔑 Obtener Token de Plex](#🔑-obtener-token-de-plex)
- [⚙️ Configuración del `.env`](#⚙️-configuración-del-env)
- [▶️ Ejecutar el analizador](#▶️-ejecutar-el-analizador)
- [📊 Dashboard Streamlit](#📊-dashboard-streamlit)
- [🧹 Borrado seguro de archivos](#🧹-borrado-seguro-de-archivos)
- [💾 Cache `omdb_cache.json`](#💾-cache-omdb_cachejson)
- [🚨 Manejo del rate limit de OMDb](#🚨-manejo-del-rate-limit-de-omdb)
- [📊 Estructura de los CSV](#📊-estructura-de-los-csv)
- [🛑 `.gitignore` recomendado](#🛑-gitignore-recomendado)
- [✨ Mejoras futuras](#✨-mejoras-futuras)

---

# ⚙️ Características

✔ Conexión directa con Plex  
✔ Obtención de IMDb + Rotten Tomatoes vía OMDb  
✔ Cache local para acelerar siguientes análisis  
✔ Ordenación automática de candidatas a borrar  
✔ Clasificación configurable por `.env`  
✔ Exportación a HTML interactivo avanzado  
✔ Sistema automático para corregir metadata en Plex  
✔ Dashboard con gráficos  
✔ Dashboard Streamlit  
✔ Exportación HTML  
✔ Borrado de archivos con DRY RUN + Confirmación

---

# 🧩 Requisitos

- Python 3.9+
- Servidor Plex accesible en red local
- API key de OMDb → https://www.omdbapi.com  
- Token de Plex
- macOS / Linux / Raspberry Pi OS

---

# 🛠 Instalación en macOS

### 1. Instalar Homebrew (si no lo tienes)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Instalar Python 3

```bash
brew install python
```

Verificar:

```bash
python3 --version
```

---

# 🐧 Instalación en Raspbian / Raspberry Pi OS

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

Verificar:

```bash
python3 --version
pip3 --version
```

---

# 🧪 Crear el entorno virtual

En la carpeta del proyecto:

```bash
python3 -m venv venv
```

Activar:

```bash
source venv/bin/activate
```

---

# 📦 Instalar dependencias

```bash
pip install plexapi python-dotenv requests streamlit pandas
```

---

# 🔑 Obtener Token de Plex

1. Entra en https://app.plex.tv/desktop  
2. Selecciona tu servidor local  
3. Pulsa **F12**  
4. Ve a pestaña **Network / Red**  
5. Busca:

```
X-Plex-Token
```

6. Copia el valor del token en tu `.env`.

---

# ⚙️ Configuración del `.env`

Crea un archivo:

```
.env
```

Contenido recomendado:

```env
# --- Datos de Plex ---
PLEX_BASEURL=http://192.168.1.10:32400
PLEX_TOKEN=TU_PLEX_TOKEN
OMDB_API_KEY=TU_API_KEY

# --- Bibliotecas a excluir ---
EXCLUDE_LIBRARIES=Series TV, Música, Familia, Fotos

# --- Prefijo CSV ---
OUTPUT_PREFIX=report

# --- Lógica de decisión ---
IMDB_KEEP_MIN_RATING=7.0
IMDB_KEEP_MIN_RATING_WITH_RT=6.5
RT_KEEP_MIN_SCORE=75
IMDB_KEEP_MIN_VOTES=50000
IMDB_DELETE_MAX_RATING=6.0
RT_DELETE_MAX_SCORE=50
IMDB_DELETE_MAX_VOTES=5000
IMDB_DELETE_MAX_VOTES_NO_RT=2000
IMDB_MIN_VOTES_FOR_KNOWN=1000

# --- Control del rate-limit de OMDb ---
OMDB_RATE_LIMIT_WAIT_SECONDS=60
OMDB_RATE_LIMIT_MAX_RETRIES=1

# --- Configuración borrado ---
DELETE_DRY_RUN=true
DELETE_REQUIRE_CONFIRM=true
```

---

# ▶️ Ejecutar el analizador

```bash
source venv/bin/activate
python analiza_plex.py
```

Genera:

- `report_all.csv`
- `report_filtered.csv`
- `report_filtered.html`
- `omdb_cache.json`

---

# 📊 Dashboard Streamlit

Ejecutar:

```bash
streamlit run dashboard.py
```

Accede en navegador a:

```
http://localhost:8501
```

Incluye:

- Vista completa del catálogo
- Candidatas DELETE/MAYBE
- Búsqueda avanzada
- Borrado seguro desde interfaz

---

# 🧹 Borrado seguro de archivos

El dashboard permite borrar archivos marcados como `DELETE`.

Protecciones:

- DRY RUN → no borra nada
- Confirmación obligatoria → escribir **BORRAR**
- Logs detallados

Si quieres borrarlo desde consola:

```bash
python delete_from_csv.py
```

---

# 💾 Cache `omdb_cache.json`

Guarda resultados de OMDb:

- Acelera análisis futuros
- Reduce bloqueos
- Persistente entre ejecuciones

---

# 🚨 Manejo del rate limit de OMDb

Si OMDb devuelve:

```json
{"Error": "Request limit reached!"}
```

El script:

1. Espera `OMDB_RATE_LIMIT_WAIT_SECONDS` (por defecto 60s)  
2. Reintenta 1 vez  
3. Si vuelve a fallar → para el análisis de manera segura

---

# 📊 Estructura de los CSV

### report_all.csv  
Contiene todo tu catálogo.

Columnas principales:

| Campo | Descripción |
|-------|-------------|
| library | Biblioteca Plex |
| title | Título |
| year | Año |
| imdb_rating | Nota IMDb |
| rt_score | Rotten Tomatoes |
| imdb_votes | Votos IMDb |
| plex_rating | Nota Plex |
| decision | KEEP / MAYBE / DELETE / UNKNOWN |
| reason | Motivo |
| misidentified_hint | Pistas sobre identificación incorrecta |
| file | Ruta del archivo |

### report_filtered.csv  
Solo contiene:

- DELETE  
- MAYBE  

Ordenado automáticamente de peor a menos peor.

---

# 🛑 .gitignore recomendado

```
venv/
.env
omdb_cache.json
__pycache__/
*.pyc
```

---

# ✨ Mejoras futuras

- Integración con TMDb API  
- Limpieza automática programada  

---

# 🎉 ¡Listo!

Tu ecosistema Plex Movies Cleaner está preparado para:

- Analizar  
- Valorar  
- Filtrar  
- Visualizar  
- Borrar  
- Mantener limpio tu servidor Plex  

