import os
import pandas as pd
from pathlib import Path

import streamlit as st
import altair as alt
from dotenv import load_dotenv

# ----------------------------------------------------
# Carga de .env
# ----------------------------------------------------
load_dotenv()

OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "report")
DELETE_DRY_RUN = os.getenv("DELETE_DRY_RUN", "true").lower() == "true"
DELETE_REQUIRE_CONFIRM = os.getenv("DELETE_REQUIRE_CONFIRM", "true").lower() == "true"

ALL_CSV = f"{OUTPUT_PREFIX}_all.csv"
FILTERED_CSV = f"{OUTPUT_PREFIX}_filtered.csv"

# Para las sugerencias de metadata
METADATA_OUTPUT_PREFIX = os.getenv("METADATA_OUTPUT_PREFIX", "metadata_fix")
METADATA_SUGG_CSV = f"{METADATA_OUTPUT_PREFIX}_suggestions.csv"

# Datos de Plex para posters y enlaces
PLEX_BASEURL = os.getenv("PLEX_BASEURL", "").rstrip("/")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")


# ----------------------------------------------------
# Función de borrado reutilizando la lógica del script
# ----------------------------------------------------
def delete_files_from_rows(rows):
    """
    rows: DataFrame con columnas al menos: title, file, reason, misidentified_hint
    Respeta DELETE_DRY_RUN y DELETE_REQUIRE_CONFIRM.
    Devuelve (num_ok, num_error, logs)
    """
    num_ok = 0
    num_error = 0
    logs = []

    for _, row in rows.iterrows():
        title = row.get("title")
        file_path = row.get("file")

        if not file_path or str(file_path).strip() == "":
            logs.append(f"[SKIP] {title} -> sin ruta de archivo")
            continue

        p = Path(str(file_path))
        if not p.exists():
            logs.append(f"[SKIP] {title} -> archivo no existe: {file_path}")
            continue

        if DELETE_DRY_RUN:
            logs.append(f"[DRY RUN] {title} -> NO se borra (DELETE_DRY_RUN=true): {file_path}")
            continue

        try:
            os.remove(p)
            logs.append(f"[OK] BORRADO {title} -> {file_path}")
            num_ok += 1
        except Exception as e:
            logs.append(f"[ERROR] {title} -> {file_path} ({e})")
            num_error += 1

    return num_ok, num_error, logs


# ----------------------------------------------------
# Helpers: posters y enlaces Plex
# ----------------------------------------------------
def build_poster_url(thumb: str | None) -> str | None:
    if not thumb or not PLEX_BASEURL:
        return None
    # thumb viene tipo "/library/metadata/1234/thumb/..."
    base = f"{PLEX_BASEURL}{thumb}"
    if PLEX_TOKEN:
        return f"{base}?X-Plex-Token={PLEX_TOKEN}"
    return base


def build_plex_item_url(rating_key) -> str | None:
    if pd.isna(rating_key) or not PLEX_BASEURL:
        return None
    # Enlace genérico basado en ratingKey
    # Plex web suele aceptar: /web/index.html#!/details?key=%2Flibrary%2Fmetadata%2F{ratingKey}
    key = f"%2Flibrary%2Fmetadata%2F{int(rating_key)}"
    return f"{PLEX_BASEURL}/web/index.html#!/details?key={key}"


def render_poster_card(row) -> str:
    poster_url = build_poster_url(row.get("thumb"))
    plex_url = build_plex_item_url(row.get("ratingKey"))
    title = row.get("title", "")
    year = row.get("year", "")
    decision = row.get("decision", "")
    imdb = row.get("imdb_rating", "")
    if not poster_url and not plex_url:
        return ""
    return f"""
    <div style="width: 180px; margin: 8px; display: inline-block; vertical-align: top; font-size: 12px;">
      <div style="border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.2); overflow: hidden; background: #fff;">
        <a href="{plex_url or '#'}" target="_blank" style="text-decoration:none; color: inherit;">
          {'<img src="'+poster_url+'" style="width: 100%; height: auto; display: block;" />' if poster_url else ''}
          <div style="padding: 6px 8px;">
            <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
              {title}
            </div>
            <div style="color: #666;">{year} · {decision}</div>
            <div style="color: #999;">IMDb: {imdb}</div>
            <div style="margin-top:4px; text-align:right;">
              <span style="font-size:11px; color:#1976d2;">Abrir en Plex ↗</span>
            </div>
          </div>
        </a>
      </div>
    </div>
    """


