from __future__ import annotations

"""
Punto de entrada unificado para análisis de películas.

Al ejecutarse, pregunta al usuario si quiere analizar:
  1) Plex
  2) DLNA / directorio local

Según la opción elegida, delega en:
  - backend.analiza_plex.analyze_all_libraries()
  - backend.analiza_dnla.analyze_dlna_server()
"""

from typing import Literal

from backend.analiza_plex import analyze_all_libraries
from backend.analiza_dnla import analyze_dlna_server


Choice = Literal["1", "2"]


def _ask_source() -> Choice:
    """Pregunta al usuario el origen de datos a analizar."""
    prompt = (
        "¿Qué origen quieres analizar?\n"
        "  1) Plex\n"
        "  2) DLNA / directorio local\n"
        "Selecciona una opción (1/2): "
    )
    while True:
        answer = input(prompt).strip()
        if answer in ("1", "2"):
            return answer  # type: ignore[return-value]
        print("Opción no válida. Introduce 1 o 2.")


def main() -> None:
    """Punto de entrada principal."""
    choice = _ask_source()

    if choice == "1":
        analyze_all_libraries()
    else:
        analyze_dlna_server()


if __name__ == "__main__":
    main()