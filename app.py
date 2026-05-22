"""
Discrepancy Analytics Dashboard
================================
Reads the sectioned CSV produced by scraper.py and displays three
clearly separated views: Discrepancy | No Discrepancy | Unmatched.

Run:
    streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from pathlib import Path
import io

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG  (must be the very first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Match Discrepancy Dashboard",
    page_icon="⚡",
    layout="wide",
)

REFRESH_INTERVAL_SEC = 7_200   # 2 hours
CSV_PATH = Path("daily_log.csv")

# ── Auto-refresh ──────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=REFRESH_INTERVAL_SEC * 1_000, key="dash_refresh")
except ImportError:
    st.markdown(
        f'<meta http-equiv="refresh" content="{REFRESH_INTERVAL_SEC}">',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADER  – handles the 3-section CSV format
# ─────────────────────────────────────────────────────────────────────────────
SECTION_LABELS = {
    "A": "=== SECTION A: GAMES WITH DISCREPANCY ===",
    "B": "=== SECTION B: GAMES WITHOUT DISCREPANCY ===",
    "C": "=== SECTION C: UNMATCHED GAMES ===",
}


@st.cache_data(ttl=REFRESH_INTERVAL_SEC)
def load_sectioned_csv(path: str) -> dict[str, pd.DataFrame]:
    """
    Parse the multi-section CSV into three DataFrames keyed by section letter.
    Returns empty DataFrames if the file is missing or malformed.
    """
    p = Path(path)
    if not p.exists():
        st.error(f"CSV file not found: {p.resolve()}\n\nRun `python scraper.py` first.")
        return {k: pd.DataFrame() for k in "ABC"}

    raw_lines = p.read_text(encoding="utf-8").splitlines()

    sections: dict[str, list[str]] = {k: [] for k in "ABC"}
    current = None
    in_header = False   # skip the column-header row right after a section label

    # Map label text → section key
    label_map = {v: k for k, v in SECTION_LABELS.items()}

    for line in raw_lines:
        stripped = line.strip().strip('"')
        # Detect section start
        for label_text, key in label_map.items():
            if stripped.startswith(label_text.split("===")[1].strip()):
                current = key
                in_header = True   # next non-blank line is the column header
                break
        else:
            if current is None:
                continue
            if not stripped:          # blank separator between sections
                continue
            if in_header:             # column header row
                sections[current].append(line)
                in_header = False
                continue
            sections[current].append(line)

    dfs: dict[str, pd.DataFrame] = {}
    for key, lines in sections.items():
        if not lines:
            dfs[key] = pd.DataFrame()
            continue
        try:
            text = "\n".join(lines)
            df = pd.read_csv(io.StringIO(text))
            # Drop placeholder rows
            df = df[df["Team1"] != "(no records)"]
            # Coerce types
            if "Difference (minutes)" in df.columns:
                df["Difference (minutes)"] = pd.to_numeric(
                    df["Difference (minutes)"], errors="coerce"
                )
            if "Timestamp" in df.columns:
                df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
            dfs[key] = df
        except Exception as exc:
            st.warning(f"Could not parse Section {key}: {exc}")
            dfs[key] = pd.DataFrame()

    return dfs


# ─────────────────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────────────────
dfs = load_sectioned_csv(str(CSV_PATH))
df_disc   = dfs["A"]   # discrepancy
df_nodis  = dfs["B"]   # no discrepancy
df_unmatch = dfs["C"]  # unmatched

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.title("⚡ Odibets × Flashscore — Match Discrepancy Dashboard")
st.caption(
    f"Last loaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} EAT  •  "
    f"Auto-refreshes every 2 hours"
)
st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY METRICS
# ─────────────────────────────────────────────────────────────────────────────
st.header("📊 Summary")

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 With Discrepancy",    len(df_disc))
c2.metric("🟢 No Discrepancy",      len(df_nodis))
c3.metric("🟡 Unmatched",           len(df_unmatch))
c4.metric("📋 Total Games Seen",    len(df_disc) + len(df_nodis) + len(df_unmatch))

if not df_disc.empty and "Difference (minutes)" in df_disc.columns:
    avg_d = df_disc["Difference (minutes)"].mean()
    max_d = df_disc["Difference (minutes)"].max()
    ca, cb = st.columns(2)
    ca.metric("Avg Discrepancy (min)", f"{avg_d:.1f}" if pd.notna(avg_d) else "N/A")
    cb.metric("Max Discrepancy (min)", f"{max_d:.0f}" if pd.notna(max_d) else "N/A")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# TABS  – one per section
# ─────────────────────────────────────────────────────────────────────────────
tab_a, tab_b, tab_c, tab_charts = st.tabs([
    "🔴 With Discrepancy",
    "🟢 No Discrepancy",
    "🟡 Unmatched",
    "📈 Charts",
])

# ── Tab A: Discrepancy ────────────────────────────────────────────────────────
with tab_a:
    st.subheader(f"Games With Discrepancy  ({len(df_disc)} games)")
    if df_disc.empty:
        st.info("No discrepancies found in the last run.")
    else:
        # Highlight high-discrepancy rows
        def highlight_disc(row):
            diff = row.get("Difference (minutes)", 0)
            if pd.notna(diff) and diff > 30:
                return ["background-color: #ffe0e0"] * len(row)
            elif pd.notna(diff) and diff > 15:
                return ["background-color: #fff3cd"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df_disc.style.apply(highlight_disc, axis=1),
            use_container_width=True,
            hide_index=True,
        )

        # League breakdown
        if "League" in df_disc.columns:
            lc = (
                df_disc.groupby("League")["Difference (minutes)"]
                .agg(Count="count", Avg_Diff="mean")
                .reset_index()
                .sort_values("Count", ascending=False)
            )
            st.markdown("**Discrepancies by League**")
            st.dataframe(lc, use_container_width=True, hide_index=True)


# ── Tab B: No Discrepancy ─────────────────────────────────────────────────────
with tab_b:
    st.subheader(f"Games Without Discrepancy  ({len(df_nodis)} games)")
    if df_nodis.empty:
        st.info("No matched games with agreeing times yet.")
    else:
        st.dataframe(df_nodis, use_container_width=True, hide_index=True)


# ── Tab C: Unmatched ──────────────────────────────────────────────────────────
with tab_c:
    st.subheader(f"Unmatched Games  ({len(df_unmatch)} games)")
    if df_unmatch.empty:
        st.info("All games were matched between the two sources.")
    else:
        # Split by source
        if "Source" in df_unmatch.columns:
            odi_only   = df_unmatch[df_unmatch["Source"] == "odibets"]
            flash_only = df_unmatch[df_unmatch["Source"] == "flashscore"]

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Odibets only** — {len(odi_only)} games")
                st.dataframe(odi_only, use_container_width=True, hide_index=True)
            with col2:
                st.markdown(f"**Flashscore only** — {len(flash_only)} games")
                st.dataframe(flash_only, use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_unmatch, use_container_width=True, hide_index=True)


# ── Tab D: Charts ─────────────────────────────────────────────────────────────
with tab_charts:
    st.subheader("📈 Analytics Charts")

    # Chart 1: Discrepancy size distribution
    if not df_disc.empty and "Difference (minutes)" in df_disc.columns:
        fig1 = px.histogram(
            df_disc.dropna(subset=["Difference (minutes)"]),
            x="Difference (minutes)",
            nbins=20,
            title="Distribution of Discrepancy Sizes",
            labels={"Difference (minutes)": "Difference (minutes)", "count": "Games"},
            color_discrete_sequence=["#e05c5c"],
        )
        st.plotly_chart(fig1, use_container_width=True)

    # Chart 2: Discrepancies by League
    combined = pd.concat(
        [df_disc.assign(Category="Discrepancy"),
         df_nodis.assign(Category="No Discrepancy"),
         df_unmatch.assign(Category="Unmatched")],
        ignore_index=True,
    )

    if "League" in combined.columns and not combined.empty:
        league_cat = (
            combined.groupby(["League", "Category"])
            .size()
            .reset_index(name="Count")
            .sort_values("Count", ascending=False)
        )
        fig2 = px.bar(
            league_cat.head(30),
            x="League",
            y="Count",
            color="Category",
            title="Games per League (colour = category)",
            color_discrete_map={
                "Discrepancy":    "#e05c5c",
                "No Discrepancy": "#4caf50",
                "Unmatched":      "#ffc107",
            },
        )
        fig2.update_xaxes(tickangle=-40)
        st.plotly_chart(fig2, use_container_width=True)

    # Chart 3: Kick-off hour heatmap (discrepancy only)
    if not df_disc.empty and "Flashscore_Time" in df_disc.columns:
        df_disc["Hour"] = (
            df_disc["Flashscore_Time"]
            .astype(str)
            .str.extract(r"(\d{1,2}):\d{2}")[0]
            .pipe(pd.to_numeric, errors="coerce")
            .astype("Int64")
        )
        hour_counts = (
            df_disc.dropna(subset=["Hour"])
            .groupby("Hour")
            .size()
            .reset_index(name="Discrepancy Count")
            .sort_values("Hour")
        )
        fig3 = px.bar(
            hour_counts,
            x="Hour",
            y="Discrepancy Count",
            title="Discrepancies by Hour of Day (Nairobi time)",
            labels={"Hour": "Hour (0–23)"},
            color_discrete_sequence=["#ff7043"],
        )
        fig3.update_xaxes(dtick=1)
        st.plotly_chart(fig3, use_container_width=True)

    # Chart 4: Trend over time
    all_ts = pd.concat(
        [df_disc.assign(Category="Discrepancy"),
         df_nodis.assign(Category="No Discrepancy")],
        ignore_index=True,
    )
    if "Timestamp" in all_ts.columns and not all_ts.empty:
        all_ts["Date"] = all_ts["Timestamp"].dt.date
        trend = (
            all_ts.groupby(["Date", "Category"])
            .size()
            .reset_index(name="Count")
        )
        fig4 = px.line(
            trend,
            x="Date",
            y="Count",
            color="Category",
            title="Daily Match Count by Category",
            markers=True,
            color_discrete_map={
                "Discrepancy":    "#e05c5c",
                "No Discrepancy": "#4caf50",
            },
        )
        st.plotly_chart(fig4, use_container_width=True)

st.divider()
st.caption(
    "Data sourced from odibets.com and flashscore.co.ke via automated scraping. "
    "Dashboard auto-refreshes every 2 hours. Reload the page to force a refresh."
)