# ----------------------------------------------------
# Configuración Streamlit
# ----------------------------------------------------
st.set_page_config(page_title="Plex Movies Cleaner", layout="wide")
st.title("🎬 Plex Movies Cleaner — Dashboard")

if not os.path.exists(ALL_CSV):
    st.error(f"No se encuentra {ALL_CSV}. Ejecuta primero analiza_plex.py.")
    st.stop()

df_all = pd.read_csv(ALL_CSV)
df_filtered = pd.read_csv(FILTERED_CSV) if os.path.exists(FILTERED_CSV) else None

# Aseguramos tipos numéricos donde aplica
for col in ["imdb_rating", "rt_score", "imdb_votes", "year", "plex_rating", "file_size", "ratingKey"]:
    if col in df_all.columns:
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce")

# Derivamos tamaño en GB
if "file_size" in df_all.columns:
    df_all["file_size_gb"] = df_all["file_size"].fillna(0) / (1024 ** 3)
else:
    df_all["file_size_gb"] = 0.0

# Cargamos sugerencias de metadata (si existen)
if os.path.exists(METADATA_SUGG_CSV):
    df_meta = pd.read_csv(METADATA_SUGG_CSV)
    # Normalizamos algunos tipos
    for col in ["plex_imdb_rating", "plex_imdb_votes", "suggested_imdb_rating", "suggested_imdb_votes", "confidence"]:
        if col in df_meta.columns:
            df_meta[col] = pd.to_numeric(df_meta[col], errors="coerce")
else:
    df_meta = None

# ----------------------------------------------------
# Resumen + gráficos rápidos + espacio
# ----------------------------------------------------
st.subheader("Resumen general")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Películas totales", len(df_all))
with col2:
    st.metric("KEEP", int((df_all["decision"] == "KEEP").sum()))
with col3:
    st.metric("DELETE + MAYBE", int(df_all["decision"].isin(["DELETE", "MAYBE"]).sum()))
with col4:
    if "imdb_rating" in df_all.columns:
        st.metric("IMDb medio", round(df_all["imdb_rating"].mean(skipna=True), 2))

# Métricas de espacio
if "file_size_gb" in df_all.columns:
    total_space = df_all["file_size_gb"].sum()
    if df_filtered is not None and "file_size" in df_filtered.columns:
        df_filtered["file_size_gb"] = df_filtered["file_size"].fillna(0) / (1024 ** 3)
        potential_delete_space = df_filtered[df_filtered["decision"] == "DELETE"]["file_size_gb"].sum()
    else:
        potential_delete_space = 0.0

    st.markdown("### Espacio en disco")
    col_es1, col_es2 = st.columns(2)
    with col_es1:
        st.metric("Espacio total estimado", f"{total_space:,.2f} GB")
    with col_es2:
        st.metric("Espacio potencial a liberar (DELETE)", f"{potential_delete_space:,.2f} GB")

st.markdown("---")

# Mini-gráficos en el resumen
col_a, col_b = st.columns(2)
with col_a:
    st.caption("Distribución por decisión (nº de películas)")
    if "decision" in df_all.columns:
        counts_dec = df_all["decision"].value_counts().reset_index()
        counts_dec.columns = ["decision", "count"]
        chart_dec = (
            alt.Chart(counts_dec)
            .mark_bar()
            .encode(
                x=alt.X("decision:N", title="Decisión"),
                y=alt.Y("count:Q", title="Nº de películas"),
                tooltip=["decision", "count"],
            )
        )
        st.altair_chart(chart_dec, use_container_width=True)

with col_b:
    st.caption("Histograma IMDb rating")
    if "imdb_rating" in df_all.columns:
        chart_hist = (
            alt.Chart(df_all.dropna(subset=["imdb_rating"]))
            .mark_bar()
            .encode(
                x=alt.X("imdb_rating:Q", bin=alt.Bin(maxbins=20), title="IMDb rating"),
                y=alt.Y("count():Q", title="Nº de películas"),
                tooltip=["count()"],
            )
        )
        st.altair_chart(chart_hist, use_container_width=True)

st.markdown("---")

