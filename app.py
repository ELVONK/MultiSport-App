import streamlit as st
import pandas as pd
import plotly.express as px

@st.cache_data
def load_data():
    df = pd.read_csv("daily_log.csv", parse_dates=["Timestamp"])
    return df

df = load_data()

st.title("⚡ Discrepancy Analytics Dashboard")

st.header("📊 General Stats")
total_discrepancies = len(df)
avg_diff = df["Difference (minutes)"].mean()
max_diff = df["Difference (minutes)"].max()
st.metric("Total Discrepancies", total_discrepancies)
st.metric("Average Difference (min)", round(avg_diff, 2))
st.metric("Max Difference (min)", max_diff)

st.header("🏆 Team/League Analysis")
team_counts = df.groupby("Team1").size().reset_index(name="Discrepancy Count")
team_counts = team_counts.sort_values(by="Discrepancy Count", ascending=False)
st.subheader("Teams with Most Discrepancies")
st.dataframe(team_counts)

if "League" in df.columns:
    league_counts = df.groupby("League").size().reset_index(name="Discrepancy Count")
    league_counts = league_counts.sort_values(by="Discrepancy Count", ascending=False)
    st.subheader("Leagues with Most Discrepancies")
    st.dataframe(league_counts)

st.header("⏱️ Discrepancy by Hour")
df["Hour"] = df["Flashscore Time"].str[:2].astype(int)
hour_counts = df.groupby("Hour").size().reset_index(name="Discrepancy Count")
fig_hour = px.bar(hour_counts, x="Hour", y="Discrepancy Count", title="Discrepancies by Hour of Day")
st.plotly_chart(fig_hour, use_container_width=True)

st.header("📈 Discrepancy Trend Over Time")
daily_summary = df.groupby(df["Timestamp"].dt.date).agg({"Difference (minutes)": ["count", "mean"]}).reset_index()
daily_summary.columns = ["Date", "Count", "Avg Difference"]
fig_trend = px.line(daily_summary, x="Date", y=["Count", "Avg Difference"],
                    labels={"value": "Count / Avg Difference", "Date": "Date"},
                    title="Daily Discrepancy Count & Average Difference")
st.plotly_chart(fig_trend, use_container_width=True)