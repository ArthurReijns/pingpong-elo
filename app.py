import streamlit as st
import pandas as pd
import math
import gspread
from google.oauth2.service_account import Credentials
import json

# =========================
# CONFIG
# =========================
K = 32
START_ELO = 1000

st.set_page_config(page_title="🏓 Ping Pong ELO Arena", layout="wide")

SHEET_NAME = "PingPongELOKARMA_matches"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    st.secrets["GOOGLE_SERVICE_ACCOUNT"],
    scopes=scope
)

client = gspread.authorize(creds)

spreadsheet = client.open(SHEET_NAME)
sheet = spreadsheet.worksheet("PingPongELOKARMA_matches")

# =========================
# HELPERS
# =========================
def clean_name(name):
    if pd.isna(name) or name is None or name == "":
        return None
    name = str(name).strip()
    return name[:1].upper() + name[1:].lower()

def get_players(row, prefix):
    players = []
    for key in [f"{prefix}_player1", f"{prefix}_player2"]:
        val = row.get(key)

        if val is None:
            continue

        val = str(val).strip()

        if val == "" or val.lower() == "nan":
            continue

        players.append(val)

    return players

def expected(a, b):
    return 1 / (1 + 10 ** ((b - a) / 400))

def valid_score(s1, s2):
    high = max(s1, s2)
    low = min(s1, s2)

    return (high == 11 and low <= 9) or (high > 11 and high - low == 2)

# =========================
# DATA
# =========================
@st.cache_data(ttl=5)
def load_data():
    cols = [
        "wedstrijdId",
        "Team1_player1",
        "Team1_player2",
        "Team2_player1",
        "Team2_player2",
        "team1_punten",
        "team2_punten",
        "datum"
    ]

    try:
        df = pd.DataFrame(sheet.get_all_records())

        for c in cols:
            if c not in df.columns:
                df[c] = None

        return df[cols]

    except:
        return pd.DataFrame(columns=cols)

def save_data(df):
    df = df.fillna("")
    sheet.clear()
    sheet.update([df.columns.tolist()] + df.astype(str).values.tolist())

# =========================
# ELO ENGINE
# =========================
def compute_elo(df):

    if df.empty:
        return (
            pd.DataFrame(columns=["speler","elo","matches","wins","winrate"]),
            pd.DataFrame(),
            pd.DataFrame()
        )

    df = df.sort_values("wedstrijdId")

    elo = {}
    stats = {}
    history = []
    form_log = []

    for _, r in df.iterrows():

        t1 = get_players(r, "Team1")
        t2 = get_players(r, "Team2")

        if len(t1) == 0 or len(t2) == 0:
            continue

        try:
            s1 = int(r["team1_punten"])
            s2 = int(r["team2_punten"])
        except:
            continue

        for p in t1 + t2:
            if p not in elo:
                elo[p] = START_ELO
                stats[p] = {"matches": 0, "wins": 0}

        e1 = sum(elo[p] for p in t1) / len(t1)
        e2 = sum(elo[p] for p in t2) / len(t2)

        res1 = 1 if s1 > s2 else 0
        res2 = 1 - res1

        # form tracking
        for p in t1:
            form_log.append((p, res1))
        for p in t2:
            form_log.append((p, res2))

        diff = abs(s1 - s2)
        mult = math.log(diff + 1)

        d1 = K * mult * (res1 - expected(e1, e2))
        d2 = -d1

        for p in t1:
            elo[p] += d1
            stats[p]["matches"] += 1
            stats[p]["wins"] += res1

        for p in t2:
            elo[p] += d2
            stats[p]["matches"] += 1
            stats[p]["wins"] += res2

        for p in elo:
            history.append({
                "wedstrijdId": r["wedstrijdId"],
                "datum": r["datum"],
                "speler": p,
                "elo": elo[p]
            })

    hist_df = pd.DataFrame(history)
    form_df = pd.DataFrame(form_log, columns=["speler","result"])

    current = []
    for p in elo:
        s = stats[p]
        wr = s["wins"] / s["matches"] if s["matches"] else 0

        current.append({
            "speler": p,
            "elo": elo[p],
            "matches": s["matches"],
            "wins": s["wins"],
            "winrate": wr
        })

    return pd.DataFrame(current), hist_df, form_df

# =========================
# LOAD
# =========================
df = load_data()
current_df, hist_df, form_df = compute_elo(df)

# =========================
# WIN PROB
# =========================
def get_elo(player):
    row = current_df[current_df["speler"] == player]
    return START_ELO if row.empty else float(row["elo"].iloc[0])

# =========================
# UI
# =========================
st.title("🏓🔥 Ping Pong ELO Arena")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "➕ Matches",
    "🏆 Leaderboard",
    "📊 Stats",
    "👤 Player",
    "🧠 Matchmaking",
    "🎯 Win Prob"
])

