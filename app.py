import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import time

# ─────────────────────────────────────────────
# PAGE CONFIG  (must be the very first st call)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Discrepancy Analytics Dashboard",
    page_icon="⚡",
    layout="wide",
)

# ─────────────────────────────────────────────
# AUTO-REFRESH EVERY 2 HOURS (7200 seconds)
# Uses streamlit-autorefresh if installed,
# otherwise falls back to meta-refresh HTML.
# ─────────────────────────────────────────────
REFRESH_INTERVAL_SEC = 7200  # 2 hours

try:
    from streamlit_autorefresh import st_autorefresh  # pip install streamlit-autorefresh
    st_autorefresh(interval=REFRESH_INTERVAL_SEC * 1000, key="dashboard_refresh")
except ImportError:
    # Graceful fallback: inject an HTML meta-refresh tag
    st.markdown(
        f'<meta http-equiv="refresh" content="{REFRESH_INTERVAL_SEC}">',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
# DATA LOADING  (ttl matches refresh interval)
# ─────────────────────────────────────────────
@st.cache_data(ttl=REFRESH_INTERVAL_SEC)
def load_data() -> pd.DataFrame:
    """Load and validate daily_log.csv."""
    df = pd.read_csv("daily_log.csv", parse_dates=["Timestamp"])

    # --- Defensive column normalisation ---
    # Strip accidental leading/trailing spaces from column names
    df.columns = df.columns.str.strip()

    # Ensure required columns exist
    required = {"Timestamp", "Difference (minutes)", "Team1", "Flashscore Time"}
    missing = required - set(df.columns)
    if missing:
        st.error(f"CSV is missing required columns: {missing}")
        st.stop()

    # Coerce 'Difference (minutes)' to numeric; bad values become NaN
    df["Difference (minutes)"] = pd.to_numeric(df["Difference (minutes)"], errors="coerce")

    # Parse hour safely: extract first two characters of 'Flashscore Time'
    # Handles both 'HH:MM:SS' and 'HH:MM' formats
    df["Hour"] = (
        df["Flashscore Time"]
        .astype(str)
        .str.strip()
        .str[:2]
        .pipe(pd.to_numeric, errors="coerce")
        .astype("Int64")   # nullable integer — survives NaN
    )

    return df


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
df = load_data()

# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
st.title("⚡ Discrepancy Analytics Dashboard")
st.caption(f"Last loaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  •  Auto-refreshes every 2 hours")

st.divider()

# ─────────────────────────────────────────────
# SECTION 1 — GENERAL STATS
# ─────────────────────────────────────────────
st.header("📊 General Stats")

total_discrepancies = len(df)
avg_diff = df["Difference (minutes)"].mean()   # NaN-safe with pandas mean()
max_diff = df["Difference (minutes)"].max()

col1, col2, col3 = st.columns(3)
col1.metric("Total Discrepancies", total_discrepancies)
col2.metric("Average Difference (min)", f"{avg_diff:.2f}" if pd.notna(avg_diff) else "N/A")
col3.metric("Max Difference (min)", f"{max_diff:.2f}" if pd.notna(max_diff) else "N/A")

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 — TEAM / LEAGUE ANALYSIS
# ─────────────────────────────────────────────
st.header("🏆 Team / League Analysis")

team_counts = (
    df.groupby("Team1", dropna=False)
    .size()
    .reset_index(name="Discrepancy Count")
    .sort_values("Discrepancy Count", ascending=False)
)

st.subheader("Teams with Most Discrepancies")
st.dataframe(team_counts, use_container_width=True, hide_index=True)

if "League" in df.columns:
    league_counts = (
        df.groupby("League", dropna=False)
        .size()
        .reset_index(name="Discrepancy Count")
        .sort_values("Discrepancy Count", ascending=False)
    )
    st.subheader("Leagues with Most Discrepancies")
    st.dataframe(league_counts, use_container_width=True, hide_index=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 3 — DISCREPANCY BY HOUR
# ─────────────────────────────────────────────
st.header("⏱️ Discrepancy by Hour")

hour_counts = (
    df.dropna(subset=["Hour"])          # drop rows where hour couldn't be parsed
    .groupby("Hour")
    .size()
    .reset_index(name="Discrepancy Count")
    .sort_values("Hour")
)

fig_hour = px.bar(
    hour_counts,
    x="Hour",
    y="Discrepancy Count",
    title="Discrepancies by Hour of Day",
    labels={"Hour": "Hour of Day (0–23)", "Discrepancy Count": "Count"},
)
fig_hour.update_xaxes(dtick=1)  # show every hour on x-axis
st.plotly_chart(fig_hour, use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 4 — TREND OVER TIME
# ─────────────────────────────────────────────
st.header("📈 Discrepancy Trend Over Time")

# FIX: group by date derived from Timestamp (was previously computed outside
# this block and could fail if Timestamp parsing had issues)
df_valid_ts = df.dropna(subset=["Timestamp"])

daily_summary = (
    df_valid_ts
    .groupby(df_valid_ts["Timestamp"].dt.date)["Difference (minutes)"]
    .agg(Count="count", Avg_Difference="mean")
    .reset_index()
    .rename(columns={"Timestamp": "Date"})  # dt.date produces 'Timestamp' as col name
)

# FIX: plotly expects string column names in y= list; rename for clarity
fig_trend = px.line(
    daily_summary,
    x="Date",
    y=["Count", "Avg_Difference"],
    labels={
        "value": "Count / Avg Difference (min)",
        "Date": "Date",
        "variable": "Metric",
    },
    title="Daily Discrepancy Count & Average Difference",
)
# Rename legend labels for readability
newnames = {"Count": "Daily Count", "Avg_Difference": "Avg Difference (min)"}
fig_trend.for_each_trace(lambda t: t.update(name=newnames.get(t.name, t.name)))
st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────
st.caption("Dashboard auto-refreshes every 2 hours. To force a refresh, reload the page.")
