# 🎬 Analiza Movies

**Analiza Movies** es una herramienta avanzada en Python para **analizar, evaluar y limpiar bibliotecas de películas** (Plex, DLNA o fuentes locales) usando datos objetivos como IMDb, Rotten Tomatoes y metadatos enriquecidos.

Está diseñada para usuarios con **grandes colecciones** que quieren tomar decisiones informadas sobre qué conservar, revisar o eliminar, **sin riesgo y con control total**.

---

## ✨ Qué hace Analiza Movies

- 📚 Analiza bibliotecas Plex, DLNA o listas manuales
- 🌐 Enriquece películas con datos externos (IMDb, RT, Wikipedia)
- 🧠 Calcula puntuaciones objetivas (rating, popularidad, antigüedad)
- 🏷️ Clasifica automáticamente:
  - 🟢 **KEEP**
  - 🔴 **DELETE**
  - 🟠 **MAYBE**
  - ⚪ **UNKNOWN**
- 📊 Genera informes HTML interactivos y dashboards
- 🧹 Ofrece borrado **manual y seguro** (nunca automático)

---

## 🧑‍💻 Público objetivo

- Usuarios avanzados de **Plex**
- Coleccionistas con cientos o miles de películas
- Personas que quieren **limpiar sin perder joyas**
- Desarrolladores que quieren extender la lógica

---

## 🚀 Instalación

### 1️⃣ Requisitos

- Python **3.10 o superior**
- Acceso a Plex (opcional)
- Clave API de OMDb (gratuita)

---

### 2️⃣ Clonar el repositorio

```bash
git clone https://github.com/tuusuario/analiza-movies.git
cd analiza-movies
```

---

### 3️⃣ Crear entorno virtual (recomendado)

```bash
python -m venv .venv
source .venv/bin/activate  # Linux / macOS
.venv\Scripts\activate   # Windows
```

---

### 4️⃣ Instalar dependencias

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración (.env)

Crea un archivo `.env` en la raíz del proyecto.

### Variables obligatorias

```env
OMDB_API_KEY=tu_api_key_de_omdb
```

### Variables Plex (opcional)

```env
PLEX_BASE_URL=http://localhost:32400
PLEX_TOKEN=tu_token_plex
```

### Variables opcionales

```env
LOG_LEVEL=INFO
CACHE_ENABLED=true
```

---

## ▶️ Uso rápido

### Análisis completo

```bash
python analiza.py
```

### Dashboard interactivo

```bash
streamlit run dashboard.py
```

### Borrado (solo tras revisar resultados)

```bash
python delete.py
```

---

## 📊 Reportes generados

### HTML interactivo
- Tabla filtrable y ordenable
- Posters
- Motivo explícito de cada decisión
- Gráficos de distribución

### CSV
- Ideal para Excel, Google Sheets o backups

---

## 🔒 Seguridad ante todo

- ❌ Nunca borra automáticamente
- ✅ El análisis y el borrado están separados
- ✅ El usuario ejecuta cada paso conscientemente
- ✅ Todo es reproducible

---

## 🛣️ Roadmap

- Configuración por YAML
- Soporte para series
- Tests automatizados
- Versionado de análisis
- Plugins de scoring

---

## 📄 Documentación técnica

- [`ARCHITECTURE.md`](ARCHITECTURE.md) – Arquitectura interna y diseño

---

## 📜 Licencia

Uso personal / educativo.  
Ajusta la licencia antes de publicar públicamente.

---

**Analiza Movies te ayuda a decidir con datos, no con nostalgia.**