# ----------------------------------------------------
# Pestañas
# ----------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "📚 Todas",
        "⚠️ Candidatas (DELETE/MAYBE)",
        "🔎 Búsqueda avanzada",
        "🧹 Borrado de archivos",
        "📊 Gráficos",
        "🧠 Sugerencias metadata",
    ]
)

# ----------------------------------------------------
# Tab 1: Todas
# ----------------------------------------------------
with tab1:
    st.write("### Todas las películas")

    library_filter = st.multiselect("Filtrar por biblioteca", sorted(df_all["library"].unique()))
    decision_filter = st.multiselect("Filtrar por decisión", sorted(df_all["decision"].unique()))

    df_view = df_all.copy()
    if library_filter:
        df_view = df_view[df_view["library"].isin(library_filter)]
    if decision_filter:
        df_view = df_view[df_view["decision"].isin(decision_filter)]

    st.dataframe(df_view, use_container_width=True)


# ----------------------------------------------------
# Tab 2: Candidatas
# ----------------------------------------------------
with tab2:
    st.write("### Películas candidatas a borrar / revisar")

    if df_filtered is None:
        st.warning("No se encontró el CSV filtrado. Ejecuta primero analiza_plex.py.")
    else:
        df_view = df_filtered.copy()

        library_filter2 = st.multiselect("Filtrar por biblioteca", sorted(df_view["library"].unique()))
        reason_filter = st.multiselect("Filtrar por reason", sorted(df_view["reason"].unique()))
        misid_only = st.checkbox("Mostrar solo posibles mal identificadas (misidentified_hint no vacío)")

        if library_filter2:
            df_view = df_view[df_view["library"].isin(library_filter2)]
        if reason_filter:
            df_view = df_view[df_view["reason"].isin(reason_filter)]
        if misid_only:
            df_view = df_view[df_view["misidentified_hint"].notna() & (df_view["misidentified_hint"] != "")]

        st.dataframe(df_view, use_container_width=True)

        # Vista rápida con pósters (primeros N)
        st.markdown("---")
        st.subheader("Vista rápida con pósters (primeros 50 resultados filtrados)")

        max_cards = st.slider("Número máximo de pósters a mostrar", 10, 100, 50, 5)
        df_cards = df_view.head(max_cards)

        if df_cards.empty:
            st.info("No hay resultados para mostrar.")
        else:
            html_cards = "".join(render_poster_card(row) for _, row in df_cards.iterrows())
            st.markdown(html_cards, unsafe_allow_html=True)


# ----------------------------------------------------
# Tab 3: Búsqueda avanzada
# ----------------------------------------------------
with tab3:
    st.write("### Búsqueda avanzada")

    title_query = st.text_input("Buscar por título (contiene):")
    min_imdb = st.slider("IMDb rating mínimo", 0.0, 10.0, 0.0, 0.1)
    max_imdb = st.slider("IMDb rating máximo", 0.0, 10.0, 10.0, 0.1)

    df_view = df_all.copy()

    if title_query:
        df_view = df_view[df_view["title"].str.contains(title_query, case=False, na=False)]

    if "imdb_rating" in df_view.columns:
        df_view = df_view[
            (df_view["imdb_rating"].fillna(0) >= min_imdb)
            & (df_view["imdb_rating"].fillna(10) <= max_imdb)
        ]

    st.dataframe(df_view, use_container_width=True)


