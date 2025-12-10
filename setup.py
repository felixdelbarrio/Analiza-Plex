from setuptools import setup

# Cargamos el README.md como descripción larga, si existe.
try:
    with open("README.md", encoding="utf-8") as f:
        long_description = f.read()
except FileNotFoundError:
    long_description = ""

setup(
    name="plex-movies-cleaner",
    version="0.1.0",
    description="Herramientas para analizar bibliotecas de Plex y sugerir limpieza/normalización de metadatos.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Félix del Barrio",
    url="",
    # No creamos paquetes; usamos los módulos sueltos existentes.
    py_modules=["analiza_plex", "dashboard"],
    # Dependencias detectadas a partir de los imports de analiza_plex.py y dashboard.py
    install_requires=[
        "python-dotenv",
        "requests",
        "plexapi",
        "googletrans==4.0.0-rc1",
        "pandas",
        "streamlit",
        "altair",
        "st-aggrid",
    ],
    extras_require={
        # Extra vacío por ahora, pero permite usar `-e .[dev]` sin romper nada.
        "dev": [],
    },
    python_requires=">=3.8",
)