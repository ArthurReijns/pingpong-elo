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

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# REPLACE with just this:
creds = Credentials.from_service_account_info(
    dict(st.secrets["google"]["service_account"]),
    scopes=scope
)

client = gspread.authorize(creds)

spreadsheet = client.open(SHEET_NAME)
sheet = spreadsheet.worksheet("PingPongELOKARMA_matches")

def load_users():
    users_df = pd.DataFrame(sheet.spreadsheet.worksheet("USERS").get_all_records())
    users_df["name"] = users_df["name"].astype(str).str.strip()
    users_df["pin"] = users_df["pin"].astype(str).str.strip()
    return users_df

users_df = load_users()

if "user" not in st.session_state:
    st.session_state.user = None


if st.session_state.user is None:
    st.title("🔐 Login")

    name = st.text_input("Name")
    pin = st.text_input("PIN", type="password")

    if st.button("Login"):
        match = users_df[
            (users_df["name"] == name) &
            (users_df["pin"] == pin)
        ]

        if not match.empty:
            st.session_state.user = name
            st.rerun()
        else:
            st.error("Wrong login")
    
    st.stop()

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

def user_matches(df):
    return df[df["created_by"] == st.session_state.user]

# =========================
# DATA
# =========================
@st.cache_data(ttl=5)
def load_data():
    cols = [
        "wedstrijdId",
        "created_by",
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
st.title("🏓🔥 KARMA Ping Pong Leaderboard 🏓🔥")
st.subheader("Become the KARMA Ping Pong GOAT!")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "➕ Matches",
    "🏆 Leaderboard",
    "📊 Stats",
    "👤 Players",
    "🧠 1v1 Matchmaking",
    "👥 2v2 Matchmaking",
    "🎯 1v1 Win Probability"
])

# =========================
# TAB 1 - MATCHES + DELETE
# =========================
with tab1:

    # =========================
    # 1. ADD MATCH (UNCHANGED)
    # =========================
    st.subheader("➕ Add Match")

    col1, col2 = st.columns(2)

    t1_p1 = clean_name(col1.text_input("Team 1 Player 1"))
    t1_p2 = clean_name(col1.text_input("Team 1 Player 2"))

    t2_p1 = clean_name(col2.text_input("Team 2 Player 1"))
    t2_p2 = clean_name(col2.text_input("Team 2 Player 2"))

    s1 = col1.number_input("Team 1 Points", 0, 30, 11)
    s2 = col2.number_input("Team 2 Points", 0, 30, 11)

    import datetime
    date = st.date_input("Match Date", max_value=datetime.date.today())

    if st.button("Add match 🚀"):

        if not valid_score(s1, s2):
            st.error("❌ Invalid score")
        else:
            new_id = 1 if df.empty else int(df["wedstrijdId"].max()) + 1

            new = pd.DataFrame([{
                "wedstrijdId": new_id,
                "created_by": st.session_state.user,
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

        st.success(f"✅ Match #{new_id} added successfully!")

        st.cache_data.clear()

        # small delay so user sees message
        import time
        time.sleep(0.5)

        st.rerun()

    st.divider()

    # =========================
    # 2. ALL MATCHES TABLE
    # =========================
    st.subheader("📋 All Matches")

    st.dataframe(
        df.sort_values("wedstrijdId", ascending=False),
        use_container_width=True,
        hide_index=True
    )


    st.divider()

    # =========================
    # 3. DELETE MATCH (SAFE)
    # =========================
    st.subheader("🗑️ Delete Match")

    user_df = user_matches(df)

    if user_df.empty:
        st.info("No matches to delete")
    else:

        st.write("Your matches:")
        st.dataframe(user_df, use_container_width=True, hide_index=True)

        del_id = st.selectbox(
            "Select match ID to delete",
            user_df["wedstrijdId"].tolist()
        )

        match_row = user_df[user_df["wedstrijdId"] == del_id].iloc[0]

        st.warning("Match selected for deletion:")
        st.write(match_row)

        # RESET CONFIRMATION WHEN ID CHANGES
        if "last_delete_id" not in st.session_state:
            st.session_state.last_delete_id = None

        if st.session_state.last_delete_id != del_id:
            st.session_state.confirm_delete = False
            st.session_state.last_delete_id = del_id

        confirm = st.checkbox(
            "I confirm I want to delete this match",
            key="confirm_delete"
        )

        if st.button("Delete ❌"):

            if confirm:
                df = df[df["wedstrijdId"] != del_id]
                save_data(df)
                st.cache_data.clear()
                st.success(f"Match {del_id} deleted successfully ✅")
                st.rerun()
            else:
                st.error("You must confirm deletion first ⚠️")

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

        col1, col2, col3 = st.columns(3)

        col1.metric("Players", len(current_df))
        col2.metric("Matches", len(df))
        col3.metric("Avg ELO", int(current_df["elo"].mean()))
        
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

    st.subheader("👤 Player Overview")

    player = st.selectbox("Select player", current_df["speler"])
    p = current_df[current_df["speler"] == player].iloc[0]

    player_hist = hist_df[hist_df["speler"] == player]

    highest_elo = player_hist["elo"].max() if not player_hist.empty else p["elo"]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Current ELO", int(p["elo"]))
    col2.metric("Highest ELO", int(highest_elo))
    col3.metric("Matches", p["matches"])
    col4.metric("Win %", f"{p['winrate']*100:.1f}%")

    st.subheader("🔥 Form (last 10)")
    f = form_df[form_df["speler"] == player].tail(10)
    st.write("".join(["🟢" if x == 1 else "🔴" for x in f["result"]]))

    st.subheader("📈 ELO evolution per match")
    st.line_chart(player_hist.set_index("wedstrijdId")["elo"])

    st.subheader("📅 ELO evolutoin per date")
    latest = player_hist.sort_values("wedstrijdId").groupby(["datum","speler"]).last().reset_index()
    st.line_chart(latest.pivot(index="datum", columns="speler", values="elo"))

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

    pa = get_elo(a)
    pb = get_elo(b)

    prob = 1 / (1 + 10 ** ((pb - pa) / 400))

    col1, col2 = st.columns(2)
    a = col1.selectbox("Player A", current_df["speler"])
    b = col2.selectbox("Player B", current_df["speler"])
    
    col3, col4 = st.columns(2)
    col3.metric(a, f"{prob*100:.1f}%")
    col4.metric(b, f"{(1-prob)*100:.1f}%")



