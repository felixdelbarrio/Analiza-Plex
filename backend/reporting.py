import csv
import json
from typing import Any, Dict, List


def write_all_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Escribe el CSV completo con todas las películas analizadas.
    """
    if not rows:
        print("No hay filas para escribir en report_all.csv")
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV completo escrito en {path}")


def write_filtered_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Escribe el CSV filtrado con DELETE/MAYBE.
    """
    if not rows:
        print("No hay filas filtradas para escribir en report_filtered.csv")
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV filtrado escrito en {path}")


def write_suggestions_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Escribe el CSV con sugerencias de metadata.

    Si no hay filas, se escribe igualmente un CSV vacío con sólo cabeceras
    estándar (incluyendo 'library') para que el dashboard no falle al leerlo.
    """
    standard_fieldnames = [
        "plex_guid",
        "library",
        "plex_title",
        "plex_year",
        "omdb_title",
        "omdb_year",
        "imdb_rating",
        "imdb_votes",
        "suggestions_json",
    ]

    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = standard_fieldnames
        print(
            "No hay sugerencias de metadata para escribir. "
            "Se crea un CSV vacío con solo cabeceras."
        )

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)

    print(f"Sugerencias de metadata escritas en {path}")


def write_interactive_html(path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Genera un informe HTML interactivo (DataTables + Chart.js) a partir de
    las filas filtradas (DELETE/MAYBE).

    El HTML resultante se parece al antiguo `report_filtered.html`:
      - Tabla interactiva con filtros/ordenación
      - Gráfico de barras por decisión
      - Gráfico de barras por biblioteca
    """
    # Preparamos las filas que se pasarán al JS.
    # Seleccionamos un subconjunto de campos relevantes.
    processed_rows = []
    for r in rows:
        processed_rows.append(
            {
                "poster_url": r.get("poster_url"),
                "library": r.get("library"),
                "title": r.get("title"),
                "year": r.get("year"),
                "imdb_rating": r.get("imdb_rating"),
                "rt_score": r.get("rt_score"),
                "imdb_votes": r.get("imdb_votes"),
                "decision": r.get("decision"),
                "reason": r.get("reason"),
                "misidentified_hint": r.get("misidentified_hint"),
                "file": r.get("file"),
            }
        )

    rows_json = json.dumps(processed_rows, ensure_ascii=False)

    # Plantilla HTML (similar a la versión anterior).
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Plex Movies Cleaner — Informe interactivo</title>

<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<style>
body {{
    font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    margin: 1.5rem;
    background: #0b1120;
    color: #e5e7eb;
}}

h1 {{
    margin-bottom: 0.25rem;
}}

.subtitle {{
    color: #9ca3af;
    margin-bottom: 1.5rem;
}}

.container {{
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 1.5rem;
}}

table.dataTable thead th {{
    background-color: #111827;
    color: #e5e7eb;
}}

table.dataTable tbody tr {{
    background-color: #020617;
    color: #e5e7eb;
}}

.tag-KEEP {{
    background-color: #166534;
    color: #dcfce7;
    padding: 0.15rem 0.4rem;
    border-radius: 999px;
    font-size: 0.75rem;
}}

.tag-DELETE {{
    background-color: #7f1d1d;
    color: #fee2e2;
    padding: 0.15rem 0.4rem;
    border-radius: 999px;
    font-size: 0.75rem;
}}

.tag-MAYBE {{
    background-color: #92400e;
    color: #ffedd5;
    padding: 0.15rem 0.4rem;
    border-radius: 999px;
    font-size: 0.75rem;
}}

.tag-UNKNOWN {{
    background-color: #374151;
    color: #e5e7eb;
    padding: 0.15rem 0.4rem;
    border-radius: 999px;
    font-size: 0.75rem;
}}

.poster-img {{
    width: 50px;
    height: auto;
    border-radius: 0.25rem;
    object-fit: cover;
}}

