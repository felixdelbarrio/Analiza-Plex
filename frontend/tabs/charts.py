import pandas as pd
import streamlit as st
import altair as alt

from frontend.data_utils import (
    explode_genres_from_omdb_json,
    build_word_counts,
    decision_color,
    safe_json_loads_single,
)


def render(df_all: pd.DataFrame) -> None:
    """Pestaña 5: Gráficos."""
    st.write("### Gráficos")

    view = st.selectbox(
        "Vista",
        [
            "Distribución por decisión",
            "Rating IMDb por decisión",
            "Ratings IMDb vs RT",
            "Distribución por década",
            "Distribución por biblioteca",
            "Distribución por género (OMDb)",
            "Espacio ocupado por biblioteca/decisión",
            "Boxplot IMDb por biblioteca",
            "Ranking de directores",
            "Palabras más frecuentes en títulos DELETE/MAYBE",
            "Distribución por scoring_rule",  # <-- NUEVA OPCIÓN
        ],
    )

    df_g = df_all.copy()

    # 1) Distribución por decisión
    if view == "Distribución por decisión":
        if "decision" not in df_g.columns:
            st.info("No hay columna 'decision'.")
        else:
            agg = df_g.groupby("decision")["title"].count().reset_index()
            agg = agg.rename(columns={"title": "count"})

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("decision:N", title="Decisión"),
                    y=alt.Y("count:Q", title="Número de películas"),
                    color=decision_color("decision"),
                    tooltip=["decision", "count"],
                )
            )
            st.altair_chart(chart, width="stretch")

    # 2) Rating IMDb por decisión
    elif view == "Rating IMDb por decisión":
        if "imdb_rating" not in df_g.columns or "decision" not in df_g.columns:
            st.info("Faltan columnas imdb_rating o decision.")
        else:
            chart = (
                alt.Chart(df_g.dropna(subset=["imdb_rating"]))
                .mark_boxplot()
                .encode(
                    x=alt.X("decision:N", title="Decisión"),
                    y=alt.Y("imdb_rating:Q", title="IMDb rating"),
                    color=decision_color("decision"),
                    tooltip=["decision"],
                )
            )
            st.altair_chart(chart, width="stretch")

    # 3) Ratings IMDb vs RT
    elif view == "Ratings IMDb vs RT":
        if "imdb_rating" not in df_g.columns or "rt_score" not in df_g.columns:
            st.info("Faltan columnas imdb_rating o rt_score.")
        else:
            chart = (
                alt.Chart(df_g.dropna(subset=["imdb_rating", "rt_score"]))
                .mark_circle(size=60, opacity=0.7)
                .encode(
                    x=alt.X("imdb_rating:Q", title="IMDb rating"),
                    y=alt.Y("rt_score:Q", title="RT score (%)"),
                    color=decision_color("decision"),
                    tooltip=[
                        "title",
                        "year",
                        "library",
                        "imdb_rating",
                        "rt_score",
                        "imdb_votes",
                        "decision",
                    ],
                )
            )
            st.altair_chart(chart, width="stretch")

    # 4) Distribución por década
    elif view == "Distribución por década":
        if "decade_label" not in df_g.columns:
            st.info("Falta columna decade_label.")
        else:
            agg = (
                df_g.dropna(subset=["decade_label"])
                .groupby(["decade_label", "decision"])
                ["title"]
                .count()
                .reset_index()
            )
            agg = agg.rename(columns={"title": "count"})

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("decade_label:N", title="Década"),
                    y=alt.Y("count:Q", title="Número de películas"),
                    color=decision_color("decision"),
                    tooltip=["decade_label", "decision", "count"],
                )
            )
            st.altair_chart(chart, width="stretch")

    # 5) Distribución por biblioteca
    elif view == "Distribución por biblioteca":
        if "library" not in df_g.columns:
            st.info("Falta columna library.")
        else:
            agg = (
                df_g.groupby(["library", "decision"])["title"]
                .count()
                .reset_index()
                .rename(columns={"title": "count"})
            )

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("library:N", title="Biblioteca"),
                    y=alt.Y("count:Q", title="Número de películas", stack="normalize"),
                    color=decision_color("decision"),
                    tooltip=["library", "decision", "count"],
                )
            )
            st.altair_chart(chart, width="stretch")

    # 6) Distribución por género (OMDb)
    elif view == "Distribución por género (OMDb)":
        df_gen = explode_genres_from_omdb_json(df_g)

        if df_gen.empty:
            st.info("No hay datos de género en omdb_json.")
        else:
            agg = (
                df_gen.groupby(["genre", "decision"])["title"]
                .count()
                .reset_index()
                .rename(columns={"title": "count"})
            )

            top_n = st.slider("Top N géneros", 5, 50, 20)
            top_genres = (
                agg.groupby("genre")["count"].sum().sort_values(ascending=False).head(top_n).index
            )
            agg = agg[agg["genre"].isin(top_genres)]

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("genre:N", title="Género"),
                    y=alt.Y("count:Q", title="Número de películas", stack="normalize"),
                    color=decision_color("decision"),
                    tooltip=["genre", "decision", "count"],
                )
            )

            st.altair_chart(chart, width="stretch")

    # 7) Espacio ocupado por biblioteca/decisión
    elif view == "Espacio ocupado por biblioteca/decisión":
        if "file_size_gb" not in df_g.columns or "library" not in df_g.columns:
            st.info("Faltan columnas file_size_gb o library.")
        else:
            agg = (
                df_g.groupby(["library", "decision"])["file_size_gb"]
                .sum()
                .reset_index()
            )

            if agg.empty:
                st.info("No hay datos de tamaño de archivos.")
            else:
                chart_space = (
                    alt.Chart(agg)
                    .mark_bar()
                    .encode(
                        x=alt.X("library:N", title="Biblioteca"),
                        y=alt.Y("file_size_gb:Q", title="Tamaño (GB)", stack="normalize"),
                        color=decision_color("decision"),
                        tooltip=[
                            "library",
                            "decision",
                            alt.Tooltip("file_size_gb:Q", format=".2f"),
                        ],
                    )
                )
                st.altair_chart(chart_space, width="stretch")

                total_space = agg["file_size_gb"].sum()
                space_delete = agg[agg["decision"] == "DELETE"]["file_size_gb"].sum()
                space_maybe = agg[agg["decision"] == "MAYBE"]["file_size_gb"].sum()

                st.markdown(
                    f"- Espacio total: **{total_space:.2f} GB**\n"
                    f"- DELETE: **{space_delete:.2f} GB**\n"
                    f"- MAYBE: **{space_maybe:.2f} GB**"
                )

    # 8) Boxplot IMDb por biblioteca
    elif view == "Boxplot IMDb por biblioteca":
        if "imdb_rating" in df_g.columns and "library" in df_g.columns:
            chart_box = (
                alt.Chart(df_g.dropna(subset=["imdb_rating", "library"]))
                .mark_boxplot()
                .encode(
                    x=alt.X("library:N", title="Biblioteca"),
                    y=alt.Y("imdb_rating:Q", title="IMDb rating"),
                    tooltip=["library"],
                )
            )
            st.altair_chart(chart_box, width="stretch")
        else:
            st.info("Faltan columnas imdb_rating / library.")

    # 9) Ranking de directores
    elif view == "Ranking de directores":
        if "omdb_json" not in df_all.columns:
            st.info("No existe información OMDb JSON (omdb_json).")
        else:
            df_dir = df_all.copy()

            def extract_directors(raw):
                d = safe_json_loads_single(raw)
                if not isinstance(d, dict):
                    return []
                val = d.get("Director")
                if not val:
                    return []
                return [x.strip() for x in str(val).split(",") if x.strip()]

            df_dir["director_list"] = df_dir["omdb_json"].apply(extract_directors)
            df_dir = df_dir.explode("director_list")
            df_dir = df_dir[df_dir["director_list"].notna() & (df_dir["director_list"] != "")]

            if df_dir.empty:
                st.info("No se encontraron directores en omdb_json.")
            else:
                min_movies = st.slider("Mínimo nº de películas por director", 1, 10, 3)

                agg = (
                    df_dir.groupby("director_list")
                    .agg(
                        imdb_mean=("imdb_rating", "mean"),
                        count=("title", "count"),
                    )
                    .reset_index()
                )
                agg = agg[agg["count"] >= min_movies].sort_values("imdb_mean", ascending=False)

                top_n = st.slider("Top N directores por IMDb medio", 5, 50, 20)
                agg_top = agg.head(top_n)

                chart = (
                    alt.Chart(agg_top)
                    .mark_bar()
                    .encode(
                        x=alt.X("director_list:N", title="Director"),
                        y=alt.Y("imdb_mean:Q", title="IMDb medio"),
                        tooltip=["director_list", "imdb_mean", "count"],
                    )
                )
                st.altair_chart(chart, width="stretch")

    # 10) Palabras más frecuentes en títulos DELETE/MAYBE
    elif view == "Palabras más frecuentes en títulos DELETE/MAYBE":
        df_words = build_word_counts(df_g, ["DELETE", "MAYBE"])

        if df_words.empty:
            st.info("No hay datos suficientes para el análisis de palabras.")
        else:
            top_n = st.slider("Top N palabras", 5, 50, 20)
            df_top = df_words.head(top_n)

            chart = (
                alt.Chart(df_top)
                .mark_bar()
                .encode(
                    x=alt.X("word:N", title="Palabra"),
                    y=alt.Y("count:Q", title="Frecuencia"),
                    color=decision_color("decision"),
                    tooltip=["word", "decision", "count"],
                )
            )
            st.altair_chart(chart, width="stretch")

    # 11) NUEVO — Distribución por scoring_rule
    elif view == "Distribución por scoring_rule":
        if "scoring_rule" not in df_g.columns:
            st.info("No hay columna 'scoring_rule'. Asegúrate de haber regenerado report_all.csv.")
        else:
            agg = (
                df_g.groupby(["scoring_rule", "decision"])["title"]
                .count()
                .reset_index()
                .rename(columns={"title": "count"})
            )

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("scoring_rule:N", title="Regla de scoring"),
                    y=alt.Y("count:Q", title="Número de películas"),
                    color=decision_color("decision"),
                    tooltip=["scoring_rule", "decision", "count"],
                )
            )

            st.altair_chart(chart, width="stretch")