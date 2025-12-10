from collections import Counter
import json
import re
from typing import List

import altair as alt
import pandas as pd


def safe_json_loads_single(x):
    """Parsea JSON solo cuando se necesita (para una fila o subconjunto)."""
    if isinstance(x, str) and x.strip():
        try:
            return json.loads(x)
        except Exception:
            return None
    if isinstance(x, dict):
        return x
    return None


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Añade columnas derivadas ligeras: tamaños, década, etc."""
    df = df.copy()

    # Tipos numéricos básicos
    for col in ["imdb_rating", "rt_score", "imdb_votes", "year", "plex_rating", "file_size"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Tamaño en GB
    if "file_size" in df.columns:
        df["file_size_gb"] = df["file_size"].astype("float64") / (1024 ** 3)

    # Década
    if "year" in df.columns:
        df["decade"] = df["year"].dropna().astype("float64")
        df["decade"] = (df["decade"] // 10) * 10
        df["decade_label"] = df["decade"].apply(
            lambda x: f"{int(x)}s" if not pd.isna(x) else None
        )

    return df


def explode_genres_from_omdb_json(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye un DataFrame 'exploded' por género usando la columna omdb_json.
    Pensado para vistas de gráficos que necesitan contar películas por género.
    """
    if "omdb_json" not in df.columns:
        return pd.DataFrame(columns=list(df.columns) + ["genre"])

    df_g = df.copy().reset_index(drop=True)

    def extract_genre(raw):
        d = safe_json_loads_single(raw)
        if not isinstance(d, dict):
            return []
        g = d.get("Genre")
        if not g:
            return []
        return [x.strip() for x in str(g).split(",") if x.strip()]

    df_g["genre_list"] = df_g["omdb_json"].apply(extract_genre)
    df_g = df_g.explode("genre_list").reset_index(drop=True)
    df_g = df_g.rename(columns={"genre_list": "genre"})

    mask = df_g["genre"].notna() & (df_g["genre"] != "")
    return df_g.loc[mask].copy()


def build_word_counts(df: pd.DataFrame, decisions: List[str]) -> pd.DataFrame:
    """
    Construye un DataFrame con recuento de palabras en títulos
    filtrando por decisiones (DELETE/MAYBE, etc.).
    """
    df = df[df["decision"].isin(decisions)].copy()
    if df.empty:
        return pd.DataFrame(columns=["word", "decision", "count"])

    stopwords = set(
        [
            "the",
            "of",
            "la",
            "el",
            "de",
            "y",
            "a",
            "en",
            "los",
            "las",
            "un",
            "una",
            "and",
            "to",
            "for",
            "con",
            "del",
            "le",
            "les",
            "die",
            "der",
            "das",
        ]
    )

    rows = []
    for dec, sub in df.groupby("decision"):
        words = []
        for t in sub["title"].dropna().astype(str):
            t_clean = re.sub(r"[^\w\s]", " ", t)
            for w in t_clean.split():
                w_norm = w.strip().lower()
                if len(w_norm) <= 2:
                    continue
                if w_norm in stopwords:
                    continue
                words.append(w_norm)

        counts = Counter(words)
        for w, c in counts.items():
            rows.append({"word": w, "decision": dec, "count": c})

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("count", ascending=False)


def decision_color(field: str = "decision"):
    """
    Paleta de colores fija por decisión para usar en gráficos Altair.
    """
    return alt.Color(
        f"{field}:N",
        title="Decisión",
        scale=alt.Scale(
            domain=["DELETE", "KEEP", "MAYBE", "UNKNOWN"],
            range=["#e53935", "#43a047", "#fbc02d", "#9e9e9e"],
        ),
    )


def format_count_size(count: int, size_gb):
    """
    Devuelve un string tipo 'N (X.XX GB)' si hay tamaño disponible.
    """
    if size_gb is None or pd.isna(size_gb):
        return str(count)
    return f"{count} ({size_gb:.2f} GB)"