.badge {{
    display: inline-flex;
    padding: 0.1rem 0.4rem;
    border-radius: 999px;
    font-size: 0.7rem;
    background-color: #1f2937;
    color: #e5e7eb;
}}

.charts {{
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
}}

.chart-card {{
    background-color: #020617;
    border-radius: 0.75rem;
    padding: 1rem;
    box-shadow: 0 10px 25px rgba(0,0,0,0.6);
    border: 1px solid #1f2937;
}}
</style>
</head>
<body>

<h1>🎬 Plex Movies Cleaner — Informe interactivo</h1>
<p class="subtitle">Vista rápida de las películas marcadas como DELETE / MAYBE.</p>

<div class="container">
  <div>
    <table id="movies" class="display" style="width:100%">
      <thead>
        <tr>
          <th>Poster</th>
          <th>Library</th>
          <th>Title</th>
          <th>Year</th>
          <th>IMDb</th>
          <th>RT</th>
          <th>IMDb votes</th>
          <th>Decision</th>
          <th>Reason</th>
          <th>MisID hint</th>
          <th>File</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="charts">
    <div class="chart-card">
      <h3>Decisiones</h3>
      <canvas id="decisionChart"></canvas>
    </div>
    <div class="chart-card">
      <h3>Películas por biblioteca</h3>
      <canvas id="libraryChart"></canvas>
    </div>
  </div>
</div>

<script>
// Datos generados por Python
const rows = {rows_json};

// Construcción de tabla
const tableData = rows.map(r => {{
  const poster = r.poster_url
    ? `<img src="${{r.poster_url}}" class="poster-img" loading="lazy">`
    : "";

  const decisionClass = r.decision ? `tag-${{r.decision}}` : "tag-UNKNOWN";
  const decisionLabel = r.decision || "UNKNOWN";

  return [
    poster,
    r.library || "",
    r.title || "",
    r.year || "",
    r.imdb_rating != null ? r.imdb_rating.toFixed ? r.imdb_rating.toFixed(1) : r.imdb_rating : "",
    r.rt_score != null ? r.rt_score + "%" : "",
    r.imdb_votes != null ? r.imdb_votes.toLocaleString() : "",
    `<span class="${{decisionClass}}">${{decisionLabel}}</span>`,
    r.reason || "",
    r.misidentified_hint || "",
    r.file || "",
  ];
}});

$(document).ready(function() {{
  $('#movies').DataTable({{
    data: tableData,
    pageLength: 25,
    order: [[4, 'asc']], // por IMDb ascendente (peores primero)
  }});
}});

// Gráfico de decisiones
(function() {{
  const counts = {{}};
  for (const r of rows) {{
    const d = r.decision || "UNKNOWN";
    counts[d] = (counts[d] || 0) + 1;
  }}
  const labels = Object.keys(counts);
  const values = labels.map(k => counts[k]);

  const ctx = document.getElementById('decisionChart').getContext('2d');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels,
      datasets: [{{
        label: 'Número de películas',
        data: values,
      }}],
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
      }},
      scales: {{
        x: {{ ticks: {{ color: '#e5e7eb' }} }},
        y: {{ ticks: {{ color: '#e5e7eb' }} }},
      }},
    }},
  }});
}})();

// Gráfico por biblioteca (top 10)
(function() {{
  const counts = {{}};
  for (const r of rows) {{
    const lib = r.library || 'Unknown';
    counts[lib] = (counts[lib] || 0) + 1;
  }}
  const entries = Object.entries(counts).sort((a,b) => b[1] - a[1]).slice(0, 10);
  const labels = entries.map(e => e[0]);
  const values = entries.map(e => e[1]);

  const ctx = document.getElementById('libraryChart').getContext('2d');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels,
      datasets: [{{
        label: 'Películas',
        data: values,
      }}],
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
      }},
      scales: {{
        x: {{ ticks: {{ color: '#e5e7eb' }} }},
        y: {{ ticks: {{ color: '#e5e7eb' }} }},
      }},
    }},
  }});
}})();
</script>

</body>
</html>
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Informe HTML interactivo escrito en {path}")