# =========================
# TAB 1 - MATCHES + DELETE
# =========================
with tab1:

    st.subheader("➕ Add Match")

    col1, col2 = st.columns(2)

    t1_p1 = clean_name(col1.text_input("Team 1 Player 1"))
    t1_p2 = clean_name(col1.text_input("Team 1 Player 2"))

    t2_p1 = clean_name(col2.text_input("Team 2 Player 1"))
    t2_p2 = clean_name(col2.text_input("Team 2 Player 2"))

    s1 = col1.number_input("Team 1 Points", 0, 30, 11)
    s2 = col2.number_input("Team 2 Points", 0, 30, 11)

    date = st.date_input("Match Date")

    if st.button("Add match 🚀"):

        if not valid_score(s1, s2):
            st.error("❌ Invalid score")
        else:
            new_id = 1 if df.empty else int(df["wedstrijdId"].max()) + 1

            new = pd.DataFrame([{
                "wedstrijdId": new_id,
                "Team1_player1": t1_p1,
                "Team1_player2": t1_p2,
                "Team2_player1": t2_p1,
                "Team2_player2": t2_p2,
                "team1_punten": s1,
                "team2_punten": s2,
                "datum": str(date)
            }])

            df = pd.concat([df, new], ignore_index=True)
            save_data(df)
            st.cache_data.clear()
            st.rerun()

    st.divider()
    st.subheader("🗑️ Delete Match")

    if not df.empty:

        del_id = st.selectbox("Select match", df["wedstrijdId"].tolist())

        match_row = df[df["wedstrijdId"] == del_id].iloc[0]

        st.write("### ⚠️ Match preview")
        st.write(f"**ID:** {del_id}")
        st.write(f"**Team 1:** {match_row['Team1_player1']} {match_row['Team1_player2'] or ''}")
        st.write(f"**Team 2:** {match_row['Team2_player1']} {match_row['Team2_player2'] or ''}")
        st.write(f"**Score:** {match_row['team1_punten']} - {match_row['team2_punten']}")
        st.write(f"**Datum:** {match_row['datum']}")

        confirm = st.checkbox("⚠️ I understand this will permanently delete this match")

        if st.button("Delete ❌"):

            if not confirm:
                st.error("You must confirm deletion first ⚠️")
            else:
                df = df[df["wedstrijdId"] != del_id]
                save_data(df)
                st.cache_data.clear()
                st.success("Match deleted")
                st.rerun()

# =========================
# TAB 2 - LEADERBOARD
# =========================
with tab2:

    st.subheader("🏆 Leaderboard")

    lb = current_df.copy()
    lb["elo"] = lb["elo"].round(0).astype(int)
    lb["win %"] = (lb["winrate"] * 100).round(1)

    st.dataframe(
        lb.sort_values("elo", ascending=False)[["speler","elo","matches","wins","win %"]],
        hide_index=True,
        use_container_width=True
    )

# =========================
# TAB 3 - STATS (FULL)
# =========================
with tab3:

    st.subheader("📊 Global Stats")

    if not current_df.empty:

        st.metric("Players", len(current_df))
        st.metric("Matches", len(df))
        st.metric("Avg ELO", int(current_df["elo"].mean()))

        top_wins = current_df.sort_values("wins", ascending=False).iloc[0]
        top_elo = current_df.sort_values("elo", ascending=False).iloc[0]

        st.write(f"🏅 Most Wins: {top_wins['speler']} ({top_wins['wins']})")
        st.write(f"🔥 Highest ELO: {top_elo['speler']} ({int(top_elo['elo'])})")

        st.subheader("📈 ELO per match")
        st.line_chart(hist_df.pivot_table(index="wedstrijdId", columns="speler", values="elo"))

        st.subheader("📅 ELO per date")
        latest = hist_df.sort_values("wedstrijdId").groupby(["datum","speler"]).last().reset_index()
        st.line_chart(latest.pivot(index="datum", columns="speler", values="elo"))

# =========================
# TAB 4 - PLAYER
# =========================
with tab4:

    st.subheader("👤 Player")

    player = st.selectbox("Select player", current_df["speler"])
    p = current_df[current_df["speler"] == player].iloc[0]

    st.metric("ELO", int(p["elo"]))
    st.metric("Matches", p["matches"])
    st.metric("Wins", p["wins"])
    st.metric("Win %", round(p["winrate"] * 100, 1))

    st.subheader("🔥 Form (last 5)")

    f = form_df[form_df["speler"] == player].tail(5)
    if not f.empty:
        st.write("".join(["🟢" if x == 1 else "🔴" for x in f["result"]]))

    ph = hist_df[hist_df["speler"] == player]
    st.line_chart(ph.set_index("wedstrijdId")["elo"])

# =========================
# TAB 5 - MATCHMAKING
# =========================
with tab5:

    st.subheader("🧠 Matchmaking")

    sorted_players = current_df.sort_values("elo")

    suggestions = []

    for i in range(len(sorted_players) - 1):
        low = sorted_players.iloc[i]
        high = sorted_players.iloc[i + 1]

        suggestions.append({
            "A": low["speler"],
            "B": high["speler"],
            "gap": int(high["elo"] - low["elo"])
        })

    st.dataframe(pd.DataFrame(suggestions), hide_index=True)

# =========================
# TAB 6 - WIN PROB
# =========================
with tab6:

    st.subheader("🎯 Win Probability")

    a = st.selectbox("A", current_df["speler"])
    b = st.selectbox("B", current_df["speler"])

    pa = get_elo(a)
    pb = get_elo(b)

    prob = 1 / (1 + 10 ** ((pb - pa) / 400))

    st.metric(a, f"{prob*100:.1f}%")
    st.metric(b, f"{(1-prob)*100:.1f}%")
