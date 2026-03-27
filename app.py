"""
Streamlit CRM for transport acquisition listings.
Run with: streamlit run app.py
"""

import pandas as pd
import streamlit as st

from db import get_all_listings, update_listing_tracking, init_db

STATUS_OPTIONS = ["À contacter", "En discussion", "Offre faite", "Refusé", "Acheté"]

st.set_page_config(
    page_title="Transport Acquisition — Listings",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🚛 Transport Acquisition — Listings")

init_db()


@st.cache_data(ttl=30)
def load_data() -> pd.DataFrame:
    rows = get_all_listings()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["contacted"]   = df["contacted"].astype(bool)
    df["interesting"] = df["interesting"].astype(bool)
    df["first_seen"]  = pd.to_datetime(df["first_seen"])
    return df


df = load_data()

# ── Sidebar filters ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filtres")

    sources = ["(Toutes)"] + sorted(df["source"].unique().tolist()) if not df.empty else ["(Toutes)"]
    sel_source = st.selectbox("Plateforme", sources)

    sel_status = st.multiselect("Statut", STATUS_OPTIONS, default=STATUS_OPTIONS)

    sel_contacted = st.radio("Contacté", ["Tous", "Oui", "Non"], horizontal=True)
    sel_interesting = st.radio("Intéressant", ["Tous", "Oui", "Non"], horizontal=True)

    keyword = st.text_input("Recherche titre", "")

    st.divider()
    if st.button("🔄 Rafraîchir"):
        st.cache_data.clear()
        st.rerun()

# ── Apply filters ────────────────────────────────────────────────────────────
filtered = df.copy() if not df.empty else df

if not filtered.empty:
    if sel_source != "(Toutes)":
        filtered = filtered[filtered["source"] == sel_source]
    if sel_status:
        filtered = filtered[filtered["status"].isin(sel_status)]
    if sel_contacted == "Oui":
        filtered = filtered[filtered["contacted"]]
    elif sel_contacted == "Non":
        filtered = filtered[~filtered["contacted"]]
    if sel_interesting == "Oui":
        filtered = filtered[filtered["interesting"]]
    elif sel_interesting == "Non":
        filtered = filtered[~filtered["interesting"]]
    if keyword:
        filtered = filtered[filtered["title"].str.contains(keyword, case=False, na=False)]

# ── Stats ────────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total annonces", len(df) if not df.empty else 0)
c2.metric("Affichées", len(filtered))
c3.metric("Intéressantes", int(df["interesting"].sum()) if not df.empty else 0)
c4.metric("Contactées",    int(df["contacted"].sum())   if not df.empty else 0)

st.divider()

# ── Editable table ────────────────────────────────────────────────────────────
COLS = ["id", "source", "title", "url", "price", "location",
        "scraped_date", "first_seen", "contacted", "interesting", "status", "notes"]

if df.empty:
    st.info("Aucune annonce en base. Lancez `python3 main.py` pour scraper des annonces.")
else:
    display_df = filtered[COLS].copy()

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="editor",
        column_config={
            "id":           st.column_config.TextColumn("ID", disabled=True, width="small"),
            "source":       st.column_config.TextColumn("Source", disabled=True, width="small"),
            "title":        st.column_config.TextColumn("Titre", disabled=True, width="large"),
            "url":          st.column_config.LinkColumn("URL", disabled=True, width="small"),
            "price":        st.column_config.TextColumn("Prix/CA", disabled=True, width="small"),
            "location":     st.column_config.TextColumn("Lieu", disabled=True, width="small"),
            "scraped_date": st.column_config.TextColumn("Date annonce", disabled=True, width="small"),
            "first_seen":   st.column_config.DatetimeColumn("Vu le", disabled=True, width="small"),
            "contacted":    st.column_config.CheckboxColumn("Contacté", width="small"),
            "interesting":  st.column_config.CheckboxColumn("Intéressant", width="small"),
            "status":       st.column_config.SelectboxColumn("Statut", options=STATUS_OPTIONS, width="medium"),
            "notes":        st.column_config.TextColumn("Notes", width="large"),
        },
    )

    # Detect and save changes
    EDITABLE = ["contacted", "interesting", "status", "notes"]
    changed = (edited_df[EDITABLE] != display_df[EDITABLE]).any(axis=1)
    changed_rows = edited_df[changed]

    if not changed_rows.empty:
        for _, row in changed_rows.iterrows():
            update_listing_tracking(
                listing_id  = row["id"],
                contacted   = bool(row["contacted"]),
                interesting = bool(row["interesting"]),
                status      = row["status"],
                notes       = row["notes"],
            )
        st.success(f"{len(changed_rows)} ligne(s) mise(s) à jour.")
        st.cache_data.clear()
        st.rerun()
