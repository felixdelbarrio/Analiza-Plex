import os
import csv
import json
import time
import math
import requests
from typing import Optional, Dict, Any, List, Tuple

from dotenv import load_dotenv
from plexapi.server import PlexServer

# ============================================================
#              CARGA DE CONFIGURACIÓN DESDE .env
# ============================================================

load_dotenv()

PLEX_BASEURL = os.getenv("PLEX_BASEURL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "report")

raw_exclude = os.getenv("EXCLUDE_LIBRARIES", "")
EXCLUDE_LIBRARIES = [x.strip() for x in raw_exclude.split(",") if x.strip()]

# Umbrales de decisión para KEEP/DELETE
IMDB_KEEP_MIN_RATING = float(os.getenv("IMDB_KEEP_MIN_RATING", "7.0"))
IMDB_KEEP_MIN_RATING_WITH_RT = float(os.getenv("IMDB_KEEP_MIN_RATING_WITH_RT", "6.5"))
RT_KEEP_MIN_SCORE = int(os.getenv("RT_KEEP_MIN_SCORE", "75"))
IMDB_KEEP_MIN_VOTES = int(os.getenv("IMDB_KEEP_MIN_VOTES", "50000"))

IMDB_DELETE_MAX_RATING = float(os.getenv("IMDB_DELETE_MAX_RATING", "6.0"))
RT_DELETE_MAX_SCORE = int(os.getenv("RT_DELETE_MAX_SCORE", "50"))
IMDB_DELETE_MAX_VOTES = int(os.getenv("IMDB_DELETE_MAX_VOTES", "5000"))
IMDB_DELETE_MAX_VOTES_NO_RT = int(os.getenv("IMDB_DELETE_MAX_VOTES_NO_RT", "2000"))

IMDB_MIN_VOTES_FOR_KNOWN = int(os.getenv("IMDB_MIN_VOTES_FOR_KNOWN", "1000"))

# Rate limit OMDb
OMDB_RATE_LIMIT_WAIT_SECONDS = int(os.getenv("OMDB_RATE_LIMIT_WAIT_SECONDS", "60"))
OMDB_RATE_LIMIT_MAX_RETRIES = int(os.getenv("OMDB_RATE_LIMIT_MAX_RETRIES", "1"))

# ----- Parámetros extra para corrección de metadata -----
METADATA_OUTPUT_PREFIX = os.getenv("METADATA_OUTPUT_PREFIX", "metadata_fix")
METADATA_MIN_RATING_FOR_OK = float(os.getenv("METADATA_MIN_RATING_FOR_OK", "6.0"))
METADATA_MIN_VOTES_FOR_OK = int(os.getenv("METADATA_MIN_VOTES_FOR_OK", "2000"))

METADATA_DRY_RUN = os.getenv("METADATA_DRY_RUN", "true").lower() == "true"
METADATA_APPLY_CHANGES = os.getenv("METADATA_APPLY_CHANGES", "false").lower() == "true"

print("DEBUG PLEX_BASEURL:", PLEX_BASEURL)
print("DEBUG TOKEN:", "****" if PLEX_TOKEN else None)
print("DEBUG EXCLUDE_LIBRARIES:", EXCLUDE_LIBRARIES)
print("DEBUG METADATA_DRY_RUN:", METADATA_DRY_RUN)
print("DEBUG METADATA_APPLY_CHANGES:", METADATA_APPLY_CHANGES)

# ============================================================
#                      CACHE OMDb LOCAL
# ============================================================

CACHE_FILE = "omdb_cache.json"


def load_cache() -> Dict[str, Any]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


omdb_cache = load_cache()

# Flag global para desactivar OMDb cuando salte el rate limit
OMDB_DISABLED = False

# ============================================================
#                      PLEX CONNECTION
# ============================================================

def connect_plex():
    if not PLEX_BASEURL or not PLEX_TOKEN:
        raise RuntimeError("Faltan PLEX_BASEURL o PLEX_TOKEN en el .env")

    print(f"Conectando a Plex en {PLEX_BASEURL} ...")
    plex = PlexServer(PLEX_BASEURL, PLEX_TOKEN)
    print("Conectado OK.")
    return plex


def get_imdb_id_from_plex_guid(guid: Optional[str]) -> Optional[str]:
    if not guid:
        return None
    if "imdb://" in guid:
        try:
            part = guid.split("imdb://", 1)[1]
            return part.split("?", 1)[0]
        except Exception:
            return None
    return None

# ============================================================
#               CONSULTA A OMDb + CACHE + DELAY
# ============================================================

def query_omdb(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Envoltura genérica para OMDb:
    - Usa cache
    - Respeta rate limit
    - Si se alcanza el límite y persiste, desactiva OMDb para el resto
      de la ejecución (OMDB_DISABLED=True) y devuelve None para nuevas peticiones
      (pero se sigue usando la caché existente).
    """
    global OMDB_DISABLED

    if not OMDB_API_KEY:
        raise RuntimeError("No hay OMDB_API_KEY en .env")

    key = json.dumps(params, sort_keys=True, ensure_ascii=False)

    # 1) Siempre mirar la caché aunque OMDB esté desactivado
    if key in omdb_cache:
        return omdb_cache[key]

    # 2) Si OMDB está desactivado, no hacemos llamadas nuevas
    if OMDB_DISABLED:
        return None

    attempts = 0
    base_params = dict(params)
    base_params["apikey"] = OMDB_API_KEY

    while True:
        time.sleep(0.5)
        try:
            resp = requests.get("https://www.omdbapi.com/", params=base_params, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"Error consultando OMDb con params={params}: {e}")
            return None

        # Rate limit de OMDb
        if data.get("Error") == "Request limit reached!":
            if attempts < OMDB_RATE_LIMIT_MAX_RETRIES:
                attempts += 1
                print("\n🚨 OMDb ha devuelto 'Request limit reached!'")
                print(
                    f"⏸ Esperando {OMDB_RATE_LIMIT_WAIT_SECONDS} segundos antes de reintentar "
                    f"(intento {attempts}/{OMDB_RATE_LIMIT_MAX_RETRIES})...\n"
                )
                time.sleep(OMDB_RATE_LIMIT_WAIT_SECONDS)
                continue
            else:
                print("\n🚨 OMDb sigue devolviendo 'Request limit reached!' tras reintentos.")
                print("⚠️ OMDb se desactiva para el resto de esta ejecución.")
                print("   Se continuará el análisis SIN datos nuevos de OMDb,")
                print("   pero se seguirá utilizando la caché local existente.\n")
                OMDB_DISABLED = True
                return None

        # Guardamos en caché y devolvemos
        omdb_cache[key] = data
        save_cache(omdb_cache)
        return data


def query_omdb_by_imdb_id(imdb_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not imdb_id:
        return None
    data = query_omdb({"i": imdb_id, "type": "movie"})
    if not data or data.get("Response") != "True":
        return None
    return data


def extract_ratings_from_omdb(data: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    imdb_rating = None
    imdb_votes = None
    rt_score = None

    if not data:
        return imdb_rating, imdb_votes, rt_score

    try:
        val = data.get("imdbRating")
        if val and val != "N/A":
            imdb_rating = float(val)
    except Exception:
        pass

    try:
        votes = data.get("imdbVotes", "0").replace(",", "")
        imdb_votes = int(votes)
    except Exception:
        pass

    for r in data.get("Ratings", []):
        if r.get("Source") == "Rotten Tomatoes":
            v = r.get("Value")
            if v and v.endswith("%"):
                try:
                    rt_score = int(v[:-1])
                except Exception:
                    pass

    return imdb_rating, imdb_votes, rt_score


def extract_ratings_from_omdb_detail(data: Dict[str, Any]) -> Tuple[Optional[float], Optional[int]]:
    """
    Versión simplificada para el sistema de metadata:
    solo imdbRating + imdbVotes.
    """
    imdb_rating = None
    imdb_votes = None

    if not data:
        return imdb_rating, imdb_votes

    try:
        val = data.get("imdbRating")
        if val and val != "N/A":
            imdb_rating = float(val)
    except Exception:
        pass

    try:
        votes = data.get("imdbVotes", "0").replace(",", "")
        imdb_votes = int(votes)
    except Exception:
        pass

    return imdb_rating, imdb_votes

# ============================================================
#                    DECISIÓN KEEP / DELETE
# ============================================================

def decide_keep_or_delete_with_reason(imdb_rating, imdb_votes, rt_score):
    """
    Devuelve tuple: (decision, reason)
    decision: KEEP / MAYBE / DELETE / UNKNOWN
    """
    if imdb_rating is None and rt_score is None and (
        imdb_votes is None or imdb_votes < IMDB_MIN_VOTES_FOR_KNOWN
    ):
        return "UNKNOWN", "no_ratings_and_few_votes"

    if imdb_rating is not None and imdb_rating >= IMDB_KEEP_MIN_RATING:
        return "KEEP", "high_imdb_rating"

    if (
        imdb_rating is not None
        and imdb_rating >= IMDB_KEEP_MIN_RATING_WITH_RT
        and rt_score is not None
        and rt_score >= RT_KEEP_MIN_SCORE
    ):
        return "KEEP", "good_imdb_and_rt"

    if imdb_votes is not None and imdb_votes >= IMDB_KEEP_MIN_VOTES:
        return "KEEP", "very_popular_imdb_votes"

    if imdb_rating is not None and imdb_rating < IMDB_DELETE_MAX_RATING:
        if rt_score is not None:
            if (
                rt_score < RT_DELETE_MAX_SCORE
                and imdb_votes is not None
                and imdb_votes < IMDB_DELETE_MAX_VOTES
            ):
                return "DELETE", "low_imdb_low_rt_few_votes"
        else:
            if imdb_votes is not None and imdb_votes < IMDB_DELETE_MAX_VOTES_NO_RT:
                return "DELETE", "low_imdb_few_votes_no_rt"

    return "MAYBE", "middle_values"


def detect_misidentified(movie, imdb_rating, imdb_votes, rt_score):
    reasons = []

    if getattr(movie, "guid", None) is None:
        reasons.append("no_guid")

    if imdb_rating is None and imdb_votes is None and rt_score is None:
        reasons.append("no_external_data")

    if imdb_rating is not None and imdb_votes is not None:
        if imdb_rating >= 9.5 and imdb_votes < 100:
            reasons.append("suspicious_high_rating_low_votes")

    return ",".join(reasons) if reasons else ""

# ============================================================
#                ORDENACIÓN DEL CSV FILTRADO
# ============================================================

def sort_filtered_rows(rows):
    def score(row):
        decision = row.get("decision")
        group = 0 if decision == "DELETE" else 1

        imdb_rating = row.get("imdb_rating")
        imdb_rating_val = imdb_rating if imdb_rating is not None else -1

        rt = row.get("rt_score")
        rt_val = rt if rt is not None else -1

        votes = row.get("imdb_votes")
        votes_val = votes if votes is not None else -1

        return (group, imdb_rating_val, rt_val, votes_val)

    return sorted(rows, key=score)

# ============================================================
#                  HTML INTERACTIVO AVANZADO
# ============================================================

def write_html_interactive(path, rows):
    if not rows:
        print(f"No hay filas para escribir en {path}.")
        return

    safe_rows = []
    for r in rows:
        safe_rows.append({
            "library": r.get("library", ""),
            "title": r.get("title", ""),
            "year": r.get("year", ""),
            "imdb_rating": r.get("imdb_rating", None),
            "rt_score": r.get("rt_score", None),
            "imdb_votes": r.get("imdb_votes", None),
            "decision": r.get("decision", ""),
            "reason": r.get("reason", ""),
            "misidentified_hint": r.get("misidentified_hint", ""),
            "file": r.get("file", ""),
        })

    rows_json = json.dumps(safe_rows, ensure_ascii=False)

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
    background: #fafafa;
}}
h1, h2 {{
    margin-top: 0;
}}
.container {{
    max-width: 1400px;
    margin: 0 auto;
}}
table.dataTable thead th {{
    background: #eee;
}}
.bad-delete {{
    background-color: #ffebee !important;
}}
.maybe-row {{
    background-color: #fffde7 !important;
}}
.chart-container {{
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    margin-bottom: 2rem;
}}
.chart-box {{
    flex: 1 1 400px;
    background: #fff;
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}}
</style>
</head>
<body>
<div class="container">
  <h1>🎬 Plex Movies Cleaner — Informe interactivo</h1>
  <p>Total filas (DELETE + MAYBE): <strong>{len(rows)}</strong></p>

  <div class="chart-container">
    <div class="chart-box">
      <h2>Recuento por decisión</h2>
      <canvas id="chart_decisions"></canvas>
    </div>
    <div class="chart-box">
      <h2>Películas por biblioteca y decisión</h2>
      <canvas id="chart_libraries"></canvas>
    </div>
  </div>

  <h2>Tabla interactiva (candidatas)</h2>
  <table id="movies" class="display" style="width:100%">
    <thead>
      <tr>
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

<script>
const rows = {rows_json};

function buildTables() {{
    const tbody = $('#movies tbody');
    rows.forEach(r => {{
        const cls = r.decision === 'DELETE' ? 'bad-delete' :
                    (r.decision === 'MAYBE' ? 'maybe-row' : '');
        const tr = $(`
            <tr class="${{cls}}">
                <td>${{r.library || ''}}</td>
                <td>${{r.title || ''}}</td>
                <td>${{r.year || ''}}</td>
                <td>${{r.imdb_rating ?? ''}}</td>
                <td>${{r.rt_score ?? ''}}</td>
                <td>${{r.imdb_votes ?? ''}}</td>
                <td>${{r.decision || ''}}</td>
                <td>${{r.reason || ''}}</td>
                <td>${{r.misidentified_hint || ''}}</td>
                <td><small>${{r.file || ''}}</small></td>
            </tr>
        `);
        tbody.append(tr);
    }});

    $('#movies').DataTable({{
        pageLength: 50,
        order: [[3, 'asc']],
    }});
}}

function buildCharts() {{
    const counts = {{}};
    const byLibraryDecision = {{}};

    rows.forEach(r => {{
        const d = r.decision || 'UNKNOWN';
        counts[d] = (counts[d] || 0) + 1;

        const lib = r.library || 'Sin biblioteca';
        if (!byLibraryDecision[lib]) byLibraryDecision[lib] = {{}};
        byLibraryDecision[lib][d] = (byLibraryDecision[lib][d] || 0) + 1;
    }});

    const ctxDecisions = document.getElementById('chart_decisions').getContext('2d');
    const decLabels = Object.keys(counts);
    const decValues = decLabels.map(k => counts[k]);

    new Chart(ctxDecisions, {{
        type: 'bar',
        data: {{
            labels: decLabels,
            datasets: [{{
                label: 'Número de películas',
                data: decValues
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
            }},
            scales: {{
                y: {{ beginAtZero: true }}
            }}
        }}
    }});

    const libs = Object.keys(byLibraryDecision);
    const allDecisions = Array.from(new Set(
        Object.values(byLibraryDecision).flatMap(d => Object.keys(d))
    ));

    const datasets = allDecisions.map(dec => {{
        return {{
            label: dec,
            data: libs.map(lib => byLibraryDecision[lib][dec] || 0),
            stack: 'stack1'
        }};
    }});

    const ctxLibs = document.getElementById('chart_libraries').getContext('2d');
    new Chart(ctxLibs, {{
        type: 'bar',
        data: {{
            labels: libs,
            datasets: datasets
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{
                    position: 'bottom'
                }}
            }},
            scales: {{
                x: {{
                    stacked: true,
                    ticks: {{
                        autoSkip: false,
                        maxRotation: 60,
                        minRotation: 30
                    }}
                }},
                y: {{
                    stacked: true,
                    beginAtZero: true
                }}
            }}
        }}
    }});
}}

$(document).ready(function() {{
    buildTables();
    buildCharts();
}});
</script>

</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML interactivo generado: {path}")

# ============================================================
#            SISTEMA AUTOMÁTICO CORRECCIÓN METADATA
# ============================================================

def search_omdb_candidates(title: str, year: Optional[int]) -> List[Dict[str, Any]]:
    params = {"s": title, "type": "movie"}
    if year:
        params["y"] = str(year)
    data = query_omdb(params)
    if not data or data.get("Response") != "True":
        return []
    results = data.get("Search", [])
    return results if isinstance(results, list) else []


def score_candidate(plex_title: str, plex_year: Optional[int], cand: Dict[str, Any]) -> float:
    cand_year = None
    try:
        cy = cand.get("Year")
        if cy and cy != "N/A":
            cand_year = int(cy[:4])
    except Exception:
        pass

    score = 0.0

    if plex_year and cand_year:
        if plex_year == cand_year:
            score += 40
        else:
            diff = abs(plex_year - cand_year)
            score += max(0, 30 - diff * 5)

    plen = len(plex_title or "")
    clen = len(cand.get("Title") or "")
    if plen and clen:
        diff_len = abs(plen - clen)
        score += max(0, 20 - diff_len * 2)

    imdb_id = cand.get("imdbID")
    if imdb_id:
        detail = query_omdb_by_imdb_id(imdb_id)
        imdb_rating, imdb_votes = extract_ratings_from_omdb_detail(detail or {})
        if imdb_rating:
            score += imdb_rating * 3
        if imdb_votes:
            score += math.log10(imdb_votes + 1) * 5

    return score


def find_best_omdb_match(title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
    candidates = search_omdb_candidates(title, year)
    if not candidates:
        return None

    best = None
    best_score = -1.0

    for cand in candidates:
        s = score_candidate(title, year, cand)
        if s > best_score:
            best_score = s
            best = cand

    if not best:
        return None

    imdb_id = best.get("imdbID")
    detail = query_omdb_by_imdb_id(imdb_id) if imdb_id else None
    imdb_rating, imdb_votes = extract_ratings_from_omdb_detail(detail or {})

    result = {
        "imdb_id": imdb_id,
        "title": best.get("Title"),
        "year": best.get("Year"),
        "type": best.get("Type"),
        "poster": best.get("Poster"),
        "imdb_rating": imdb_rating,
        "imdb_votes": imdb_votes,
        "raw_detail": detail,
        "score": best_score,
    }
    return result


def is_metadata_suspicious(
    imdb_id: Optional[str],
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
) -> Tuple[bool, List[str]]:
    reasons = []

    if imdb_id is None:
        reasons.append("no_imdb_id")

    if imdb_rating is None and imdb_votes is None:
        reasons.append("no_external_data")

    if imdb_rating is not None and imdb_rating < METADATA_MIN_RATING_FOR_OK:
        reasons.append("low_rating")

    if imdb_votes is not None and imdb_votes < METADATA_MIN_VOTES_FOR_OK:
        reasons.append("few_votes")

    return (len(reasons) > 0), reasons


def apply_new_imdb_guid(movie, new_imdb_id: str) -> Tuple[bool, str]:
    new_guid = f"com.plexapp.agents.imdb://{new_imdb_id}?lang=en"
    try:
        if METADATA_DRY_RUN:
            msg = f"[DRY RUN] Cambiar GUID de '{movie.title}' a {new_guid}"
            return True, msg

        if not METADATA_APPLY_CHANGES:
            msg = (
                f"[SKIP] METADATA_APPLY_CHANGES=false -> No se modifica GUID de '{movie.title}' "
                f"(nuevo GUID sugerido: {new_guid})"
            )
            return False, msg

        # 🚨 Esta parte puede necesitar ajuste según tu versión de Plex/plexapi
        movie._edit(**{"guid": new_guid})
        movie.reload()
        movie.refresh()

        msg = f"[OK] GUID de '{movie.title}' actualizado a {new_guid} y metadata refrescada"
        return True, msg

    except Exception as e:
        return False, f"[ERROR] Fallo actualizando GUID de '{movie.title}' -> {e}"


def write_suggestions_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print(f"No hay sugerencias para escribir en {path}.")
        return

    fieldnames = [
        "library",
        "plex_title",
        "plex_year",
        "plex_imdb_id",
        "plex_imdb_rating",
        "plex_imdb_votes",
        "suspicious_reason",
        "suggested_imdb_id",
        "suggested_title",
        "suggested_year",
        "suggested_imdb_rating",
        "suggested_imdb_votes",
        "suggested_score",
        "confidence",
        "action",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"CSV de sugerencias generado: {path}")

# ============================================================
#                ANÁLISIS DE UNA BIBLIOTECA
# ============================================================

def analyze_single_library(section, suggestions: List[Dict[str, Any]], logs: List[str]):
    rows = []

    print(f"\n--- Analizando biblioteca: {section.title} ---")
    movies = section.all()
    total = len(movies)
    print(f"Películas encontradas en {section.title}: {total}")

    for idx, movie in enumerate(movies, start=1):
        print(f"[{idx}/{total}] {movie.title} ({movie.year})")

        imdb_id = get_imdb_id_from_plex_guid(getattr(movie, "guid", None))

        omdb_data = query_omdb_by_imdb_id(imdb_id) if imdb_id else None
        imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_data)

        decision, reason = decide_keep_or_delete_with_reason(
            imdb_rating, imdb_votes, rt_score
        )

        misid_flag = detect_misidentified(movie, imdb_rating, imdb_votes, rt_score)

        # -----------------------------
        #  TAMAÑO Y RUTA DEL FICHERO (desde Plex)
        # -----------------------------
        file_path = None
        file_size = None

        try:
            if movie.media:
                media = movie.media[0]
                if media.parts:
                    total_size = 0
                    for part in media.parts:
                        print(
                            f"   -> part file={getattr(part, 'file', None)} "
                            f"size={getattr(part, 'size', None)} "
                            f"type={type(part)}"
                        )

                        if hasattr(part, "size") and part.size is not None:
                            total_size += int(part.size)

                        if file_path is None:
                            file_path = getattr(part, "file", None)

                    if total_size > 0:
                        file_size = total_size
                    else:
                        print(f"   !! WARNING: movie '{movie.title}' sin size en parts")
                else:
                    print(f"   !! WARNING: movie '{movie.title}' sin parts en media[0]")
            else:
                print(f"   !! WARNING: movie '{movie.title}' sin media")
        except Exception as e:
            print(f"   !! ERROR obteniendo tamaño para '{movie.title}': {e}")

        print(f"   -> RESULT file_path={file_path}, file_size={file_size}")

        rows.append({
            "library": section.title,
            "title": movie.title,
            "year": movie.year,
            "imdb_id": imdb_id,
            "imdb_rating": imdb_rating,
            "imdb_votes": imdb_votes,
            "rt_score": rt_score,
            "plex_rating": movie.rating,
            "file": file_path,
            "file_size": file_size,            # bytes desde Plex (suma de todas las parts)
            "ratingKey": movie.ratingKey,
            "thumb": movie.thumb,
            "decision": decision,
            "reason": reason,
            "misidentified_hint": misid_flag,
        })

        # ------ Parte de corrección de metadata ------
        suspicious, suspicious_reasons = is_metadata_suspicious(imdb_id, imdb_rating, imdb_votes)
        if not suspicious:
            continue

        try:
            suggested = find_best_omdb_match(movie.title, movie.year)
        except SystemExit:
            raise
        except Exception as e:
            logs.append(f"[ERROR] Buscando match OMDb para '{movie.title}': {e}")
            continue

        if not suggested:
            logs.append(f"[INFO] Sin sugerencia clara para '{movie.title}'")
            continue

        raw_score = suggested.get("score", 0.0)
        confidence = max(0, min(100, int(raw_score)))

        suggested_imdb_id = suggested.get("imdb_id")
        suggested_title = suggested.get("title")
        suggested_year = suggested.get("year")
        suggested_imdb_rating = suggested.get("imdb_rating")
        suggested_imdb_votes = suggested.get("imdb_votes")

        action = "REVIEW"
        if confidence >= 70:
            action = "AUTO_APPLY"
        elif confidence >= 40:
            action = "MAYBE"

        suggestions.append({
            "library": section.title,
            "plex_title": movie.title,
            "plex_year": movie.year,
            "plex_imdb_id": imdb_id,
            "plex_imdb_rating": imdb_rating,
            "plex_imdb_votes": imdb_votes,
            "suspicious_reason": ",".join(suspicious_reasons),
            "suggested_imdb_id": suggested_imdb_id,
            "suggested_title": suggested_title,
            "suggested_year": suggested_year,
            "suggested_imdb_rating": suggested_imdb_rating,
            "suggested_imdb_votes": suggested_imdb_votes,
            "suggested_score": raw_score,
            "confidence": confidence,
            "action": action,
        })

        if action == "AUTO_APPLY" and suggested_imdb_id:
            ok, msg = apply_new_imdb_guid(movie, suggested_imdb_id)
            logs.append(msg)
        else:
            logs.append(
                f"[INFO] '{movie.title}' -> sugerido imdb_id={suggested_imdb_id} "
                f"(conf={confidence}, action={action})"
            )

    return rows

# ============================================================
#                        CSV OUTPUT
# ============================================================

def write_csv(path, rows):
    if not rows:
        print(f"No hay filas para escribir en {path}.")
        return

    fieldnames = rows[0].keys()

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"CSV generado: {path}")

# ============================================================
#                   ANÁLISIS GLOBAL DE LIBRERÍAS
# ============================================================

def analyze_all_libraries():
    plex = connect_plex()
    sections = plex.library.sections()

    print("\nBibliotecas encontradas en Plex:")
    for s in sections:
        print(f"- {s.title} (tipo: {s.type})")
    print("\nExcluyendo:", EXCLUDE_LIBRARIES if EXCLUDE_LIBRARIES else "ninguna")

    all_rows = []
    suggestions: List[Dict[str, Any]] = []
    logs: List[str] = []

    for section in sections:
        if section.title in EXCLUDE_LIBRARIES:
            print(f"Saltando biblioteca excluida: {section.title}")
            continue

        if section.type != "movie":
            print(f"Saltando {section.title} porque no es de películas (tipo: {section.type})")
            continue

        rows_section = analyze_single_library(section, suggestions, logs)
        all_rows.extend(rows_section)

    if not all_rows:
        print("No se han encontrado películas en las bibliotecas analizadas.")
        return

    # CSV completo
    write_csv(f"{OUTPUT_PREFIX}_all.csv", all_rows)

    # CSV filtrado (solo MAYBE / DELETE), ordenado
    filtered = [r for r in all_rows if r.get("decision") in ("DELETE", "MAYBE")]
    filtered = sort_filtered_rows(filtered)
    write_csv(f"{OUTPUT_PREFIX}_filtered.csv", filtered)

    # Informe HTML interactivo de filtradas
    write_html_interactive(f"{OUTPUT_PREFIX}_filtered.html", filtered)

    # CSV de sugerencias de metadata
    sugg_csv = f"{METADATA_OUTPUT_PREFIX}_suggestions.csv"
    write_suggestions_csv(sugg_csv, suggestions)

    # Log de metadata
    log_path = f"{METADATA_OUTPUT_PREFIX}_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        for line in logs:
            f.write(line + "\n")
    print(f"Log de corrección metadata: {log_path}")

# ============================================================
#                        MAIN
# ============================================================

if __name__ == "__main__":
    analyze_all_libraries()