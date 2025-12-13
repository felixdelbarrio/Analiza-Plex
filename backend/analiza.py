# analiza.py
"""
Punto de entrada unificado para análisis de películas.

Al ejecutarse, pregunta al usuario si quiere analizar:
  1) Plex
  2) DNLA

Según la opción elegida, delega en:
  - analiza_plex.analyze_all_libraries()
  - analiza_dlna.analyze_dlna_server()
"""

from typing import Literal

from analiza_plex import analyze_all_libraries
from analiza_dlna import analyze_dlna_server


def _ask_source() -> Literal["1", "2"]:
    """
    Pregunta en bucle al usuario de dónde quiere importar las películas.

    Solo acepta '1' o '2'. Para cualquier otra entrada, muestra un
    mensaje de error y vuelve a preguntar.
    """
    while True:
        print("¿De dónde quieres importar las películas?")
        print("  1) Plex")
        print("  2) DNLA")
        choice = input("Selecciona una opción (1/2): ").strip()

        if choice in ("1", "2"):
            return choice

        print("\n⚠ Opción no válida. Por favor introduce '1' o '2'.\n")


def main() -> None:
    """
    Función principal del script unificado.

    - Si el usuario elige '1' → ejecuta el flujo actual de Plex
      llamando a analyze_all_libraries() de analiza_plex.py.
    - Si el usuario elige '2' → ejecuta el flujo DNLA llamando a
      analyze_dlna_server() de analiza_dlna.py.
    """
    choice = _ask_source()

    if choice == "1":
        # Flujo actual de Plex (no se toca su implementación)
        analyze_all_libraries()
    else:
        # Flujo DNLA (debes tener implementado analyze_dlna_server()
        # en tu script analiza_dlna.py)
        analyze_dlna_server()


if __name__ == "__main__":
    main()