# ----------------------------------------------------
# Tab 4: Borrado de archivos
# ----------------------------------------------------
with tab4:
    st.write("### 🧹 Borrado de archivos marcados como DELETE")
    st.info(
        "Este módulo trabaja sobre el CSV filtrado "
        f"**{FILTERED_CSV}** y solo afecta a filas con `decision = DELETE`.\n\n"
        f"**DELETE_DRY_RUN = {DELETE_DRY_RUN}** | **DELETE_REQUIRE_CONFIRM = {DELETE_REQUIRE_CONFIRM}**"
    )

    if df_filtered is None:
        st.warning("No se encontró el CSV filtrado. Ejecuta primero analiza_plex.py.")
    else:
        df_del = df_filtered[df_filtered["decision"] == "DELETE"].copy()
        st.write(f"Películas marcadas como DELETE en el CSV: **{len(df_del)}**")

        if df_del.empty:
            st.stop()

        # Filtros
        library_del_filter = st.multiselect(
            "Filtrar por biblioteca (para borrado)",
            sorted(df_del["library"].unique()),
            placeholder="(opcional)"
        )
        if library_del_filter:
            df_del = df_del[df_del["library"].isin(library_del_filter)]

        st.write(f"Seleccionadas tras filtros: **{len(df_del)}**")

        cols_show = ["library", "title", "year", "imdb_rating", "rt_score", "imdb_votes", "reason", "file"]
        if "file_size_gb" in df_del.columns:
            cols_show.append("file_size_gb")

        st.dataframe(
            df_del[cols_show],
            use_container_width=True,
        )

        st.markdown("---")

        if DELETE_DRY_RUN:
            st.warning("**DELETE_DRY_RUN=true** → NO se borrará ningún archivo. Se mostrará solo un log simulado.")

        # Confirmación fuerte
        if DELETE_REQUIRE_CONFIRM:
            confirm_text = st.text_input(
                "Escribe EXACTAMENTE 'BORRAR' para habilitar el botón de borrado:",
                type="default",
            )
            confirmed = confirm_text.strip().upper() == "BORRAR"
        else:
            confirmed = True

        delete_button = st.button("🚨 Ejecutar borrado de archivos (según configuración)")

        if delete_button:
            if not confirmed:
                st.error("No has escrito 'BORRAR'. Operación cancelada.")
            elif df_del.empty:
                st.warning("No hay filas DELETE después de aplicar filtros.")
            else:
                with st.spinner("Procesando borrado..."):
                    num_ok, num_error, logs = delete_files_from_rows(df_del)

                st.success(f"Borrado completado. OK: {num_ok}, Errores: {num_error}")
                st.text_area("Log de operación", value="\n".join(logs), height=300)


# ----------------------------------------------------
# Tab 5: Gráficos detallados
# ----------------------------------------------------
with tab5:
    st.write("### 📊 Visualización de datos")

    if df_all.empty:
        st.warning("No hay datos para mostrar.")
    else:
        # Selector de biblioteca (opcional)
        libs = ["(Todas)"] + sorted(df_all["library"].dropna().unique())
        sel_lib = st.selectbox("Filtrar por biblioteca (para gráficos)", libs)
        df_g = df_all.copy()
        if sel_lib != "(Todas)":
            df_g = df_g[df_g["library"] == sel_lib]

        # Row 1: IMDb vs votos
        colg1, colg2 = st.columns(2)

        with colg1:
            st.caption("IMDb rating vs número de votos (color por decisión)")
            if "imdb_rating" in df_g.columns and "imdb_votes" in df_g.columns:
                chart_scatter = (
                    alt.Chart(df_g.dropna(subset=["imdb_rating", "imdb_votes"]))
                    .mark_circle(size=60, opacity=0.7)
                    .encode(
                        x=alt.X("imdb_rating:Q", title="IMDb rating"),
                        y=alt.Y("imdb_votes:Q", title="IMDb votos", scale=alt.Scale(type="log", nice=True)),
                        color=alt.Color("decision:N", title="Decisión"),
                        tooltip=["title", "year", "imdb_rating", "imdb_votes", "decision"],
                    )
                    .interactive()
                )
                st.altair_chart(chart_scatter, use_container_width=True)

        with colg2:
            st.caption("Recuento de películas por biblioteca y decisión")
            if "library" in df_g.columns and "decision" in df_g.columns:
                counts_lib_dec = (
                    df_g.groupby(["library", "decision"])["title"]
                    .count()
                    .reset_index()
                    .rename(columns={"title": "count"})
                )
                chart_lib_dec = (
                    alt.Chart(counts_lib_dec)
                    .mark_bar()
                    .encode(
                        x=alt.X("library:N", title="Biblioteca"),
                        y=alt.Y("count:Q", title="Nº de películas"),
                        color=alt.Color("decision:N", title="Decisión"),
                        tooltip=["library", "decision", "count"],
                    )
                )
                st.altair_chart(chart_lib_dec, use_container_width=True)

        st.markdown("---")

        # Row 2: distribución por año y decisión
        st.caption("Distribución por año y decisión (stacked)")
        if "year" in df_g.columns and "decision" in df_g.columns:
            df_year = df_g.dropna(subset=["year"])
            df_year["year"] = df_year["year"].astype(int)
            counts_year_dec = (
                df_year.groupby(["year", "decision"])["title"]
                .count()
                .reset_index()
                .rename(columns={"title": "count"})
            )
            chart_year = (
                alt.Chart(counts_year_dec)
                .mark_bar()
                .encode(
                    x=alt.X("year:O", title="Año"),
                    y=alt.Y("count:Q", stack="normalize", title="% de películas"),
                    color=alt.Color("decision:N", title="Decisión"),
                    tooltip=["year", "decision", "count"],
                )
            )
            st.altair_chart(chart_year, use_container_width=True)

        st.markdown("---")

        # Row 3: espacio por biblioteca y por decisión
        st.caption("Espacio por biblioteca (GB)")
        if "file_size_gb" in df_g.columns:
            df_space_lib = (
                df_g.groupby("library")["file_size_gb"]
                .sum()
                .reset_index()
                .rename(columns={"file_size_gb": "space_gb"})
            )
            chart_space_lib = (
                alt.Chart(df_space_lib)
                .mark_bar()
                .encode(
                    x=alt.X("library:N", title="Biblioteca"),
                    y=alt.Y("space_gb:Q", title="Espacio (GB)"),
                    tooltip=["library", "space_gb"],
                )
            )
            st.altair_chart(chart_space_lib, use_container_width=True)

            st.caption("Espacio por decisión (GB)")
            df_space_dec = (
                df_g.groupby("decision")["file_size_gb"]
                .sum()
                .reset_index()
                .rename(columns={"file_size_gb": "space_gb"})
            )
            chart_space_dec = (
                alt.Chart(df_space_dec)
                .mark_bar()
                .encode(
                    x=alt.X("decision:N", title="Decisión"),
                    y=alt.Y("space_gb:Q", title="Espacio (GB)"),
                    tooltip=["decision", "space_gb"],
                )
            )
            st.altair_chart(chart_space_dec, use_container_width=True)


