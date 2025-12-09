import os
import csv
import json
import time
import requests
from dotenv import load_dotenv
from plexapi.server import PlexServer
from html import escape

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

# Umbrales de decisión desde .env (con valores por defecto)
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

print("DEBUG PLEX_BASEURL:", PLEX_BASEURL)
print("DEBUG TOKEN:", "****" if PLEX_TOKEN else None)
print("DEBUG EXCLUDE_LIBRARIES:", EXCLUDE_LIBRARIES)

# ============================================================
#                      CACHE OMDb LOCAL
# ============================================================

CACHE_FILE = "omdb_cache.json"


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


omdb_cache = load_cache()

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


def get_imdb_id_from_plex_guid(guid: str | None):
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

def query_omdb_by_imdb_id(imdb_id: str | None):
    """
    Consulta OMDb respetando:
    - Cache local (omdb_cache.json)
    - Delay de 0.5s entre peticiones
    - Espera OMDB_RATE_LIMIT_WAIT_SECONDS y reintenta una vez si hay "Request limit reached!"
    - Si vuelve a fallar tras el reintento, parada limpia del script.
    """
    if not imdb_id:
        return None

    # 1) Revisar CACHE primero
    if imdb_id in omdb_cache:
        return omdb_cache[imdb_id]

    if not OMDB_API_KEY:
        raise RuntimeError("No hay OMDB_API_KEY en .env")

    attempts = 0

    while True:
        time.sleep(0.5)  # delay anti-rate-limit

        params = {
            "apikey": OMDB_API_KEY,
            "i": imdb_id,
            "type": "movie",
        }

        try:
            resp = requests.get("https://www.omdbapi.com/", params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"Error consultando OMDb para {imdb_id}: {e}")
            return None

        # rate limit
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
                print("⛔ Deteniendo el script para evitar un bloqueo diario más largo.\n")
                raise SystemExit("Script stopped due to OMDb rate limit.")

        if data.get("Response") != "True":
            return None

        omdb_cache[imdb_id] = data
        save_cache(omdb_cache)
        return data


def extract_ratings_from_omdb(data):
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

# ============================================================
#                    DECISIÓN + REASON + FLAGS
# ============================================================

def decide_keep_or_delete_with_reason(imdb_rating, imdb_votes, rt_score):
    """
    Devuelve tuple: (decision, reason)
    decision: KEEP / MAYBE / DELETE / UNKNOWN
    reason: string explicando el porqué.
    """
    # Sin info suficiente
    if imdb_rating is None and rt_score is None and (
        imdb_votes is None or imdb_votes < IMDB_MIN_VOTES_FOR_KNOWN
    ):
        return "UNKNOWN", "no_ratings_and_few_votes"

    # KEEP fuerte por rating
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

    # DELETE candidatos claros
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

    # Resto → MAYBE
    return "MAYBE", "middle_values"


def detect_misidentified(movie, imdb_rating, imdb_votes, rt_score):
    """
    Heurística sencilla para marcar posibles películas mal identificadas:
    - Sin imdb_id
    - O puntuaciones extremadamente raras/contradictorias
    - O año / título muy raros (por ahora solo datos externos)
    """
    reasons = []

    if getattr(movie, "guid", None) is None:
        reasons.append("no_guid")

    if imdb_rating is None and imdb_votes is None and rt_score is None:
        reasons.append("no_external_data")

    # Por ejemplo, rating muy bajo pero con muchos votos puede ser intencionado,
    # pero rating altísimo con 0 votos podría ser raro.
    if imdb_rating is not None and imdb_votes is not None:
        if imdb_rating >= 9.5 and imdb_votes < 100:
            reasons.append("suspicious_high_rating_low_votes")

    return ",".join(reasons) if reasons else ""


# ============================================================
#                ORDENACIÓN DEL CSV FILTRADO
# ============================================================

def sort_filtered_rows(rows):
    """
    Ordena primero DELETE luego MAYBE, y dentro de cada grupo
    de peor a menos peor usando imdb_rating, rt_score y imdb_votes.
    """

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
#                ANÁLISIS DE UNA BIBLIOTECA
# ============================================================

def analyze_single_library(section):
    rows = []

    print(f"\n--- Analizando biblioteca: {section.title} ---")
    movies = section.all()
    total = len(movies)
    print(f"Películas encontradas en {section.title}: {total}")

    for idx, movie in enumerate(movies, start=1):
        print(f"[{idx}/{total}] {movie.title} ({movie.year})")

        imdb_id = get_imdb_id_from_plex_guid(movie.guid)

        omdb_data = query_omdb_by_imdb_id(imdb_id)
        imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_data)

        decision, reason = decide_keep_or_delete_with_reason(
            imdb_rating, imdb_votes, rt_score
        )

        misid_flag = detect_misidentified(movie, imdb_rating, imdb_votes, rt_score)

        file_path = None
        try:
            if movie.media and movie.media[0].parts:
                file_path = movie.media[0].parts[0].file
        except Exception:
            pass

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
            "decision": decision,
            "reason": reason,
            "misidentified_hint": misid_flag,
        })

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
#                        HTML OUTPUT
# ============================================================

def write_html_filtered(path, rows):
    """
    Genera un informe HTML sencillo con tabla de las pelis filtradas.
    """
    html_rows = []
    for r in rows:
        html_rows.append(
            "<tr>"
            f"<td>{escape(str(r.get('library', '')))}</td>"
            f"<td>{escape(str(r.get('title', '')))}</td>"
            f"<td>{escape(str(r.get('year', '')))}</td>"
            f"<td>{escape(str(r.get('imdb_rating', '')))}</td>"
            f"<td>{escape(str(r.get('rt_score', '')))}</td>"
            f"<td>{escape(str(r.get('imdb_votes', '')))}</td>"
            f"<td>{escape(str(r.get('decision', '')))}</td>"
            f"<td>{escape(str(r.get('reason', '')))}</td>"
            f"<td>{escape(str(r.get('misidentified_hint', '')))}</td>"
            f"<td><small>{escape(str(r.get('file', '')))}</small></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe películas candidatas</title>
<style>
body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ border: 1px solid #ccc; padding: 4px 6px; }}
th {{ background: #eee; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #fafafa; }}
.bad-delete {{ background: #ffebee; }}
.maybe-row {{ background: #fffde7; }}
</style>
</head>
<body>
<h1>Películas candidatas a revisar / borrar</h1>
<p>Total filas: {len(rows)}</p>
<table>
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
<tbody>
{''.join(html_rows)}
</tbody>
</table>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML generado: {path}")


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

    for section in sections:
        if section.title in EXCLUDE_LIBRARIES:
            print(f"Saltando biblioteca excluida: {section.title}")
            continue

        if section.type != "movie":
            print(f"Saltando {section.title} porque no es de películas (tipo: {section.type})")
            continue

        rows_section = analyze_single_library(section)
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

    # Informe HTML de filtradas
    write_html_filtered(f"{OUTPUT_PREFIX}_filtered.html", filtered)


# ============================================================
#                        MAIN
# ============================================================

if __name__ == "__main__":
    analyze_all_libraries()