# ----------------------------------------------------
# Tab 6: Sugerencias de metadata
# ----------------------------------------------------
with tab6:
    st.write("### 🧠 Sugerencias automáticas de metadata (OMDb)")

    if df_meta is None or df_meta.empty:
        st.info(
            "No se ha encontrado ningún fichero de sugerencias "
            f"(**{METADATA_SUGG_CSV}**).\n\n"
            "Ejecuta primero `analiza_plex.py` con el sistema de corrección de metadata activado."
        )
    else:
        st.markdown(
            "- Cada fila representa una película cuya metadata parece sospechosa.\n"
            "- Se muestran los datos actuales de Plex y la sugerencia de OMDb.\n"
            "- La columna **action** indica: `AUTO_APPLY`, `MAYBE` o `REVIEW`."
        )

        def confidence_label(c):
            try:
                c = float(c)
            except Exception:
                return "Desconocida"
            if c >= 70:
                return "Alta"
            if c >= 40:
                return "Media"
            return "Baja"

        df_meta["confidence_level"] = df_meta["confidence"].apply(confidence_label)

        # Filtros
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            libs_meta = sorted(df_meta["library"].dropna().unique())
            lib_filter = st.multiselect("Filtrar por biblioteca", libs_meta)

        with col_m2:
            actions = sorted(df_meta["action"].dropna().unique())
            action_filter = st.multiselect("Filtrar por acción", actions, default=actions)

        with col_m3:
            min_conf, max_conf = st.slider(
                "Rango de confianza",
                0, 100, (0, 100),
                help="Basado en el score heurístico de matching OMDb"
            )

        df_view = df_meta.copy()

        if lib_filter:
            df_view = df_view[df_view["library"].isin(lib_filter)]
        if action_filter:
            df_view = df_view[df_view["action"].isin(action_filter)]

        df_view = df_view[
            (df_view["confidence"].fillna(0) >= min_conf)
            & (df_view["confidence"].fillna(0) <= max_conf)
        ]

        st.write(f"Sugerencias tras filtros: **{len(df_view)}**")

        if not df_view.empty:
            cols_show = [
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
                "confidence",
                "confidence_level",
                "action",
            ]
            cols_show = [c for c in cols_show if c in df_view.columns]

            st.dataframe(df_view[cols_show], use_container_width=True)

        st.markdown(
            "> 💡 Para aplicar cambios automáticamente en Plex, ajusta "
            "`METADATA_DRY_RUN=false` y `METADATA_APPLY_CHANGES=true` en el `.env` "
            "y vuelve a ejecutar `analiza_plex.py`. (La parte de GUID puede requerir "
            "un pequeño ajuste según tu versión de Plex/plexapi)."
        )